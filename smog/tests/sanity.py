"""
Holds the unit tests for the basic sanity tests

TODO:  The unit tests should probably be metaclasses.  We need some way of
       specifying any requirements for the test, such as for example, a
       multinode install, or shared storage configuration
"""
__author__ = 'stoner'

import unittest
import xmlrunner
import os
import time
import multiprocessing

import libvirt
import novaclient.exceptions
from novaclient.exceptions import NotFound
import toolz

from smog.tests import base
from smog.core.logger import glob_logger
from smog.core.downloader import Downloader
from smog.core.watcher import Handler
from smog.core.exceptions import ArgumentError
from smog.glance import create_image
from smog.core.commander import Command
import smog.virt
import smog.nova

all_states = ["pause", "unpause", "suspend", "resume", "shelve",
              "unshelve", "shelve-offload", "reboot"]


class NovaSanity(base.BaseStack):
    def __init__(self, logger=glob_logger, **kwargs):
        """
        This class will only contain immutable data.

        See the BaseStack init for **kwargs keywords
        """
        super(NovaSanity, self).__init__(logger=logger, **kwargs)

    # FIXME: This method shouldn't be confined to this class
    @staticmethod
    def get_cloud_image(location, name):
        # Download a cirros image
        if not os.path.exists(location):
            if not Downloader.download_url(location, "/tmp", binary=True):
                raise Exception("Could not download cirros image")
            else:
                location = "/tmp/" + name
        return location


class ConfigDriveHandler(Handler):
    """
    This is an example class for using a Handler derived type that can be
    used by a Watchdog
    """
    def __init__(self, rdr, instance_id):
        super(ConfigDriveHandler, self).__init__(rdr)
        self.line = None
        self.id = instance_id
        self.res_q = multiprocessing.Queue()

    def __call__(self, line):
        instance = "[instance: {}] Creating config drive".format(self.id)
        if instance in line:
            self.found += 1
            if self.found >= self.counts:
                self.res_q.put(("Success", line))
                glob_logger.info("Found a match: " + line)
                self.rdr.terminate()
                return False
        return True

    @property
    def result(self):
        if self._result is None:
            glob_logger.info("Getting result from res_q")
            if self.res_q.empty():
                self._result = ("Failed", "")
            else:
                self._result = self.res_q.get()
        return self._result

    @result.setter
    def result(self, val):
        if self._result is None:
            self._result = val
        else:
            raise ArgumentError("Can't assign result more than once")


class ConfigDriveTest(base.NovaTest):
    """
    Tests config drive functionality that is embedded in the image itself
    """

    config_dir = __file__
    config_file = "drive_config.yml"

    def _setup(self):
        if not hasattr(self, "sanity"):
            self.sanity = NovaSanity()
        self._base_setup(self.sanity)

        # Create a ServerGroupAffinity, so that we can ensure a hosts is created
        # on a particular hosts ("compute1")
        group_create = smog.nova.server_group_create
        self.group = group_create(self.sanity.nova, "config-group",
                                  policies="affinity")
        self.group_id = {"group": self.group.id}
        self.data["group"] = self.group

    def tearDown(self):
        if "cirros" in self.data and os.path.exists(self.data["cirros"]):
            os.unlink(self.data["cirros"])
        if "image" in self.data and self.data["image"]:
            print("Deleting ", self.data["image"])
            self.data["image"].delete()
        if "instances" in self.data and self.data["instances"]:
            for instance in self.data["instances"]:
                instance.stop()
                instance.delete()

        self.data = {}

    # FIXME: might want to make this a context manager or decorator, so that
    # we can close the rdr and mntr processes


    @base.declare
    def test_mandatory_no_config(self):
        """
        Tests image property with mandatory config drive, and no boot config
        drive option is set

        - Creates a glance image with img_config_drive set to "mandatory"
        - boots an image without specifying a config drive
        - verifies that the config drive is automatically created
        """
        # Get an image that we can inject the property into
        location = self.config["cirros"]["location"]
        name = self.config["cirros"]["name"]
        disk_format = self.config["cirros"]["disk_format"]
        cirros_loc = self.sanity.get_cloud_image(location, name)
        self.data.update({"cirros": cirros_loc})

        # create the glance image with the image property set
        self.logger.info("Creating config drive image...")
        config_drive_prop = {"img_config_drive": "mandatory"}
        img = create_image(self.sanity.glance, cirros_loc,
                           disk_format=disk_format,
                           img_name="config_drive_image",
                           properties=config_drive_prop)
        time.sleep(5)

        # Make sure the property was set
        props = img.properties
        self.assertTrue("img_config_drive" in props)
        self.assertTrue(props.get("img_config_drive") == "mandatory")
        self.data.update({"image": img})

        # Now, boot up the instance with this image and the small flavor
        self.logger.info("Booting up instance...")
        flave = self.sanity.get_flavor("m1.small")
        self.assertTrue(flave and flave.name == "m1.small")
        self.logger.info("Image status: {}".format(img))
        instance = self.sanity.boot_instance(img, flave,
                                             scheduler_hints=self.group_id)

        # FIXME: This is a very fragile way of determining if the config
        # drive got created.  Will this work on kilo if the logs change?
        # Create a monitor that will look for when the config drive is created.
        # We need to know where our initial boot object is first
        self.logger.info("Creating log monitor")
        inst = self.sanity.discover()[0]
        host_ip = inst.host.host
        cmd = "tail -f /var/log/nova/nova-compute.log"
        mon_name = "config_drive"
        iid = instance.id
        watcher = self.sanity.monitor(cmd, mon_name, host_ip,
                                      ConfigDriveHandler, iid)
        self.data["instances"] = [instance]

        # Poll for the instance
        self.logger.info("Waiting for instance to become ACTIVE")
        achieved = smog.nova.poll_status(instance, "ACTIVE")

        self.assertTrue(achieved)
        status = watcher.handler.result
        msg = "Status was {}".format(status)
        self.logger.info(msg)
        self.assertTrue(status[0] == "Success", "Monitor should find success")

    def test_vfat_migration(self):
        """
        Tests that an instance using a config drive with the vfat format can
        be successfully migrated using block migration

        -
        """


class EvacuateTest(base.NovaTest):
    """
    Tests the evacuation of a guest instance to another compute node hosts.

    These tests require that one of the compute nodes goes down.  Because of
    this, it is much simpler to perform this test on VM's than on bare metal.
    Running this test on masters
    """

    config_dir = __file__
    config_file = "evacuate_config.yml"

    def _setup(self):
        """
        Use this instead of self.setUp() because we don't want to run this
        before the test method itself
        :return:
        """
        if not hasattr(self, "sanity"):
            self.sanity = NovaSanity()
        self._base_setup(self.sanity)

        # We cant tell nova which hosts to build on.  So we create a tiny guest
        # and add it to an affinity group.  Then we can determine which hosts
        # it is on, get its numa characteristics and start adding other guests
        # to that hosts
        # FIXME: remove the hard-coded names
        glob_logger.info("Booting up initial instance")
        test_flv = self.sanity.get_flavor("m1.tiny")
        test_img = self.sanity.get_image_name("cirros")
        test_inst = self.sanity.boot_instances([test_img], [test_flv])
        self.data.update({"test_instances": test_inst})

        # Figure out what the master is
        instances = self.sanity.discover()
        test_vm = instances[0]
        hosts = self.config["hosts"]
        computes = hosts["computes"]
        host_for_test = test_vm.host.host
        for compute in computes:
            if compute["host"] == host_for_test:
                self.data.update({"master": compute["parent"]})
                self.data.update({"compute_name": compute["name"]})
                self.data.update({"compute_host": compute["host"]})
                break

    def live_migrate(self, info):
        """
        Performs a live migration if needed (for example, when the instance
        is on the same node as the one and only controllers)

        :param instance: An smog.base.Instance object
        :param controllers: (str) of the controllers ip address
        :param orig_host: (str) of the original hostname
        :param hosts:
        """
        instance = info.instance
        controller = info.controller
        orig_host = info.orig_hostname

        # if controllers is the same as our compute name, we need to migrate it
        # to another hosts
        glob_logger.info("Need to migrate instance to another compute node")
        msg = "instance {} is on controllers hosts: {}"
        glob_logger.info(msg.format(instance.instance.id, controller))

        filt = lambda x: x.host_ip != controller
        hypers = smog.nova.list_hypervisors(self.sanity.nova, fn=filt)
        if not hypers:
            raise Exception("No other compute nodes found")
        info.hypervisor = hypers[0]
        final = info.hypervisor.hypervisor_hostname

        # migrate to final
        msg = "Migrating instance({}) on hosts {} to hosts {}"
        glob_logger.info(msg.format(instance.instance.id, orig_host, final))
        vm = instance.instance
        vm.live_migrate(host=final)  # FIXME: what about block migration
        start_time = time.time()
        end_time = start_time + 30
        while True:
            vm.get()
            host_attr = getattr(vm, "OS-EXT-SRV-ATTR:host")
            if host_attr and host_attr != orig_host:
                break
            if time.time() > end_time:
                raise Exception("live migration failed")
            time.sleep(1)

        # FIXME: Ugghhh all this state management.  I feel dirty
        self.update_info(info, self.sanity)
        return info

    def _base(self, host=None, instance_name=None):
        """
        Creates an instance on a multinode deployment, and determines which hosts
        the instance is on. If the guest is running on a node that is also a
        controllers, it will live migrate the instance to another compute node.
        It will then power off that hosts where the guest is running, and
        evacuate by specifying a possible hosts.  It verifies that the
        status_code is 200 from the evacuate command.

        :param host: if "valid", chose a known good hosts.  otherwise a hostname
        :return:
        """
        info = self.get_info(self.sanity, self.data)

        if info.controller == info.comp_host:
            self.live_migrate(info)

        master = info.master
        name = info.name
        hv = info.hypervisor
        if instance_name is None:
            instance = info.instance
        else:
            instance = filter(lambda x: x.name == instance_name, info.instances)[0]

        conn = libvirt.open("qemu+ssh://root@{}/system".format(master))
        domain = conn.lookupByName(name)
        glob_logger.info("Shutting down {} for evacuation".format(name))
        smog.virt.shutdown(domain)

        # Make sure the hypervisor is down
        # FIXME: I believe there's a bug here.  It doesn't seem like the state
        # or status of the hypervisor ever changes, even if it goes down
        hv.get()  # refresh the state
        # Evacuate without specifying the hosts
        guest = instance.instance
        time.sleep(60)

        # FIXME: how to tell if using shared storage?
        filt = lambda x: x.host_ip == info.controller
        hvs = smog.nova.list_hypervisors(self.sanity.nova, fn=filt)
        if not hvs:
            raise Exception("Could not find a valid hosts")
        hostname = hvs[0].hypervisor_hostname
        if host == "valid":
            host = hostname

        glob_logger.info("Evacuating hosts to {}".format(hostname))
        result = guest.evacuate(host=host)
        glob_logger.info("status_code = {}".format(result[0].status_code))
        self.assertTrue(result[0].status_code == 200)

        # make sure it's on the right compute hosts
        discovered = self.sanity.discover()[0]
        dh = discovered.host.hostname
        msg = "discovered hostname {}, hostname {}".format(dh, hostname)
        glob_logger.info(msg)
        self.assertTrue(discovered.host.hostname == hostname)

        # power back on the compute hosts node
        smog.virt.power_on(domain)
        time.sleep(30)  # FIXME: how do we know the system is fully up?
        cmd = Command("setenforce 0", host=info.comp_host)
        res = cmd(remote=True)
        self.assertTrue(res == 0)

    @base.declare
    def test_evacuate_passive(self):
        """
        This will evacuate an instance to a hosts and let the scheduler figure
        out what hosts to schedule it on.

        - Creates an instance on a multinode deployment
        - Determine which hosts node the instance is on
          - if the guest is running on a node that is also a controllers, it
            will live migrate the instance to another compute node
        - Power off the hosts node where the guest is running
        - Evacuate without specifying another hosts
        - Verify that the status_code == 200
        """
        self._base()

    @base.declare
    def test_evacuate_active(self):
        """
        This test will evacuate an instance to a specified hosts

        - Creates an instance on a multinode deployment
        - Determine which hosts node the instance is on
        - Power off that hosts node
        - Determine remaining hosts hypervisors and pick one
        - Evacuate the instance to one of the remaining hosts
        - Verify that the status_code from evacuate == 200
        """
        self._base(host="valid")

    @base.declare
    def test_evacuate_bad_host(self):
        """
        This test will specify an invalid hosts

        - Creates an instance on a multinode deployment
        - Determine which hosts the instance is on
        - Power off that hosts
        - Evacuate the instance to a non-existent hosts
        - Verify that we get exception
        """
        self.assertRaises(novaclient.exceptions.NotFound, self._base,
                          host="foo.bar.baz.com")

    @base.declare
    def test_evacuate_bad_affinity(self):
        """
        This will evacuate an instance which had anti-affinity set

        - Creates an instance on a multinode deployment
        - Determine which hosts the instance is on
        - Power off that hosts
        - Determine remaining hosts hypervisors and pick one
        - Evacuate the instance to one of the remaining hosts
        """
        # Delete our existing instance created from _setup
        self.sanity.delete_instances()

        # Create a ServerGroupAntiAffinity.
        group_create = smog.nova.server_group_create
        self.group = group_create(self.sanity.nova, "anti-group",
                                  policies="anti-affinity")
        self.group_id = {"group": self.group.id}
        self.data["group"] = self.group

        # Create a ServerGroupAffinity, so that we can ensure a hosts is created
        # on a particular hosts ("compute1")
        group_create = smog.nova.server_group_create
        self.agroup = group_create(self.sanity.nova, "numa-group",
                                   policies="affinity")
        self.agroup_id = {"agroup": self.group.id}
        self.data["agroup"] = self.group

        # Boot one instance into the affinity group
        a_instance = self.sanity.boot_instance(name="aff-test",
                                               scheduler_hints=self.agroup_id)

        # Boot another instance into the anti-affinity group
        aa_instance = self.sanity.boot_instance(name="aa-test",
                                                scheduler_hints=self.group_id)

        # Make sure that both instances belong to the same host
        # FIXME: assumes 2 compute nodes only
        discovered = self.sanity.discover()
        fn = lambda x: x.host
        hosts = map(fn, discovered)
        initial = hosts[0].hostname
        is_same = all(map(lambda x: x.hostname == initial, hosts))
        self.assertFalse(is_same)

        # Now, try to evacuate the anti-affinity instance
        self._base(instance_name="aa-test")

    @base.declare
    def test_evacuate_bad_numa(self):
        """
        Test evacuating to a hosts which does not have the NUMA topology needed
        by the guest, and the flavor specifies a strict NUMA policy
        :return:
        """
        pass


class SanityTest(base.NovaTest):
    """
    Does the basic sanity test plan (see TCMS)
    """

    config_dir = __file__
    config_file = "sanity_config.yml"

    def _setup(self):
        if not hasattr(self, "sanity"):
            self.sanity = NovaSanity()
        self._base_setup(self.sanity)

    def get_status(self, inst):
        inst.get()   # to update state
        return inst.status

    @base.declare
    def test_bringup_instance(self):
        """
        Very simple test to verify that we can create an instance

        :return:
        """
        self.logger.info("Creating instance...")
        instance = self.create_instance(self.sanity)
        active = smog.nova.poll_status(instance, "ACTIVE", timeout=600)
        self.assertTrue(active)

    @base.declare
    def test_qcow_too_big(self):
        """
        Verify that when booting an instance from a flavor with a disk size smaller than the glance image, that the
        boot will fail
        :return:
        """
        # check if we already have this glance image
        download = True
        flt = lambda x: x.name == "centos6"
        imgs = filter(flt, smog.glance.glance_image_list(self.sanity.glance))
        if len(imgs) > 0:
            download = False

        img_name = "CentOS-6-x86_64-GenericCloud.qcow2"
        url = "http://cloud.centos.org/centos/6/images/CentOS-6-x86_64-GenericCloud.qcow2"
        host = self.config["hosts"]["controllers"]
        if download:
            self.logger.info("Creating instance with too large glance image")
            self.logger.info("Downloading {}".format(url))
            import smog.core.downloader
            dl = smog.core.downloader.Downloader()
            dl.download_url(url, output_dir="/tmp")
            img_res = smog.glance.create_image(self.sanity.glance, os.path.join("/tmp", img_name), "centos6")

        # Verify we created the glance image
        imgs = list(filter(flt, smog.glance.glance_image_list(self.sanity.glance)))
        self.assertTrue(len(imgs) == 1)
        onegb = 1024 * 1024 * 1024
        size = imgs[0].size
        self.assertTrue(size >= onegb)

        # Use the tiny flavor
        flv = self.sanity.get_flavor("m1.tiny")
        inst = self.sanity.boot_instance(imgs[0], flv=flv, name="qcowtest")
        achieved = smog.nova.poll_status(inst, "ERROR")
        self.assertTrue(achieved)

    @base.declare
    def test_server_actions(self):
        """
        Tests pausing, unpausing, shutting down, and bringing back on a server
        :return:
        """
        self.logger.info("Creating instance...")
        instance = self.create_instance(self.sanity)
        self.logger.info("Pausing instance...")
        instance.pause()
        status = self.get_status(instance)

        # Ughhh, poll to get actual status.  Assume if we dont get the right
        # state in 5 seconds, it's a real failure
        def poller(status, state, timeout=5):
            start_time = time.time()
            end_time = start_time + timeout
            while status != state and end_time > time.time():
                time.sleep(1)
                status = self.get_status(instance)
            return status

        final_status = poller(status, "PAUSED")
        self.assertTrue(final_status == "PAUSED", "status = {}".format(status))

        self.logger.info("Unpausing instance...")
        instance.unpause()
        status = self.get_status(instance)
        active_status = poller(status, "ACTIVE")
        self.assertTrue(active_status == "ACTIVE", active_status)

        self.logger.info("Suspending instance...")
        instance.suspend()
        status = self.get_status(instance)
        suspend_status = poller(status, "SUSPENDED")
        self.assertTrue(suspend_status == "SUSPENDED", suspend_status)

        # Try to pause while suspended
        self.assertRaises(novaclient.exceptions.Conflict, instance.pause)

    def dnt_config_drive(self):
        # create a temp file
        with open("dummy.txt", "w") as dummy:
            opts = {"config_drive": True}

    def dnt_serial_proxy(self):
        """Tests the serial proxy
        """
        pass


class LiveMigrationTest(base.NovaTest):
    """
    All the various live migration tests go here
    """

    config_dir = __file__
    config_file = "live_migration_config.yml"

    @classmethod
    def setUpClass(cls):
        super(LiveMigrationTest, cls).setUpClass()
        cls.set_base_config()

    def _setup(self):
        """
        clean up
        :return:
        """
        if not hasattr(self, "sanity"):
            self.sanity = NovaSanity()
        self._base_setup(self.sanity)

    @base.declare
    def test_live_migration(self):
        """
        Verifies live migration environment and performs a simple live
        migration test (non block migration)

        :return:
        """
        # Make sure we have at least 2 compute nodes available
        hvs = smog.nova.list_hypervisors(self.sanity.nova)
        if len(hvs) < 2:
            self.fail("Must have at least 2 compute nodes")

        # Create an instance and discover which host it is on
        inst = self.create_instance(self.sanity)
        disc_inst = self.sanity.discover()
        self.logger.info("Test instance is currently on host {}")

        if len(disc_inst) != 1:
            self.fail("Should only have one instance running now")

        guest = disc_inst[0]
        current_host = guest.host.hostname
        hostname = ""

        for hypv in hvs:
            hostname = hypv.hypervisor_hostname
            if current_host != hostname:
                inst.live_migrate(host=hostname)
                break

        # FIXME: we should monitor the log, and know when to check
        time.sleep(20)
        discovered = self.sanity.discover()
        if len(discovered) != 1:
            self.fail("Should only have one instance running")
        guest = discovered[0]
        self.assertTrue(guest.host.hostname == hostname)

    def test_live_migration_auto(self):
        """
        Perform a live migration without specifying a hosts explicitly (let the
        scheduler decide which hosts to pick)
        - Without NUMA extra_specs
        - With NUMA extra_specs
        :return:
        """
        pass

    def test_live_migration_no_available(self):
        """
        Attempt to perform a live migration with no available hosts.
        - No other compute node available
        - Other compute nodes, but full
        - Host given does not exist

        :return:
        """
        pass

    def test_live_migration_active(self):
        """
        Tests live migration while the instance is busy performing heavy
        computation

        :return:
        """
        pass

    def test_live_migration_stateful(self):
        """
        Tests live migration while the instance is in a state other than ACTIVE

        :return:
        """
        pass

    def test_live_migration_bad_host_numa(self):
        """
        Tests live migration where the target hosts does not have a numa topo
        compatible with the guest instance

        :return:
        """
        pass

    def test_live_migration_with_pinning(self):
        """
        Pin a guest's vcpu to a pcpu, and perform a live migration

        :return:
        """
        pass

    def test_live_migration_bad_host_affinity(self):
        """
        Tests live migration where the hosts specified does
        :return:
        """
        pass

    @base.declare
    def test_live_migrate_anti_affinity(self):
        """
        Make sure that if we have an anti-affinity group set, and we try
        to live migrate to a host with the anti-affinity group, it will
        fail

        - Creates an
        :return:
        """
        data = self.setup_affinities(self.sanity)

        # Make sure that the affinity and anti-aff instances are booted up
        aff_inst = data["aff_instance"]
        anti_inst = data["anti_instance"]
        smog.nova.poll_status(aff_inst, "ACTIVE")
        smog.nova.poll_status(anti_inst, "ACTIVE")

        # Now, perform a live migration for the anti_inst.  This should fail
        # Get what host the instance is currently on, and compare before/after
        discovered = self.sanity.discover()
        fltrfn = lambda x: x.instance.name == "aa-test"

        # In functional-speak, find the instance object in out discovered
        # discovered Instance objects whose name is 'aff-test'.  There should
        # only be one of these, so take the first one.  Use toolz.first rather
        # than use index ([0]).  In the general case this is better (for
        # example, what if we use a generator or iterator instead of list or
        # tuple.  Remember, functional programming rulez!
        before_inst = toolz.first(filter(fltrfn, [inst for inst in discovered]))
        before_host = before_inst.host
        anti_inst.live_migrate()
        discovered = self.sanity.discover()
        after_inst = toolz.first(filter(fltrfn, [inst for inst in discovered]))
        after_host = after_inst.host
        self.assertTrue(before_host.hostname == after_host.hostname)

    def test_live_migration_overcommitted(self):
        """
        Test where the hosts to migrate to will be overcommitted

        :return:
        """
        pass

    def test_live_migration_failed_host(self):
        """
        While a live migration is being performed, kill the compute hosts
        that the instance is set to go to

        This test requires that the hosts be explicitly specified.
        :return:
        """
        pass


class BlockMigrationTest(base.NovaTest):
    pass


if __name__ == "__main__":
    unittest.main(
        testRunner=xmlrunner.XMLTestRunner(output='test-reports'),
        # these make sure that some options that are not applicable
        # remain hidden from the help menu.
        failfast=False, buffer=False, catchbreak=False)
