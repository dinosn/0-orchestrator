import os
from zeroos.core0.client.client import Timeout
import json


class ContainerContext:
    def __init__(self, node, flist):
        self.node = node
        self.flist = flist
        self.container = None

    def __enter__(self):
        self.container = self.node.containers.create('heathcheck', self.flist, host_network=True, privileged=True)
        return self.container

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.container:
            self.container.stop()


class HealthCheck:
    def __init__(self, node):
        self.node = node
        self.healtcheckfolder = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'healthchecks')

    def with_container(self, flist):
        return ContainerContext(self.node, flist)

    def run(self, container, name, timeout=None):
        try:
            healthcheckfile = os.path.join(self.healtcheckfolder, name + '.py')
            if not os.path.exists(healthcheckfile):
                raise RuntimeError("Healtcheck with name {} not found".format(name))
            container.client.filesystem.upload_file('/tmp/{}.py'.format(name), healthcheckfile)
            try:
                job = container.client.bash('python3 /tmp/{}.py'.format(name))
                response = job.get(timeout)
            except Timeout:
                container.client.job.kill(job.id, 9)
                raise RuntimeError("Failed to execute {} on time".format(name))
            if response.state == 'ERROR':
                raise RuntimeError("Failed to execute {} {}".format(name, response.stdout))
            try:
                return json.loads(response.stdout)
            except Exception:
                raise RuntimeError("Failed to parse response of {}".format(name))
        except Exception as e:
            healtcheck = {
                'id': name,
                'resource': '',
                'status': 'ERROR',
                'message': str(e)
            }
            return [healtcheck]
    def calc_cpu_mem(self):
        from .healthchecks.cpu_mem_core_check import action
        results = action(self.node)
        return results
