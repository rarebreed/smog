# Make sure you use python3

import xml.etree.ElementTree as ET

from smog.tests.numa import NUMA
from smog.core.logger import glob_logger
from smog.core.exceptions import ArgumentError
import smog.nova
import argparse
import os

parser = argparse.ArgumentParser(description="Simple NUMA topology creation")
parser.add_argument("--username", help="Username. Defaults to environment's OS_USERNAME",
                    default=os.environ.get("OS_USERNAME"))
parser.add_argument("--password", help="Password for user.  Defaults to OS_PASSWORD",
                    default=os.environ.get("OS_PASSWORD"))
parser.add_argument("--auth-url", help="keystone auth url.  Defaults to OS_AUTH_URL",
                    default=os.environ.get("OS_AUTH_URL"))
parser.add_argument("--tenant-name", help="tenant name.  Defaults to OS_TENANT_NAME",
                    default=os.environ.get("OS_TENANT_NAME"))
parser.add_argument("--flavor", help="a comma separated string of RAM,VCPUs,disk",
                    default="1024,2,10")
parser.add_argument("--key", help="a key value pair that will be used for extra_specs"
                                  "EG hw:mem_policy=strict Can be specified multiple time",
                    nargs="+")
parser.add_argument("--clean", action="store_true", help="clean after a run", default=False)

# Parse our command line arguments
args = parser.parse_args()
ram, vcpus, disk = args.flavor.split(",")
if args.key is not None:
    pairs = [item.split("=") for item in args.key]
    specs = {k: v for k, v in pairs}

username = args.username
tenant_name = args.tenant_name
auth_url = args.auth_url
password = args.password
creds = {"username": username, "tenant_name": tenant_name, "auth_url": auth_url, "password": password}
missing = [k for k, v in creds.items() if v is None]
for m in missing:
    glob_logger.error("Must supply --{} or have value in environment".format(m))
    raise ArgumentError("Argument {} not supplied for credentials".format(m))

numa = NUMA(**creds)  # Create a NUMA object
numa.clean()          # make sure we have a clean system

# Create a new flavor that will have the extra specs we need
numa_flavor = numa.create_flavor("numa_flavor", ram=ram, vcpus=vcpus, disksize=disk, specs=None)

# Modify the flavor with the appropriate extra_specs
numa_flavor = numa.create_numa_topo_extra_specs(flv=numa_flavor, numa_nodes=1)

# Now we have a flavor with 2 NUMA nodes defined.  You can display the extra_specs
extra_specs = numa_flavor.get_keys()
glob_logger.info(str(extra_specs))

# Now that we have a flavor with a simple numa topology defined, we can boot an instance.
# Note that the flavor that was defined only specified 1 NUMA nodes and a memory policy of
# preferred.  There are many additional permutations that can be done, such as having asymmetrical
# cpus to to NUMA nodes, asymmetrical memory to NUMA nodes, or combining NUMA topology with
# vcpu pinning or large page memory support
image = numa.get_image_name("cirros")
instance = numa.boot_instance(img=image, flv=numa_flavor, name="numa_instance")

# Poll to see when the instance is done booting up
active = smog.nova.poll_status(instance, "ACTIVE", timeout=600)
if not active:
    print("Failed to boot instance")

# Now that the instance is actually up, check to see that it actually has 2 NUMA nodes defined
discovered = numa.discover(guests=[instance])  # Find the instance we have booted
inst = discovered[0]
dump = inst.dumpxml()

# Verify we have the NUMA topology created
root = ET.fromstring(dump)
cpu = next(root.iter("cpu"))

# Look for the <numa> element inside <cpu>
numa_e = [child for child in cpu.iter() if child.tag == "numa"]
if not numa:
    glob_logger.error("FAIL: No <numa> element found")
else:
    glob_logger.info("Got <numa> element...")
    cell = [child for child in numa_e[0].iter() if child.tag == "cell"]
    if not cell:
        glob_logger.error("FAIL: no <cell> element found")
    else:
        glob_logger.info(cell[0].attrib)

# Now that we are done, clean everything up
if args.clean:
    numa.clean()
