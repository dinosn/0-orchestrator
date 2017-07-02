from js9 import j


def install(job):
    j.tools.async.wrappers.sync(job.service.executeAction('start', context=job.context))


def start(job):
    from zeroos.orchestrator.sal.ARDB import ARDB

    service = job.service
    ardb = ARDB.from_ays(service, job.context['token'])
    ardb.start()
    service.model.data.status = 'running'


def stop(job):
    from zeroos.orchestrator.sal.ARDB import ARDB

    service = job.service
    ardb = ARDB.from_ays(service, job.context['token'])
    ardb.stop()
    service.model.data.status = 'halted'


def monitor(job):
    from zeroos.orchestrator.sal.ARDB import ARDB
    from zeroos.orchestrator.configuration import get_jwt_token

    service = job.service

    if service.model.actionsState['install'] == 'ok':
        ardb = ARDB.from_ays(service, get_jwt_token(service.aysrepo))
        running, process = ardb.is_running()

        if not running:
            try:
                job.logger.warning("ardb {} not running, trying to restart".format(service.name))
                service.model.data.status = 'halted'
                ardb.start()
                running, _ = ardb.is_running()
                if running:
                    service.model.data.status = 'running'
            except:
                job.logger.error("can't restart ardb {} not running".format(service.name))
                service.model.data.status = 'halted'
