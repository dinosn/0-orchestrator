# NBD server
The NBD server is being monitored by it's respective AYS through the monitor action scheduled to be running every 5 minutes. In the monitor action the service action needs to use the new 0-core API introduced in ticket https://github.com/zero-os/0-core/issues/115 to implement long polling towards the NBD server job for 5 minutes.

# NBD server failure
When an NBD server would crash, AYS will discover that instantaneously through its long polling monitor action.
AYS then needs to restarts the NBD server and the corresponding VM.

# Tlog server failure
As we deploy multiple Tlog servers per NBD server (https://github.com/zero-os/0-Disk/issues/279), AYS just needs to restart the Tlog server when it crashed.

# SSD failure in Primary Storage Cluster
When an NBD server is unable to read or write from storage engine (ARDB server) with modulo X, it will fail over to the backup storage cluster to continue serving blocks for shard X. At the same time it will report the failure on its stderr stream that is monitored by the long-polling monitor action of it's service.

The monitor action will then **atomically update the storage engine service** (support for this is being added in AYS: https://github.com/Jumpscale/ays9/issues/38) to flag the storage engine as down & start the recovery actions to rebalance the broken shard over the remaining working storage engines in the storage cluster. The atomic nature of this is important because all NDB servers will report the failure of the storage engine, and we need to make sure that only 1 rebalancing effort is started. So only the first NDB server monitor action that responds on the failing storage engine can start the rebalancing.

NBD server communicating a failure on stderr:
```json
FAILURE: {"type": "storageengine-failure", "data": "10.100.0.1:22005"}
```

## NON DEDUPED disks

### Rebalancing step1: Need information
> **get information of free disk space per remaining storage engine.**
In order to keep the storage spreading as optimal as possible we first need to identify what the optimal way will be to re-spread the storage of the failed chard in the storage cluster. To be able to do that we need to know the free diskspace of every storage engine.

### Rebalancing step2: Recalculate spread
> **reassign the storage engine per vdisk to one of the remaining storage engines in the storagecluster**
The Storage Cluster service sorts the vdisks from large to small, and then finds the optimal storage engine to assign the broken shard to on a per vdisk level.

### Rebalancing step3: Start rebalancing
> **update the NDB server configs with the updated shard configuration**
After the config is rewritten (with the notion rebalancing is not complete yet) and the NBD server SIGHUB'ed, it reloads its config and will start rebalancing the broken shard.

VDisk storage engine re-mapping snippet from NBD server config:
```yaml
vdisks: # A required map of vdisks,
        # only 1 vdisk is required,
        # the ID of the vdisk is the same one that the user of this vdisk (nbd client)
        # used to connect to this nbdserver
  myvdisk: # Required (string) ID of this vdisk
    blockSize: 4096 # Required static (uint64) size of each block
    readOnly: false # Defines if this vdisk can be written to or not
                    # (optional, false by default)
    size: 10 # Required (uint64) total size in GiB of this vdisk
    storageCluster:
      name: mycluster # Required (string) ID of the storage cluster to use
                              # for this vdisk's storage, has to be a storage cluster
                              # defined in the `storageClusters` section of THIS config file
      failureModuloMapping:
        4: 10-rebalancing
    rootStorageCluster: rootcluster # Optional (string) ID of the (root) storage cluster to use
                                    # for this vdisk's fallback/root/template storage, has to be
                                    # a storage cluster defined in the `storageClusters` section
                                    # of THIS config file
    rootVdiskID: mytemplate # Optional (string) ID of the template vdisk,
                            # only used for `db` vdisk
    type: boot # Required (VdiskType) type of this vdisk
               # which also defines if its deduped or nondeduped,
               # valid types are: `boot`, `db`, `cache` and `tmp`
  # ... more (optional) vdisks
```
The snippet primarily shows that storageengine modulo 4 has been remapped to storageengine module 10 and, that it still needs to be rebalanced.

### Rebalancing step4: Get back to normal
> **NDB server communicated the rebalance is done**
After the completion of the rebalancing effort of the vdisks served by the NBD server, it will report that to AYS by communicating it to its stderr, which is then picked by AYS. AYS will then update its model indicating those vdisks are back to normal, and update the NBD server configuration accordingly.

NBD server communicating that it has completed rebalancing:
```json
SUCCESS: {"type": "storageengine-rebalance", "data": "10.100.0.1:22005"}
```

VDisk storage engine re-mapping snippet from NBD server config:
```yaml
vdisks: # A required map of vdisks,
        # only 1 vdisk is required,
        # the ID of the vdisk is the same one that the user of this vdisk (nbd client)
        # used to connect to this nbdserver
  myvdisk: # Required (string) ID of this vdisk
    blockSize: 4096 # Required static (uint64) size of each block
    readOnly: false # Defines if this vdisk can be written to or not
                    # (optional, false by default)
    size: 10 # Required (uint64) total size in GiB of this vdisk
    storageCluster:
      name: mycluster # Required (string) ID of the storage cluster to use
                              # for this vdisk's storage, has to be a storage cluster
                              # defined in the `storageClusters` section of THIS config file
      failureModuloMapping:
        4: 10
    rootStorageCluster: rootcluster # Optional (string) ID of the (root) storage cluster to use
                                    # for this vdisk's fallback/root/template storage, has to be
                                    # a storage cluster defined in the `storageClusters` section
                                    # of THIS config file
    rootVdiskID: mytemplate # Optional (string) ID of the template vdisk,
                            # only used for `db` vdisk
    type: boot # Required (VdiskType) type of this vdisk
               # which also defines if its deduped or nondeduped,      
               # valid types are: `boot`, `db`, `cache` and `tmp`
  # ... more (optional) vdisks
```
This snippet shows the re-mapping after the rebalancing completed, and AYS updated the config of the NBD server again.

## DEDUPED disks

### Rebalancing step1: Flag the broken storage engine as rebalancing
> **Update all NBD server configs to flag the broken storage engine as broken.**
This step indicates the NBD servers that reading and writing blocks to this shard, should be done directly to the storage engine in the backup storage cluster.

NBD server configuration snippet showing a broken storage engine that is rebalancing:
```yaml
storageClusters: # A required map of storage clusters,
                 # only 1 storage cluster is required
  mycluster: # Required (string) ID of this storage cluster,
             # you are free to name the cluster however you want
    dataStorage: # A required array of connection (dial)strings, used to store data
      - address: 192.168.58.146:2000 # At least 1 connection (dial)string is required
        status: rebalancing          # indicates this storage engine is rebalancing
      - address: 192.123.123.123:2001 # more connections are optional
      - address: 192.123.123.123:2002 # more connections are optional
      - address: 192.123.123.123:2003 # more connections are optional

    metadataStorage: # Required ONLY when used as the (Root)StorageCluster of a `boot` vdisk
      address: 192.168.58.146:2001 # Required connection (dial)string,
                                   # used to store meta data (LBA indices)
```

### Rebalancing step2: Rebalance the broken storage engine
> **Execute 0-ctl --rebalance <NBD server config file>** to re-spread the blocks of the broken storage engine over the remaining storage engines in the storage cluster. This step only needs to be executed on 1 NBD container.

### Rebalancing step3: flag the broken storage engine as broken
> When rebalancing has completed when can notify the NBD servers that they can read blocks again from the primary storage cluster using the broken-re-spreaded-storage-engine algorithm implemented in the NBD server.

NBD server configuration snippet showing a broken storage engine that has finished rebalancing:
```yaml
storageClusters: # A required map of storage clusters,
                 # only 1 storage cluster is required
  mycluster: # Required (string) ID of this storage cluster,
             # you are free to name the cluster however you want
    dataStorage: # A required array of connection (dial)strings, used to store data
      - address: 192.168.58.146:2000 # At least 1 connection (dial)string is required
        status: broken          # indicates this storage engine is broken
      - address: 192.123.123.123:2001 # more connections are optional
      - address: 192.123.123.123:2002 # more connections are optional
      - address: 192.123.123.123:2003 # more connections are optional

    metadataStorage: # Required ONLY when used as the (Root)StorageCluster of a `boot` vdisk
      address: 192.168.58.146:2001 # Required connection (dial)string,
                                   # used to store meta data (LBA indices)
```

# SSD failure in Backup Storage Cluster
When an SSD fails in the Backup Storage Cluster the NBD server will act similarly as it acts for the Primary Storage Cluster, performing the same kind of restoring actions.
