from js9 import j


def input(job):
    ays_repo = job.service.aysrepo
    services = ays_repo.servicesFind(actor=job.service.model.dbobj.actorName)

    if services and job.service.name != services[0].name:
        raise j.exceptions.RuntimeError('Repo can\'t contain multiple statsdb services')


def init(job):
    from zeroos.orchestrator.sal.templates import render
    from zeroos.orchestrator.sal.StorageCluster import StorageCluster
    service = job.service
    influxdb_actor = service.aysrepo.actorGet('influxdb')

    args = {
        'node': service.model.data.node,
        'port': service.model.data.port,
        'databases': ['statistics']
    }
    influxdb_service = influxdb_actor.serviceCreate(instance='statsdb', args=args)
    service.consume(influxdb_service)

    grafana_actor = service.aysrepo.actorGet('grafana')

    args = {
        'node': service.model.data.node,
        'influxdb': ['statsdb']
    }
    grafana_service = grafana_actor.serviceCreate(instance='statsdb', args=args)
    service.consume(grafana_service)

    dashboard_actor = service.aysrepo.actorGet('dashboard')

    args = {
        'grafana': 'statsdb',
        'dashboard': render('dashboards/overview.json')
    }
    dashboard_actor.serviceCreate(instance='overview', args=args)

    # Install stats_collector on all nodes
    stats_collector_actor = job.service.aysrepo.actorGet('stats_collector')
    node_services = job.service.aysrepo.servicesFind(actor='node.zero-os')
    for node_service in node_services:
        stats_collector_service = get_stats_collector_from_node(node_service)
        if not stats_collector_service:
            args = {
                'node': node_service.name,
                'port': job.service.model.data.port,
                'ip': job.service.parent.model.data.redisAddr,

            }
            stats_collector_service = stats_collector_actor.serviceCreate(instance=node_service.name, args=args)
            stats_collector_service.consume(node_service)

    # Create storage cluster dashboards
    cluster_services = job.service.aysrepo.servicesFind(actor='storage_cluster')
    for clusterservice in cluster_services:
        cluster = StorageCluster.from_ays(clusterservice, '')
        board = cluster.dashboard

        args = {
            'grafana': 'statsdb',
            'dashboard': board
        }
        dashboard_actor.serviceCreate(instance=cluster.name, args=args)
        stats_collector_service.consume(clusterservice)


def get_influxdb(service, force=True):
    influxdbs = service.producers.get('influxdb')
    if not influxdbs:
        if force:
            raise RuntimeError('Service didn\'t consume any influxdbs')
        else:
            return
    return influxdbs[0]


def get_grafana(service, force=True):
    grafanas = service.producers.get('grafana')
    if not grafanas:
        if force:
            raise RuntimeError('Service didn\'t consume any grafana')
        else:
            return
    return grafanas[0]


def get_stats_collector_from_node(service):
    stats_collectors_services = service.consumers.get('stats_collector')
    if stats_collectors_services:
        return stats_collectors_services[0]


def install(job):
    j.tools.async.wrappers.sync(job.service.executeAction('start', context=job.context))


def start(job):
    influxdb = get_influxdb(job.service)
    grafana = get_grafana(job.service)
    j.tools.async.wrappers.sync(influxdb.executeAction('install', context=job.context))
    j.tools.async.wrappers.sync(grafana.executeAction('install', context=job.context))
    job.service.model.data.status = 'running'
    job.service.saveAll()

    # Install stats_collector on all nodes
    node_services = job.service.aysrepo.servicesFind(actor='node.zero-os')
    for node_service in node_services:
        stats_collector_service = get_stats_collector_from_node(node_service)

        if stats_collector_service:
            if stats_collector_service.model.data.status == 'running':
                j.tools.async.wrappers.sync(stats_collector_service.executeAction('stop', context=job.context))
            j.tools.async.wrappers.sync(stats_collector_service.executeAction('start', context=job.context))


def stop(job):
    influxdb = get_influxdb(job.service)
    grafana = get_grafana(job.service)
    j.tools.async.wrappers.sync(influxdb.executeAction('stop', context=job.context))
    j.tools.async.wrappers.sync(grafana.executeAction('stop', context=job.context))
    job.service.model.data.status = 'halted'
    job.service.saveAll()
    node_services = job.service.aysrepo.servicesFind(actor='node.zero-os')
    for node_service in node_services:
        stats_collector_service = get_stats_collector_from_node(node_service)
        if stats_collector_service and stats_collector_service.model.data.status == 'running':
            j.tools.async.wrappers.sync(stats_collector_service.executeAction('stop', context=job.context))


def uninstall(job):
    influxdb = get_influxdb(job.service, False)
    grafana = get_grafana(job.service, False)

    if grafana:
        j.tools.async.wrappers.sync(grafana.executeAction('uninstall', context=job.context))
    if influxdb:
        j.tools.async.wrappers.sync(influxdb.executeAction('uninstall', context=job.context))

    node_services = job.service.aysrepo.servicesFind(actor='node.zero-os')
    for node_service in node_services:
        stats_collector_service = get_stats_collector_from_node(node_service)
        if stats_collector_service:
            j.tools.async.wrappers.sync(stats_collector_service.executeAction('uninstall', context=job.context))
    j.tools.async.wrappers.sync(job.service.delete())


def processChange(job):
    from zeroos.orchestrator.configuration import get_jwt_token_from_job
    service = job.service
    args = job.model.args
    if args.get('changeCategory') != 'dataschema' or service.model.actionsState['install'] in ['new', 'scheduled']:
        return

    if args.get('port'):
        influxdb = get_influxdb(job.service)
        grafana = get_grafana(job.service)
        job.context['token'] = get_jwt_token_from_job(job)
        j.tools.async.wrappers.sync(
            influxdb.executeAction('processChange', context=job.context, args=args))
        j.tools.async.wrappers.sync(
            grafana.executeAction('processChange', context=job.context, args=args))
        influxdb = get_influxdb(job.service)
        grafana = get_grafana(job.service)
        if str(influxdb.model.data.status) == 'running' and str(grafana.model.data.status) == 'running':
            job.service.model.data.status = str(influxdb.model.data.status)
        else:
            job.service.model.data.status = 'halted'
    service.saveAll()


def init_actions_(service, args):
    return {
        'init': [],
        'install': ['init'],
        'monitor': ['start'],
        'delete': ['uninstall'],
        'uninstall': [],
    }
