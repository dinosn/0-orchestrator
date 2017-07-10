# Setup a Storage Cluster

Setting up a storage cluster is achieved through the RESTful API exposed by the Zero-OS Orchestrator.

So you first need to setup a Zero-OS cluster, as documented in [Setup a Zero-OS Cluster](/docs/setup/README.md).

Once the Zero-OS cluster is setup, following storage cluster API endpoint is exposed by the Orchestrator:

![](storageclusterapi.png)

Clicking **Post** will show you the details:

![](post.png)

So the arguments to pass are:
- **label**: name the storage cluster
- **servers**: number of StorageEngine server to instantiate
- **driverType**: type of disk to use
- **slaveNodes**: if set to true, an extra slave StorageEngine server will be create for master StorageEngine server
- **nodes**: list of the nodes where the disks should be found

In the example shown above you will end up with a cluster of 256 master StorageEngine servers and another 256 slave StorageEngine servers using all SSDs in node1 and node2. So if each node has 6 SSDs that are not yet used, then you'll get 12 disk, used by 512 StorageEngines. What actually will happen is that for each free SSD a new storage pool will be created. So each storage pool then includes on SSD disk.

Once you have a storage cluster setup it can be used for multiple purposes, most importantly for creating vdisks as discussed in [Block Storage](/docs/blockstorage/README.md).
