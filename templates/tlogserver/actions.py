from js9 import j


def get_container(service, password):
    from zeroos.orchestrator.sal.Container import Container
    return Container.from_ays(service.parent, password)


def is_port_listening(container, port, timeout=60):
    import time
    start = time.time()
    while start + timeout > time.time():
        if port not in container.node.freeports(port, nrports=3):
            return True
        time.sleep(0.2)
    return False


def is_job_running(container, cmd='/bin/tlogserver'):
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


def install(job):
    import yaml
    from io import BytesIO
    service = job.service
    vm = service.aysrepo.serviceGet(role='vm', instance=service.name)
    vdisks = vm.producers.get('vdisk', [])
    container = get_container(service, job.context['token'])
    config = {
        'vdisks': {},
        'storageClusters': {},
        'k': 0,
        'm': 0,
    }

    backup = False
    for vdiskservice in vdisks:
        tlogcluster = vdiskservice.model.data.tlogStoragecluster
        if tlogcluster and tlogcluster not in config['storageClusters']:
            clusterconfig, k, m = get_storagecluster_config(job, tlogcluster)
            config['storageClusters'][tlogcluster] = {"dataStorage": clusterconfig["dataStorage"]}
            config['vdisks'][vdiskservice.name] = {'tlogStorageCluster': tlogcluster}
            config['k'] += k
            config['m'] += m

        backupcluster = vdiskservice.model.data.backupStoragecluster
        if backupcluster and backupcluster not in config['storageClusters']:
            vdisk_type = "cache" if str(vdiskservice.model.data.type) == "tmp" else str(vdiskservice.model.data.type)
            clusterconfig, _, _ = get_storagecluster_config(job, backupcluster)
            config['storageClusters'][backupcluster] = clusterconfig
            vdisk = config['vdisks'][vdiskservice.name]
            vdisk['storageCluster'] = backupcluster
            vdisk['tlogSlaveSync'] = True
            vdisk['blockSize'] = vdiskservice.model.data.blocksize
            vdisk['readOnly'] = vdiskservice.model.data.readOnly
            vdisk['size'] = vdiskservice.model.data.size
            vdisk['type'] = vdisk_type

            backup = True

    if config['storageClusters']:
        k = config.pop('k')
        m = config.pop('m')

        configpath = "/tlog_{}.config".format(service.name)
        yamlconfig = yaml.safe_dump(config, default_flow_style=False)
        configstream = BytesIO(yamlconfig.encode('utf8'))
        configstream.seek(0)
        container.client.filesystem.upload(configpath, configstream)
        bind = service.model.data.bind or None
        if not bind or not is_port_listening(container, int(bind.split(':')[1])):
            ip = container.node.storageAddr
            port = container.node.freeports(baseport=11211, nrports=1)[0]
            logpath = '/tlog_{}.log'.format(service.name)
            cmd = '/bin/tlogserver \
                    -address {ip}:{port} \
                    -k {k} \
                    -m {m} \
                    -config {config} \
                    '.format(ip=ip,
                             port=port,
                             config=configpath,
                             k=k,
                             m=m,
                             log=logpath)
            if backup:
                cmd += '-with-slave-sync'
            container.client.system(cmd, id="{}.{}".format(service.model.role, service.name))
            if not is_port_listening(container, port):
                raise j.exceptions.RuntimeError('Failed to start tlogserver {}'.format(service.name))
            service.model.data.bind = '%s:%s' % (ip, port)
            if service.model.data.status != 'running':
                container.node.client.nft.open_port(port)
                service.model.data.status = 'running'
        else:
            # send a siganl sigub(1) to reload the config in case it was changed.
            import signal
            port = int(service.model.data.bind.split(':')[1])
            job = is_job_running(container)
            container.client.job.kill(job['cmd']['id'], signal=int(signal.SIGHUP))
            service.model.data.status = 'running'


def start(job):
    service = job.service
    j.tools.async.wrappers.sync(service.executeAction('install', context=job.context))


def get_storagecluster_config(job, storagecluster):
    from zeroos.orchestrator.sal.StorageCluster import StorageCluster
    storageclusterservice = job.service.aysrepo.serviceGet(role='storage_cluster',
                                                           instance=storagecluster)
    cluster = StorageCluster.from_ays(storageclusterservice, job.context['token'])
    return cluster.get_config(), cluster.k, cluster.m


def stop(job):
    import time
    service = job.service
    service.model.data.status = 'halting'
    container = get_container(service, job.context['token'])
    bind = service.model.data.bind
    if bind:
        port = int(bind.split(':')[1])
        container.node.client.nft.drop_port(port)
        tlogjob = is_job_running(container)
        if tlogjob:
            job.logger.info("killing job {}".format(tlogjob['cmd']['arguments']['name']))
            container.client.job.kill(tlogjob['cmd']['id'])

            job.logger.info("wait for tlogserver to stop")
            for i in range(60):
                time.sleep(1)
                if not is_port_listening(container, port):
                    break
                raise j.exceptions.RuntimeError("Failed to stop Tlog server")
    service.model.data.status = 'halted'


def monitor(job):
    from zeroos.orchestrator.configuration import get_jwt_token

    service = job.service
    if not service.model.actionsState['install'] == 'ok':
        return

    if str(service.model.data.status) != 'running':
        return

    bind = service.model.data.bind
    port = int(bind.split(':')[1])
    container = get_container(service, get_jwt_token(job.service.aysrepo))
    if is_port_listening(container, port):
        return

    j.tools.async.wrappers.sync(service.executeAction('start', context={"token": get_jwt_token(job.service.aysrepo)}))


def watchdog_handler(job):
    service = job.service
    if str(service.model.data.status) != 'running':
        return
    eof = job.model.args['eof']
    if eof:
        j.tools.async.wrappers.sync(service.executeAction('start', context=job.context))
