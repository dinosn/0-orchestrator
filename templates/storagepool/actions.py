from JumpScaler import j


def input(job):
    service = job.service
    for notempty in ['metadataProfile', 'dataProfile', 'devices']:
        if job.model.args.get(notempty, "") == "":
            raise j.exceptions.Input("{} argument cannot be empty, cannot continue init of {}".format(notempty, service))


def install(job):
    from zeroos.orchestrator.sal.Node import Node
    service = job.service
    pservice = service.parent
    node = Node.from_ays(pservice, job.context['token'])

    devices = [d.device for d in service.model.data.devices]
    name = service.name
    dataProfile = str(service.model.data.dataProfile)
    metadataProfile = str(service.model.data.metadataProfile)
    mountpoint = str(service.model.data.mountpoint) or None
    created = False
    try:
        pool = node.storagepools.get(name)
    except ValueError:
        # pool does not exists lets create it
        pool = node.storagepools.create(name, devices, metadataProfile, dataProfile, overwrite=True)
        created = True

    # mount device
    # if pool already mounted and user ask a specific mountpoint, remount to the correct location
    if pool.mountpoint and mountpoint:
        if pool.mountpoint != mountpoint:
            pool.umount()
            pool.mount(mountpoint)
    # if pool already mounted and not specific endpoint asked, do nothing
    if pool.mountpoint and not mountpoint:
        pass
    # if pool not mounted and no mountpoint specified, use automatic mount
    elif not pool.mountpoint and not mountpoint:
        pool.mount()

    # lets check if devices need to be added removed and the profile still matches
    if pool.fsinfo['data']['profile'].lower() != dataProfile:
        raise RuntimeError("Data profile of storagepool {} does not match".format(name))
    if pool.fsinfo['metadata']['profile'].lower() != metadataProfile:
        raise RuntimeError("Metadata profile of storagepool {} does not match".format(name))

    if not created:
        updateDevices(service, pool, devices)

    pool.ays.create(service.aysrepo)


def delete(job):
    from zeroos.orchestrator.sal.Node import Node
    service = job.service
    pservice = service.parent
    node = Node.from_ays(pservice, job.context['token'])
    name = service.name

    try:
        pool = node.storagepools.get(name)
        pool.delete()
    except ValueError:
        # pool does not exists, nothing to do
        pass


def updateDevices(service, pool, devices):
    pooldevices = set(pool.devices)
    requireddevices = set(devices)

    def in_pool(device):
        for pooldevice in pooldevices:
            if pooldevice.startswith(device):
                return True
        return False

    def in_devices(pooldevice):
        for device in requireddevices:
            if pooldevice.startswith(device):
                return True
        return False

    # add extra devices
    extradevices = set()
    for device in requireddevices:
        if not in_pool(device):
            extradevices.add(device)
    if extradevices:
        pool.device_add(*extradevices)

    # remove devices
    removeddevices = set()
    for pooldevice in pooldevices:
        if not in_devices(pooldevice):
            removeddevices.add(pooldevice)

    if removeddevices:
        for device in service.model.data.devices:
            if device.device in removeddevices:
                device.status = 'removing'
        pool.device_remove(*removeddevices)


def processChange(job):
    from zeroos.orchestrator.sal.Node import Node
    from zeroos.orchestrator.configuration import get_jwt_token_from_job

    service = job.service
    if service.model.actionsState['install'] in ['new', 'scheduled']:
        return
    args = job.model.args
    category = args.pop('changeCategory')
    if category == "dataschema":
        pservice = service.parent

        node = Node.from_ays(pservice, get_jwt_token_from_job(job))
        try:
            pool = node.storagepools.get(service.name)
            devices = [d['device'] for d in args['devices']]
            updateDevices(service, pool, devices)
            pool.ays.create(service.aysrepo)
        except ValueError:
            job.logger.error("pool %s doesn't exist, cant update devices", service.name)


def monitor(job):
    from zeroos.orchestrator.sal.Node import Node
    from zeroos.orchestrator.configuration import get_jwt_token

    service = job.service
    if service.model.actionsState['install'] == 'ok':
        pservice = service.parent
        node = Node.from_ays(pservice, get_jwt_token(job.service.aysrepo))

        try:
            pool = node.storagepools.get(service.name)
            devices, status = pool.get_devices_and_status()

            service.model.data.init('devices', len(devices))
            for i, device in enumerate(devices):
                service.model.data.devices[i] = device

            service.model.data.status = status
            service.saveAll()

        except ValueError:
            job.logger.error("pool %s doesn't exist, cant monitor pool", service.name)
