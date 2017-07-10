import os

import json
import click
import logging
import time
import yaml

from zeroos.core0.client import Client as Client0
from zeroos.orchestrator import client as apiclient

os.environ['LC_ALL'] = 'C.UTF-8'
os.environ['LANG'] = 'C.UTF-8'

logging.basicConfig(level=logging.INFO)


@click.command()
@click.option('--orchestratorserver', required=True, help='0-orchestrator api server endpoint. Eg http://192.168.193.212:8080')
@click.option('--storagecluster', required=True, help='Name of the storage cluster in which the vdisks need to be created')
@click.option('--vdiskCount', required=True, type=int, help='Number of vdisks that need to be created')
@click.option('--vdiskSize', required=True, type=int, help='Size of disks in GB')
@click.option('--runtime', required=True, type=int, help='Time fio should be run')
@click.option('--vdiskType', required=True, type=click.Choice(['boot', 'db', 'cache', 'tmp']), help='Type of disk')
@click.option('--resultDir', required=True, help='Results directory path')
@click.option('--nodeLimit', type=int, help='Limit the number of nodes')
def test_fio_nbd(orchestratorserver, storagecluster, vdiskcount, vdisksize, runtime, vdisktype, resultdir, nodelimit):
    """Creates a storagecluster on all the nodes in the resourcepool"""
    api = apiclient.APIClient(orchestratorserver)
    logging.info("Discovering nodes in the cluster ...")
    nodes = api.nodes.ListNodes().json()
    nodes = [node for node in nodes if node["status"] == "running"]

    nodelimit = nodelimit if nodelimit is None or nodelimit <= len(nodes) else len(nodes)

    if nodelimit is not None:
        if vdiskcount < nodelimit:
            raise ValueError("Vdisk count should be at least the same as number of nodes")
    elif vdiskcount < len(nodes):
        raise ValueError("Vdisk count should be at least the same as number of nodes")

    vdiskcount = int(vdiskcount / len(nodes)) if nodelimit is None else int(vdiskcount / nodelimit)

    logging.info("Found %s ready nodes..." % (len(nodes)))
    nodeIDs = [node['id'] for node in nodes]
    nodeIPs = [node['ipaddress'] for node in nodes]
    if nodelimit:
        nodeIDs = nodeIDs[:nodelimit]
        nodeIPs = nodeIPs[:nodelimit]

    deployInfo = {}
    try:
        deployInfo = deploy(api, nodeIDs, nodeIPs, orchestratorserver, storagecluster, vdiskcount, vdisksize, vdisktype)
        mountVdisks(api, deployInfo, nodeIDs)
        cycle = 0
        while runtime:
            if runtime < 3600:
                cycle_time = runtime
                runtime = 0
            else:
                cycle_time = 3600
                runtime -= 3600
            cycle += 1
            cycle_dir = os.path.join(resultdir, str(cycle))
            os.makedirs(cycle_dir, exist_ok=True)
            test(api, deployInfo, nodeIDs, cycle_time)
            waitForData(api, nodeIDs, deployInfo, cycle_time, cycle_dir)
    except Exception as e:
        raise RuntimeError(e)
    finally:
        cleanUp(api, nodeIDs, deployInfo)


def StartContainerJob(api, **kwargs):
    res = api.nodes.StartContainerJob(**kwargs)
    return res.headers["Location"].split("/")[-1]


def waitForData(api, nodeIDs, deployInfo, runtime, resultdir):
    os.makedirs(resultdir, exist_ok=True)
    for nodeID in nodeIDs:
        start = time.time()
        while start + (runtime + 120) > time.time():
            try:
                containername = deployInfo[nodeID]["testContainer"]
                filepath = '/%s.test.json' % nodeID
                res = api.nodes.FileDownload(containername=containername,
                                             nodeid=nodeID,
                                             query_params={"path": filepath})
            except:
                time.sleep(1)
            else:
                if res.content == b'':
                    time.sleep(5)
                    continue
                file = '%s/%s.test.json' % (resultdir, nodeID)
                logging.info("Saving test data in %s ..." % file)
                with open(file, 'wb') as outfile:
                    outfile.write(res.content)
                    break


def mountVdisks(api, deployInfo, nodeIDs):
    for nodeID in nodeIDs:
        containername = deployInfo[nodeID]["testContainer"]
        nbdConfig = deployInfo[nodeID]["nbdConfig"]
        deployInfo[nodeID]["nbdClientInfo"] = nbdClientConnect(api, nodeID, containername, nbdConfig)


def test(api, deployInfo, nodeIDs, runtime):
    for nodeID in nodeIDs:
        containername = deployInfo[nodeID]["testContainer"]
        clientInfo = deployInfo[nodeID]["nbdClientInfo"]
        filenames = clientInfo["filenames"]
        client_pids = clientInfo["client_pids"]
        deployInfo[nodeID]["filenames"] = filenames
        deployInfo[nodeID]["clientPids"] = client_pids
        fioCommand = {
            'name': '/bin/fio',
            'pwd': '',
            'args': ['--iodepth=16',
                     '--ioengine=libaio',
                     '--size=100000000000M',
                     '--readwrite=randrw',
                     '--rwmixwrite=20',
                     '--filename=%s' % filenames,
                     '--runtime=%s' % runtime,
                     '--output=%s.test.json' % nodeID,
                     '--numjobs=%s' % (len(filenames.split(":")) * 2),
                     '--name=test1',
                     '--group_reporting',
                     '--output-format=json',
                     '--direct=1'],
        }

        api.nodes.StartContainerJob(data=fioCommand, containername=containername, nodeid=nodeID)


def cleanUp(api, nodeIDs, deployInfo):
    logging.info("Cleaning up...")

    for nodeID in nodeIDs:
        if deployInfo.get(nodeID, None):
            nbdConfig = deployInfo[nodeID]["nbdConfig"]
            nbdContainer = deployInfo[nodeID]["nbdContainer"]
            testContainer = deployInfo[nodeID]["testContainer"]
            filenames = deployInfo[nodeID]["filenames"]
            client_pids = deployInfo[nodeID]["clientPids"]

            # Disconnecting nbd disks
            for idx, filename in enumerate(filenames.split(":")):
                disconnectDiskCommand = {
                    'name': '/bin/nbd-client',
                    'pwd': '',
                    'args': ['-d', filename],
                }
                jobId = StartContainerJob(api, data=disconnectDiskCommand, containername=testContainer, nodeid=nodeID)
                exit = waitProcess(api, disconnectDiskCommand, jobId, nodeID, testContainer, raiseError=False)
                if not exit:
                    api.nodes.KillContainerJob(client_pids[idx], testContainer, nodeID)

            deleteDiskCommand = {
                'name': '/bin/zeroctl',
                'pwd': '',
                'args': ['delete', 'vdisks', '--config', nbdConfig["configpath"]],
            }
            jobId = StartContainerJob(api, data=deleteDiskCommand, containername=nbdContainer, nodeid=nodeID)
            waitProcess(api, deleteDiskCommand, jobId, nodeID, nbdContainer)

            api.nodes.DeleteContainer(nbdContainer, nodeID)
            api.nodes.DeleteContainer(testContainer, nodeID)


def deploy(api, nodeIDs, nodeIPs, orchestratorserver, storagecluster, vdiskcount, vdisksize, vdisktype):
    deployInfo = {}
    storageclusterInfo = getStorageClusterInfo(api, storagecluster)
    for idx, nodeID in enumerate(nodeIDs):
        # Create filesystem to be shared amongst fio and nbd server contianers
        fss = _create_fss(orchestratorserver, api, nodeID)

        # Create block device container and start nbd
        nbdContainer = "nbd_{}".format(str(time.time()).replace('.', ''))
        nbdFlist = "https://hub.gig.tech/gig-official-apps/0-disk-master.flist"
        nodeClient = Client0(nodeIPs[idx])
        createContainer(orchestratorserver, api, nodeID, [fss], nbdFlist, nbdContainer)

        nbdConfig = startNbd(api=api,
                             nodeID=nodeID,
                             storagecluster=storagecluster,
                             fs=fss,
                             containername=nbdContainer,
                             vdiskCount=vdiskcount,
                             vdiskSize=vdisksize,
                             vdiskType=vdisktype,
                             storageclusterInfo=storageclusterInfo)

        # Create and setup the test container
        testContainer = "bptest_{}".format(str(time.time()).replace('.', ''))
        fioFlist = "https://hub.gig.tech/gig-official-apps/performance-test.flist"
        createContainer(orchestratorserver, api, nodeID, [fss], fioFlist, testContainer)
        # Load nbd kernel module
        nodeClient.system("modprobe nbd nbds_max=512").get()

        deployInfo[nodeID] = {
            "nbdContainer": nbdContainer,
            "testContainer": testContainer,
            "nbdConfig": nbdConfig,
        }
    return deployInfo


def getStorageClusterInfo(api, storagecluster):
    logging.info("Getting storagecluster info...")
    storageclusterInfo = api.storageclusters.GetClusterInfo(storagecluster).json()
    datastorages = []
    metadatastorage = ''

    clusterconfig = {
        'dataStorage': [],
    }
    for storage in storageclusterInfo.get('dataStorage', []):
        datastorages.append("%s:%s" % (storage['ip'], storage['port']))
        clusterconfig['dataStorage'].append({"address": "%s:%s" % (storage['ip'], storage['port'])})

    for storage in storageclusterInfo.get('metadataStorage', []):
        metadatastorage = "%s:%s" % (storage['ip'], storage['port'])
        clusterconfig['metadataStorage'] = {"address": "%s:%s" % (storage['ip'], storage['port'])}

    return {
        "clusterconfig": clusterconfig,
        "datastorage": datastorages,
        "metadatastorage": metadatastorage,
    }


def startNbd(api, nodeID, storagecluster, fs, containername, vdiskCount, vdiskSize, vdiskType, storageclusterInfo):
    # Start nbd servers
    fs = fs.replace(':', os.sep)
    socketpath = '/fs/{}/server.socket.{}'.format(fs, containername)
    configpath = "/{}.config".format(containername)

    config = {
        'storageClusters': {storagecluster: storageclusterInfo["clusterconfig"]},
        'vdisks': {},
    }
    vdiskIDs = []
    for i in range(vdiskCount):
        # Run nbd

        vdiskID = "testvdisk_{}".format(str(time.time()).replace('.', ''))
        vdiskIDs.append(vdiskID)
        vdiskconfig = {
            'blockSize': 4096,
            'readOnly': False,
            'size': vdiskSize,
            'storageCluster': storagecluster,
            'type': vdiskType
        }
        config['vdisks'][vdiskID] = vdiskconfig

    yamlconfig = yaml.safe_dump(config, default_flow_style=False)
    data = {"file": (yamlconfig)}
    api.nodes.FileUpload(containername=containername,
                         nodeid=nodeID,
                         data=data,
                         query_params={"path": configpath},
                         content_type="multipart/form-data")

    nbdCommand = {
        'name': '/bin/nbdserver',
        'pwd': '',
        'args': ['-protocol=unix', '-address=%s' % socketpath, '-config=%s' % configpath]
    }

    jobId = StartContainerJob(api, data=nbdCommand, containername=containername, nodeid=nodeID)
    logging.info("Starting nbdserver on node: %s", nodeID)
    nbdConfig = {
        "socketpath": socketpath,
        "datastorage": storageclusterInfo["datastorage"],
        "metadatastorage": storageclusterInfo["metadatastorage"],
        "pid": jobId,
        "vdisks": vdiskIDs,
        "configpath": configpath,
    }

    logging.info("Waiting for 10 seconds to evaluate nbdserver processes")
    time.sleep(10)
    res = api.nodes.GetContainerJob(jobId, containername, nodeID).json()
    if res["state"].upper() != "RUNNING":
        raise ValueError("nbd server on node %s is not in a valid state: %s" % (nodeID, res["state"]))
    return nbdConfig


def createContainer(orchestratorserver, cl, nodeID, fs, flist, hostname):
    container = apiclient.CreateContainer.create(filesystems=fs,
                                                 flist=flist,
                                                 hostNetworking=True,
                                                 hostname=hostname,
                                                 initProcesses=[],
                                                 nics=[],
                                                 ports=[],
                                                 name=hostname)

    req = json.dumps(container.as_dict(), indent=4)
    link = "POST /nodes/{nodeid}/containers".format(nodeid=nodeID)
    logging.info("Sending the following request to the /containers api:\n{}\n\n{}".format(link, req))
    res = cl.nodes.CreateContainer(nodeid=nodeID, data=container)
    logging.info(
        "Creating new container...\n You can follow here: %s%s" % (orchestratorserver, res.headers['Location']))

    # wait for container to be running
    res = cl.nodes.GetContainer(hostname, nodeID).json()
    start = time.time()
    while start + 100 > time.time():
        if res['status'] == 'running':
            break
        else:
            time.sleep(1)
            res = cl.nodes.GetContainer(hostname, nodeID).json()
    if res['status'] != 'running':
        raise RuntimeError("Failed to create container %s on node %s" % (hostname, nodeID))


def waitProcess(cl, command, jobid, nodeID, containername, state="SUCCESS", timeout=10, raiseError=True):
    res = cl.nodes.GetContainerJob(jobid, containername, nodeID).json()
    start = time.time()
    while start + timeout > time.time():
        if res["state"] == state:
            return True
        elif res["state"] == "ERROR":
            if raiseError:
                raise RuntimeError("Command %s failed to execute successfully. %s" % (command, res["stderr"]))
            return False
        else:
            time.sleep(0.5)
            res = cl.nodes.GetContainerJob(jobid, containername, nodeID).json()
    return False


def nbdClientConnect(api, nodeID, containername, nbdConfig):
    filenames = ''
    client_pids = []
    for idx, val in enumerate(nbdConfig["vdisks"]):
        nbdDisk = '/dev/nbd%s' % idx
        nbdClientCommand = {
            'name': '/bin/nbd-client',
            'pwd': '',
            'args': ['-N', val, '-u', nbdConfig['socketpath'], nbdDisk, '-b', '4096'],
        }
        jobid = StartContainerJob(api, data=nbdClientCommand, containername=containername, nodeid=nodeID)
        waitProcess(api, nbdClientCommand, jobid, nodeID, containername)
        filenames = nbdDisk if filenames == '' else '%s:%s' % (filenames, nbdDisk)
        client_pids.append(jobid)
    return {"filenames": filenames, "client_pids": client_pids}


def _create_fss(orchestratorserver, cl, nodeID):
    pool = "{}_fscache".format(nodeID)
    fs_id = "fs_{}".format(str(time.time()).replace('.', ''))
    fs = apiclient.FilesystemCreate.create(name=fs_id,
                                           quota=0,
                                           readOnly=False)

    req = json.dumps(fs.as_dict(), indent=4)

    link = "POST /nodes/{nodeid}/storagepools/{pool}/filesystems".format(nodeid=nodeID, pool=pool)
    logging.info("Sending the following request to the /filesystem api:\n{}\n\n{}".format(link, req))
    res = cl.nodes.CreateFilesystem(nodeid=nodeID, storagepoolname=pool, data=fs)

    logging.info(
        "Creating new filesystem...\n You can follow here: %s%s" % (orchestratorserver, res.headers['Location']))
    return "{}:{}".format(pool, fs_id)


if __name__ == "__main__":
    test_fio_nbd()
