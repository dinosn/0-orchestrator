def install(job):
    service = job.service
    from zeroos.orchestrator.sal.Node import Node
    node = Node.from_ays(service.parent, job.context['token'])
    node.client.nft.open_port(service.model.data.port)


def drop(job):
    service = job.service
    from zeroos.orchestrator.sal.Node import Node
    node = Node.from_ays(service.parent, job.context['token'])
    node.client.nft.drop_port(service.model.data.port)
