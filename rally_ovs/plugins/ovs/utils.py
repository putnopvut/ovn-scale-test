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

import random
import netaddr
import six

from consts import ResourceType
from rally.common import sshutils
from rally.common import objects
from rally.common import utils

from rally.common import db

import socket
import selectors
import time
import logging

LOG = logging.getLogger(__name__)

cidr_incr = utils.RAMInt()

'''
    Find credential resource from DB by deployment uuid, and return
    info as a dict.

    :param deployment deployment uuid
'''
def get_credential_from_resource(deployment):

    res = None
    if not isinstance(deployment, objects.Deployment):
        deployment = objects.Deployment.get(deployment)

    res = deployment.get_resources(type=ResourceType.CREDENTIAL)

    return res["info"]



def get_ssh_from_credential(cred):
    sshcli = sshutils.SSH(cred["user"], cred["host"],
                       port = cred["port"],
                       key_filename = cred["key"],
                       password = cred["password"])
    return sshcli


def get_ssh_client_from_deployment(deployment):
    cred = get_credential_from_resource(deployment)

    return get_ssh_from_credential(cred)



def get_random_sandbox(sandboxes):
    info = random.choice(sandboxes)
    sandbox = random.choice(info["sandboxes"])

    return info["farm"], sandbox



def get_random_mac(base_mac):
    mac = [int(base_mac[0], 16), int(base_mac[1], 16),
           int(base_mac[2], 16), random.randint(0x00, 0xff),
           random.randint(0x00, 0xff), random.randint(0x00, 0xff)]
    if base_mac[3] != '00':
        mac[3] = int(base_mac[3], 16)
    return ':'.join(["%02x" % x for x in mac])



def generate_cidr(start_cidr="10.2.0.0/24"):
    """Generate next CIDR for network or subnet, without IP overlapping.

    This is process and thread safe, because `cidr_incr' points to
    value stored directly in RAM. This guarantees that CIDRs will be
    serial and unique even under hard multiprocessing/threading load.

    :param start_cidr: start CIDR str
    :returns: next available CIDR str
    """
    cidr = str(netaddr.IPNetwork(start_cidr).next(next(cidr_incr)))
    return cidr




def py_to_val(pyval):
    """Convert python value to ovs-vsctl value argument"""
    if isinstance(pyval, bool):
        return 'true' if pyval is True else 'false'
    elif pyval == '':
        return '""'
    else:
        return pyval



def get_farm_nodes(deploy_uuid):
    deployments = db.deployment_list(parent_uuid=deploy_uuid)

    farm_nodes = []
    for dep in deployments:
        res = db.resource_get_all(dep["uuid"], type=ResourceType.SANDBOXES)
        if len(res) == 0 or len(res[0].info["sandboxes"]) == 0:
            continue

        farm_nodes.append(res[0].info["farm"])

    return farm_nodes




def get_sandboxes(deploy_uuid, farm="", tag=""):

    sandboxes = []
    deployments = db.deployment_list(parent_uuid=deploy_uuid)
    for dep in deployments:
        res = db.resource_get_all(dep["uuid"], type=ResourceType.SANDBOXES)
        if len(res) == 0 or len(res[0].info["sandboxes"]) == 0:
            continue

        info = res[0].info

        if farm and farm != info["farm"]:
            continue

        for k,v in six.iteritems(info["sandboxes"]):
            if tag and tag != v:
                continue

            sandbox = {"name": k, "tag": v, "farm": info["farm"],
                       "host_container": info["host_container"]}
            sandboxes.append(sandbox)


    return sandboxes


class NCatError(Exception):
    def __init__(self, details):
        self.details = details


class NCatClient(object):
    def __init__(self, server, port):
        self.server = server
        LOG.info(f"Creating connection to {server}:{port}")
        self.sock = socket.create_connection((server, port))
        self.sel = selectors.DefaultSelector()
        self.sel.register(self.sock, selectors.EVENT_READ)

    def put_file(source_path, dest_path):
        first_line = True
        with open(source_path) as infile:
            for line in infile:
                redirect = '>' if first_line else '>>'
                self.run(f'echo -e "{line}" {redirect} {dest_path}')
                first_line = False

    def run(self, cmd, stdin=None, stdout=None, stderr=None,
            raise_on_error=True, timeout=3600):
        start = time.clock_gettime(time.CLOCK_MONOTONIC)
        end = time.clock_gettime(time.CLOCK_MONOTONIC) + timeout
        to = end - start
        # We have to doctor the command a bit for three reasons:
        # 1. We need to add a newline to ensure that the command
        #    gets sent to the server and doesn't just get put in
        #    the socket's write buffer.
        # 2. We need to pipe stderr to stdout so that stderr gets
        #    returned over the client connection.
        # 3. We need to add some marker text so our client knows
        #    that it has received all output from the command. This
        #    marker text let's us know if the command completed
        #    successfully or not.
        good = "SUCCESS"
        bad = "FAIL"
        result = f"&& echo -n {good} || echo -n {bad}"
        LOG.info(f"Sending command {cmd}")
        self.sock.send(f"({cmd}) 2>&1 {result}\n".encode('utf-8'))
        out = ""
        stream = None
        error = False
        while True:
            events = self.sel.select(to)
            if len(events) == 0:
                break
            for key, mask in events:
                buf = key.fileobj.recv(4096).decode('utf-8')
                LOG.info(f"Received {buf}")
                if buf.endswith(good):
                    LOG.info("Ends with good!")
                    out += buf[:-len(good)]
                    stream = stdout
                    to = 0
                    break
                elif buf.endswith(bad):
                    LOG.info("Ends with bad!")
                    out += buf[:-len(bad)]
                    # We assume that if the command errored, then everything
                    # that was output was stderr. This isn't necessarily
                    # accurate but it hopefully won't ruffle too many feathers.
                    stream = stderr
                    error = True
                    to = 0
                    break
                else:
                    LOG.info("Ends with other")
                    out += buf
                    to = end - time.clock_gettime(time.CLOCK_MONOTONIC)

        if stream is not None:
            stream.write(out)

        if error and raise_on_error:
            details = (f"Error running command {cmd}\n"
                       f"Last stderr output is {out}\n")
            raise NCatError(details)


def get_client_connection(cred, server_type):
    if server_type == "plaintext":
        return NCatClient(cred["host"], cred.get('port', 8000))
    else:
        return get_ssh_from_credential(cred)

def put_file(client, source, dest):
    if isinstance(client, NCatClient):
        client.put_file(source, dest)
    else:
        # SSH client
        client.ssh.put_file(source, dest)
