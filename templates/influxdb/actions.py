def get_container(service, force=True):
    containers = service.producers.get('container')
    if not containers:
        if force:
            raise RuntimeError('Service didn\'t consume any containers')
        else:
            return
    return containers[0]


def init(job):
    from zeroos.orchestrator.configuration import get_configuration

    service = job.service
    container_actor = service.aysrepo.actorGet('container')
    config = get_configuration(service.aysrepo)

    args = {
        'node': service.model.data.node,
        'flist': config.get(
            'influxdb-flist', 'https://hub.gig.tech/gig-official-apps/influxdb.flist'),
        'hostNetworking': True
    }
    cont_service = container_actor.serviceCreate(instance='{}_influxdb'.format(service.name), args=args)
    service.consume(cont_service)


def install(job):
    j.tools.async.wrappers.sync(job.service.executeAction('start', context=job.context))


def start(job):
    from zeroos.orchestrator.sal.Container import Container
    from zeroos.orchestrator.sal.influxdb.influxdb import InfluxDB

    service = job.service
    container = get_container(service)
    j.tools.async.wrappers.sync(container.executeAction('start', context=job.context))
    container_ays = Container.from_ays(container, job.context['token'])
    influx = InfluxDB(
        container_ays, service.parent.model.data.redisAddr, service.model.data.port)
    influx.start()
    service.model.data.status = 'running'
    influx.create_databases(service.model.data.databases)
    service.saveAll()


def stop(job):
    from zeroos.orchestrator.sal.Container import Container
    from zeroos.orchestrator.sal.influxdb.influxdb import InfluxDB

    service = job.service
    container = get_container(service)
    container_ays = Container.from_ays(container, job.context['token'])

    if container_ays.is_running():
        influx = InfluxDB(
            container_ays, service.parent.model.data.redisAddr, service.model.data.port)
        influx.stop()
        j.tools.async.wrappers.sync(container.executeAction('stop', context=job.context))
    service.model.data.status = 'halted'
    service.saveAll()


def uninstall(job):
    service = job.service
    container = get_container(service, False)

    if container:
        j.tools.async.wrappers.sync(service.executeAction('stop', context=job.context))
        j.tools.async.wrappers.sync(container.delete())
    j.tools.async.wrappers.sync(service.delete())


def processChange(job):
    from zeroos.orchestrator.sal.Container import Container
    from zeroos.orchestrator.sal.influxdb.influxdb import InfluxDB
    from zeroos.orchestrator.configuration import get_jwt_token_from_job

    service = job.service
    args = job.model.args
    if args.pop('changeCategory') != 'dataschema' or service.model.actionsState['install'] in ['new', 'scheduled']:
        return

    container_service = get_container(service)

    container = Container.from_ays(container_service, get_jwt_token_from_job(job))
    influx = InfluxDB(
        container, service.parent.model.data.redisAddr, service.model.data.port)

    if args.get('port'):
        if container.is_running() and influx.is_running()[0]:
            influx.stop()
            service.model.data.status = 'halted'
            influx.port = args['port']
            influx.start()
            service.model.data.status = 'running'
        service.model.data.port = args['port']

    if args.get('databases'):
        if container.is_running() and influx.is_running()[0]:
            create_dbs = set(args['databases']) - set(service.model.data.databases)
            drop_dbs = set(service.model.data.databases) - set(args['databases'])
            influx.create_databases(create_dbs)
            influx.drop_databases(drop_dbs)
        service.model.data.databases = args['databases']

    service.saveAll()


def init_actions_(service, args):
    return {
        'init': [],
        'install': ['init'],
        'monitor': ['start'],
        'delete': ['uninstall'],
        'uninstall': [],
    }