"""
A script to help configure bare metal machines for PCI Passthrough and SRIOV

This is not a complete script, and you may run into problems, especially when
the system to be configured reboots.  It also only handles the case where
the PCI device is an intel NIC using the igb driver, and the system itself
is an Intel based machine.  AMD based processors will need to modify the
kernel parameters slightly to allow IOMMU to work.  Note that BIOS/EFI
support for IOMMU must be enabled.
"""

__author__ = 'stoner'

import argparse
import time
import os
import threading
import sys
import untangle

import hy
import smog.utils.pci.pci_passthrough as pci
from smog.tests.base import scp, get_nova_conf, get_cfg, set_cfg
from smog.tests.numa import NUMA
from smog.core.logger import glob_logger
from smog.core.commander import Command
from smog.core.watcher import make_watcher, ReaderHandler
import smog.utils.pkgmgr.yum as yum
import smog.virt as virt
from smog.utils.rc_helper import read_rc_file

DO_PACKSTACK = False


def setup_sriov_agent(host):
    """
    """
    # install sriov agent
    install_res = yum.yum_install(host, ["openstack-neutron-sriov-nic-agent.noarch"])



parser = argparse.ArgumentParser()
parser.add_argument("-s", "--server", help="IP address of bare metal server")
parser.add_argument("-d", "--driver", help="Driver to modify", default="igb")
parser.add_argument("--vfs", default=2, type=int, help="Number of max_vfs")
parser.add_argument("-c", "--compute", action="append",
                    help="IP address for a compute node"
                         "Can be specified multiple times.  For example:"
                         "--compute=10.8.29.58 --compute=10.8.29.167")

args = parser.parse_args()


# We will dynamically generate a script that we will copy to the remote
# machine and run (which means the remote host must have python installed)
# The script will bring network services down, unload the igb driver,
# reload the igb driver to use max_vfs (to enable Virtual Functions), then
# restart networking.
# Note that all of this was necessary due to some strange bug in RHEL or
# the igb driver not honoring /etc/modprobe.d/igb.conf
change_modprobe = """
from subprocess import Popen, PIPE, STDOUT
import sys

keys = {"stdout": PIPE, "stderr": STDOUT}
driver = sys.argv[1]
vfs = sys.argv[2]

# take down networking
proc = Popen("systemctl stop network".split(), **keys)
proc.communicate()

# remove the igb driver
cmd = "modprobe -r {}".format(driver).split()
proc = Popen(cmd, stdout=PIPE, stderr=STDOUT)
pout, _ = proc.communicate()

# set igb to use max_vfs=2
cmd = "modprobe {} max_vfs={}".format(driver, vfs).split()
proc = Popen(cmd, **keys)
proc.communicate()

# bring up networking
proc = Popen("systemctl start network".split(), **keys)
proc.communicate()

with open("completed.txt", "w") as complete:
    complete.write("Got to the end of the script")
"""

# Now set the nova.conf pci_alias on our compute nodes.  Copy the remote
# nova.conf file locally, edit it, then copy it back to the remote machine
alias_name = "pci_pass_test"

# TODO: use computes instead, and iterate through computes
# let's see if we already have a VFS setup and we have the right kernel params
for host in args.compute:
    is_grub_set = pci.verify_cmdline(host)     # Check if intel_iommu=on

    # I have noticed that when I install RHEL, the default interface script does
    # not have the ON_BOOT=yes.  That becomes a problem when we restart the network
    # because otherwise we will need to manually specify dhclient def_iface
    # TODO: either edit the /etc/sysconfig/network-scripts/ifcfg-{def_iface}
    # to use ON_BOOT=yes, or add in change_modprobe, to call dhclient def_iface
    # at the end of the script
    def_iface = pci.get_default_iface(host)

    # If we dont have intel_iommu=on in /proc/cmdline, we need to set it
    # and reboot the system
    if not is_grub_set:
        glob_logger.info("Setting intel_iommu=on")
        res1 = pci.set_grub_cmdline(host)
        res2 = pci.grub2_mkconfig(host)

        # reboot the host
        virt.rebooter(host)
        virt.pinger(host, timeout=600)

    # This is really only needed for SRIOV or PCI Passthrough with an ethernet
    # device (PCI passthrough and SRIOV only works on VF's not PF's)
    is_vfs_here = pci.get_lspci_info(host)     # Check if we have VF's
    if not is_vfs_here:
        # So there's a bug with using /etc/modprobe.d and setting max_Vfs
        # in a conf file.  So we have to do this ugly hack.
        # scp the change_modprobe.py to remote machine and run it.
        # poll until system is back up
        glob_logger.info("Setting up {} driver to use max_vfs={}".format(args.driver, args.vfs))
        with open("change_modprobe.py", "w") as script:
            script.write(change_modprobe)
        src = "./change_modprobe.py"
        dest = "root@{}:/root".format(host)
        cp_res = scp(src, dest)
        os.unlink("change_modprobe.py")

        # Now, run the script and wait for networking to come back up
        c = "python /root/change_modprobe.py {} {}".format(args.driver, args.vfs)
        cmd = Command(c, host=host)

        # Ughh, we need to throw this in a separate thread because the Command object
        # is using ssh.  Since the script cuts the network, ssh is left hanging
        mp_thr = threading.Thread(target=cmd, kwargs={"throws": False},
                                  daemon=True)
        mp_thr.start()
        virt.pinger(host, timeout=600)
        time.sleep(5)  # give a bit of time for system services to come up

    # Determine what the vendor and product ID are.  intel is always 8086,
    # and that's all we have tested on, but there may be others for other
    # SRIOV or PCI passthrough devices
    lspci_info = pci.get_lspci(host)
    lspci_txt = lspci_info.output
    parsed = pci.lspci_parser(lspci_txt)
    vfs = pci.collect(parsed, "Virtual Function")
    parsed_vfs = list(map(pci.block_parser, vfs))

    # Get the product and vendor ids
    v_id = parsed_vfs[0]['\ufdd0:vendor']
    p_id = parsed_vfs[0]['\ufdd0:product']

    # At this point, we can install packstack.  The reason we should do this
    # _after_ installing packstack, is that if we install packstack first,
    # neutron might get confused by the new VFS (and new ethernet ifaces)
    if DO_PACKSTACK:
        res = Command("which packstack", host=host)(throws=False)
        if res != 0:
            glob_logger.info("You must yum install openstack-packstack first")
            sys.exit()
        watcher = make_watcher("packstack --allinone", host, ReaderHandler, log=sys.stdout)

        # Periodically check to see if we're done.  This is one of the nicer features
        # of smog if I do say so myself.  We can watch the output of a long running
        # process.  Sometimes you need this, even for automation.  What if you have a
        # 72hr test.  Do you really want to wait 3 days to find out it failed in the
        # first 5 minutes?  And yes, 72 and even week long stress tests are not
        # uncommon.  When just running at the python shell, it's easier to just do this
        # res = Command("packstack --allinone", host=host)(throws=False, block=False)
        # res.output
        while watcher.poll() is None:
            time.sleep(1)
        watcher.close()  # close all our threads (TODO: close automatically)

    cmpt = host
    alias_res = pci.set_pci_alias(cmpt, alias_name, v_id, p_id)
    white_res = pci.set_pci_whitelist(cmpt, v_id, p_id, "./nova.conf")
    filter_res = pci.set_pci_filter(cmpt, "./nova.conf")
    src = "./nova.conf"
    dest = "root@{}:/etc/nova/nova.conf".format(cmpt)
    res = scp(src, dest)

    # TODO: Add the NUMATopologyFilter to the default_scheduler_filter list
    nova_conf = get_nova_conf(host)
    lines = get_cfg("scheduler_default_filters", nova_conf)
    lines_ = list(filter(lambda l: l.comment is None, lines))
    if not lines_:
        glob_logger.error("Unable to get")

    # restart nova
    pci.openstack_service(cmpt, "restart", "nova")


# Setup example
creds = read_rc_file(args.server, "/root/keystonerc_admin")

# Now, we create a PCI flavor and attempt to boot
numa = NUMA(**creds)
flv = numa.create_flavor("pci_small", ram=512, vcpus=1)
pci_pass_flv = numa.create_pci_flavor(alias_name, flv=flv)
glob_logger.info(str(pci_pass_flv.get_keys()))

guest = numa.boot_instance(flv=pci_pass_flv, name="pci-testing")
instance = numa.discover(guests=[guest])[0]

# TODO verify the instance is actually using
xmldump = instance.dumpxml()
dump = untangle.parse(xmldump)

