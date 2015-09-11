__author__ = 'stoner'

import xml.etree.ElementTree as ET
import unittest
import untangle

from smog.tests.numa import NUMA
from smog.core.logger import glob_logger
from smog.core.exceptions import ArgumentError
from smog.utils.nested_virt.nested import Compute, _setup_nested_support
from smog.utils.rc_helper import read_rc_file
import smog.virt
import smog.nova
import argparse
import os


def compute_factory(computes):
    c = lambda ip, dom, bm: Compute(bm, dom, ip, "root", "vm", "none")
    computes_ = [c(ip, dom, bm) for ip, dom, bm in computes]
    return computes_


def ensure_nested_support(computes):
    glob_logger.info("Ensuring that L1 hypervisors are set match host model...")
    _computes = compute_factory(computes)
    _setup_nested_support(_computes)   # Will make sure that our L1 compute nodes have host-model match


def make_parser():
    parser = argparse.ArgumentParser(description="Simple NUMA topology creation")
    parser.add_argument("--rc-file-host", help="IP address of host with keystonerc file")
    parser.add_argument("--rc-file-path", help="Path to rc file (default to /root/keystonerc_admin",
                        default="/root/keystonerc_admin")
    parser.add_argument("--username", help="Username. Defaults to environment's OS_USERNAME, or "
                                           "if --rc-file-* is specified will use it",
                        default=os.environ.get("OS_USERNAME"))
    parser.add_argument("--password", help="Password for user.  Defaults to OS_PASSWORD",
                        default=os.environ.get("OS_PASSWORD"))
    parser.add_argument("--auth-url", help="keystone auth url.  Defaults to OS_AUTH_URL",
                        default=os.environ.get("OS_AUTH_URL"))
    parser.add_argument("--tenant-name", help="tenant name.  Defaults to OS_TENANT_NAME",
                        default=os.environ.get("OS_TENANT_NAME"))
    parser.add_argument("--flavor", help="a comma separated string of RAM,VCPUs,disk",
                        default="1024,8,5")
    parser.add_argument("--key", help="a key value pair that will be used for extra_specs"
                                      "EG hw:mem_policy=strict Can be specified multiple time",
                        nargs="+", action="append")
    parser.add_argument("--clean", action="store_true", help="clean after a run", default=False)
    parser.add_argument("--compute", help="A comma separated list of compute IP (L1), the domain"
                                          "name for libvirt,  and its parent baremetal (L0).  "
                                          "Can be specified multiple times.  For example:"
                                          "--compute=10.8.29.58,rhel71-kilo-1,10.8.0.58",
                        action="append")
    return parser


def get_flavor(args):
    ram, vcpus, disk = [int(x) for x in args.flavor.split(",")]
    return ram, vcpus, disk


def get_keys(args):
    specs = {}
    if args.key is not None:
        pairs = [item.split("=") for item in args.key]
        specs = {k: v for k, v in pairs}
    return specs


def get_computes(args):
    # print(args.compute)
    computes = [item.split(",") for item in args.compute]
    return computes


def get_credentials(args):
    if args.rc_file_host and args.rc_file_path:
        creds = read_rc_file(args.rc_file_host, args.rc_file_path)
    else:
        username = args.username
        tenant_name = args.tenant_name
        auth_url = args.auth_url
        password = args.password
        creds = {"username": username, "tenant_name": tenant_name,
                 "auth_url": auth_url, "password": password}
    return creds


class VCPUPinTest(unittest.TestCase):
    def check_args(self, creds):
        missing = [k for k, v in creds.items() if v is None]
        for m in missing:
            glob_logger.error("Must supply --{} or have value in environment".format(m))
            raise ArgumentError("Argument {} not supplied for credentials".format(m))

    def __init__(self, args):
        super(VCPUPinTest, self).__init__()
        self.args = args
        creds = get_credentials(args)
        self.creds = creds
        self.check_args(creds)
        self.numa = NUMA(**creds)  # Create a NUMA object
        self.numa.clean()          # make sure we have a clean system
        self.logger = glob_logger

        # 1. First, make sure our system is enabled for vcpu pinning.  We assume that our environment
        #    is a nested virtual environment with 2 L1 hypervisors running on the L0 baremetal host.
        #    First, get the virsh capabilities from the baremetal.
        self.computes = get_computes(args)
        self.nested = False
        if len(self.computes[0]) > 1:
            self.nested = True
            ensure_nested_support(self.computes)

    def create_aggregates(self):
        # 2. Create aggregate server groups: 1 for pinned=true, the other for pinned=false
        if len(self.computes) > 1:
            meta = "pinned"
            pos_agg, neg_agg, ip = self.numa.create_aggregate_groups(meta)
            extra = {meta: "true"}
        else:
            extra = {}
            pos_agg, neg_agg = None, None
            ip = self.computes[0][0]
        return pos_agg, neg_agg, ip, extra

    def create_pin_flavors(self, name, ram=512, vcpus=2, disk=10, extra=None):
        # 3. Create the pin flavors
        if extra is None:
            extra = {}

        pin_flavor = self.numa.create_flavor(name, ram=ram, vcpus=vcpus, disksize=disk, specs=extra)
        pin_flavor = self.numa.create_vcpu_pin_flavor(flv=pin_flavor)
        glob_logger.info(str(pin_flavor.get_keys()))
        return pin_flavor

    def boot_pinned_instances(self, pin_flavor):
        pin_instance = self.numa.boot_instance(flv=pin_flavor, name="pin_test")
        active = smog.nova.poll_status(pin_instance, "ACTIVE")
        if not active:
            glob_logger.error("FAIL: The pinned instance could not be created")

    def verify(self):
        # 4. Verify the instance is actually pinned by looking at the domain's <cputune> element
        #    Validation here can get tricky if you use this in combination with VCPU Topology.
        #    By default if you dont have VCPU topology configured, then you should have one <vcpupin> node
        #    for each vcpu you requested to have pinned.  But, if you combine this with a vcpu topology,
        #    that may not be the case (for example, you can define a topology with multiple cores per
        #    socket, rather than one core per socket (then there's threads....)
        discovered = self.numa.discover()[0]
        root = ET.fromstring(discovered.dumpxml())
        cputune = next(root.iter("cputune"))
        vcpupins = [child for child in cputune.iter() if child.tag == "vcpupin"]

    def tearDown(self):
        self.numa.clean()

    def test_pin_instance(self):
        pos_agg, neg_agg, ip, extra = self.create_aggregates()

        ram, vcpus, disk = get_flavor(self.args)
        bigger_pin = vcpus
        small_pin = 1
        pin_big_flv = self.create_pin_flavors("pin_big", ram=ram, vcpus=bigger_pin, disk=disk, extra=extra)
        pin_small_flv = self.create_pin_flavors("pin_small", ram=512, vcpus=small_pin, extra=extra)

        # Check how many pcpus we have
        if not self.nested:
            computes = [x[0] for x in self.computes]
        else:
            computes = [x.host for x in compute_factory(self.computes)]

        cpus_left = 0
        for ip in computes:
            conn = smog.virt.get_connection(ip)
            cells = smog.virt.get_cpu_topology(conn)
            info = smog.virt.friendly_topology(cells)
            num_nodes = info["num_numa_nodes"]

            # Get all pcpus
            for i in range(num_nodes):
                cpus_left += int(info[i]["cpus"])

        id_ = 0
        while cpus_left > 0:
            test_name = "pintest_" + str(id_)
            if cpus_left >= bigger_pin:
                self.logger.info("Booting instance with pin_flavor_2...")
                inst = self.numa.boot_instance(flv=pin_big_flv, name=test_name)
                cpus_left -= bigger_pin
                vcpus = bigger_pin
            elif cpus_left == 1:
                self.logger.info("Booting instance with pin_flavor_1...")
                inst = self.numa.boot_instance(flv=pin_small_flv, name=test_name)
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


if __name__ == "__main__":
    # Parse our command line arguments
    parser = make_parser()
    args = parser.parse_args()
    vcpu_t = VCPUPinTest(args)
    vcpu_t.test_pin_instance()



# TODO: Try to live migrate the instance to the other host.  Since it belongs to an aggregate
# group, it should fail (unless the host you migrate to also belongs to the aggregate group)

# TODO: Make a combined flavor with vcpu pinning and a NUMA topology

# TODO: Keep booting instances until all pcpus have run out.  It should work as long as there
# are still pcpus left (pinning ignores CPU overcommit)
