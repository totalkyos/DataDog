# project
from utils.service_discovery.abstract_config_store import AbstractConfigStore
from utils.service_discovery.etcd_config_store import EtcdStore
from utils.service_discovery.consul_config_store import ConsulStore

SD_TEMPLATE_DIR = '/datadog/check_configs'
CONFIG_FROM_AUTOCONF = 'auto-configuration'
CONFIG_FROM_TEMPLATE = 'template'


def get_config_store(agentConfig):
    if agentConfig.get('sd_config_backend') == 'etcd':
        return EtcdStore(agentConfig)
    elif agentConfig.get('sd_config_backend') == 'consul':
        return ConsulStore(agentConfig)
    elif agentConfig.get('sd_config_backend') is None:
        return StubStore(agentConfig)


class StubStore(AbstractConfigStore):
    """Used when no valid config store was found. Allow to use auto_config."""
    def _extract_settings(self, config):
        pass

    def get_client(self):
        pass

    def crawl_config_template(self):
        # There is no user provided templates in auto_config mode
        return False
