# Setup a Zero-OS Cluster

This is the recommended and currently the only supported option to setup a Zero-OS cluster.

In order to have a full Zero-OS cluster you'll need to perform the following steps:
1. [Create a JumpScale9 Docker container](#create-a-jumpscale9-docker-container)
2. [ItsYou.online preparation](#itsyou.online-preparation)
3. [Install the Zero-OS Orchestrator](#install-the-orchestrator)
4. [Create a JWT](#create-the-jwt)
5. [Start the AYS Configuration service](#start-the-ays-configuration-service)
6. [Setup the backplane network](#setup-the-backplane-network)
7. [Setup the AYS Bootstrap service](#start-the-bootstrap-service)
8. [Boot your Zero-OS nodes](#boot-your-zero-os-nodes)
9. [Setup Statistics Monitoring](#setup-statistics-monitoring)


## Create a JumpScale9 Docker container

Create the Docker container with JumpScale9 development environment by following the documentation at https://github.com/Jumpscale/developer#jumpscale-9.
> **Important:** Make sure you set the `GIGBRANCH` environment variable to **9.0.3** before running `jsinit.sh`. This version of 0-orchestrator will only work with this version of JumpScale.

> **Important:**: Make sure to build the js9 docker with `js9_build -l` and not directly start the docker with `js9_start -b` cause this will not install all the requires libraries.


## ItsYou.online preparation

If not already done so, first register on https://www.ItsYou.online.

Once registered create an API key:

![](images/itsyou.png)

And then create an ItsYou.online organization:

![](images/itsyou2.png)


## Install the Orchestrator

SSH into your JumpScale9 Docker container and install the Orchestrator using the [`install-orchestrator.sh`](../../scripts/install-orchestrator.sh) script.

> **I mportant:**: Install Zerotier tools by executing `curl -s 'https://pgp.mit.edu/pks/lookup?op=get&search=0x1657198823E52A61' | gpg --import && if z=$(curl -s 'https://install.zerotier.com/' | gpg); then echo "$z" | bash; fi`


Before actually performing the Orchestrator installation the script will first join the Docker container into the ZeroTier management network that will be used to manage the Zero-OS nodes in your cluster.
The orchestrator by default installs caddy and runs using https. If the domain is passed, it will try to create certificates for that domain, unless `--development` is used, then it will use self signed certificates.

This script takes the following parameters:
- `BRANCH`: 0-orchestrator development branch
- `ZEROTIERNWID`: ZeroTier network ID
- `ZEROTIERTOKEN`: ZeroTier API token
- `ITSYOUONLINEORG`: ItsYou.online organization to authenticate against
- `DOMAIN`: Optional domain to listen on, if omitted Caddy will listen on the Zero-Tier network with a self-signed certificate
- `--development`: When domain is passed and you want to force a self-signed certificate

So:
```bash
cd /tmp
export BRANCH="1.1.0-alpha-5"
export ZEROTIERNWID="<Your ZeroTier network ID>"
export ZEROTIERTOKEN="<Your ZeroTier token>"
export ITSYOUONLINEORG="<itsyou.online organization>"
export DOMAIN="<Your domain name>"
curl -o install-orchestrator.sh https://raw.githubusercontent.com/zero-os/0-orchestrator/${BRANCH}/scripts/install-orchestrator.sh
bash install-orchestrator.sh "$BRANCH" "$ZEROTIERNWID" "$ZEROTIERTOKEN" "$ITSYOUONLINEORG" ["$DOMAIN" [--development]]
```

In order to see the full log details while `install-orchestrator.sh` executes:
```shell
tail -f /tmp/install.log
```

> **Important:**
- The ZeroTier network needs to be a private network
- The script will wait until you authorize your JumpScale9 Docker container into the network

Once installed a new TMUX session will have been created, in order to attach to it execute:
```bash
tmux at
```

![](images/tmux.png)

You'll see three TMUX session windows, one for each of the following processes:
- AYS Server
- Orchestrator
- Caddy Server, for SSL offloading

You can switch between the TMUX session windows using `CTRL-B` and then `0`, `1` or `3`.

In order to detach for the TMUX session use `CTRL-B` and then `d`.

## Create a JWT

As a preparation to the next step, which requires using the AYS command line tool, we need to create a JSON Web token (JWT).

Since AYS is protected with a JWT, you have to generate a JWT token so the AYS command line tool can authenticate against the AYS server.

The AYS command line tool provides and easy way to do it:

```shell
ays generatetoken --clientid {CLIENT_ID} --clientsecret {CLIENT_SECRET} --organization $ITSYOUONLINEORG --validity 3600
```

`CLIENT_ID` AND `CLIENT_SECRET` have to be generated on [ItsYou.online](https://itsyou.online), as discused above.

This command will output something like:
```shell
# Generated Token, please run to use in client:
export JWT='eyJhbGciOiJFUzM4NCIsInR5cCI6IkpXVCJ9.eyJhenAiOiJLa0Y0c3IyUll4cXVYWTZlWjVtMWtic0dTbVJRIiwiZXhwIjoxNDk4MTM0MDMyLCJpc3MiOiJpdHN5b3VvbmxpbmUiLCJyZWZyZXNoX3Rva2VuIjoiU2xxLWVfY9ktSjBEalRDbmZPNzA1SDN1ZFN5UyIsInNjb3BlIjpbInVzZXI6bWVtYmVyb2Y6Z3JlZW5pdGdsb2JlLmVudmlyb25tZW50cy5iZS1nOC0zIl0sInVzZXJuYW1lIjoiemFpYm9uIn0.sKVUHPxSb6rxOMx1DKV8w0T0dpyuMya4fBgOV66VFl6-R4p53crvSkHidXRjsKbgbyxV2stsbxV67mo5JPvRN9uaf-pnJ9cXxs74lSq8OoFwre6aG9pG0JPmVt9uMy56'
```

Copy the export statetement and execute it in your terminal. This will allow the AYS command line tool to be authenticate against the AYS RESTful API from now one.


## Start the AYS Configuration service

In order for the Orchestrator to know which flists and version of JumpScale to use, and which Zero-OS version is required on the nodes, create the following blueprint in `/optvar/cockpit_repos/orchestrator-server/blueprints/configuration.bp`:

```yaml
configuration__main:
  configurations:
  - key: '0-core-version'
    value: '1.1.0-alpha-5'
  - key: 'js-version'
    value: '9.0.3'
  - key: 'gw-flist'
    value: 'https://hub.gig.tech/gig-official-apps/zero-os-gw-1.1.0-alpha-5.flist'
  - key: 'ovs-flist'
    value: 'https://hub.gig.tech/gig-official-apps/ovs.flist'
  - key: '0-disk-flist'
    value: 'https://hub.gig.tech/gig-official-apps/0-disk-master.flist'
  - key: '0-statscollector-flist'
    value: 'https://hub.gig.tech/gig-official-apps/0-statscollector-master.flist'
  - key: 'jwt-token'
    value: '<The JWT generted at the previous step>'
  - key: 'jwt-key'
    value: 'MHYwEAYHKoZIzj0CAQYFK4EEACIDYgAES5X8XrfKdx9gYayFITc89wad4usrk0n27MjiGYvqalizeSWTHEpnd7oea9IQ8T5oJjMVH5cc0H5tFSKilFFeh//wngxIyny66+Vq5t5B0V0Ehy01+2ceEon2Y0XDkIKv'
```

See [Versioning](versioning.md) for more details about the AYS configuration service.

After creating this blueprint, issue the following AYS command to install the configuration service:
```bash
cd /optvar/cockpit_repos/orchestrator-server
ays blueprint configuration.bp
```

## Setup the backplane network
This optional setup allows you to interconnect your nodes using the (if available) 10GE+ network infrastructure. Skip this step if you don't have this in your setup.

Create a new blueprint `/optvar/cockpit_repos/orchestrator-server/blueprints/network.bp` and depending on the available 10GE+ network infrastructure specify following configuration:

### G8 setup
```yaml
network.zero-os__storage:
  vlanTag: 101
  cidr: "192.168.58.0/24"
```
> **Important:** Change the vlanTag and the cidr according to the needs of your environment.

### Switchless setup
```yaml
network.switchless__storage:
  vlanTag: 101
  cidr: "192.168.58.0/24"
```
> **Important:** Change the vlanTag and the cidr according to the needs of your environment.

See [Switchless Setup](images/switchless.md) for instructions on how to interconnect the nodes in case there is no Gigabit Ethernet switch.

### Packet.net setup

```yaml
network.publicstorage__storage:
```

After creating this blueprint, issue the following AYS command to install it:
```shell
cd /optvar/cockpit_repos/orchestrator-server
ays blueprint network.bp
```

## Start the AYS Bootstrap service

Then we need to update the bootstrap service so that it deploys the storage network when bootstrapping the nodes. The bootstrap service also authorizes ZeroTier join requests form Zero-OS nodes if they meet the conditions as set in the Configuration blueprint.

So edit `/optvar/cockpit_repos/orchestrator-server/blueprints/bootstrap.bp` as follows:
```yaml
bootstrap.zero-os__grid1:
  zerotierNetID: '<Your ZeroTier network id>'
  zerotierToken: '<Your ZeroTier token>'
  wipedisks: true # indicate you want to wipe the disks of the nodes when adding them
  networks:
    - storage
```

Now issue the following AYS commands to reinstall the updated bootstrap service:
```shell
cd /optvar/cockpit_repos/orchestrator-server
ays service delete -n grid1 -y
ays blueprint bootstrap.bp
ays run create -y
```

## Boot your Zero-OS nodes

The final step is to boot your Zero-OS nodes into your ZeroTier network.

Via iPXE from the following URL: `https://bootstrap.gig.tech/ipxe/master/${ZEROTIERNWID}/organization="${ITSYOUONLINEORG}"`

Or download your ISO from the following URL: `https://bootstrap.gig.tech/iso/master/${ZEROTIERNWID}/organization="${ITSYOUONLINEORG}"`

See the [0-core documentation](https://github.com/zero-os/0-core/blob/master/docs/booting) for more information on booting Zero-OS.

## Setup Statistics Monitoring

To have statistics monitoring, you need to have an InfluxDB and Grafana running on any of the nodes. And you need to run the [0-stats-collector](https://github.com/zero-os/0-statscollector) on all the nodes you want to monitor.

The [0-stats-collector](https://github.com/zero-os/0-statscollector) reads the statistics from 0-core and dumps them in InfluxDB, fron which Grafana can visualize the data.

The fastest way to achieve this is to install the [statsdb](https://github.com/zero-os/0-orchestrator/tree/master/templates/statsdb) AYS service on any of the nodes. This service will install both InfluxDB and Grafana. Once installed, it will iterate all nodes and install the 0-stat-collector on them.

Example of the statsdb blueprint:
```yaml
statsdb__statistics:
  node: '54a9f715dbb1'
  port: 9086

actions:
  - action: install

```

The port will be the port on which InfluxDB will run. Executing this blueprint will create a container with InfluxDB running on the specified port and will add database `statistics` to InfluxDB. It will also create a container with Grafana running on it and add a data source for the `statistics` database.
