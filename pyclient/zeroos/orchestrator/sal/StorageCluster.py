import json

from js9 import j
from .StorageEngine import StorageEngine

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StorageCluster:
    """StorageCluster is a cluster of StorageEngine servers"""

    def __init__(self, label, nodes=None, disk_type=None):
        """
        @param label: string repsenting the name of the storage cluster
        """
        self.label = label
        self.name = label
        self.nodes = nodes or []
        self.filesystems = []
        self.storage_servers = []
        self.disk_type = disk_type
        self.k = 0
        self.m = 0
        self._ays = None

    @classmethod
    def from_ays(cls, service, password):
        logger.debug("load cluster storage cluster from service (%s)", service)
        disk_type = str(service.model.data.diskType)

        nodes = []
        storage_servers = []
        for storageEngine_service in service.producers.get('storage_engine', []):
            storages_server = StorageServer.from_ays(storageEngine_service, password)
            storage_servers.append(storages_server)
            if storages_server.node not in nodes:
                nodes.append(storages_server.node)

        cluster = cls(label=service.name, nodes=nodes, disk_type=disk_type)
        cluster.storage_servers = storage_servers
        cluster.k = service.model.data.k
        cluster.m = service.model.data.m
        return cluster

    @property
    def dashboard(self):
        board = StorageDashboard(self)
        return board.template

    def get_config(self):
        data = {'dataStorage': [],
                'metadataStorage': None,
                'label': self.name,
                'status': 'ready' if self.is_running() else 'error',
                'nodes': [node.name for node in self.nodes]}
        for storageserver in self.storage_servers:
            if 'metadata' in storageserver.name:
                data['metadataStorage'] = {'address': storageserver.storageEngine.bind}
            else:
                data['dataStorage'].append({'address': storageserver.storageEngine.bind})
        return data

    @property
    def nr_server(self):
        """
        Number of storage server part of this cluster
        """
        return len(self.storage_servers)

    def find_disks(self):
        """
        return a list of disk that are not used by storage pool
        or has a different type as the one required for this cluster
        """
        logger.debug("find available_disks")
        cluster_name = 'sp_cluster_{}'.format(self.label)
        available_disks = {}

        def check_partition(disk):
            for partition in disk.partitions:
                for filesystem in partition.filesystems:
                    if filesystem['label'].startswith(cluster_name):
                        return True

        for node in self.nodes:
            for disk in node.disks.list():
                # skip disks of wrong type
                if disk.type.name != self.disk_type:
                    continue
                # skip devices which have filesystems on the device
                if len(disk.filesystems) > 0:
                    continue

                # include devices which have partitions
                if len(disk.partitions) == 0:
                    available_disks.setdefault(node.name, []).append(disk)
                else:
                    if check_partition(disk):
                        # devices that have partitions with correct label will be in the beginning
                        available_disks.setdefault(node.name, []).insert(0, disk)
        return available_disks

    def start(self):
        logger.debug("start %s", self)
        for server in self.storage_servers:
            server.start()

    def stop(self):
        logger.debug("stop %s", self)
        for server in self.storage_servers:
            server.stop()

    def is_running(self):
        # TODO: Improve this, what about part of server running and part stopped
        for server in self.storage_servers:
            if not server.is_running():
                return False
        return True

    def health(self):
        """
        Return a view of the state all storage server running in this cluster
        example :
        {
        'cluster1_1': {'storageEngine': True, 'container': True},
        'cluster1_2': {'storageEngine': True, 'container': True},
        }
        """
        health = {}
        for server in self.storage_servers:
            running, _ = server.storageEngine.is_running()
            health[server.name] = {
                'storageEngine': running,
                'container': server.container.is_running(),
            }
        return health

    def __str__(self):
        return "StorageCluster <{}>".format(self.label)

    def __repr__(self):
        return str(self)


class StorageServer:
    """StorageEngine servers"""

    def __init__(self, cluster):
        self.cluster = cluster
        self.container = None
        self.storageEngine = None

    @classmethod
    def from_ays(cls, storageEngine_services, password=None):
        storageEngine = StorageEngine.from_ays(storageEngine_services, password)
        storage_server = cls(None)
        storage_server.container = storageEngine.container
        storage_server.storageEngine = storageEngine
        return storage_server

    @property
    def name(self):
        if self.storageEngine:
            return self.storageEngine.name
        return None

    @property
    def node(self):
        if self.container:
            return self.container.node
        return None

    def _find_port(self, start_port=2000):
        while True:
            if j.sal.nettools.tcpPortConnectionTest(self.node.addr, start_port, timeout=2):
                start_port += 1
                continue
            return start_port

    def start(self, timeout=30):
        logger.debug("start %s", self)
        if not self.container.is_running():
            self.container.start()

        ip, port = self.storageEngine.bind.split(":")
        self.storageEngine.bind = '{}:{}'.format(ip, self._find_port(port))
        self.storageEngine.start(timeout=timeout)

    def stop(self, timeout=30):
        logger.debug("stop %s", self)
        self.storageEngine.stop(timeout=timeout)
        self.container.stop()

    def is_running(self):
        container = self.container.is_running()
        storageEngine, _ = self.storageEngine.is_running()
        return (container and storageEngine)

    def __str__(self):
        return "StorageServer <{}>".format(self.container.name)

    def __repr__(self):
        return str(self)


class StorageDashboard:
    def __init__(self, cluster):
        self.cluster = cluster
        self.store = 'statsdb'

    def build_templating(self):
        templating = {
            "list": [],
            "rows": []
        }
        return templating

    def dashboard_template(self):
        return {
            "annotations": {
                "list": []
            },
            "editable": True,
            "gnetId": None,
            "graphTooltip": 0,
            "hideControls": False,
            "id": None,
            "links": [],
            "rows": [],
            "schemaVersion": 14,
            "style": "dark",
            "tags": [],
            "time": {
                "from": "now/d",
                "to": "now"
            },
            "timepicker": {
                "refresh_intervals": [
                    "5s",
                    "10s",
                    "30s",
                    "1m",
                    "5m",
                    "15m",
                    "30m",
                    "1h",
                    "2h",
                    "1d"
                ],
                "time_options": [
                    "5m",
                    "15m",
                    "1h",
                    "6h",
                    "12h",
                    "24h",
                    "2d",
                    "7d",
                    "30d"
                ]
            },
            "timezone": "",
            "title": self.cluster.name,
            "version": 8
        }

    def build_row(self, panel):
        template = {
            "collapse": False,
            "height": 295,
            "panels": [],
            "repeat": None,
            "repeatIteration": None,
            "repeatRowId": None,
            "showTitle": False,
            "title": "Dashboard Row",
            "titleSize": "h6"
        }
        template["panels"] += panel
        return template

    def build_panel(self, title, target, panel_id, unit):
        template = {
            "aliasColors": {},
            "bars": False,
            "dashLength": 10,
            "dashes": False,
            "datasource": self.store,
            "fill": 1,
            "id": panel_id,
            "legend": {
                "avg": False,
                "current": False,
                "max": False,
                "min": False,
                "show": True,
                "total": False,
                "values": False
            },
            "lines": True,
            "linewidth": 1,
            "links": [],
            "nullPointMode": "null",
            "percentage": False,
            "pointradius": 5,
            "points": False,
            "renderer": "flot",
            "seriesOverrides": [],
            "spaceLength": 10,
            "span": 6,
            "stack": True,
            "steppedLine": False,
            "targets": [],
            "thresholds": [],
            "timeFrom": None,
            "timeShift": None,
            "tooltip": {
                "shared": True,
                "sort": 0,
                "value_type": "individual"
            },
            "type": "graph",
            "xaxis": {
                "buckets": None,
                "mode": "time",
                "name": None,
                "show": True,
                "values": []
            },
            "yaxes": [
                {
                    "format": unit,
                    "label": None,
                    "logBase": 1,
                    "max": None,
                    "min": None,
                    "show": True
                },
                {
                    "format": "short",
                    "label": None,
                    "logBase": 1,
                    "max": None,
                    "min": None,
                    "show": True
                }
            ]
        }
        template["title"] = title
        template["targets"].append(target)
        return template

    def build_target(self, measurement, disks):
        template = {
            "alias": "$tag_node/$tag_id",
            "dsType": "influxdb",
            "groupBy": [
                {
                    "params": [
                        "$__interval"
                    ],
                    "type": "time"
                },
                {
                    "params": [
                        "node"
                    ],
                    "type": "tag"
                },
                {
                    "params": [
                        "id"
                    ],
                    "type": "tag"
                },
                {
                    "params": [
                        "none"
                    ],
                    "type": "fill"
                }
            ],
            "orderByTime": "ASC",
            "policy": "default",
            "rawQuery": False,
            "refId": "A",
            "resultFormat": "time_series",
            "select": [
                [
                    {
                        "params": [
                            "value"
                        ],
                        "type": "field"
                    },
                    {
                        "params": [],
                        "type": "mean"
                    }
                ]
            ],
            "tags": [
                {
                    "key": "type",
                    "operator": "=",
                    "value": "phys"
                }
            ]
        }
        template["measurement"] = measurement

        for idx, disk in enumerate(disks):
            tag = [
                {
                    "key": "node",
                    "operator": "=",
                    "value": disk.split("_")[0]
                },
                {
                    "condition": "AND",
                    "key": "id",
                    "operator": "=",
                    "value": disk.split("_")[1]
                }
            ]
            if idx == 0:
                tag[0]["condition"] = "AND"
            else:
                tag[0]["condition"] = "OR"
            template["tags"] += tag
        return template

    @property
    def template(self):
        AGGREGATED_CONFIG = {
            "Aggregated read IOPs": "disk.iops.read|m",
            "Aggregated write IOPs": "disk.iops.write|m",
            "Aggregated free size": "disk.size.free|m",
        }
        panel_id = 1
        disks = set()
        for server in self.cluster.storage_servers:
            server = server.name.split("_")
            disks.add("{}_{}".format(server[1], server[-3]))
        disks = list(disks)
        panels = []
        for title, measurement in AGGREGATED_CONFIG.items():
            if 'size' in title:
                partitions = [disk+'1' for disk in disks]
                target = self.build_target(measurement, partitions)
                panels.append(self.build_panel(title, target, panel_id, "decbytes"))
            else:
                target = self.build_target(measurement, disks)
                panels.append(self.build_panel(title, target, panel_id, "iops"))
            panel_id += 1

        for disk in disks:
            target = self.build_target("disk.iops.read|m", [disk])
            panels.append(self.build_panel("Read IOPs", target, panel_id, "iops"))
            panel_id += 1
            target = self.build_target("disk.iops.write|m", [disk])
            panels.append(self.build_panel("Write IOPs", target, panel_id, "iops"))
            panel_id += 1
            target = self.build_target("disk.size.free|m", [disk+'1'])
            panels.append(self.build_panel("Free size", target, panel_id, "decbytes"))
            panel_id += 1

        template = self.dashboard_template()
        for idx, panel in enumerate(panels):
            if idx % 2 == 0:
                row = self.build_row(panels[idx:idx+2])
                template["rows"].append(row)
        template = json.dumps(template)
        return template
