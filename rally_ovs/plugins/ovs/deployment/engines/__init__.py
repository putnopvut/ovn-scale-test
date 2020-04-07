
import os
from rally_ovs.plugins.ovs.deployment.providers.ovn_sandbox_provider import OvsServer


OVS_REPO = "https://github.com/openvswitch/ovs.git"
OVS_BRANCH = "master"
OVS_USER = "rally"


def get_script(name):
    return open(os.path.join(os.path.abspath(
        os.path.dirname(__file__)), "ovs", name), "rb")


def get_script_path(name):
    return os.path.join(os.path.abspath(
        os.path.dirname(__file__)), "ovs", name);

def get_updated_server(server, **kwargs):
    credentials = server.get_credentials()
    credentials.update(kwargs)
    return OvsServer(server.config, credentials)
