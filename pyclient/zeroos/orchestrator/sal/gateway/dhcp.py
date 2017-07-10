import signal
import time

from zeroos.orchestrator.sal import templates

DNSMASQ = '/bin/dnsmasq --conf-file=/etc/dnsmasq.conf -d'


class DHCP:
    def __init__(self, container, domain, dhcps):
        self.container = container
        self.domain = domain
        self.dhcps = dhcps

    def apply_config(self):
        dnsmasq = templates.render('dnsmasq.conf', domain=self.domain, dhcps=self.dhcps)
        self.container.upload_content('/etc/dnsmasq.conf', dnsmasq)

        dhcp = templates.render('dhcp', dhcps=self.dhcps)
        self.container.upload_content('/etc/dhcp', dhcp)

        for process in self.container.client.process.list():
            if 'dnsmasq' in process['cmdline']:
                self.container.client.process.kill(process['pid'], signal.SIGTERM)
                start = time.time()
                while start + 10 > time.time():
                    if not self.is_running():
                        break
                    time.sleep(0.2)
                break

        self.container.client.system(DNSMASQ)
        # check if command is listening for dhcp
        start = time.time()
        while start + 10 > time.time():
            if self.is_running():
                break
            time.sleep(0.2)
        else:
            raise RuntimeError('Failed to run dnsmasq')

    def is_running(self):
        for port in self.container.client.info.port():
            if port['network'] == 'udp' and port['port'] == 53:
                return True
