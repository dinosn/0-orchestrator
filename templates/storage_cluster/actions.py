from js9 import j


def input(job):
    for arg in ['filesystems', 'arbds']:
        if job.model.args.get(arg, []) != []:
            raise j.exceptions.Input("{} should not be set as input".format(arg))

    nodes = job.model.args.get('nodes', [])
    nrserver = job.model.args.get('nrServer', 0)
    if len(nodes) == 0:
        raise j.exceptions.Input("Invalid amount of nodes provided")
    if nrserver % len(nodes) != 0:
        raise j.exceptions.Input("Invalid spread provided can not evenly spread servers over amount of nodes")

    cluster_type = job.model.args.get("clusterType")

    if cluster_type == "tlog":
        k = job.model.args.get("k", 0)
        m = job.model.args.get("m", 0)
        if not k and not m:
            raise j.exceptions.Input("K and M should be larger than 0")
        if (k + m) > nrserver:
            raise j.exceptions.Input("K and M should be greater than or equal to number of servers")
    return job.model.args


def get_cluster(job):
    from zeroos.orchestrator.sal.StorageCluster import StorageCluster
    return StorageCluster.from_ays(job.service, job.context['token'])


def init(job):
    from zeroos.orchestrator.configuration import get_configuration
    from zeroos.orchestrator.sal.Node import Node

    service = job.service
    nodes = set()
    for node_service in service.producers['node']:
        nodes.add(Node.from_ays(node_service, job.context['token']))
    nodes = list(nodes)
    nodemap = {node.name: node for node in nodes}

    availabledisks = get_availabledisks(job, nodes)
    diskpernode = int(service.model.data.nrServer / len(nodes))
    # validate amount of disks and remove unneeded disks
    if service.model.data.nrServer % len(nodes) != 0:
        raise j.exceptions.Input("Amount of servers is not equally devidable by amount of nodes")
    for node, disks in availabledisks.items():
        if len(disks) < diskpernode:
            raise j.exceptions.Input("Not enough available disks on node {}".format(node))
        availabledisks[node] = disks[:diskpernode]
    for node in nodes:
        if node.name not in availabledisks:
            raise j.exceptions.Input("Not enough available disks on node {}".format(node.name))

    # lets create some services
    spactor = service.aysrepo.actorGet("storagepool")
    fsactor = service.aysrepo.actorGet("filesystem")
    containeractor = service.aysrepo.actorGet("container")
    storageEngineActor = service.aysrepo.actorGet("storage_engine")
    filesystems = []
    storageEngines = []

    def create_server(node, disk, baseport, tcp, variant='data'):
        diskmap = [{'device': disk.devicename}]
        args = {
            'node': node.name,
            'metadataProfile': 'single',
            'dataProfile': 'single',
            'devices': diskmap
        }
        storagepoolname = 'cluster_{}_{}_{}'.format(node.name, service.name, disk.name)
        spservice = spactor.serviceCreate(instance=storagepoolname, args=args)
        service.consume(spservice)
        containername = '{}_{}_{}'.format(storagepoolname, variant, baseport)
        # adding filesystem
        args = {
            'storagePool': storagepoolname,
            'name': containername,
        }
        filesystems.append(fsactor.serviceCreate(instance=containername, args=args))
        config = get_configuration(job.service.aysrepo)

        # create containers
        args = {
            'node': node.name,
            'hostname': containername,
            'flist': config.get('storage-engine-flist', 'https://hub.gig.tech/gig-official-apps/ardb-rocksdb.flist'),
            'mounts': [{'filesystem': containername, 'target': '/mnt/data'}],
            'hostNetworking': True
        }
        containeractor.serviceCreate(instance=containername, args=args)
        # create storageEngines
        args = {
            'homeDir': '/mnt/data',
            'bind': '{}:{}'.format(node.storageAddr, baseport),
            'container': containername
        }
        storageEngine = storageEngineActor.serviceCreate(instance=containername, args=args)
        storageEngine.consume(tcp)
        storageEngines.append(storageEngine)

    for nodename, disks in availabledisks.items():
        node = nodemap[nodename]
        # making the storagepool
        baseports, tcpservices = get_baseports(job, node, baseport=2000, nrports=len(disks) + 1)
        for idx, disk in enumerate(disks):
            create_server(node, disk, baseports[idx], tcpservices[idx])

    if str(service.model.data.clusterType) != 'tlog':
        create_server(node, disk, baseports[-1], tcpservices[-1], variant='metadata')

    service.model.data.init('filesystems', len(filesystems))
    service.model.data.init('storageEngines', len(storageEngines))

    for index, fs in enumerate(filesystems):
        service.consume(fs)
        service.model.data.filesystems[index] = fs.name
    for index, storageEngine in enumerate(storageEngines):
        service.consume(storageEngine)
        service.model.data.storageEngines[index] = storageEngine.name

    grafanasrv = service.aysrepo.serviceGet(role='grafana', instance='statsdb', die=False)
    if grafanasrv:
        dashboard_actor = service.aysrepo.actorGet('dashboard')
        cluster = get_cluster(job)
        board = cluster.dashboard
        args = {
            'grafana': 'statsdb',
            'dashboard': board
        }
        dashboard_actor.serviceCreate(instance=cluster.name, args=args)
    job.service.model.data.status = 'empty'


def get_availabledisks(job, nodes):
    from zeroos.orchestrator.sal.StorageCluster import StorageCluster

    service = job.service
    used_disks = {}
    for node in nodes:
        disks = set()
        pools = service.aysrepo.servicesFind(role='storagepool', parent='node.zero-os!%s' % node.name)
        for pool in pools:
            devices = {device.device for device in pool.model.data.devices}
            disks.update(devices)
        used_disks[node.name] = disks

    cluster = StorageCluster(service.name, nodes, service.model.data.diskType)
    availabledisks = cluster.find_disks()
    freedisks = {}
    for node, disks in availabledisks.items():
        node_disks = []
        for disk in disks:
            if disk.devicename not in used_disks[node]:
                node_disks.append(disk)
        freedisks[node] = node_disks
    return freedisks


def get_baseports(job, node, baseport, nrports):
    service = job.service
    tcps = service.aysrepo.servicesFind(role='tcp', parent='node.zero-os!%s' % node.name)

    usedports = set()
    for tcp in tcps:
        usedports.add(tcp.model.data.port)

    freeports = []
    tcpactor = service.aysrepo.actorGet("tcp")
    tcpservices = []
    while True:
        if baseport not in usedports:
            baseport = node.freeports(baseport=baseport, nrports=1)[0]
            args = {
                'node': node.name,
                'port': baseport,
            }
            tcp = 'tcp_{}_{}'.format(node.name, baseport)
            tcpservices.append(tcpactor.serviceCreate(instance=tcp, args=args))
            freeports.append(baseport)
            if len(freeports) >= nrports:
                return freeports, tcpservices
        baseport += 1


def install(job):
    job.service.model.actions['start'].state = 'ok'
    job.service.model.data.status = 'ready'


def start(job):
    service = job.service

    cluster = get_cluster(job)
    job.logger.info("start cluster {}".format(service.name))
    cluster.start()
    job.service.model.data.status = 'ready'


def stop(job):
    service = job.service
    cluster = get_cluster(job)
    job.logger.info("stop cluster {}".format(service.name))
    cluster.stop()


def delete(job):
    service = job.service
    storageEngines = service.producers.get('storage_engine', [])
    pools = service.producers.get('storagepool', [])

    for storageEngine in storageEngines:
        tcps = storageEngine.producers.get('tcp', [])
        for tcp in tcps:
            j.tools.async.wrappers.sync(tcp.executeAction('drop', context=job.context))
            j.tools.async.wrappers.sync(tcp.delete())

        container = storageEngine.parent
        j.tools.async.wrappers.sync(container.executeAction('stop', context=job.context))
        j.tools.async.wrappers.sync(container.delete())

    for pool in pools:
        j.tools.async.wrappers.sync(pool.executeAction('delete', context=job.context))
        j.tools.async.wrappers.sync(pool.delete())

    job.logger.info("stop cluster {}".format(service.name))
    job.service.model.data.status = 'empty'


def addStorageServer(job):
    raise NotImplementedError()


def reoveStorageServer(job):
    raise NotImplementedError()
