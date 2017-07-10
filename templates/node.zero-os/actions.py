from js9 import j


def get_stats_collector(service):
    stats_collectors_services = service.consumers.get('stats_collector')
    if stats_collectors_services:
        return stats_collectors_services[0]


def get_statsdb(service):
    statsdb_services = service.aysrepo.servicesFind(role='statsdb')
    if statsdb_services:
        return statsdb_services[0]


def input(job):
    from zeroos.orchestrator.sal.Node import Node
    from zeroos.orchestrator.configuration import get_configuration, get_jwt_token

    args = job.model.args
    ip = args.get('redisAddr')
    node = Node(ip, args.get('redisPort'), get_jwt_token(job.service.aysrepo))

    config = get_configuration(job.service.aysrepo)
    version = node.client.info.version()
    core0_version = config.get('0-core-version')
    core0_revision = config.get('0-core-revision')

    if (core0_version and core0_version != version['branch']) or \
            (core0_revision and core0_revision != version['revision']):
        raise RuntimeError("Node with IP {} has a wrong version. Found version {}@{} and expected version {}@{} ".format(ip, version['branch'], version['revision'], core0_version, core0_revision))


def init(job):
    from zeroos.orchestrator.sal.Node import Node
    from zeroos.orchestrator.configuration import get_jwt_token

    service = job.service
    node = Node.from_ays(service, get_jwt_token(service.aysrepo))
    job.logger.info("create storage pool for fuse cache")
    poolname = "{}_fscache".format(service.name)

    storagepool = node.ensure_persistance(poolname)
    storagepool.ays.create(service.aysrepo)

    statsdb_service = get_statsdb(service)
    if statsdb_service:
        stats_collector_actor = service.aysrepo.actorGet('stats_collector')
        args = {
            'node': service.name,
            'port': statsdb_service.model.data.port,
            'ip': statsdb_service.parent.model.data.redisAddr,

        }
        stats_collector_service = stats_collector_actor.serviceCreate(instance=service.name, args=args)
        stats_collector_service.consume(service)


def getAddresses(job):
    service = job.service
    networks = service.producers.get('network', [])
    networkmap = {}
    for network in networks:
        job = network.getJob('getAddresses', args={'node_name': service.name})
        networkmap[network.name] = j.tools.async.wrappers.sync(job.execute())
    return networkmap


def isConfigured(node, name):
    poolname = "{}_fscache".format(name)
    fscache_sp = node.find_persistance(poolname)
    if fscache_sp is None:
        return False
    return bool(fscache_sp.mountpoint)


def install(job):
    from zeroos.orchestrator.sal.Node import Node
    from zeroos.orchestrator.configuration import get_jwt_token

    # at each boot recreate the complete state in the system
    service = job.service
    node = Node.from_ays(service, get_jwt_token(job.service.aysrepo))
    job.logger.info("mount storage pool for fuse cache")
    poolname = "{}_fscache".format(service.name)
    node.ensure_persistance(poolname)

    job.logger.info("configure networks")
    for network in service.producers.get('network', []):
        job = network.getJob('configure', args={'node_name': service.name})
        j.tools.async.wrappers.sync(job.execute())

    stats_collector_service = get_stats_collector(service)
    statsdb_service = get_statsdb(service)
    if stats_collector_service and statsdb_service and statsdb_service.model.data.status == 'running':
        j.tools.async.wrappers.sync(stats_collector_service.executeAction(
            'install', context=job.context))


def monitor(job):
    from zeroos.orchestrator.sal.Node import Node
    from zeroos.orchestrator.configuration import get_jwt_token
    import redis
    service = job.service
    token = get_jwt_token(job.service.aysrepo)
    if service.model.actionsState['install'] != 'ok':
        return

    try:
        node = Node.from_ays(service, token, timeout=15)
        node.client.testConnectionAttempts = 0
        state = node.client.ping()
    except RuntimeError:
        state = False
    except redis.ConnectionError:
        state = False

    if state:
        service.model.data.status = 'running'
        configured = isConfigured(node, service.name)
        if not configured:
            job = service.getJob('install', args={})
            j.tools.async.wrappers.sync(job.execute())

        job.context['token'] = token
        stats_collector_service = get_stats_collector(service)
        statsdb_service = get_statsdb(service)

        # Check if statsdb is installed on this node and start it if needed
        if (statsdb_service and str(statsdb_service.parent) == str(job.service)
                and statsdb_service.model.data.status != 'running'):
            j.tools.async.wrappers.sync(statsdb_service.executeAction(
                'start', context=job.context))

        # Check if there is a running statsdb and if so make sure stats_collector for this node is started
        if (stats_collector_service and stats_collector_service.model.data.status != 'running'
                and statsdb_service.model.data.status == 'running'):
            j.tools.async.wrappers.sync(stats_collector_service.executeAction(
                'start', context=job.context))
    else:
        service.model.data.status = 'halted'
    service.saveAll()


def reboot(job):
    from zeroos.orchestrator.sal.Node import Node
    service = job.service

    # Check if statsdb is installed on this node and stop it
    statsdb_service = get_statsdb(service)
    if statsdb_service and str(statsdb_service.parent) == str(job.service):
        j.tools.async.wrappers.sync(statsdb_service.executeAction(
            'stop', context=job.context))

    # Chceck if stats_collector is installed on this node and stop it
    stats_collector_service = get_stats_collector(service)
    if stats_collector_service and stats_collector_service.model.data.status == 'running':
        j.tools.async.wrappers.sync(stats_collector_service.executeAction(
            'stop', context=job.context))

    job.logger.info("reboot node {}".format(service))
    node = Node.from_ays(service, job.context['token'])
    node.client.raw('core.reboot', {})


def uninstall(job):
    service = job.service
    stats_collector_service = get_stats_collector(service)
    if stats_collector_service:
        j.tools.async.wrappers.sync(stats_collector_service.executeAction(
            'uninstall', context=job.context))

    statsdb_service = get_statsdb(service)
    if statsdb_service and str(statsdb_service.parent) == str(service):
        j.tools.async.wrappers.sync(statsdb_service.executeAction(
            'uninstall', context=job.context))

    bootstraps = service.aysrepo.servicesFind(actor='bootstrap.zero-os')
    if bootstraps:
        j.tools.async.wrappers.sync(bootstraps[0].getJob('delete_node', args={'node_name': service.name}).execute())
