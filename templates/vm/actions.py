from js9 import j


def input(job):
    service = job.service
    # Check the blueprint input for errors
    args = job.model.args
    if args.get('vdisks'):
        raise j.exceptions.Input('vdisks property should not be set in the blueprint. Instead use disks property.')
    disks = args.get("disks", [])
    args['vdisks'] = []
    if disks != []:
        for disk in disks:
            if not disk["vdiskid"]:
                continue
            service.aysrepo.serviceGet(role='vdisk', instance=disk["vdiskid"])
            args['vdisks'].append(disk['vdiskid'])
    return args


def get_node(job):
    from zeroos.orchestrator.sal.Node import Node
    return Node.from_ays(job.service.parent, job.context['token'])


def create_zerodisk_container(job, parent):
    """
    first check if the vdisks container for this vm exists.
    if not it creates it.
    return the container service
    """
    from zeroos.orchestrator.configuration import get_configuration
    service = job.service
    config = get_configuration(service.aysrepo)
    actor = service.aysrepo.actorGet("container")
    args = {
        'node': parent.name,
        'flist': config.get('0-disk-flist', 'https://hub.gig.tech/gig-official-apps/0-disk-master.flist'),
        'hostNetworking': True,
    }
    container_name = 'vdisks_{}_{}'.format(service.name, parent.name)
    containerservice = actor.serviceCreate(instance=container_name, args=args)
    # make sure the container has the right parent, the node where this vm runs.
    containerservice.model.changeParent(parent)
    j.tools.async.wrappers.sync(containerservice.executeAction('start', context=job.context))

    return containerservice


def create_service(service, container, role='nbdserver'):
    """
    first check if the nbd server exists.'zerodisk'
    if not it creates it.
    return the nbdserver service
    """
    service_name = service.name

    try:
        nbdserver = service.aysrepo.serviceGet(role=role, instance=service_name)
    except j.exceptions.NotFound:
        nbdserver = None

    if nbdserver is None:
        nbd_actor = service.aysrepo.actorGet(role)
        args = {
            'container': container.name,
        }
        nbdserver = nbd_actor.serviceCreate(instance=service_name, args=args)
    return nbdserver


def _init_zerodisk_services(job, nbd_container, tlog_container=None):
    service = job.service
    # Create nbderver service
    nbdserver = create_service(service, nbd_container)
    job.logger.info("creates nbd server for vm {}".format(service.name))
    service.consume(nbdserver)

    if tlog_container:
        # Create tlogserver service
        tlogserver = create_service(service, tlog_container, role='tlogserver')
        job.logger.info("creates tlog server for vm {}".format(service.name))
        service.consume(tlogserver)
        nbdserver.consume(tlogserver)


def _nbd_url(container, nbdserver, vdisk):
    container_root = container.info['container']['root']
    socket_path = j.sal.fs.joinPaths(container_root, nbdserver.model.data.socketPath.lstrip('/'))
    return 'nbd+unix:///{id}?socket={socket}'.format(id=vdisk, socket=socket_path)


def init(job):
    import random
    service = job.service

    # creates all nbd servers for each vdisk this vm uses
    job.logger.info("creates vdisks container for vm {}".format(service.name))
    services = [ node for node in service.aysrepo.servicesFind(role="node") if node.model.data.status != "halted" ]

    node = random.choice(services)
    if len(services) > 1 and node.name == service.parent.name:
        node = services.index(node)
        services.pop(node)
        node = random.choice(services)

    tlog_container = create_zerodisk_container(job, node)

    nbd_container = create_zerodisk_container(job, service.parent)
    _init_zerodisk_services(job, nbd_container, tlog_container)


def _start_nbd(job):
    from zeroos.orchestrator.sal.Container import Container

    # get all path to the vdisks serve by the nbdservers
    medias = []
    nbdservers = job.service.producers.get('nbdserver', None)
    if not nbdservers:
        raise j.exceptions.RuntimeError("Failed to start nbds, no nbds created to start")
    nbdserver = nbdservers[0]
    # build full path of the nbdserver unix socket on the host filesystem
    container = Container.from_ays(nbdserver.parent, job.context['token'])
    if not container.is_running():
        # start container
        j.tools.async.wrappers.sync(nbdserver.parent.executeAction('start', context=job.context))

    # make sure the nbdserver is started
    j.tools.async.wrappers.sync(nbdserver.executeAction('start', context=job.context))
    for vdisk in job.service.model.data.vdisks:
        url = _nbd_url(container, nbdserver, vdisk)
        medias.append({'url': url})
    return medias


def start_tlog(job):
    from zeroos.orchestrator.sal.Container import Container

    tlogservers = job.service.producers.get('tlogserver', None)
    if not tlogservers:
        raise j.exceptions.RuntimeError("Failed to start tlogs, no tlogs created to start")
    tlogserver = tlogservers[0]
    # build full path of the tlogserver unix socket on the host filesystem
    container = Container.from_ays(tlogserver.parent, password=job.context['token'])
    # make sure container is up
    if not container.is_running():
        j.tools.async.wrappers.sync(tlogserver.parent.executeAction('start', context=job.context))

    # make sure the tlogserver is started
    j.tools.async.wrappers.sync(tlogserver.executeAction('start', context=job.context))


def get_media_for_disk(medias, disk):
    from urllib.parse import urlparse
    for media in medias:
        url = urlparse(media['url'])
        if disk['vdiskid'] == url.path.lstrip('/'):
            return media


def install(job):
    import time
    service = job.service

    # get all path to the vdisks serve by the nbdservers
    start_tlog(job)
    medias = _start_nbd(job)

    job.logger.info("create vm {}".format(service.name))
    node = get_node(job)
    nics = []
    for nic in service.model.data.nics:
        nic = nic.to_dict()
        nic['hwaddr'] = nic.pop('macaddress', None)
        nics.append(nic)
    for disk in service.model.data.disks:
        if disk.maxIOps > 0:
            media = get_media_for_disk(medias, disk.to_dict())
            media['iotune'] = {'totaliopssec': disk.maxIOps,
                               'totaliopssecset': True}

    kvm = get_domain(job)
    if not kvm:
        node.client.kvm.create(
            service.name,
            media=medias,
            cpu=service.model.data.cpu,
            memory=service.model.data.memory,
            nics=nics,
        )
        # wait for max 60 seconds for vm to be running
        start = time.time()
        while start + 60 > time.time():
            kvm = get_domain(job)
            if kvm:
                service.model.data.vnc = kvm['vnc']
                if kvm['vnc'] != -1:
                    node.client.nft.open_port(kvm['vnc'])
                break
            else:
                time.sleep(3)
        else:
            service.model.data.status = 'error'
            raise j.exceptions.RuntimeError("Failed to start vm {}".format(service.name))

    service.model.data.status = 'running'
    service.saveAll()


def start(job):
    service = job.service
    service.model.data.status = 'starting'
    service.saveAll()
    j.tools.async.wrappers.sync(service.executeAction('install', context=job.context))


def get_domain(job):
    node = get_node(job)
    for kvm in node.client.kvm.list():
        if kvm['name'] == job.service.name:
            return kvm


def stop(job):
    service = job.service
    job.logger.info("stop vm {}".format(service.name))
    node = get_node(job)
    kvm = get_domain(job)
    if kvm:
        node.client.kvm.destroy(kvm['uuid'])
    cleanupzerodisk(job)


def destroy(job):
    stop(job)
    service = job.service
    tlogservers = service.producers.get('tlogserver', [])
    nbdservers = service.producers.get('nbdserver', [])

    for tlogserver in tlogservers:
        j.tools.async.wrappers.sync(tlogserver.delete())
        j.tools.async.wrappers.sync(tlogserver.parent.delete())

    for nbdserver in nbdservers:
        j.tools.async.wrappers.sync(nbdserver.delete())
        j.tools.async.wrappers.sync(nbdserver.parent.delete())


def cleanupzerodisk(job):
    service = job.service
    for nbdserver in service.producers.get('nbdserver', []):
        job.logger.info("stop nbdserver for vm {}".format(service.name))
        # make sure the nbdserver is stopped
        j.tools.async.wrappers.sync(nbdserver.executeAction('stop', context=job.context))

    for tlogserver in service.producers.get('tlogserver', []):
        job.logger.info("stop tlogserver for vm {}".format(service.name))
        # make sure the tlogserver is stopped
        j.tools.async.wrappers.sync(tlogserver.executeAction('stop', context=job.context))

    job.logger.info("stop vdisks container for vm {}".format(service.name))
    try:
        container_name = 'vdisks_{}_{}'.format(service.name, service.parent.name)
        container = service.aysrepo.serviceGet(role='container', instance=container_name)
        j.tools.async.wrappers.sync(container.executeAction('stop', context=job.context))
    except j.exceptions.NotFound:
        job.logger.info("container doesn't exists.")

    service.model.data.status = 'halted'

    node = get_node(job)

    vnc = service.model.data.vnc
    if vnc != -1:
        node.client.nft.drop_port(vnc)
        service.model.data.vnc = -1

    service.saveAll()


def pause(job):
    service = job.service
    job.logger.info("pause vm {}".format(service.name))
    node = get_node(job)
    kvm = get_domain(job)
    if kvm:
        node.client.kvm.pause(kvm['uuid'])
        service.model.data.status = 'paused'
        service.saveAll()


def resume(job):
    service = job.service
    job.logger.info("resume vm {}".format(service.name))
    node = get_node(job)
    kvm = get_domain(job)
    if kvm:
        node.client.kvm.resume(kvm['uuid'])
        service.model.data.status = 'running'
        service.saveAll()


def shutdown(job):
    import time
    service = job.service
    job.logger.info("shutdown vm {}".format(service.name))
    node = get_node(job)
    kvm = get_domain(job)
    if kvm:
        service.model.data.status = 'halting'
        node.client.kvm.shutdown(kvm['uuid'])
        # wait for max 60 seconds for vm to be shutdown
        start = time.time()
        while start + 60 > time.time():
            kvm = get_domain(job)
            if kvm:
                time.sleep(3)
            else:
                cleanupzerodisk(job)
                service.model.data.status = 'halted'
                break
        else:
            service.model.data.status = 'error'
            raise j.exceptions.RuntimeError("Failed to shutdown vm {}".format(service.name))
    else:
        service.model.data.status = 'halted'
        cleanupzerodisk(job)

    service.saveAll()


def migrate(job):
    service = job.service

    service.model.data.status = 'migrating'

    node = job.service.model.data.node
    if not node:
        raise j.exceptions.Input("migrate action expect to have the destination node in the argument")

    target_node = service.aysrepo.serviceGet('node', node)
    job.logger.info("start migration of vm {} from {} to {}".format(service.name, service.parent.name, target_node.name))

    old_nbd = service.producers.get('nbdserver', [])
    container_name = 'vdisks_{}_{}'.format(service.name, service.parent.name)
    old_vdisk_container = service.aysrepo.serviceGet('container', container_name)

    # start new nbdserver on target node
    vdisk_container = create_zerodisk_container(job, target_node)
    job.logger.info("start nbd server for migration of vm {}".format(service.name))
    nbdserver = create_service(service, vdisk_container)
    service.consume(nbdserver)

    # TODO: migrate domain, not impleented yet in core0

    service.model.changeParent(target_node)
    service.model.data.status = 'running'

    # delete current nbd services and volue container
    job.logger.info("delete current nbd services and vdisk container")
    for nbdserver in old_nbd:
        j.tools.async.wrappers.sync(nbdserver.executeAction('stop', context=job.context))
        j.tools.async.wrappers.sync(nbdserver.delete())

    j.tools.async.wrappers.sync(old_vdisk_container.executeAction('stop', context=job.context))
    j.tools.async.wrappers.sync(old_vdisk_container.delete())
    service.saveAll()


def _remove_duplicates(col):
    try:
        return [dict(t) for t in set([tuple(element.items()) for element in col])]
    except AttributeError:
        return [dict(t) for t in set([tuple(element.to_dict().items()) for element in col])]


def _diff(col1, col2):
    col1 = _remove_duplicates(col1)
    col2 = _remove_duplicates(col2)
    return [elem for elem in col1 if elem not in col2]


def updateDisks(job, client, args):
    from zeroos.orchestrator.sal.Container import Container
    service = job.service

    uuid = get_domain(job)['uuid']

    # mean we want to migrate vm from a node to another
    if 'node' in args and args['node'] != service.model.data.node:
        j.tools.async.wrappers.sync(service.executeAction('migrate', context=job.context, args={'node': args['node']}))

    # Get new and old disks
    new_disks = _diff(args.get('disks', []), service.model.data.disks)
    old_disks = _diff(service.model.data.disks, args.get('disks', []))

    # Do nothing if no disk change
    if new_disks == [] and old_disks == []:
        return

    # Set model to new data
    service.model.data.disks = args.get('disks', [])
    vdisk_container = create_zerodisk_container(job, service.parent)
    container = Container.from_ays(vdisk_container, job.context['token'])

    # Detatching and Cleaning old disks
    if old_disks != []:
        nbdserver = service.producers.get('nbdserver', [])[0]
        for old_disk in old_disks:
            url = _nbd_url(container, nbdserver, old_disk['vdiskid'])
            client.client.kvm.detach_disk(uuid, {'url': url})
            j.tools.async.wrappers.sync(nbdserver.executeAction('install', context=job.context))

    # Attaching new disks
    if new_disks != []:
        _init_zerodisk_services(job, vdisk_container)
        for disk in new_disks:
            diskservice = service.aysrepo.serviceGet('vdisk', disk['vdiskid'])
            service.consume(diskservice)
        service.saveAll()
        _start_nbd(job)
        nbdserver = service.producers.get('nbdserver', [])[0]
        for disk in new_disks:
            media = {'url': _nbd_url(container, nbdserver, disk['vdiskid'])}
            if disk['maxIOps']:
                media['iotune'] = {'totaliopssec': disk['maxIOps'],
                                   'totaliopssecset': True}
            client.client.kvm.attach_disk(uuid, media)
    service.saveAll()


def updateNics(job, client, args):
    service = job.service
    uuid = get_domain(job)['uuid']

    # Get new and old disks
    new_nics = _diff(args.get('nics', []), service.model.data.nics)
    old_nics = _diff(service.model.data.nics, args.get('nics', []))
    # Do nothing if no nic change
    if new_nics == [] and old_nics == []:
        return

    # Add new nics
    for nic in new_nics:
        if nic not in service.model.data.nics:
            client.client.kvm.add_nic(uuid=uuid,
                                      type=nic['type'],
                                      id=nic['id'] or None,
                                      hwaddr=nic['macaddress'] or None)

    # Remove old nics
    for nic in old_nics:
        client.client.kvm.remove_nic(uuid=uuid,
                                     type=nic['type'],
                                     id=nic['id'] or None,
                                     hwaddr=nic['macaddress'] or None)

    service.model.data.nics = args.get('nics', [])
    service.saveAll()


def monitor(job):
    pass
    # raise NotADirectoryError()


def update_data(job, args):
    service = job.service
    service.model.data.node = args.get('node', service.model.data.node)
    service.model.data.memory = args.get('memory', service.model.data.memory)
    service.model.data.cpu = args.get('cpu', service.model.data.cpu)


def processChange(job):
    from zeroos.orchestrator.configuration import get_jwt_token_from_job

    service = job.service
    args = job.model.args
    category = args.pop('changeCategory')
    if category == "dataschema" and service.model.actionsState['install'] == 'ok':
        try:
            job.context['token'] = get_jwt_token_from_job(job)
            node = get_node(job)
            update_data(job, args)
            updateDisks(job, node, args)
            updateNics(job, node, args)
        except ValueError:
            job.logger.error("vm {} doesn't exist, cant update devices", service.name)
