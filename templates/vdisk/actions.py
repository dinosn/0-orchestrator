from js9 import j


def install(job):
    import random
    from urllib.parse import urlparse
    import yaml

    service = job.service
    service.model.data.status = 'halted'
    if service.model.data.size > 2048:
        raise j.exceptions.Input("Maximum disk size is 2TB")
    if service.model.data.templateVdisk:
        template = urlparse(service.model.data.templateVdisk)
        targetconfig = get_cluster_config(job)
        target_node = random.choice(targetconfig['nodes'])
        storagecluster = service.model.data.storageCluster

        volume_container = create_from_template_container(job, target_node)
        try:
            srcstorageEngine = get_srcstorageEngine(volume_container, template)
            configpath = "/config.yml"
            disktype = "cache" if str(service.model.data.type) == "tmp" else str(service.model.data.type)
            config = {
                "storageClusters": {
                    storagecluster: targetconfig['config'],
                    "srccluster": {
                        "metadataStorage": {
                            "address": srcstorageEngine
                        },
                        "dataStorage": [
                            {"address": srcstorageEngine},
                        ],
                    },
                },
                "vdisks": {
                    template.path.lstrip('/'): {
                        "blockSize": service.model.data.blocksize,  # Random value needed only to complete the config
                        "readOnly": service.model.data.readOnly,  # Random value needed only to complete the config
                        "size": service.model.data.size,  # Random value needed only to complete the config
                        "storageCluster": "srccluster",
                        "type": disktype,
                    }
                }
            }
            yamlconfig = yaml.safe_dump(config, default_flow_style=False)
            volume_container.upload_content(configpath, yamlconfig)

            CMD = '/bin/zeroctl copy vdisk {src_name} {dst_name} {tgtcluster}'
            cmd = CMD.format(dst_name=service.name, src_name=template.path.lstrip('/'), tgtcluster=storagecluster)

            print(cmd)
            result = volume_container.client.system(cmd).get()
            if result.state != 'SUCCESS':
                raise j.exceptions.RuntimeError("Failed to run zeroctl copy {} {}".format(result.stdout, result.stderr))

        finally:
            volume_container.stop()


def delete(job):
    import random
    import yaml

    service = job.service
    storagecluster = service.model.data.storageCluster
    clusterconfig = get_cluster_config(job)
    node = random.choice(clusterconfig['nodes'])
    container = create_from_template_container(job, node)
    try:
        configpath = "/config.yaml"
        disktype = "cache" if str(service.model.data.type) == "tmp" else str(service.model.data.type)
        config = {
                    "storageClusters": {
                        storagecluster: clusterconfig['config']
                    },
                    "vdisks": {
                        service.name: {
                            "blockSize": service.model.data.blocksize,
                            "readOnly": service.model.data.readOnly,
                            "size": service.model.data.size,
                            "storageCluster": storagecluster,
                            "type": disktype,
                        }
                    }
                }
        yamlconfig = yaml.safe_dump(config, default_flow_style=False)
        container.upload_content(configpath, yamlconfig)

        cmd = '/bin/zeroctl delete vdisks --config {}'.format(configpath)
        print(cmd)
        result = container.client.system(cmd).get()
        if result.state != 'SUCCESS':
            raise j.exceptions.RuntimeError("Failed to run zeroctl delete {} {}".format(result.stdout, result.stderr))
    finally:
        container.stop()


def get_srcstorageEngine(container, template):
    from urllib.parse import urlparse

    if template.scheme in ('', 'ardb'):
        if template.scheme == '' or template.netloc == '':
            config = container.node.client.config.get()
            return urlparse(config['globals']['storage']).netloc
        return template.netloc
    else:
        raise j.exceptions.RuntimeError("Unsupport protocol {}".format(template.scheme))


def get_cluster_config(job, type="storage"):
    from zeroos.orchestrator.sal.StorageCluster import StorageCluster
    if type == "tlog":
        cluster = job.service.model.data.tlogStoragecluster
    else:
        cluster = job.service.model.data.storageCluster

    storageclusterservice = job.service.aysrepo.serviceGet(role='storage_cluster',
                                                           instance=cluster)
    cluster = StorageCluster.from_ays(storageclusterservice, job.context['token'])
    nodes = list(set(storageclusterservice.producers["node"]))
    return {"config": cluster.get_config(), "nodes": nodes, 'k': cluster.k, 'm': cluster.m}


def create_from_template_container(job, parent):
    """
    if not it creates it.
    return the container service
    """
    from zeroos.orchestrator.configuration import get_configuration
    from zeroos.orchestrator.sal.Container import Container
    from zeroos.orchestrator.sal.Node import Node

    container_name = 'vdisk_{}_{}'.format(job.service.name, parent.name)
    node = Node.from_ays(parent, job.context['token'])
    config = get_configuration(job.service.aysrepo)
    container = Container(name=container_name,
                          flist=config.get('0-disk-flist', 'https://hub.gig.tech/gig-official-apps/0-disk-master.flist'),
                          host_network=True,
                          node=node)
    container.start()
    return container


def start(job):
    service = job.service
    service.model.data.status = 'running'


def pause(job):
    service = job.service
    service.model.data.status = 'halted'


def rollback(job):
    import random
    import yaml
    service = job.service
    service.model.data.status = 'rollingback'
    ts = job.model.args['timestamp']

    storagecluster = service.model.data.storageCluster
    clusterconfig = get_cluster_config(job)

    tlogcluster = service.model.data.tlogStoragecluster
    tlogclusterconfig = get_cluster_config(job, type='tlog')

    node = random.choice(clusterconfig['nodes'])
    container = create_from_template_container(job, node)
    try:
        configpath = "/config.yaml"
        disktype = "cache" if str(service.model.data.type) == "tmp" else str(service.model.data.type)
        config = {
                    "storageClusters": {
                        storagecluster: clusterconfig['config'],
                        tlogcluster: tlogclusterconfig['config']
                    },
                    "vdisks": {
                        service.name: {
                            "blockSize": service.model.data.blocksize,
                            "readOnly": service.model.data.readOnly,
                            "size": service.model.data.size,
                            "storageCluster": storagecluster,
                            "tlogStorageCluster": tlogcluster,
                            "type": disktype,
                        }
                    }
                }
        yamlconfig = yaml.safe_dump(config, default_flow_style=False)
        container.upload_content(configpath, yamlconfig)
        k = tlogclusterconfig.pop('k')
        m = tlogclusterconfig.pop('m')
        cmd = '/bin/zeroctl restore vdisk {vdisk} --config {config} --end-timestamp {ts} --k {k} --m {m}'.format(vdisk=service.name,
                                                                                                                 config=configpath,
                                                                                                                 ts=ts, k=k, m=m)
        print(cmd)
        result = container.client.system(cmd).get()
        if result.state != 'SUCCESS':
            raise j.exceptions.RuntimeError("Failed to run zeroctl restore {} {}".format(result.stdout, result.stderr))
        service.model.data.status = 'running'
    finally:
        container.stop()


def resize(job):
    service = job.service
    job.logger.info("resize vdisk {}".format(service.name))

    if 'size' not in job.model.args:
        raise j.exceptions.Input("size is not present in the arguments of the job")

    size = int(job.model.args['size'])
    if size > 2048:
        raise j.exceptions.Input("Maximun disk size is 2TB")
    if size < service.model.data.size:
        raise j.exceptions.Input("size is smaller then current size, disks can  only be grown")

    service.model.data.size = size


def processChange(job):
    from zeroos.orchestrator.configuration import get_jwt_token_from_job
    service = job.service

    args = job.model.args
    category = args.pop('changeCategory')
    if category == "dataschema" and service.model.actionsState['install'] == 'ok':
        if args.get('size', None):
            job.context['token'] = get_jwt_token_from_job(job)
            j.tools.async.wrappers.sync(service.executeAction('resize', context=job.context, args={'size': args['size']}))
        if args.get('timestamp', None):
            if str(service.model.data.status) != "halted":
                raise j.exceptions.RuntimeError("Failed to rollback vdisk, vdisk must be halted to rollback")
            if str(service.model.data.type) not in ["boot", "db"]:
                raise j.exceptions.RuntimeError("Failed to rollback vdisk, vdisk must be of type boot or db")
            args['timestamp'] = args['timestamp'] * 10**9
            job.context['token'] = get_jwt_token_from_job(job)
            j.tools.async.wrappers.sync(service.executeAction('rollback', args={'timestamp': args['timestamp']}, context=job.context))
