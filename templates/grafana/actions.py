from js9 import j


def get_container(service, force=True):
    containers = service.producers.get('container')
    if not containers:
        if force:
            raise RuntimeError('Service didn\'t consume any containers')
        else:
            return
    return containers[0]


def configure_datasources(job, grafana):
    service = job.service
    influxes = service.producers.get('influxdb')
    for influx in influxes:
        for i, database in enumerate(influx.model.data.databases):
            grafana.add_data_source(database, influx.name, influx.parent.model.data.redisAddr, influx.model.data.port, i)


def init(job):
    from zeroos.orchestrator.configuration import get_configuration

    service = job.service
    container_actor = service.aysrepo.actorGet('container')
    config = get_configuration(service.aysrepo)

    args = {
        'node': service.model.data.node,
        'flist': config.get(
            '0-grafana-flist', 'https://hub.gig.tech/gig-official-apps/grafana.flist'),
        'hostNetworking': True
    }
    cont_service = container_actor.serviceCreate(instance='{}_grafana'.format(service.name), args=args)
    service.consume(cont_service)


def install(job):
    j.tools.async.wrappers.sync(job.service.executeAction('start', context=job.context))


def start(job):
    from zeroos.orchestrator.sal.grafana.grafana import Grafana
    from zeroos.orchestrator.sal.Container import Container

    service = job.service
    container = get_container(service)
    j.tools.async.wrappers.sync(container.executeAction('start', context=job.context))
    container_ays = Container.from_ays(container, job.context['token'])
    grafana = Grafana(container_ays, service.parent.model.data.redisAddr, job.service.model.data.port)
    grafana.start()
    service.model.data.status = 'running'
    configure_datasources(job, grafana)
    service.saveAll()


def stop(job):
    from zeroos.orchestrator.sal.grafana.grafana import Grafana
    from zeroos.orchestrator.sal.Container import Container

    service = job.service
    container = get_container(service)
    container_ays = Container.from_ays(container, job.context['token'])
    if container_ays.is_running():
        grafana = Grafana(container_ays, service.parent.model.data.redisAddr, job.service.model.data.port)
        grafana.stop()
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
    from zeroos.orchestrator.sal.grafana.grafana import Grafana
    from zeroos.orchestrator.sal.Container import Container

    service = job.service
    args = job.model.args

    if args.pop('changeCategory') != 'dataschema' or service.model.actionsState['install'] in ['new', 'scheduled']:
        return
    container = get_container(service)
    container_ays = Container.from_ays(container, job.context['token'])
    grafana = Grafana(container_ays, service.parent.model.data.redisAddr, job.service.model.data.port)

    if args.get('port'):
        if container_ays.is_running() and grafana.is_running()[0]:
            grafana.stop()
            service.model.data.status = 'halted'
            grafana.port = args['port']
            grafana.start()
            service.model.data.status = 'running'
    service.model.data.port = args['port']

    # @TODO: Handle influxdb list change

    service.saveAll()


def init_actions_(service, args):
    return {
        'init': [],
        'install': ['init'],
        'monitor': ['start'],
        'delete': ['uninstall'],
        'uninstall': [],
    }
