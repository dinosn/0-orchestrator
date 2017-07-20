from js9  import j

descr = """
Checks average memory and CPU usage/load. If average per hour is higher than expected an error condition is thrown.

For both memory and CPU usage throws WARNING if more than 80% used and throws ERROR if more than 95% used.

Result will be shown in the "System Load" section of the Grid Portal / Status Overview / Node Status page.
"""

def action(node):
    category = 'System Load'

    total_mem = node.client.info.mem()['total']/(1024*1024)
    mem_history = node.client.aggregator.query('machine.memory.ram.available')['machine.memory.ram.available']['history']


    if '3600' not in mem_history:
        memoryresult = {}
        memoryresult['status'] = 'WARNING'
        memoryresult['resource'] = category
        memoryresult['message'] = 'Average memory load is not collected yet'
        memoryresult['id'] = 'MEMORY'
        memoryresult['name'] = 'MEMORY'
    else:
        avg_available_mem = mem_history['3600'][-1]['avg']
        avg_used_mem = total_mem - avg_available_mem
        avg_mem_percent = avg_used_mem/float(total_mem) * 100
        memoryresult = get_results('memory', avg_mem_percent)

    cpupercent = 0
    count = 0

    cpu_usage = node.client.aggregator.query('machine.CPU.percent')
    for cpu, data in cpu_usage.items():
        if '3600' not in data['history']:
            continue
        cpupercent += (data['history']['3600'][-1]['avg'])
        count += 1

    if count == 0:
        cpuresult = {}
        cpuresult['status'] = 'WARNING'
        cpuresult['resource'] = category
        cpuresult['message'] = 'Average CPU load is not collected yet'
        cpuresult['id'] = "CPU"
        cpuresult['name'] = "CPU"
    else:
        cpuavg = cpupercent / float(count)
        cpuresult = get_results('cpu', cpuavg)
    return [memoryresult, cpuresult]


def get_results(type_, percent):
    level = None
    result = dict()
    result['status'] = 'OK'
    result['message'] = r'Average %s load during last hour was: %.2f%%' % (type_.upper(), percent)
    result['resource'] = 'System Load'
    result['id'] = r'%s' % (type_.upper())
    result['name'] = r'%s' % (type_.upper())
    if percent > 95:
        level = 1
        result['status'] = 'ERROR'
        result['message'] = r'Average %s load during last hour was too high' % (type_.upper())
    elif percent > 80:
        level = 2
        result['status'] = 'WARNING'
        result['message'] = r'Avergage %s load during last hour was too high' % (type_.upper())
    if level:
        msg = 'Avergage %s load during last hour was above threshhold value: %.2f%%' % (type_.upper(), percent)
        eco = j.errorconditionhandler.getErrorConditionObject(msg=msg, category='monitoring', level=level, type='OPERATIONS')
        eco.nid = j.application.whoAmI.nid
        eco.gid = j.application.whoAmI.gid
        eco.process()
    return result

if __name__ == '__main__':
    import yaml
    print(yaml.dump(action(), default_flow_style=False))
