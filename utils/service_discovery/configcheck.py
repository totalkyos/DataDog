from config import load_check_directory
from util import get_hostname


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
