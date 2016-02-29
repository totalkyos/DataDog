# stdlib
import os
import random

# project
from config import check_yaml, get_confd_path
from utils.singleton import Singleton


class NTPUtil():
    __metaclass__ = Singleton

    DEFAULT_VERSION = 3
    DEFAULT_TIMEOUT = 1  # in seconds
    DEFAULT_PORT = "ntp"

    def __init__(self):
        try:
            ntp_check_config = check_yaml(os.path.join(get_confd_path(), 'ntp.yaml'))
            settings = ntp_check_config['instances'][0]
        except Exception:
            settings = {}

        self.host = settings.get('host') or "{0}.datadog.pool.ntp.org".format(random.randint(0, 3))
        self.version = int(settings.get("version") or NTPUtil.DEFAULT_VERSION)
        self.port = settings.get('port') or NTPUtil.DEFAULT_PORT
        self.timeout = float(settings.get('timeout') or NTPUtil.DEFAULT_TIMEOUT)

        self.args = {
            'host':    self.host,
            'port':    self.port,
            'version': self.version,
            'timeout': self.timeout,
        }
