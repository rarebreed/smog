"""
This module contains both the NUMA class helper, and its tests.  This is unlike
most test environments where you will see a separation in the file of the
unittest.TestCase class and any utilities it may use.  The reason these classes
are combined in the same module is to also allow for easier manual, ad-hoc
exploratory testing within a python REPL.
"""
from smog.tests.base import safe_delete

__author__ = 'Sean Toner'

import re
import xml.etree.ElementTree as et
import uuid
from pprint import pprint
import time
import os
from functools import wraps

from toolz.itertoolz import take
import libvirt
import untangle

from smog.tests import base
from smog.core.exceptions import ArgumentError, BootException
from smog.core.logger import glob_logger, make_timestamped_filename
from smog.core.commander import Command
from smog.core.decorators import require_remote
from smog.core.xml.helper import get_xml_children
from smog.core.functional import bytes_iter, powers_two
from smog.glance import create_image, get_cloud_image
import smog.nova
import smog.virt


def determine_fit(nodes, mem_type, delta="smaller", factor=2, size_fmt="MB"):
    """
    This function will give an amount of memory suitable for allotting to an
    instance.  It looks up the free or total memory size (that is contained in
    the nodes dict), and will determine how much memory to allocate accordingly

    :param nodes: returned dict from NUMA.get_host_numactl
    :param mem_type: one of "free" or "size"
    :param delta: if "smaller", divide the numa available memory by factor,
                  otherwise multiply by factor
    :param factor: A multiplier (if delta is larger) or divisor (if smaller)
                   for the amount of memory to return
    :return: a dict of {node_num: {mem_type: calculated size}}
    """
    kb, mb, gb, tb = take(4, bytes_iter())
    mult = {"KB": kb, "MB": mb, "GB": gb, "TB": tb}

    if "number" in nodes:
        _ = nodes.pop("number")

    size = {}
    for node in nodes:
        size[node] = {}
        subnode = nodes[node]
        for mem, qual in [subnode[mem_type].split()
                          for attr in subnode.keys()
                          if attr in [mem_type]]:
            total_mem_bytes = int(mem) * mult[qual]
            for two in powers_two():
                size_qualified = two * mult[qual]
                if total_mem_bytes > size_qualified:
                    continue
                else:
                    if delta == "smaller":
                        size_qualified /= factor
                    else:
                        size_qualified *= factor
                    size_qualified /= mult[size_fmt]
                    size[node].update({mem_type: size_qualified})
                    break
    return size


def get_cpus_from_node(nodes, node_num):
    """Determines the number of cpus for a given node

    :param nodes: the returned dict from NUMA.get_host_numactl
    :param node_num: the node number to look up in nodes
    :return: the number of cpus in that node
    """
    cpu_list = [int(elem) for elem in nodes[node_num]["cpus"].split()]
    return len(cpu_list)


def make_root(xmlstring):
    """
    Simply generates an xml.etree.ElementTree from an xml defined string

    :param xmlstring: A str which is xml
    :return: Element
    """
    return et.fromstring(xmlstring)


def get_nova_instance_info(instance, key=None):
    info = instance.to_dict()
    if key is None:
        return info
    # purposefully raise KeyError if key isn't in instance
    return info[key]


def check_largepage_support_persist(host):
    smog.tests.base.scp("root@{}:/etc/sysctl.conf".format(host), ".")

    patt = re.compile(r"vm\.nr_hugepages=(\d+)")
    hp = 0
    with open("sysctl.conf") as sysctl:
        for line in sysctl:
            m = patt.search(line)
            if m:
                hp = m.groups()[0]
                break

    os.unlink("sysctl.conf")
    return hp


def check_largepage_support_current(host):
    cmd = Command("cat /proc/sys/vm/nr_hugepages", host=host)
    res = cmd(shell=True, remote=True)


    patt = re.compile(r"vm\.nr_hugepages=(\d+)")
    hp = 0
    with open("sysctl.conf") as sysctl:
        for line in sysctl:
            m = patt.search(line)
            if m:
                hp = m.groups()[0]
                break

    os.unlink("sysctl.conf")
    return hp


def setup_largepage_support(host, numpages=128):
    """
    Sets large page support on the hypervisor hosts.  This echoes a value
    to sysconfig and then reboots the machine.  Note that the hosts has
    to be the hosts itself....not a VM
    :return:
    """
    sysfile = "/etc/sysctl.conf"
    cmd = 'echo "vm.nr_hugepages={}" >> {}'.format(numpages, sysfile)
    command = Command(cmd, host=host)
    result = command()
    if result != 0:
        Exception("Unable to set large pages to /etc/sysctl.conf")

    # Verify it was set
    command = Command("virsh freepages --all", host=host)
    result = command(remote=True, shell=True)

    # TODO: parse the output
    return result


def check_nested_vm_support(host):
    """
    This function will run a quick modinfo to see if nested support is capable
    :param host:
    :return:
    """
    pass


def enable_nested_vm_support(host):
    """
    Edits the /etc/modprobe.d/dist.conf file to add in nested option
    to persist across reboots

    :param host:
    :return:
    """
    pass


def verify_nested_vm_support(host):
    """
    Reads in /sys/module/kvm_intel/parameters/nested

    :param host:
    :return:
    """
    pass


def flavor_comp(fn):
    """
    A decorator used to compose flavor creation.  The function that it decorates
    should have a keyword argument called flv or flavor.  The value is a flavor
    object.  The function should return the extra_specs it created.
    :param fn:
    :return:
    """
    @wraps(fn)
    def inner(*args, **kwargs):
        self = args[0]

        if "flv" not in kwargs or ("flv" in kwargs and kwargs["flv"] is None):
            # Create a default flavor
            flavor_num = len(self.get_all_flavors()) + 1
            flvname = fn.__name__ + str(flavor_num)
            return self.create_flavor(flvname)
        else:
            flv = kwargs["flv"]

        specs = fn(*args, **kwargs)
        orig_keys = flv.get_keys()
        specs.update(orig_keys)
        flv.set_keys(specs)
        return flv
    return inner


class NUMA(base.BaseStack):
    """
    A class that represents functionality to setup NUMA related tasks (eg,
    NUMA guest topology definition, vcpu pinning, large page support, etc)
    """
    def __init__(self, logger=glob_logger, **kwargs):
        """
        This class will only contain immutable data.  It is a helper to set the
        extra specs and dumpxml to verify

        See the BaseStack init for **kwargs keywords
        """
        super(NUMA, self).__init__(logger=logger, **kwargs)

    def get_all_flavors(self):
        return self.nova.flavors.list()

    @flavor_comp
    def create_numa_topo_extra_specs(self, flv=None, numa_nodes=1,
                                     numa_mempolicy="preferred",
                                     specs=None):
        """
        Sets the extra specs that will be used to set the NUMA defintions

        :param flavor: A Flavor object
        :param numa_nodes: The number of numa nodes to give the guest topology
        :param numa_mempolicy: (str) One of "preferred"|"strict"
        :param specs: a dictionary with the following valid key,value pairs

          - "hw:numa_cpus.X": where X is the numa node id, value is a comma
                              separated list of cores
          - "hw:numa_mem.X": where X is the numa node id, value is the amount of
                             RAM in kb for that numa node

        :return: The dictionary representing the extra specs

        Usage::

            nt = NUMATest()
            flavor = nt.get_flavor("m1.tiny")
            specs = nt.create_numa_topo_extra_specs(numa_nodes=2, specs=
                                       {"hw:numa_cpus.0": "0,1,2,3",
                                        "hw:numa_cpus.1": "4,5,6,7",
                                        "hw:numa_mem.0": 1024,
                                        "hw:numa_mem.1": 1024})
        """
        extra_specs = {"hw:numa_nodes": numa_nodes,
                       "hw:numa_policy": numa_mempolicy}

        if specs is not None:
            extra_specs.update(specs)
        return extra_specs

    @flavor_comp
    def create_pci_flavor(self, alias_name, num_devs=1, flv=None):
        form = "{}:{}".format(alias_name, num_devs)
        extra_specs = {"pci_passthrough:alias": form}
        return extra_specs

    @flavor_comp
    def create_large_page_flavor(self, flv=None, size="large"):
        """

        :param flv:
        :param size:
        :return: :raise ArgumentError:
        """
        choices = ("large", "small", "any")
        if size not in choices:
            raise ArgumentError("size must be in {}".format(choices))
        extra_specs = {"hw:mem_page_size": size}
        return extra_specs

    @flavor_comp
    def create_vcpu_topo_flavor(self, flv=None, cores="1:",
                                threads=":",
                                sockets="1:"):
        """
        Creates a vcpu topology.  By default, libvirt will create as many
        sockets as there are vcpus.  So for example, if you have 8 cpus, and
        you request a flavor with 4 vcpus, libvirt will create 4 sockets, with
        1 core apiece.  This allows you to create different topologies.

        This is not to be confused however with vcpu pinning.  The vcpus are
        still allowed to float across different pcpus.  This feature was mainly
        designed to get around licensing restrictions some OS'es place

        :param flv: a Flavor object
        :param cores: a colon separated str, the number on the left is the
                      desired number of cores, the second is the max.  If the
                      2nd is blank, there is no maximum.
        :param sockets: Same as above, but for requested sockets
        :param threads: Same as above, but for requested cores.
        :return:
        """
        specs = {}
        kwargs = {"hw:cpu_threads": threads, "hw:cpu_cores": cores,
                  "hw:cpu_sockets": sockets}
        for k, val in kwargs.items():
            v, m = val.split(":")
            if v:
                specs.update({k: v})
            if m:
                key = "hw:max_cpu_{}".format(k)
                specs.update({key: m})
        return specs

    @flavor_comp
    def create_vcpu_pin_flavor(self, flv=None, policy="dedicated",
                               thread_policy="prefer"):
        """
        Creates a flavor that can specify if a vcpu is pinned to a pcpu


        :param flv:
        :param policy: one of dedicated or shared
        :param thread_policy: one of avoid|separate|isolate|prefer
        :return: dict of the extra specs
        """
        return {"hw:cpu_policy": policy, "hw:cpu_thread_policy": thread_policy}

    @require_remote("numactl")
    def get_host_numactl(self, **kwargs):
        """
        Retrieves the numactl -H information for a hosts

        To call on a remote machine, the keywords of hosts, username, and
        password must be supplied which will be passed to paramiko to make the
        remote call.  If no kwargs are given, it is assumed the command will be
        run on the local machine

        :param kwargs: Optional hosts= ipaddress of remote machine
                                username= username to ssh as
        :return: a dictionary of
          node_num:  # where node_num is an int of the numa node index
             "cpus": a string of the cpus in that node
             "size": the total memory on the node in MB
             "free": the free amount of memory on the numa node in MB
        """
        # FIXME: replace the dependency on numactl by using libvirt
        cmd = Command("numactl -H", host=kwargs["host"],
                      user=kwargs["username"])
        res = cmd(throws=True, showout=False, remote=True)
        output = res.output

        _patt = re.compile(r"node\s+(\d+)\s+(cpus|size|free):\s+(.+)")
        nodes = {}
        for line in output.split("\n"):
            m = _patt.search(line)
            if m:
                node_num, key, val = m.groups()
                node_num = int(node_num)

                if node_num not in nodes:
                    nodes[node_num] = {}
                nodes[node_num].update({key: val})
        nodes["number"] = len(nodes.keys())
        return nodes

    def dumpxml(self, uid, host=None, driver="qemu+ssh", user="root"):
        """
        Retrieves the XML dump for the given uuid on hosts.  If hosts is not None,
        requires ssh key to have been copied to remote machine for user

        :param uid: the uuid string of the instance to get xml dump from
        :param host: the ip address or hostname
        :param driver: (str) the libvirt driver to use
        :return: a string of the XML domain information
        """
        drv_format = "qemu:///system"
        if host is not None:
            drv_format = "{}://{}@{}/system".format(driver, user, host)
        self.logger.info("getting libvirt xml from {}".format(drv_format))
        conn = libvirt.open(drv_format)
        xml_desc = None
        try:
            inst = conn.lookupByUUIDString(uid)
            xml_desc = inst.XMLDesc()
        except libvirt.libvirtError as le:
            msg = "Unable to find instance with UUID: {}".format(uid)
            self.logger.error(msg)
            raise le
        finally:
            conn.close()
            return xml_desc

    def get_hypervisors(self):
        return [hyper.host_ip for hyper in self.nova.hypervisors.list()]

    def get_large_page_info(self, bare_metal):
        res = base.read_proc_file(bare_metal, "/proc/sys/vm/nr_hugepages")
        return res.output

    def set_large_page_info(self, bare_metal, num_pages=128):
        return base.set_hugepages(bare_metal, num_pages=num_pages)


class NUMAVCPUPinningTest(base.NovaTest):
    """
    Tests the vcpu pinning feature
    """
    config_file = "numa_vcpu_config.yml"
    config_dir = __file__

    @classmethod
    def setUpClass(cls):
        super(NUMAVCPUPinningTest, cls).setUpClass()
        cls.set_base_config()
        cls.setup_nested_support()

    def _setup(self):
        self.numa = NUMA()
        self._base_setup(self.numa)

    def tearDown(self):
        self._base_setup(self.numa)
        if hasattr(self, "watcher"):
            print("cleaning up watcher")
            self.watcher.close()

    @base.declare
    def test_simple_vcpu_pinning(self):
        """
        This test creates a flavor where the vcpu is pinned to a host's pcpus

        - Create 2 aggregate groups

          - One will have metadata of pinned=true, the other pinned=false
          - One random compute host added to pinned=true, others to false

        - Create 2 flavors

          - One only needs 1 vcpu, the other 2 vcpus

        - Determine how many pcpus are available on the pinned=true host

          - Start with the largest flavor we can use to create new instance
          - Verify that instance launches successfully
          - Continue launching until no more pcpus left, and verify boot fails

        """
        pos_agg, neg_agg, ip = self.numa.create_aggregate_groups("pinned")
        conn = smog.virt.get_connection(ip)
        cells = smog.virt.get_cpu_topology(conn)
        info = smog.virt.friendly_topology(cells)

        # FIXME: We need a way to figure out which cell.  We will assume the
        # first numa node for now
        num_cpus = int(info[0]["cpus"])

        # Create the flavor we need
        extras = {"aggregate_instance_extra_specs:pinned": "true"}
        small_pin = 1
        pin_flavor = self.numa.create_flavor("pin_flavor_1", ram=512,
                                             vcpus=small_pin, specs=extras)
        specs = self.numa.create_vcpu_pin_flavor(flv=pin_flavor)
        self.logger.info("pin_flavor_1: " + str(specs.get_keys()))

        bigger_pin = 2
        pin_flavor2 = self.numa.create_flavor("pin_flavor_2", ram=512,
                                              vcpus=bigger_pin, specs=extras)
        spec2 = self.numa.create_vcpu_pin_flavor(flv=pin_flavor2)
        self.logger.info("pin_flavor_2: " + str(spec2.get_keys()))

        # Figure out how many pcpus we have left, and start pinning them
        # Since we just started the test, we should have 0 domains running
        # (unless there are non-Openstack VM's on your hypervisor)
        cpus_left = num_cpus
        id_ = 0
        while cpus_left > 0:
            test_name = "pintest_" + str(id_)
            if cpus_left >= bigger_pin:
                self.logger.info("Booting instance with pin_flavor_2...")
                inst = self.numa.boot_instance(flv=pin_flavor2, name=test_name)
                cpus_left -= bigger_pin
                vcpus = bigger_pin
            elif cpus_left == 1:
                self.logger.info("Booting instance with pin_flavor_1...")
                inst = self.numa.boot_instance(flv=pin_flavor, name=test_name)
                cpus_left -= small_pin
                vcpus = small_pin

            id_ += 1
            if inst:
                active = smog.nova.poll_status(inst, "ACTIVE")
                self.assertTrue(active)
                # Now, verify we actually have this pinned and that the
                # instance is on the right host
                discovered = self.numa.discover(guests=[inst])[0]
                xmldump = discovered.dumpxml()
                dump = untangle.parse(xmldump)
                placement = dump.domain.vcpu["placement"]
                txt = str(dump.domain.vcpu.cdata)
                self.assertTrue(placement == "static")
                self.logger.info("<vcpu placement='{}'>".format(placement))
                self.assertTrue(txt == str(vcpus))
                self.logger.info("vcpu cdata = {}".format(txt))
                self.assertTrue(discovered.host.host == ip)

        # We have filled up all our pcpus, so let's try to pin one more, and
        # verify that it fails
        self.logger.info("Negative test: No more huge pages left...")
        inst = self.numa.boot_instance(flv=pin_flavor, name="negative_pin")
        inactive = smog.nova.poll_status(inst, "ERROR")
        self.assertTrue(inactive)

    def _create_flavor(self, name, num_cpus, size, flavor=None, memsize="large",
                       specs=None, disksize=10):
        """
        """
        if not flavor:
            desc = "Creating large page flavor hw:mem_page_size={}"
            desc = desc.format(memsize)
            self.numa.logger.info(desc)
            flavor = self.numa.create_flavor(name, ram=size, vcpus=num_cpus,
                                             disksize=disksize)
        base = {"hw:mem_page_size": memsize}

        if specs is None:
            specs = base
        else:
            specs.update(base)

        flavor.set_keys(specs)
        # TODO: assert successful insertion of the extra specs
        extras = flavor.get_keys()
        self.numa.logger.info("Setting extra specs to {}".format(extras))
        return flavor


class NUMATopologyTest(base.NovaTest):
    """
    Tests the new libvirt features that allow a guest topology to be created.

    Because we can't be sure which compute node nova might select to create
    the instance, and because we need the actual hosts's physical capabilities,
    we have a bit of a problem.  There are a few solutions:

    - Assume the worst case, and the smallest hosts might be chosen for its
      numa information
    - Create an affinity, so that we know which hosts an instance will be
      created on
    - Create a host aggregate group

    The first solution has a problem where we may wind up trying to create a
    scenario where we do want to overcommit, but the guest gets placed on a
    larger compute node that is capable of handling the topology.

    The second solution sort of defeats the purpose of letting the scheduler
    decide where to place a guest instance.  However, it does allow us to
    determine where the instances (and therefore the flavor that defines the
    topology) will land

    TODO: The aggregate server group is a better solution but was unknown at
    the time this class was written
    """

    config_file = "numa_config.yml"
    config_dir = __file__

    @classmethod
    def setUpClass(cls):
        super(NUMATopologyTest, cls).setUpClass()
        cls.set_base_config()
        cls.setup_nested_support()

    def _setup(self):
        self.data = {}
        self.numa = NUMA()
        self.logger = self.numa.logger

        # Clean up
        self.numa.delete_instances()
        self.numa.delete_flavors()
        self.numa.delete_server_groups()

        # Create a ServerGroupAffinity, so that we can ensure a hosts is created
        # on a particular hosts ("compute1")
        self.logger.info("Creating affinity server group")
        self.group = smog.nova.server_group_create(self.numa.nova, "numa-group",
                                                   policies="affinity")
        self.group_id = {"group": self.group.id}
        self.data["group"] = self.group

        # We cant tell nova which hosts to build on.  So we create a tiny guest
        # and add it to an affinity group.  Then we can determine which hosts
        # it is on, get its numa characteristics and start adding other guests
        # to that hosts
        self.logger.info("Booting up initial instance to prime affinity group")
        test_flv = self.numa.get_flavor("m1.tiny")
        test_img = self.numa.get_image_name("cirros")
        test_inst = self.numa.boot_instance(test_img, test_flv, name="dummy",
                                            scheduler_hints=self.group_id)
        active = smog.nova.poll_status(test_inst, "ACTIVE", timeout=300)
        if not active:
            raise Exception("Instance did not come up")

        self.data.update({"test_instance": test_inst})
        time.sleep(1)
        test = self.numa.discover()[0]

        # Get the hosts of our sole test instance, and get our NUMA info. since
        # we used am affinity group, we know the hosts this instance is on is
        # the hosts the other instances will be on too
        self.nodes = self.numa.get_host_numactl(host=test.host.host)
        self.logger.info("NUMA info on hosts {}: {}".format(test.host.host,
                                                            self.nodes))
        self.num_nodes = self.nodes.pop("number")

    def cleanup(self):
        if self.data:
            # delete the instance, as we only needed it to know where
            if "test_instance" in self.data:
                test_inst = self.data.pop("test_instance")
                safe_delete([test_inst])
            if "group" in self.data:
                group = self.data.pop("group")
                self.numa.nova.server_groups.delete(group.id)
            if "guests" in self.data:
                guests = self.data.pop("guests")
                safe_delete(guest.instance for guest in guests)
            for node in self.data:
                obj = self.data[node]
                try:
                    flv = obj["flavor"]
                    flv.delete()
                except (KeyError, TypeError):
                    pass

        self.data = {}

    def tearDown(self):
        self.cleanup()

    def _create_numa_image(self, properties, location=None, name=None,
                           disk_format=None, img_name="test-img"):
        """
        The NUMA data can be put in the image properties instead of in the
        extra_specs of a flavor.  This returns a glance image that can be used

        :param properties: a dict of k:v pairs
        :param location: (str) URL for cirros image to download
        :param name: file name of cirros image
        :param disk_format: (str) eg "qcow2"
        :param img_name: (str) a name to give the image
        :return:
        """
        if location is None:
            location = self.config["cirros"]["location"]
        if name is None:
            name = self.config["cirros"]["name"]
        if disk_format is None:
            disk_format = self.config["cirros"]["disk_format"]

        cirros_loc = get_cloud_image(location, name)
        self.data.update({"cirros": cirros_loc})

        # create the glance image with the image property set
        img = create_image(self.numa.glance, cirros_loc,
                           disk_format=disk_format,
                           img_name=img_name,
                           properties=properties)
        return img

    def _create_numa_flavor(self, name, num_cpus, size, node_num=0, flavor=None,
                            extra_nodes=0, policy="preferred", specs=None):
        """
        Creates a flavor for a NUMA topology

        :param name: (str) name to give the flavor
        :param num_cpus: (int) how many vcpus to give the topology
        :param size: (int) size in MB to give the topology
        :param node_num: (int) which node to create for (starts at 0)
        :param flavor: (Flavor) an existing flavor to add extra_specs to
        :param extra_nodes: (int) The default is to define a single NUMA topology.
                            The number here is added to the number of NUMA nodes
        :param policy: One of 'preferred' or 'strict'
        :param specs: an optional dict that will be merged with the extra_specs
        :return:
        """
        if not flavor:
            desc = "Creating {} with cpus={}, memory={}"
            desc = desc.format(name, num_cpus, size)
            self.numa.logger.info(desc)
            flavor = self.numa.create_flavor(name, ram=size, vcpus=num_cpus,
                                             disksize=10)
            self.data[node_num].update({"vcpus": num_cpus, "size": size})
            # TODO: assert successful creation of the flavor

        # Create the extra specs.
        total_nodes = self.num_nodes + extra_nodes
        flave = self.numa.create_numa_topo_extra_specs(flv=flavor,
                                          numa_nodes=total_nodes,
                                          numa_mempolicy=policy,
                                          specs=specs)
        # TODO: assert successful insertion of the extra specs
        extras = flavor.get_keys()
        self.numa.logger.info("Setting extra specs to {}".format(extras))
        self.data[node_num].update({"flavor": flave})
        self.data[node_num].update({"specs": extras})
        return flavor

    def _base(self, fit, node=0, cpu_multiplier=1, extra_nodes=0,
              policy="preferred", image=None, flavor=None, instances=None,
              num_instances=1, specs=None):
        """
        Used as a generic function that the test functions can use.  This
        function will determine how many cpus and how much memory to give
        a topology based on the

        :param fit: dict provided from determine_fit() function
        :param node: Which NUMA node to configure
        :param cpu_multiplier: How much to multiply the node vcpus by
        :param extra_nodes: This number will be added to the hosts numa nodes
                            (to test overprovisioning)
        :param policy: One of "preferred" or "strict"
        :param image: an optional Image object to use (default is to use a built
                      in cirros image)
        :param flavor: A flavor that can be used (by default one will be created
                       for the test)
        :param instances: A sequence of instance objects.  By default, these
                          will be created for the test
        :param num_instances: How many instances to use/create
        :param specs: a dictionary of the extra specs options
        :return: a dictionary that contains state for cleanup
        """
        self.data[node] = {}

        # Determine how much memory and cpus to give a topology.  It uses
        # mem_multiplier to make
        mem_size = fit[node]["size"]  # in MB
        if mem_size < 512:
            mem_size = 512
        cpus = get_cpus_from_node(self.nodes, node) * cpu_multiplier

        # Create the flavor with the numa topology.  Here we set the flavor
        # with the number of nodes and the policy
        uid = uuid.uuid4()
        name = "numa-{}-{}".format(node, uid)
        if not flavor:
            flavor = self._create_numa_flavor(name, cpus, mem_size,
                                              node_num=node, policy=policy,
                                              extra_nodes=extra_nodes,
                                              specs=specs)

        # Get a basic cirros image
        if image is None:
            img = self.numa.get_image_name("cirros")
            self.data[node].update({"image": img})
        else:
            img = image

        # Now boot up the instances with our chosen flavor
        if not instances:
            images = [img for _ in range(num_instances)]
            flavors = [flavor for _ in range(num_instances)]
            boot = self.numa.boot_instances
            _ = boot(images, flavors, scheduler_hints=self.group_id)

        guests = self.numa.discover()
        self.data["guests"] = guests
        return self.data

    @base.declare
    def test_simple(self):
        """
        This test creates a simple topology in which the guest can fit in the
        hosts.  This should always pass since we are checking the hosts memory
        to ensure we create a flavor that the hosts can handle.

        - Determine how much memory per numa node is available

          - Done by determine_fit() in _base(), and set mem_multiplier=1

        - Create a flavor with only as much memory as there is on the node
        - Launch instance, and verify it is operational with a small stress test

        """
        mem_fit = determine_fit(self.nodes, "size", delta="smaller", factor=2)
        data = self._base(mem_fit, cpu_multiplier=1)
        guests = data["guests"]
        self.assertTrue(len(guests) == 2)

        # get the instance matching our NUMA topology, and get its domain
        # xml.  Look for the <cpu> element.  It should look something like this
        # for a single NUMA node::
        #   <cpu>
        #     <topology sockets='4' cores='1' threads='1'/>
        #       <numa>
        #         <cell id='0' cpus='0-3' memory='2097152'/>
        #       </numa>
        #   </cpu>
        for guest in guests:
            dump = guest.dumpxml()
            root = et.fromstring(dump)
            print(dump)

            # Look for the <numa> element inside <cpu>
            numa = [child for child in root.iter("cpu") if child.tag == "numa"]
            self.assertTrue(numa, msg="domain xml did not have <numa> element")
            cell = [child for child in numa[0].iter() if child.tag == "cell"]
            self.assertTrue(cell)

        # TODO:  Create a small stress test (IO traffic for 1 min)
        self.assertTrue(1)

    @base.declare
    def test_simple_w_image(self):
        """
        This test creates a simple topology in which the guest can fit in the
        hosts.  Rather than use a flavor with extra_specs, the fields are put
        as properties in a glance image.  This test should always pass, since we
        are checking the host's memory to ensure we create a topology that the
        host can handle

        - Determine how much memory per numa node is available

          - Done by determine_fit() in _base(), and set mem_multiplier=1

        - Create an image with only as much memory as there is on the node
        - Launch instance, and verify it is operational with a small stress test

        :return:
        """
        mem_fit = determine_fit(self.nodes, "size", delta="smaller", factor=2)
        flv = self.numa.get_flavor("m1.tiny")
        img_props = {"hw_numa_nodes": self.num_nodes,
                     "hw_numa_policy": "preferred"}
        img = self._create_numa_image(img_props)
        data = self._base(mem_fit, cpu_multiplier=1, flavor=flv, image=img)
        guests = data["guests"]
        self.assertTrue(len(guests) == 2)

        for guest in guests:
            dump = guest.dumpxml()
            root = et.fromstring(dump)
            print(dump)

            # Look for the <numa> element inside <cpu>
            numa = [child for child in root.iter("cpu") if child.tag == "numa"]
            self.assertTrue(numa, msg="domain xml did not have <numa> element")
            cell = [child for child in numa[0].iter() if child.tag == "cell"]
            self.assertTrue(cell)

    @base.declare
    def test_too_many_nodes(self):
        """
        This test creates a NUMA topology with 1024 total NUMA nodes
        physical hosts has. This should always fail,  since no computer can have
        this many NUMA nodes.

        - Set the number of extra_nodes=1000
        - Create a flavor with only as much memory as there is on the node
        - Launch instance, and verify it is operational with a small stress test

        """
        mem_fit = determine_fit(self.nodes, "size", delta="smaller", factor=2)
        total_nodes = 2
        nodes = range(total_nodes)
        # Calculate the extra specs
        fmt_cpu = "hw:numa_cpu.{}"
        fmt_mem = "hw:numa_mem.{}"
        extras = {}
        mem = mem_fit[0]["size"] / total_nodes
        for node in nodes:
            cpu_data = {fmt_cpu.format(node): node}
            mem_data = {fmt_mem.format(node): mem}
            extras.update(cpu_data)
            extras.update(mem_data)
        pprint(extras)
        self._base(mem_fit, cpu_multiplier=1, extra_nodes=total_nodes-1,
                   policy="strict", specs=extras)

    @base.declare
    def test_mem_strict(self):
        """
        Creates a topology that specifies a mempolicy of strict.  In the first
        case, specify only as much memory that can fit on the hosts given its
        NUMA characteristics.

        - Determine how much memory per numa node is available

          - Done by determine_fit() in _base(), and set mem_multiplier=1

        - Create a flavor that specifies hw:mem_policy="strict"

          - Only give it as much memory as there is on the node

        - Launch instance, and verify it is operational with a small stress test
        """
        mem_fit = determine_fit(self.nodes, "size", delta="smaller", factor=2)
        # data = self._base(mem_fit, cpu_multiplier=1, policy="strict")
        data = self._base(mem_fit, cpu_multiplier=1)
        guests = data["guests"]
        self.assertTrue(len(guests) == 2)
        self.same_host(guests)
        for dump in self._get_xml(guests):
            print(dump)

        # TODO: validate the xml dump

    @base.declare
    def test_mem_too_large(self):
        """
        Creates a topology that specifies a mempolicy of strict.  Create a
        topology that has more memory than is available on the hosts.  This test
        should fail since a policy of strict was put in.

        In the second case, set the policy to "preferred".

        - Determine how much memory per numa node is available

          - Done by determine_fit() in _base(), and set mem_multiplier=1

        - Create a flavor that specifies hw:mem_policy="strict"

          - Only give it as much memory as there is on the node

        - Try to launch instance, but verify it raises a BootException
          since we set policy to strict, but allocated more memory than hosts
        """
        mem_fit = determine_fit(self.nodes, "size", delta="larger", factor=2)
        self.assertRaises(BootException, self._base, mem_fit, policy="strict")

        mem_fit = determine_fit(self.nodes, "size", delta="larger", factor=2)
        self.assertRaises(BootException, self._base, mem_fit)


    @base.declare
    def test_extra_nodes(self):
        """
        This simply creates one more node than exists on the physical hosts.  The
        flavor that is created will only have as much memory as can fit on the
        hosts, and cpu allocation will also fit.

        # FIXME: When will adding an extra numa node fail?

        :return:
        """
        mem_fit = determine_fit(self.nodes, "size", factor=1)

        data = self._base(mem_fit, cpu_multiplier=1, extra_nodes=0,
                          policy="strict")
        guests = data["guests"]
        self.assertTrue(len(guests) == 2)
        self.same_host(guests)
        for guest in guests:
            dump = guest.dumpxml()
            root = et.fromstring(dump)
            print(dump)

            # Look for the <numa> element inside <cpu>
            numa = [child for child in root.iter("cpu") if child.tag == "numa"]
            self.assertTrue(numa, msg="domain xml did not have <numa> element")
            cell = [child for child in numa[0].iter() if child.tag == "cell"]
            self.assertTrue(cell)

    def not_ready_test_split_node(self):
        """
        Creates a topology with more than one NUMA node.  Half the CPUs and
        memory go to one node, and the rest to the other.

        :return:
        """
        # split the cpus evenly across the numa nodes
        extra_nodes = 0
        if self.num_nodes % 2 == 1:
            # we have an odd number, so adding 1 node is easy
            extra_nodes = 1

        mem_fit = determine_fit(self.nodes, "free")

        spec_cpu = "hw:numa_cpu.{}"
        spec_mem = "hw:numa_mem.{}"
        for node in self.nodes:
            cpus = get_cpus_from_node(self.nodes, node)
            spec_str = spec_cpu.format(node)

        data = self._base(cpu_multiplier=2, extra_nodes=extra_nodes,
                          policy="strict")

        guests = data["guests"]
        self.assertTrue(len(guests) == 1)
        self.same_host(guests)
        for dump in self._get_xml(guests):
            print(dump)

        should_num_nodes = self.num_nodes
        should_mem = 512  # FIXME
        self.assertTrue(1)


class NUMALargePage(base.NovaTest):
    """
    Tests large page NUMA support.  This test will ensure that the hypervisor
    has large memory page backing, proper scheduler filters, and host aggregates
    to ensure we can pin the correct host with the memory requirement we need
    of it.  It uses libvirt to extract an instance's domain XML to verify that
    the memory pinning was proper, as well as check the hypervisor host's
    /proc/meminfo, and the qemu process is using large pages
    """
    config_file = "numa_lp_config.yml"
    config_dir = __file__

    @classmethod
    def set_largepages(cls):
        do_large_page = cls.config["nova"]["large_page"]
        pages = cls.config["nova"]["large_page_num"]
        baremetal = cls.config["baremetal"]

        if do_large_page:
            for name, ip in baremetal.items():
                num = base.set_hugepages(ip, int(pages))
                _ = Command("openstack-service restart nova", host=ip)()
                if num != pages:
                    raise Exception("Unable to set huge pages")

    @classmethod
    def setUpClass(cls):
        # TODO: Need to add large page support for the bare metal system
        super(NUMALargePage, cls).setUpClass()
        cls.set_base_config()
        cls.set_largepages()

        # FIXME: Only call setup_nested_support if the compute type is a VM
        # This may require redoing this function to take a list of compute
        # nodes
        cls.setup_nested_support()

    def _setup(self):
        self.numa = NUMA()
        self._base_setup(self.numa)

    def tearDown(self):
        self._base_setup(self.numa)
        if hasattr(self, "watcher"):
            glob_logger.debug("cleaning up watcher")
            self.watcher.close()

    @base.declare
    def test_large_pages(self):
        """
        Create a flavor with large pages flavor.  Boot instances until all huge
        pages are gone

        - Create Host Aggregate with large_page=true and add host to this aggregate
        - Create another Host Aggregate group with large_page=false

          - All other compute hosts added to this group

        - Create a flavor with hw:mem_page_size=large and large_page"="true"
        - Boot an instance with this flavor

          - Make sure it goes to the host in the Aggregate large_page=true
          - Verify that huge pages are decreased (by RAM amount of instance)

        - Repeat the above until all free huge pages are gone
        - Verify that once all free huge pages are gone, no more instances can
          be created with the large page flavor
        - Then try to boot instances using a regular (non-large page) flavor

          - These will not specify an aggregate, so they may go to any node

        - Try to boot an instance with the any size flavor.

          - Verify this succeeds.  This flavor will go to the large_page=true
          - Since it still has small pages for memory, it should succeed
        """
        self.logger.info("Creating aggregate instance groups...")
        meta_key = "large_page"
        ta, fa, lg_host_ip = self.numa.create_aggregate_groups(meta_key)

        # Get which host the ta (true aggregate) is so that we can verify our
        # instances land on this host.  The Aggregrate will only have one host
        large_page_host = ta.hosts[0]

        # Create the large page flavor
        extra = {"hw:mem_page_size": "large", meta_key: "true",
                 "aggregate_instance_extra_specs:{}".format(meta_key): "true"}
        lp_flavor = self.numa.create_flavor("lp_flavor", ram=128)
        lp_flavor.set_keys(extra)

        # Create an any flavor which the scheduler can use to boot either small
        # or large page backed instances from
        extra = {"hw:mem_page_size": "any", meta_key: "true",
                 "aggregate_instance_extra_specs:{}".format(meta_key): "true"}
        any_flavor = self.numa.create_flavor("any_flavor", ram=128)
        any_flavor.set_keys(extra)

        # Make sure we have large pages enabled on our lg_host_ip node
        check_hp = base.get_free_hugepages(lg_host_ip)
        msg = "Currently have {} large pages on {}"
        self.logger.info(msg.format(check_hp, lg_host_ip))
        self.data["original_hp"] = {}
        self.data["original_hp"].update({lg_host_ip: check_hp})
        if check_hp < 64:
            self.logger.info("Attempting to set large pages...")
            self.numa.set_large_page_info(lg_host_ip)
        check_hp = base.get_free_hugepages(lg_host_ip)
        self.assertTrue(check_hp > 0)

        # Boot an instance with our flavor.  Keep booting up instances until
        # we no longer have any free large pages.  Verify that:
        # - when no more free large pages, instance creation fails
        # - that the instance is on the host in the right host aggregate
        img = self.numa.get_image_name("cirros")
        instances = []
        counter = 0
        while True:
            counter += 1
            name = "large_page{}".format(counter)
            self.logger.info("Booting up large page backed instance...")
            inst = self.numa.boot_instance(img, lp_flavor, name=name)
            active = smog.nova.poll_status(inst, "ACTIVE")
            self.assertTrue(active, msg="Instance failed to boot with HP")
            if active:
                # verify the instance is on the right aggregate group
                test_inst = self.numa.discover(guests=[inst])[0]
                on_host = test_inst.host.hostname
                self.assertTrue(on_host == large_page_host)

                # verify the domain xml for <memoryBacking> is right
                self.assertTrue(test_inst.verify_hugepage())

                instances.append(inst)
                free_pages = base.get_free_hugepages(lg_host_ip)
                self.logger.info("Free huge pages left: {}".format(free_pages))
                if free_pages <= 0:
                    break

        # Do one more lp creation.  This should fail because we don't have any
        # more huge free pages
        final = self.numa.boot_instance(img, lp_flavor, name="final")
        active = smog.nova.poll_status(final, "ERROR")
        self.assertTrue(active, msg="Instance booted even though no free HP")

        # Now, try to create some instance with small pages. Since we are using
        # a regular flavor, this can go on any compute host
        self.logger.info("Booting instance with small pages...")
        small_inst = self.numa.boot_instance(name="small_page")
        active = smog.nova.poll_status(small_inst, "ACTIVE")
        self.assertTrue(active)

        # And also with some "any" pages type.  Since we didn't
        # delete any large page instances, this should boot up with small pages
        self.logger.info("Booting instance with 'any' page flavor...")
        any_inst = self.numa.boot_instance(img, any_flavor, name="any_page")
        active = smog.nova.poll_status(any_inst, "ACTIVE")
        self.assertTrue(active)
        any = self.numa.discover(guests=[any_inst])[0]
        self.assertFalse(any.verify_hugepage())


class NUMAVCPUTopologyTest(base.NovaTest):
    """
    Tests the new libvirt features that allow a guest topology to be created
    with a specific cpu topology.

    This tests the feature where a user can request a layout of sockets, cores
    and threads.  By default, libvirt will create 1 socket/1 core, for each
    vcpu requested.  This feature allows creating multiple cores per socket,
    and multiple threads.  It can also specify the maximum number of sockets,
    cores or threads.

    This is not to be confused with vcpu pinning.  Pinning pins a vcpu to a pcpu
    while this feature still allows a vcpu to float across available pcpus.
    This is also different from NUMA topology, where the number of numa nodes,
    and vcpus per NUMA node are requested.

    All 3 features may be combined.
    """

    config_file = "numa_config_vcpu.yml"
    config_dir = __file__

    @classmethod
    def setUpClass(cls):
        super(NUMAVCPUTopologyTest, cls).setUpClass()
        cls.set_base_config()
        cls.setup_nested_support()

    def _setup(self):
        self.numa = NUMA()
        self._base_setup(self.numa)

    def test_two_cores_per_sockets(self):
        """
        Check to make sure that we dont have a default topology by requesting
        2 cores on one socket.

        :return:
        """
        flv = self.numa.create_flavor(vcpus=2, ram=512)
        flv = self.numa.create_vcpu_topo_flavor(flv=flv, sockets="1:",
                                                cores="2:")
        inst = self.numa.boot_instance(flv=flv, name="vcpu-test")
        guest = self.numa.discover()[0]

        # TODO: verify that the xml has the right <cpu>


if __name__ == "__main__":
    #unittest.main()
    if 0:
        with open("/home/stoner/dummy.xml", "r") as dummy:
            text = dummy.read()

        items = {}
        xml = et.fromstring(text)
        cpus = xml.findall("cpu")[0]
        get_xml_children(cpus, items)

        print(items)
