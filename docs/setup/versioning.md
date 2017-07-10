# Versioning

Versioning in the Orchestrator is done through the `configuration` AYS service.

This is an example of a configuration blueprint:

```yaml
configuration__main:
  configurations:
  - key: 'gw-flist'
    value: 'https://hub.gig.tech/deboeckj/g8osgw.flist'
  - key: '0-core-version'
    value: 'master'
```

The schema contains one attribute `configuration` which is a list of an objects containing `key` and `value` attributes.

The following are the available keys:

* `js-version`:
  - Specifies the JumpScale version the Orchestrator services can be installed on
  - If not configured, any version will be allowed
* `gw-flist`:
  - Specifies the flist used for the Gateway container
  - Defaults to 'https://hub.gig.tech/gig-official-apps/g8osgw.flist'
* `ovs-flist`:
  - Specifies the flist used for the Open vSwitch (OVS) container
  - Defaults to 'https://hub.gig.tech/gig-official-apps/ovs.flist'
* `0-core-version`:
  - Specifies the branch/tag used to control the build version of the core0 nodes
  - If not configured, any branch will be allowed
* `0-core-revision`:
  - Specifies the revision used to control the build revision of the core0 nodes
  - If not configured, any revision will be allowed
* `storage-engine-flist`:
  - Specifies the flist used for the ARDB container
  - Defaults to 'https://hub.gig.tech/gig-official-apps/ardb-rocksdb.flist'
* `0-disk-flist`:
  - Specifies the flist for the 0-disk containers
  - Defaults to 'https://hub.gig.tech/gig-official-apps/0-disk-master.flist'
* `0-statscollector-flist`:
  - Specifies the flist used for the stats-collector container.
  - Defaults to 'https://hub.gig.tech/gig-official-apps/0-statscollector-master.flist'
* `jwt-token`:
  - Specifies a refreshable JWT token. To configure jwt-token, the jwt-key must be supplied too.
  - If not configured, the services will connect to 0core with supplying a password.
* `jwt-key`:
  - Key used to validate the jwt-token.