# std
import logging
import os
import re
import requests
import simplejson as json

# project
from config import check_yaml
from utils.checkfiles import get_conf_path
from utils.service_discovery.config_stores import ConfigStore
from utils.dockerutil import get_client as get_docker_client
from utils.kubeutil import _get_default_router, DEFAULT_KUBELET_PORT

log = logging.getLogger(__name__)


KUBERNETES_CHECK_NAME = 'kubernetes'


class ServiceDiscoveryBackend(object):
    """Singleton for service discovery backends"""
    _instance = None
    PLACEHOLDER_REGEX = re.compile(r'%%.+?%%')

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            agentConfig = kwargs.get('agentConfig', {})
            if agentConfig.get('service_discovery_backend') == 'docker':
                cls._instance = object.__new__(SDDockerBackend, agentConfig)
            else:
                log.error("Service discovery backend not supported. This feature won't be enabled")
                return
        return cls._instance

    def __init__(self, agentConfig=None):
        self.agentConfig = agentConfig

    def get_configs(self):
        """Get the config for all docker containers running on the host."""
        raise NotImplementedError()

    def _render_template(self, init_config_tpl, instance_tpl, variables):
        """Replace placeholders in a template with the proper values.
           Return a tuple made of `init_config` and `instances`."""
        config = (init_config_tpl, instance_tpl)
        for tpl in config:
            for key in tpl:
                # iterate over template variables found in the templates
                for var in self.PLACEHOLDER_REGEX.findall(str(tpl[key])):
                    if var.strip('%') in variables and variables[var.strip('%')]:
                        # if the variable is found in a list (for example {'tags': ['%%tags%%', 'env:prod']})
                        # we need to iterate over its elements
                        if isinstance(tpl[key], list):
                            for idx, val in enumerate(tpl[key]):
                                tpl[key][idx] = val.replace(var, variables[var.strip('%')])
                        else:
                            tpl[key] = tpl[key].replace(var, variables[var.strip('%')])
                    else:
                        log.warning('Failed to find interpolate variable {0} for the {1} parameter.'
                                    ' The check might not be configured properly.'.format(var, key))
                        if isinstance(tpl[key], list):
                            for idx, val in enumerate(tpl[key]):
                                tpl[key][idx] = val.replace(var, '')
                        else:
                            tpl[key].replace(var, '')
        return config

    @classmethod
    def _drop(cls):
        cls._instance = None


class SDDockerBackend(ServiceDiscoveryBackend):
    """Docker-based service discovery"""

    def __init__(self, agentConfig):
        self.docker_client = get_docker_client()

        try:
            self.config_store = ConfigStore(agentConfig=agentConfig)
        except Exception as e:
            log.error('Failed to instantiate the config store client. '
                      'Auto-config only will be used. %s' % str(e))
            agentConfig['sd_config_backend'] = None
            ConfigStore._drop()
            self.config_store = ConfigStore(agentConfig=agentConfig)

        self.VAR_MAPPING = {
            'host': self._get_host,
            'port': self._get_ports,
            'tags': self._get_additional_tags,
        }
        ServiceDiscoveryBackend.__init__(self, agentConfig)

    def _get_host(self, container_inspect):
        """Extract the host IP from a docker inspect object, or the kubelet API."""
        ip_addr = container_inspect.get('NetworkSettings', {}).get('IPAddress')
        if not ip_addr:
            log.debug("Didn't find the IP address for container %s (%s), using the kubernetes way." %
                      (container_inspect.get('Id', '')[:12], container_inspect.get('Config', {}).get('Image', '')))
            # kubernetes case
            pod_list = self._get_pod_list()
            c_id = container_inspect.get('Id')

            for pod in pod_list:
                pod_ip = pod.get('status', {}).get('podIP')
                if pod_ip is None:
                    continue
                else:
                    c_statuses = pod.get('status', {}).get('containerStatuses', [])
                    for status in c_statuses:
                        # compare the container id with those of containers in the current pod
                        if c_id == status.get('containerID', '').split('//')[-1]:
                            ip_addr = pod_ip

        return ip_addr

    def _get_ports(self, container_inspect):
        """Extract a list of available ports from a docker inspect object. Sort them numerically."""
        c_id = container_inspect.get('Id', '')
        try:
            ports = map(lambda x: x.split('/')[0], container_inspect['NetworkSettings']['Ports'].keys())
        except (IndexError, KeyError, AttributeError):
            log.debug("Didn't find the port for container %s (%s), trying the kubernetes way." %
                      (c_id[:12], container_inspect.get('Config', {}).get('Image', '')))
            # kubernetes case
            # first we try to get it from the docker API
            # it works if the image has an EXPOSE instruction
            ports = map(lambda x: x.split('/')[0], container_inspect['Config'].get('ExposedPorts', {}).keys())
            # if it failed, try with the kubernetes API
            if not ports:
                co_statuses = self._get_kube_config(c_id, 'status').get('containerStatuses', [])
                c_name = None
                for co in co_statuses:
                    if co.get('containerID', '').split('//')[-1] == c_id:
                        c_name = co.get('name')
                        break
                containers = self._get_kube_config(c_id, 'spec').get('containers', [])
                for co in containers:
                    if co.get('name') == c_name:
                        ports = map(lambda x: str(x.get('containerPort')), co.get('ports', []))
        ports = sorted(ports, key=lambda x: int(x))
        return ports

    def get_tags(self, c_inspect):
        """Extract useful tags from docker or platform APIs. These are collected by default."""
        tags = []
        # if is_kubernetes
        if os.environ.get('KUBERNETES_PORT', False):
            pod_metadata = self._get_kube_config(c_inspect.get('Id'), 'metadata')

            if pod_metadata is None:
                log.warning("Failed to fetch pod metadata for container %s."
                            " Kubernetes tags may be missing." % c_inspect.get('Id', '')[:12])
                return []
            # get labels
            kube_labels = pod_metadata.get('labels', {})
            for label, value in kube_labels.iteritems():
                tags.append('%s:%s' % (label, value))

            # get replication controller
            created_by = json.loads(pod_metadata.get('annotations', {}).get('kubernetes.io/created-by', '{}'))
            if created_by.get('reference', {}).get('kind') == 'ReplicationController':
                tags.append('kube_replication_controller:%s' % created_by.get('reference', {}).get('name'))

            # get kubernetes namespace
            tags.append('kube_namespace:%s' % pod_metadata.get('namespace'))

        return tags

    def _get_additional_tags(self, container_inspect):
        tags = []
        pod_metadata = self._get_kube_config(container_inspect.get('Id'), 'metadata')
        pod_spec = self._get_kube_config(container_inspect.get('Id'), 'spec')
        tags.append('node_name:%s' % pod_spec.get('nodeName'))
        tags.append('pod_name:%s' % pod_metadata.get('name'))
        return tags

    def _get_kube_config(self, c_id, key):
        """Get a part of a pod config from the kubernetes API"""
        pods = self._get_pod_list()
        for pod in pods:
            c_statuses = pod.get('status', {}).get('containerStatuses', [])
            for status in c_statuses:
                if c_id == status.get('containerID', '').split('//')[-1]:
                    return pod.get(key, {})

    def _get_pod_list(self):
        """Query the pod list from the kubernetes API and returns it as a list"""
        host_ip = _get_default_router()
        config_file_path = get_conf_path(KUBERNETES_CHECK_NAME)
        check_config = check_yaml(config_file_path)
        instances = check_config.get('instances', [{}])
        kube_port = instances[0].get('kubelet_port', DEFAULT_KUBELET_PORT)
        pod_list = requests.get('http://%s:%s/pods' % (host_ip, kube_port)).json()
        return pod_list.get('items', [])

    def get_configs(self):
        """Get the config for all docker containers running on the host."""
        containers = [(container.get('Image').split(':')[0].split('/')[-1], container.get('Id'), container.get('Labels')) for container in self.docker_client.containers()]
        configs = {}
        # used by the configcheck agent command to trace where check configs come from
        trace_config = self.agentConfig.get('trace_config', False)

        for image, cid, labels in containers:
            try:
                conf = self._get_check_config(cid, image, trace_config=trace_config)
                if trace_config and conf is not None:
                    source, conf = conf
                if conf is not None:
                    check_name = conf[0]
                    # build instances list if needed
                    if configs.get(check_name) is None:
                        if trace_config:
                            configs[check_name] = (source, (conf[1], [conf[2]]))
                        else:
                            configs[check_name] = (conf[1], [conf[2]])
                    else:
                        if trace_config:
                            if configs[check_name][1][0] != conf[1]:
                                log.warning('different versions of `init_config` found for check {0}.'
                                            ' Keeping the first one found.'.format(check_name))
                            configs[check_name][1][1].append(conf[2])
                        else:
                            if configs[check_name][0] != conf[1]:
                                log.warning('different versions of `init_config` found for check {0}.'
                                            ' Keeping the first one found.'.format(check_name))
                            configs[check_name][1].append(conf[2])
            except Exception:
                log.exception('Building config for container %s based on image %s using service'
                              ' discovery failed, leaving it alone.' % (cid[:12], image))
        log.debug('check configs: %s' % configs)
        return configs

    def _get_check_config(self, c_id, image, trace_config=False):
        """Retrieve a configuration template and fill it with data pulled from docker."""
        inspect = self.docker_client.inspect_container(c_id)
        template_config = self._get_template_config(image, trace_config=trace_config)
        if template_config is None:
            log.debug('Template config is None, container %s with image %s '
                      'will be left unconfigured.' % (c_id[:12], image))
            return None

        if trace_config:
            source, template_config = template_config

        check_name, init_config_tpl, instance_tpl, variables = template_config
        var_values = {}

        # add default tags to the instance
        tags = self.get_tags(inspect)
        if tags:
            tags += instance_tpl.get('tags', [])
            instance_tpl['tags'] = tags

        for v in variables:
            # variables can be suffixed with an index in case a list is found
            var_parts = v.split('_')
            if var_parts[0] in self.VAR_MAPPING:
                try:
                    res = self.VAR_MAPPING[var_parts[0]](inspect)
                    # if an index is found in the variable, use it to select a value
                    if len(var_parts) > 1 and isinstance(res, list) and int(var_parts[-1]) <= len(res):
                        var_values[v] = res[int(var_parts[-1])]
                    # if no valid index was found but we have a list, return the last element
                    elif isinstance(res, list):
                        var_values[v] = res[-1]
                    else:
                        var_values[v] = res
                except Exception as ex:
                    log.error("Could not find a value for the template variable %s: %s" % (v, str(ex)))
            else:
                log.error("No method was found to interpolate template variable %s." % v)
        init_config, instances = self._render_template(init_config_tpl or {}, instance_tpl or {}, var_values)

        if trace_config:
            return (source, (check_name, init_config, instances))

        return (check_name, init_config, instances)

    def _get_template_config(self, image_name, trace_config=False):
        """Extract a template config from a K/V store and returns it as a dict object."""
        config_backend = self.agentConfig.get('sd_config_backend')
        if config_backend is None:
            auto_conf = True
            log.warning('No supported configuration backend was provided, using auto-config only.')
        else:
            auto_conf = False

        tpl = self.config_store.get_check_tpl(image_name, auto_conf=auto_conf, trace_config=trace_config)

        if trace_config and tpl is not None:
            source, tpl = tpl
        if tpl is not None and len(tpl) == 3:
            check_name, init_config_tpl, instance_tpl = tpl
        else:
            log.debug('No template was found for image %s, leaving it alone.' % image_name)
            return None
        try:
            # build a list of all variables to replace in the template
            variables = self.PLACEHOLDER_REGEX.findall(str(init_config_tpl)) + \
                self.PLACEHOLDER_REGEX.findall(str(instance_tpl))
            variables = map(lambda x: x.strip('%'), variables)
            if not isinstance(init_config_tpl, dict):
                init_config_tpl = json.loads(init_config_tpl or '{}')
            if not isinstance(instance_tpl, dict):
                instance_tpl = json.loads(instance_tpl)
        except json.JSONDecodeError:
            log.exception('Failed to decode the JSON template fetched from {0}. Configuration'
                          ' by service discovery failed for {1}.'.format(config_backend, image_name))
            return None

        if trace_config:
            return (source, (check_name, init_config_tpl, instance_tpl, variables))

        return (check_name, init_config_tpl, instance_tpl, variables)
