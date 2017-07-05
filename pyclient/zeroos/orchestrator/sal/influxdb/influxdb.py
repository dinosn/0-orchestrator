import signal
import time

from zeroos.orchestrator.sal import templates
from js9 import j


class InfluxDB:
    def __init__(self, container, ip, port):
        self.container = container
        self.ip = ip
        self.port = port

    def apply_config(self):
        influx_conf = templates.render('influxdb.conf', ip=self.ip, port=self.port)
        self.container.upload_content('/etc/influxdb/influxdb.conf', influx_conf)

    def is_running(self):
        for process in self.container.client.process.list():
            if 'influxd' in process['cmdline']:
                return True, process['pid']
        return False, None

    def stop(self, timeout=30):
        is_running, pid = self.is_running()
        if not is_running:
            return

        self.container.client.process.kill(pid, signal.SIGTERM)
        start = time.time()
        end = start + timeout
        is_running, _ = self.is_running()
        while is_running and time.time() < end:
            time.sleep(1)
            is_running, _ = self.is_running()

        if is_running:
            raise RuntimeError('Failed to stop influxd.')

        self.container.node.client.nft.drop_port(self.port)

    def start(self, timeout=30):
        is_running, _ = self.is_running()
        if is_running:
            return

        self.apply_config()
        self.container.node.client.nft.open_port(self.port)
        self.container.client.system('influxd')
        time.sleep(1)

        start = time.time()
        end = start + timeout
        is_running, _ = self.is_running()
        while not is_running and time.time() < end:
            time.sleep(1)
            is_running, _ = self.is_running()

        if not is_running:
            self.container.node.client.nft.drop_port(self.port)
            raise RuntimeError('Failed to start influxd.')

    def create_databases(self, databases):
        client = j.clients.influxdb.get(self.ip, port=self.port)

        for database in databases:
            client.create_database(database)

    def drop_databases(self, databases):
        client = j.clients.influxdb.get(self.ip, port=self.port)

        for database in databases:
            client.drop_database(database)