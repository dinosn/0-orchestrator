## 0-statscollector

The stats-collector is a service used to collect statistics from a 0-core node and dump it to influx db.
This is done by creating a container using the 0-statscollector flist and running the 0-stascollector binary.


This is an example of the stats_collector blueprint to create and start the stats collection:

```yaml
stats_collector__mycollector:
  node: '525400123456'
  db: 'statistics'
  ip: '192.168.21.226'
  port: 8086
  retention: '5d'
actions:
  - action: install
```

* `node`: The name of the service of the node from which the stats will be collected/
* `ip`: The ip where the influxdb server is running.
* `port`: The port where the influxdb server is running.
* `retention`: The retention policy of influxdb.
* `db`: Name of the database where the stats should be dumped.

Running the following commands will create a container with the statscollector on it and start collectiong/dumping statistics in influxdb:

```bash
ays blueprint <blueprint name>
ays run create
```

Any future changes in the arguments of the service will cause a stop of the collection process and start it with the new arguments.
