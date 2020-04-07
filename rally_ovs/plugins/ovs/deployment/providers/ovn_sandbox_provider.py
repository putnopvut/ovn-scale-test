# Copyright 2016 Ebay Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from rally.deployment.serverprovider import provider
from rally.common import sshutils
from utils import NCatClient


class OvsServer(provider.Server):
    def __init__(self, config, cred):
        self.config = config
        self.host = cred["host"]
        self.user = cred["user"]
        self.key = cred.get("key")
        self.password = cred.get("password")
        server_type = config.get("server_type", "ssh")
        self.port = cred.get("port", 22 if server_type == "ssh" else 8000)
        if server_type == "plaintext":
            self.client = NCatClient(self.host, self.port)
        else:
            self.client = sshutils.SSH(self.user, self.host,
                                       key_filename=self.key,
                                       port=self.port,
                                       password=self.password)


@provider.configure(name="OvsSandboxProvider")
class OvsSandboxProvider(provider.ProviderFactory):
    """Provide VMs using an existing OpenStack cloud.

    Sample configuration:

        {
            "type": "OvsSandboxProvider",
            "deployment_name": "OVS sandbox controller",
            "credentials": [
                {
                    "host": "192.168.20.10",
                    "user": "root"}
            ]
        }
    """

    CREDENTIALS_SCHEMA = {
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "port": {"type": "integer"},
            "user": {"type": "string"},
            "key": {"type": "string"},
            "password": {"type": "string"}
        },
        "required": ["host", "user"]
    }


    CONFIG_SCHEMA = {
        "type": "object",
        "properties": {
            "type": {"type": "string"},
            "server_type": {"type": "string"},
            "credentials": {
                "type": "array",
                "items": CREDENTIALS_SCHEMA
            },
        },
        "additionalProperties": False,
        "required": ["credentials"]
    }

    def __init__(self, deployment, config):
        super(OvsSandboxProvider, self).__init__(deployment, config)
        self.credentials = config["credentials"]
        self.config = config

    def create_servers(self):
        servers = []

        for credential in self.credentials:
            servers.append(OvsServer(self.config, credential))

        return servers

    def destroy_servers(self):
        pass
