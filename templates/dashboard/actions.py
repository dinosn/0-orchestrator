def init(job):
    if job.service.model.data.slug != '':
        raise j.exceptions.Input("slug value shouldn't be passed manually")


def install(job):
    service = job.service
    grafanaclient = j.clients.grafana.get(url='http://%s:%d' % (service.parent.parent.model.data.redisAddr, service.parent.model.data.port), username='admin', password='admin')

    result = grafanaclient.updateDashboard(service.model.data.dashboard)
    if result['status'] == 'success':
        service.model.data.slug = result['slug']
        service.saveAll()
    else:
        raise RuntimeError('Cannot add dashboard, got: {}'.format(result))


def uninstall(job):
    service = job.service
    grafanaclient = j.clients.grafana.get(url='http://%s:%d' % (service.parent.parent.model.data.redisAddr, service.parent.model.data.port), username='admin', password='admin')

    result = grafanaclient.deleteDashboard(service.model.data.slug)
    if 'title' in result or result.get('message') == 'Dashboard not found':
        service.model.data.slug = ''
        service.saveAll()
    else:
        raise RuntimeError('Cannot remove dashboard, got: {}'.format(result))

    j.tools.async.wrappers.sync(service.delete())


def processChange(job):
    service = job.service
    args = job.model.args

    if args.pop('changeCategory') != 'dataschema' or service.model.actionsState['install'] in ['new', 'scheduled']:
        return

    if args.get('dashboard'):
        service.model.data.dashboard = args['dashboard']
    j.tools.async.wrappers.sync(service.uninstall())
    j.tools.async.wrappers.sync(service.instal(l))

    service.saveAll()


def init_actions_(service, args):
    return {
        'init': [],
        'install': ['init'],
        'delete': ['uninstall'],
        'uninstall': [],
    }
