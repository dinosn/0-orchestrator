from js9 import j


def get_container(service, password):
    from zeroos.orchestrator.sal.Container import Container
    return Container.from_ays(service.parent, password)


def is_job_running(container, cmd='/bin/nbdserver'):
    try:
        for job in container.client.job.list():
            arguments = job['cmd']['arguments']
            if 'name' in arguments and arguments['name'] == cmd:
                return job
        return False
    except Exception as err:
        if str(err).find("invalid container id"):
            return False
        raise


def is_socket_listening(container, socketpath):
    for connection in container.client.info.port():
        if connection['network'] == 'unix' and connection['unix'] == socketpath:
            return True
    return False


def install(job):
    import time
    import yaml
    from io import BytesIO
    from urllib.parse import urlparse
    service = job.service

    tlog = False
    vm = service.consumers['vm'][0]
    vdisks = vm.producers.get('vdisk', [])
    container = get_container(service, job.context['token'])
    config = {
        'storageClusters': {},
        'vdisks': {},
    }

    socketpath = '/server.socket.{id}'.format(id=vm.name)
    configpath = "/nbd_{}.config".format(vm.name)

    for vdiskservice in vdisks:
        if vdiskservice.model.data.tlogStoragecluster:
            tlog = True

        template = urlparse(vdiskservice.model.data.templateVdisk)
        if template.scheme == 'ardb' and template.netloc:
            rootstorageEngine = template.netloc
        else:
            conf = container.node.client.config.get()
            rootstorageEngine = urlparse(conf['globals']['storage']).netloc

        if vdiskservice.model.data.storageCluster not in config['storageClusters']:
            storagecluster = vdiskservice.model.data.storageCluster
            clusterconfig = get_storagecluster_config(job, storagecluster)
            rootcluster = {'dataStorage': [{'address': rootstorageEngine}], 'metadataStorage': {'address': rootstorageEngine}}
            rootclustername = hash(j.data.serializer.json.dumps(rootcluster, sort_keys=True))
            config['storageClusters'][storagecluster] = clusterconfig

        backupStoragecluster = vdiskservice.model.data.backupStoragecluster
        if backupStoragecluster and backupStoragecluster not in config['storageClusters']:
            clusterconfig = get_storagecluster_config(job, backupStoragecluster)
            rootcluster = {'dataStorage': [{'address': rootstorageEngine}], 'metadataStorage': {'address': rootstorageEngine}}
            rootclustername = hash(j.data.serializer.json.dumps(rootcluster, sort_keys=True))
            config['storageClusters'][backupStoragecluster] = clusterconfig

        if rootclustername not in config['storageClusters']:
            config['storageClusters'][rootclustername] = rootcluster

        tlogStoragecluster = vdiskservice.model.data.tlogStoragecluster
        if tlogStoragecluster and vdiskservice.model.data.tlogStoragecluster not in config['storageClusters']:
            clusterconfig = get_storagecluster_config(job, tlogStoragecluster)
            config['storageClusters'][tlogStoragecluster] = clusterconfig

        vdisk_type = "cache" if str(vdiskservice.model.data.type) == "tmp" else str(vdiskservice.model.data.type)
        vdiskconfig = {'blockSize': vdiskservice.model.data.blocksize,
                       'id': vdiskservice.name,
                       'readOnly': vdiskservice.model.data.readOnly,
                       'size': vdiskservice.model.data.size,
                       'storageCluster': vdiskservice.model.data.storageCluster,
                       'rootStorageCluster': rootclustername,
                       'type': vdisk_type}

        if vdiskservice.model.data.tlogStoragecluster:
            vdiskconfig['tlogstoragecluster'] = vdiskservice.model.data.tlogStoragecluster
        if vdiskservice.model.data.backupStoragecluster:
            vdiskconfig['slaveStorageCluster'] = vdiskservice.model.data.backupStoragecluster

        config['vdisks'][vdiskservice.name] = vdiskconfig

    yamlconfig = yaml.safe_dump(config, default_flow_style=False)
    configstream = BytesIO(yamlconfig.encode('utf8'))
    configstream.seek(0)
    container.client.filesystem.upload(configpath, configstream)

    if not is_job_running(container):
        cmd = '/bin/nbdserver \
            -protocol unix \
            -address "{socketpath}" \
            -config {config} \
            '.format(socketpath=socketpath, config=configpath)
        if tlog:
            tlogservice = service.aysrepo.serviceGet(role='tlogserver', instance=vm.name)
            tlogip = tlogservice.model.data.bind.split(':')
            cmd += '-tlogrpc {tlogip}:{tlogport}'.format(tlogip=tlogip[0], tlogport=tlogip[1])
        job.logger.info("Starting nbd server: %s" % cmd)
        container.client.system(cmd, id="{}.{}".format(service.model.role, service.name))

        # wait for socket to be created
        start = time.time()
        while start + 60 > time.time():
            if is_socket_listening(container, socketpath):
                break
            time.sleep(0.2)
        else:
            raise j.exceptions.RuntimeError("Failed to start nbdserver {}".format(vm.name))
        # make sure nbd is still running
        running = is_job_running(container)
        for vdisk in vdisks:
            if running:
                vdisk.model.data.status = 'running'
                vdisk.saveAll()
        if not running:
            raise j.exceptions.RuntimeError("Failed to start nbdserver {}".format(vm.name))
    else:
        # send a siganl sigub(1) to reload the config in case it was changed.
        import signal
        job = is_job_running(container)
        container.client.job.kill(job['cmd']['id'], signal=int(signal.SIGHUP))
    service.model.data.socketPath = socketpath
    service.saveAll()


def start(job):
    service = job.service
    j.tools.async.wrappers.sync(service.executeAction('install', context=job.context))


def get_storagecluster_config(job, storagecluster):
    from zeroos.orchestrator.sal.StorageCluster import StorageCluster
    storageclusterservice = job.service.aysrepo.serviceGet(role='storage_cluster',
                                                           instance=storagecluster)
    cluster = StorageCluster.from_ays(storageclusterservice, job.context['token'])
    return cluster.get_config()


def stop(job):
    import time
    service = job.service
    container = get_container(service, job.context['token'])

    vm = service.consumers['vm'][0]
    vdisks = vm.producers.get('vdisk', [])

    # Delete tmp vdisks
    for vdiskservice in vdisks:
        j.tools.async.wrappers.sync(vdiskservice.executeAction('pause'))
        if vdiskservice.model.data.type == "tmp":
            j.tools.async.wrappers.sync(vdiskservice.executeAction('delete', context=job.context))

    nbdjob = is_job_running(container)
    if nbdjob:
        job.logger.info("killing job {}".format(nbdjob['cmd']['arguments']['name']))
        container.client.job.kill(nbdjob['cmd']['id'])

        job.logger.info("wait for nbdserver to stop")
        for i in range(60):
            time.sleep(1)
            if is_job_running(container):
                continue
            return
        raise j.exceptions.RuntimeError("nbdserver didn't stopped")


def monitor(job):
    from zeroos.orchestrator.configuration import get_jwt_token

    service = job.service
    if not service.model.actionsState['install'] == 'ok':
        return

    if str(service.parent.model.data.status) != 'running':
        return
    vm = service.consumers['vm'][0]
    vdisks = vm.producers.get('vdisk', [])
    container = get_container(service, get_jwt_token(job.service.aysrepo))
    running = is_job_running(container)
    for vdisk in vdisks:
        if running:
            j.tools.async.wrappers.sync(vdisk.executeAction('start'))
        else:
            j.tools.async.wrappers.sync(vdisk.executeAction('pause'))


def watchdog_handler(job):
    eof = job.model.args['eof']
    service = job.service
    if eof:
        j.tools.async.wrappers.sync(service.executeAction('start', context=job.context))