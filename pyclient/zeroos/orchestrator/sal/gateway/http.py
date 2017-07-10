from zeroos.orchestrator.sal import templates
import signal
import time


class HTTPServer:
    def __init__(self, container, httpproxies):
        self.container = container
        self.httpproxies = httpproxies

    def apply_rules(self):
        # caddy
        caddyconfig = templates.render('caddy.conf', httpproxies=self.httpproxies)
        self.container.upload_content('/etc/caddy.conf', caddyconfig)
        job = self.get_job()
        if job:
            self.container.client.job.kill(job['cmd']['id'], int(signal.SIGUSR1))
        else:
            self.container.client.system('caddy -agree -conf /etc/caddy.conf')
        start = time.time()
        while start + 10 > time.time():
            if self.is_running():
                return True
            time.sleep(0.5)
        raise RuntimeError("Failed to start caddy server")

    def get_job(self):
        for job in self.container.client.job.list():
            cmd = job['cmd']
            if cmd['command'] != 'core.system':
                continue
            if cmd['arguments']['name'] == 'caddy':
                return job

    def is_running(self):
        for port in self.container.client.info.port():
            if port['network'].startswith('tcp') and port['port'] in [80, 443]:
                return True
        return False
