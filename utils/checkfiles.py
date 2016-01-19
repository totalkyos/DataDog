"""Helpers to work with check files (Python and YAML)."""
# std
import itertools
import logging
import os

log = logging.getLogger(__name__)


def get_conf_path(check_name):
    """Return the yaml config file path for a given check name."""
    from config import get_confd_path, PathNotFound
    confd_path = ''

    try:
        confd_path = get_confd_path()
    except PathNotFound:
        log.error("Couldn't find the check configuration folder, not using the docker hostname.")
        return None

    conf_path = os.path.join(confd_path, '%s.yaml' % check_name)
    if not os.path.exists(conf_path):
        default_conf_path = os.path.join(confd_path, '%s.yaml.default' % check_name)
        if not os.path.exists(default_conf_path):
            log.error("Couldn't find any configuration file for the %s check." % check_name)
            return None
        else:
            conf_path = default_conf_path
    return conf_path


def get_check_class(agentConfig, check_name):
    """Return the class object for a given check name"""
    from config import get_os, get_checks_paths, get_check_class

    osname = get_os()
    checks_paths = get_checks_paths(agentConfig, osname)
    for check in itertools.chain(*checks_paths):
        py_check_name = os.path.basename(check).split('.')[0]
        if py_check_name == check_name:
            check_class = get_check_class(check_name, check)
            if isinstance(check_class, dict) or check_class is None:
                log.warning('Failed to load the check class for %s.' % check_name)
                return None
            else:
                return check_class


def get_auto_conf(agentConfig, check_name):
    """Return the yaml auto_config dict for a check name (None if it doesn't exist)."""
    from config import check_yaml, PathNotFound, get_auto_confd_path
    auto_conf, auto_confd_path = None, None

    try:
        auto_confd_path = get_auto_confd_path()
    except PathNotFound:
        log.error("Couldn't find the check auto-configuration folder, no auto configuration will be used.")
        return None

    auto_conf_path = os.path.join(auto_confd_path, '%s.yaml' % check_name)
    if not os.path.exists(auto_conf_path):
        log.error("Couldn't find any auto configuration file for the %s check." % check_name)
        return None

    try:
        auto_conf = check_yaml(auto_conf_path)
    except Exception as e:
        log.error("Enable to load the auto-config, yaml file.\n%s" % str(e))

    return auto_conf
