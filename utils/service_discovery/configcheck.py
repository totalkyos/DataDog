from config import load_check_directory
from util import get_hostname
from utils.dockerutil import DockerUtil


def sd_configcheck(agentConfig):
    hostname = get_hostname(agentConfig)
    agentConfig['trace_config'] = True
    configs = {
        # check_name: (config_source, config)
    }

    print("\nLoading check configurations...\n\n")
    configs = load_check_directory(agentConfig, hostname)
    print("\nSource of the configuration objects built by the agent:\n")
    for check_name, config in configs.iteritems():
        print('Check "%s":\n  source --> %s\n  config --> %s\n' % (check_name, config[0], config[1]))

    try:
        print_containers()
    except Exception:
        print("Failed to collect containers info.")


def print_containers():
    containers = DockerUtil().client.containers()
    print("\nContainers info:\n")
    print("Number of containers found: %s" % len(containers))
    for co in containers:
        c_id = 'ID: %s' % co.get('Id')[:12]
        c_image = 'image: %s' % co.get('Image')
        c_name = 'name: %s' % DockerUtil.container_name_extractor(co)[0]
        print("\t- %s %s %s" % (c_id, c_image, c_name))


# def print_templates(agemtConfig):
