from .abstracts import Mountable
import os
import time

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _prepare_device(node, devicename):
    logger.debug("prepare device %s", devicename)
    ss = devicename.split('/')
    if len(ss) < 3:
        raise RuntimeError("bad device name: {}".format(devicename))
    name = ss[2]

    disk = node.disks.get(name)
    if disk is None:
        raise ValueError("device {} not found".format(name))

    node.client.system('parted -s /dev/{} mklabel gpt mkpart primary 1m 100%'.format(name)).get()
    now = time.time()
    # check partitions is ready and writable
    while now + 60 > time.time():
        try:
            disk = node.disks.get(name)
            if len(disk.partitions) > 0:
                partition = disk.partitions[0]
                resp = node.client.bash('test -b {0} && dd if={0} of=/dev/null bs=4k count=1024'.format(partition.devicename)).get()
                if resp.state == 'SUCCESS':
                    return partition
        except:
            time.sleep(1)
            continue
    else:
        raise RuntimeError("Failed to create partition")


class StoragePools:
    def __init__(self, node):
        self.node = node
        self._client = node._client

    def list(self):
        storagepools = []
        btrfs_list = self._client.btrfs.list()
        if btrfs_list:
            for btrfs in self._client.btrfs.list():
                if btrfs['label'].startswith('sp_'):
                    name = btrfs['label'].split('_', 1)[1]
                    devicenames = [device['path'] for device in btrfs['devices']]
                    storagepools.append(StoragePool(self.node, name, devicenames))
        return storagepools

    def get(self, name):
        for pool in self.list():
            if pool.name == name:
                return pool
        raise ValueError("Could not find StoragePool with name {}".format(name))

    def create(self, name, devices, metadata_profile, data_profile, overwrite=False):
        label = 'sp_{}'.format(name)
        logger.debug("create storagepool %s", label)

        device_names = []
        for device in devices:
            part = _prepare_device(self.node, device)
            device_names.append(part.devicename)

        self._client.btrfs.create(label, device_names, metadata_profile, data_profile, overwrite=overwrite)
        pool = StoragePool(self.node, name, device_names)
        return pool


class StoragePool(Mountable):

    def __init__(self, node, name, devices):
        self.node = node
        self._client = node._client
        self.devices = devices
        self.name = name
        self._mountpoint = None
        self._ays = None

    @property
    def devicename(self):
        return 'UUID={}'.format(self.uuid)

    def mount(self, target=None):
        if target is None:
            target = os.path.join('/mnt/storagepools/{}'.format(self.name))
        return super().mount(target)

    def delete(self, zero=True):
        """
        Destroy storage pool
        param zero: write zeros (nulls) to the first 500MB of each disk in this storagepool
        """

        if self.mountpoint:
            self.umount()
        partitionmap = {}
        for disk in self.node.disks.list():
            for partition in disk.partitions:
                partitionmap[partition.name] = partition
        for device in self.devices:
            diskpath = os.path.basename(device)
            partition = partitionmap.get(diskpath)
            if partition:
                disk = partition.disk
                self._client.disk.rmpart(disk.name, 1)
                if zero:
                    self._client.bash('test -b /dev/{0} && dd if=/dev/zero bs=1M count=500 of=/dev/{0}'.format(diskpath)).get()
                return True
        return False

    @property
    def mountpoint(self):
        mounts = self.node.list_mounts()
        for device in self.devices:
            for mount in mounts:
                if mount.device == device:
                    options = mount.options.split(',')
                    if 'subvol=/' in options:
                        return mount.mountpoint

    def is_device_used(self, device):
        """
        check if the device passed as argument is already part of this storagepool
        @param device: str e.g: /dev/sda
        """
        for d in self.devices:
            if d.startswith(device):
                return True
        return False

    def device_add(self, *devices):
        to_add = []
        for device in devices:
            if self.is_device_used(device):
                continue
            part = _prepare_device(self.node, device)
            logger.debug("add device %s to %s", device, self)
            to_add.append(part.devicename)

        self._client.btrfs.device_add(self._get_mountpoint(), *to_add)
        self.devices.extend(to_add)

    def device_remove(self, *devices):
        self._client.btrfs.device_remove(self._get_mountpoint(), *devices)
        for device in devices:
            if device in self.devices:
                logger.debug("remove device %s to %s", device, self)
                self.devices.remove(device)

    @property
    def fsinfo(self):
        if self.mountpoint is None:
            raise ValueError("can't get fsinfo if storagepool is not mounted")
        return self._client.btrfs.info(self.mountpoint)

    @mountpoint.setter
    def mountpoint(self, value):
        # do not do anything mountpoint is dynamic
        return

    def _get_mountpoint(self):
        mountpoint = self.mountpoint
        if not mountpoint:
            raise RuntimeError("Can not perform action when filesystem is not mounted")
        return mountpoint

    @property
    def info(self):
        for fs in self._client.btrfs.list():
            if fs['label'] == 'sp_{}'.format(self.name):
                return fs
        return None

    def raw_list(self):
        mountpoint = self._get_mountpoint()
        return self._client.btrfs.subvol_list(mountpoint) or []

    def get_devices_and_status(self):
        device_map = []
        disks = self._client.disk.list()['blockdevices']
        pool_status = 'healthy'
        for device in self.devices:
            info = None
            for disk in disks:
                disk_name = "/dev/%s" % disk['kname']
                if device == disk_name and disk['mountpoint']:
                    info = disk
                    break
                for part in disk.get('children', []) or []:
                    if device == "/dev/%s" % part['kname']:
                        info = part
                        break
                if info:
                    break

            status = 'healthy'
            if info['subsystems'] != 'block:virtio:pci':
                result = self._client.bash("smartctl -H %s > /dev/null ;echo $?" % disk_name).get()
                exit_status = int(result.stdout)

                if exit_status & 1 << 0:
                    status = "unknown"
                    pool_status = 'degraded'
                if (exit_status & 1 << 2) or (exit_status & 1 << 3):
                    status = 'degraded'
                    pool_status = 'degraded'

            device_map.append({
                'device': device,
                'partUUID': info['partuuid'] or '' if info else '',
                'status': status,
            })

        return device_map, pool_status

    def list(self):
        subvolumes = []
        for subvol in self.raw_list():
            path = subvol['Path']
            type_, _, name = path.partition('/')
            if type_ == 'filesystems':
                subvolumes.append(FileSystem(name, self))
        return subvolumes

    def get(self, name):
        """
        Get Filesystem
        """
        for filesystem in self.list():
            if filesystem.name == name:
                return filesystem
        raise ValueError("Could not find filesystem with name {}".format(name))

    def exists(self, name):
        """
        Check if filesystem with name exists
        """
        for subvolume in self.list():
            if subvolume.name == name:
                return True
        return False

    def create(self, name, quota=None):
        """
        Create filesystem
        """
        logger.debug("Create filesystem %s on %s", name, self)
        mountpoint = self._get_mountpoint()
        fspath = os.path.join(mountpoint, 'filesystems')
        self._client.filesystem.mkdir(fspath)
        subvolpath = os.path.join(fspath, name)
        self._client.btrfs.subvol_create(subvolpath)
        if quota:
            pass
        return FileSystem(name, self)

    @property
    def size(self):
        total = 0
        fs = self.info
        if fs:
            for device in fs['devices']:
                total += device['size']
        return total

    @property
    def uuid(self):
        fs = self.info
        if fs:
            return fs['uuid']
        return None

    @property
    def used(self):
        total = 0
        fs = self.info
        if fs:
            for device in fs['devices']:
                total += device['used']
        return total

    @property
    def ays(self):
        if self._ays is None:
            from zeroos.orchestrator.sal.atyourservice.StoragePool import StoragePoolAys
            self._ays = StoragePoolAys(self)
        return self._ays

    def __repr__(self):
        return "StoragePool <{}>".format(self.name)


class FileSystem:
    def __init__(self, name, pool):
        self.name = name
        self.pool = pool
        self._client = pool.node.client
        self.subvolume = "filesystems/{}".format(name)
        self.path = os.path.join(self.pool.mountpoint, self.subvolume)
        self.snapshotspath = os.path.join(self.pool.mountpoint, 'snapshots', self.name)
        self._ays = None

    def delete(self, includesnapshots=True):
        """
        Delete filesystem
        """
        paths = [fs['Path'] for fs in self._client.btrfs.subvol_list(self.path)]
        paths.sort(reverse=True)
        for path in paths:
            rpath = os.path.join(self.path, os.path.relpath(path, self.subvolume))
            self._client.btrfs.subvol_delete(rpath)
        self._client.btrfs.subvol_delete(self.path)
        if includesnapshots:
            for snapshot in self.list():
                snapshot.delete()
            self._client.filesystem.remove(self.snapshotspath)

    def get(self, name):
        """
        Get snapshot
        """
        for snap in self.list():
            if snap.name == name:
                return snap
        raise ValueError("Could not find snapshot {}".format(name))

    def list(self):
        """
        List snapshots
        """
        snapshots = []
        if self._client.filesystem.exists(self.snapshotspath):
            for fileentry in self._client.filesystem.list(self.snapshotspath):
                if fileentry['is_dir']:
                    snapshots.append(Snapshot(fileentry['name'], self))
        return snapshots

    def exists(self, name):
        """
        Check if a snapshot exists
        """
        return name in self.list()

    def create(self, name):
        """
        Create snapshot
        """
        logger.debug("create snapshot %s on %s", name, self.pool)
        snapshot = Snapshot(name, self)
        if self.exists(name):
            raise RuntimeError("Snapshot path {} exists.")
        self._client.filesystem.mkdir(self.snapshotspath)
        self._client.btrfs.subvol_snapshot(self.path, snapshot.path)
        return snapshot

    @property
    def ays(self):
        if self._ays is None:
            from JumpScale.sal.g8os.atyourservice.StoragePool import FileSystemAys
            self._ays = FileSystemAys(self)
        return self._ays

    def __repr__(self):
        return "FileSystem <{}: {!r}>".format(self.name, self.pool)


class Snapshot:
    def __init__(self, name, filesystem):
        self.filesystem = filesystem
        self._client = filesystem.pool.node.client
        self.name = name
        self.path = os.path.join(self.filesystem.snapshotspath, name)
        self.subvolume = "snapshots/{}/{}".format(self.filesystem.name, name)

    def rollback(self):
        self.filesystem.delete(False)
        self._client.btrfs.subvol_snapshot(self.path, self.filesystem.path)

    def delete(self):
        self._client.btrfs.subvol_delete(self.path)

    def __repr__(self):
        return "Snapshot <{}: {!r}>".format(self.name, self.filesystem)
