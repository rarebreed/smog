"""
This module will cover an upgrade scenario from Icehouse to Juno.  In this
example, we will use 2 VM's, each with RHEL 7, but they are both currently
running RHOS 5.0 (icehouse).

First, it is good to take a look at the official documentation for upgrading
which can be found here:

    http://docbuilder.usersys.redhat.com/22894/

Once you have read through that document, take a look at this one, which is
specific to Nova upgrade scenarios:

    http://people.redhat.com/~lkellogg/rhos6-upgrade-docs/overview.html

"""


__author__ = 'stoner'

from abc import ABCMeta, abstractmethod
import shutil
import os
import sys
import re

from smog.core.commander import Command, freader
from smog.core.logger import glob_logger
from smog.tests.base import scp, get_cfg,  openstack_config, BaseStack
from smog.utils.rc_helper import read_rc_file

rhos6 = "rhos-release 6"

stop = "openstack-service stop {}"
yumup = "yum upgrade -y openstack-{}"
db_sync = "openstack-db --service {} --update"
restart = "openstack-service start {}"

services = ["keystone", "swift", "cinder", "glance", "neutron", "horizon"]
commands = [stop, yumup, db_sync, restart]


def configure_rhos_repos(ip, rhos_rel_path, version="6"):
    """
    Unregisters subscription-manager, installs rhos-release rpm, and runs
    rhos-release version

    :param ip: (str) IP address of the host to issue command to
    :param version: (str) the version to upgrade to (ie "5" for icehouse)
    :return:
    """
    rhos_release = rhos_rel_ath
    unregister_sm = "subscription-manager unregister"
    ins_rr = "rpm -ivh  " + rhos_release
    cmd = Command(ins_rr, host=ip)  # install rhos-release
    res = cmd()

    # Unregister subscription-manager
    cmd = Command(unregister_sm, host=ip)
    res = cmd(throws=False)

    # install rhos-release 6
    cmd = Command("rhos-release {}".format(version), host=ip)
    res = cmd()


class Upgrade(object):
    """
    This is an abstract class which all the other openstack service Upgrade
    classes can inherit from.  It will provide the basic feature to upgrade
    the rpm packages, stop and start the service, and synch with the database
    (if needed).

    The upgrade() function is an abstractmethod and must therefore be overridden
    in the derived class.  This function should do all the steps necessary to
    do the actual upgrading, including any other steps.  For example, editing
    any configuration files.
    """

    __metaclass__ = ABCMeta

    def __init__(self, name, hosts, path_to_rhos_release):
        """

        :param name: (str) name of the service
        :param hosts: (list) list of all hosts that provide this service
        :return:
        """
        self.name = name
        self.stop = stop.format(name)
        self.update = r"yum -d1 -y upgrade \*{}\* python-migrate".format(name)
        self.sync_db = db_sync.format(name)
        self.start = restart.format(name)
        self.hosts = hosts
        self.rhos_release = path_to_rhos_release
        self.ins_rr = "yum install -y " + self.rhos_release
        self.unregister_sm = "subscription-manager unregister"

    @abstractmethod
    def upgrade(self):
        pass

    def _upgrade(self, commands):
        # Make sure to stop the service first
        for host in self.hosts:
            cmds = [Command(x, host=host) for x in commands]
            for cmd in cmds:
                glob_logger.info("Calling: {}".format(cmd.cmd))
                try:
                    res = cmd()
                    if res != 0:
                        glob_logger.error("Unable to run {}".format(cmd.cmd))
                except:
                    cmdstr = cmd.cmd
                    glob_logger.error("Could not execute {}".format(cmdstr))

        state = self.get_service_state()
        if "active" not in state:
            raise Exception("Service {} did not come up".format(self.name))

    def get_service_state(self):
        """
        Gets the state of the service

        FIXME: Some services will return states for several sub-services.  Since
        this regex is greedy, it will find the first match which may not cover
        all the other services
        :return:
        """
        for host in self.hosts:
            cmd = Command("openstack-service status {}".format(self.name),
                          host=host)
            patt = re.compile(r"\s+is (\w+)")
            res = cmd()
            m = patt.search(res.output)
            state = "unknown"
            if m:
                state = m.groups()[0]
            return state


class KeystoneUpgrade(Upgrade):
    def __init__(self, hosts):
        super(KeystoneUpgrade, self).__init__("keystone", hosts)
        self.token_flush = "keystone-manage token_flush"

    def upgrade(self):
        commands = [self.stop, self.update, self.token_flush, self.sync_db,
                    self.start]

        self._upgrade(commands)


class SwiftUpgrade(Upgrade):
    def __init__(self, hosts):
        super(SwiftUpgrade, self).__init__("swift", hosts)
        self.update = r"yum -d1 -y upgrade \*swift\*"

    def upgrade(self):
        commands = [self.stop, self.update, self.start]
        self._upgrade(commands)


class CinderUpgrade(Upgrade):
    def __init__(self, hosts):
        super(CinderUpgrade, self).__init__("cinder", hosts)

    def upgrade(self):
        commands = [self.stop, self.update, self.sync_db, self.start]
        self._upgrade(commands)


class GlanceUpgrade(Upgrade):
    def __init__(self, hosts):
        super(GlanceUpgrade, self).__init__("glance", hosts)

    def upgrade(self):
        commands = [self.stop, self.update, self.sync_db, self.start]
        self._upgrade(commands)


class CeilometerUpgrad(Upgrade):
    def __init__(self, hosts):
        super(CeilometerUpgrad, self).__init__("ceilometer", hosts)

    def upgrade(self):
        commands = [self.stop, self.update, self.start]
        self._upgrade(commands)


class HeatUpgrade(Upgrade):
    def __init__(self, hosts):
        super(HeatUpgrade, self).__init__("heat", hosts)

    def upgrade(self):
        commands = [self.stop, self.update, self.sync_db, self.start]
        self._upgrade(commands)


class HorizonUpgrade(Upgrade):
    def __init__(self, hosts):
        super(HorizonUpgrade, self).__init__("horizon", hosts)

    def backup_settings(self):
        settings_p = "/etc/openstack-dashboard/"
        settings_f = "local_settings"
        settings_full = os.path.join(settings_p, settings_f)

        for host in self.hosts:
            src = "root@{}:{}".format(host, settings_full)
            scp(src, ".")
            shutil.move(settings_f, settings_f + ".old")
            shutil.copy(settings_f, settings_f + ".rpmnew")

            # Check that we have ALLOWED_HOSTS
            found = get_cfg("ALLOWED_HOSTS", "local_settings.rpmnew")
            found = filter(lambda x: x.comment is None, found)
            if found and found[0].val:
                pass
            else:
                glob_logger.error("Need to correct ALLOWED_HOSTS")
                sys.exit(1)

    def copy_settings(self):
        settings_p = "/etc/openstack-dashboard/"
        src = "local_settings.rpmnew"
        shutil.copy(src, "local_settings")

        for host in self.hosts:
            dest = "root@{}:{}".format(host, settings_p)
            res = scp(src, dest)
            if res != 0:
                glob_logger.error("Could not copy local_settings to remote")

    def upgrade(self):
        commands = [self.update]
        self._upgrade(commands)
        self.backup_settings()
        self.copy_settings()


class NovaUpgrade(Upgrade):
    def __init__(self, hosts, ignores, basestack, controllers):
        super(NovaUpgrade, self).__init__("nova", hosts)
        self.update = r"yum -y upgrade \*nova\* python-migrate"
        self.base = basestack
        self.version = "6"
        self.ignores = ignores
        self.controllers = controllers

        # these are all the compute node hostnames that are not controllers
        # ie, they are only dedicated compute nodes
        self.hyps = [(h.host_ip, h.hypervisor_hostname)
                     for h in self.base.get_hypervisors()
                     if h.host_ip not in self.controllers]

        # These are the nodes that WILL get upgraded to juno
        juno = set(self.hosts) - set(self.ignores)
        self.juno = [(h.host_ip, h.hypervisor_hostname)
                     for h in self.base.get_hypervisors()
                     if h.host_ip in juno]

    def add_ignore(self, hosts):
        """
        Add a list of hosts to ignore for compute updates

        :param hosts:(seq) a list of hostnames of compute nodes to filter out
                     of self.hyps
        :return:
        """
        for host in hosts:
            if host not in self.ignores:
                self.ignores.append(host)

        fn = lambda x: x[0] not in self.ignores
        self.hyps = filter(fn, self.hyps)
        return self.hyps

    def set_upgrade_level(self, version, hosts=None, key="compute"):
        """
        On the juno nodes, edit the /etc/nova/nova.conf and set the
        [upgrade_levels]
        compute=version
        :return:
        """
        if hosts is None:
            hosts = self.juno

        section = "[upgrade_levels]"
        cfg = "/etc/nova/nova.conf"
        for host, _ in self.juno:
            ans = openstack_config(cfg, section, key, opt="get", host=host)
            if version not in ans.output:
                openstack_config(cfg, section, key, opt="set", host=host,
                                 value=version)

    def upgrade(self):
        commands = [self.stop, self.update, self.sync_db, self.start]
        self._upgrade(commands)

        self.upgrade_computes()

    def disable_computes(self):
        """
        Disables all the nodes from self.hyps.  If you do not wish to disable
        a compute node, make sure to call self.add_ignore([nodes]) which will
        remove the hostnames in the sequence given to add_ignore()
        :return:
        """
        for ip, hostname in self.hyps:
            disable = self.base.nova.services.disable_log_reason
            s = disable(hostname, "nova-compute", "upgrade")
            if s.status != "disabled":
                raise Exception("{} nova-compute not disabled".format(hostname))

            cmd = Command("openstack-service stop nova-compute", host=ip)
            res = cmd()

    def reenable_computes(self):
        """
        Reenables the nova service on all compute nodes in self.hyps

        :return: None
        """
        for ip, hostname in self.hyps:
            cmd = Command("openstack-service restart nova", host=ip)
            res = cmd()

            s = self.base.nova.services.enable(hostname, "nova-compute")
            if s.status != "enabled":
                raise Exception("{} nova-compute not enabled".format(hostname))

    def upgrade_computes(self):
        """
        For each compute node hostname in self.hyps, disables the nova service,
        sets up the rhos_release repositories necessary for packages, and
        performs a package update, then re-enables the nova service
        :return:
        """
        version = self.version
        self.disable_computes()
        for ip, _ in self.hyps:
            # setup rhos-release 6
            configure_rhos_repos(ip, version=version)

            # Perform the update
            Command(self.update, host=ip)()
        self.reenable_computes()


class NeutronUpgrade(Upgrade):
    def __init__(self, host, others, base):
        super(NeutronUpgrade, self).__init__("neutron", host)
        self.others = others  # list of all nodes using neutron services

        self.base = base
        self.admin = self.base.keystone.username
        self.pwd = self.base.keystone.password
        self.auth_url = self.base.keystone.auth_url
        self.tenant_id = self.base.keystone.tenant_id

    def upgrade(self):
        commands = [self.stop, self.update, self.sync_db]
        self._upgrade(commands)

        conf = "/etc/neutron/neutron.conf"
        DEFAULT = "DEFAULT"

        def test_and_set(k, v, cfg=conf, section=DEFAULT):
            host = self.hosts
            ans = openstack_config(cfg, section, k, opt="get", host=host)
            if v not in ans.output:
                openstack_config(cfg, section, k, opt="set", host=host, value=v)

        key = "notify_nova_on_port_status_changes"
        val = "true"
        test_and_set(key, val)

        key = "nova_url"
        val = "http://{}:8774/v2".format(self.hosts)
        test_and_set(key, val)

        def set_creds(key, value):
            r = openstack_config(conf, "DEFAULT", key, opt="set", value=value)
            return r

        # This appears to not have changed.  Also, we need the nova credentials
        # not the admin credentials
        if 0:
            for kv in [("nova_admin_username", self.admin),
                       ("nova_admin_password", self.pwd),
                       ("nova_admin_tenant_id", self.tenant_id),
                       ("nova_admin_auth_url", self.auth_url)]:
                set_creds(*kv)


        ans = input("Please check the /etc/neutron/neutron.conf.rpmnew file"
                    " and enter c to continue")
        while str(ans).lower != "c":
            ans = input("Please check the /etc/neutron/neutron.conf.rpmnew "
                        "file and enter c to continue")

        openstack_config(conf, DEFAULT, "agent_down_time", value="75",
                         opt="set", host=self.hosts)

        for neu in self.others:
            openstack_config(conf, "agent", "report_interval", value="30",
                             opt="set", host=neu)

        cmd = Command("killall dnsmasq", host=self.hosts)
        cmd()

        cmd = Command(self.start, host=self.hosts)
        cmd()

if __name__ == "__main__":
    import argparse

    # Get our arguments from the command line.  We should list the controllers(s)
    # in our deployment, and possibly some compute nodes that should not be
    # upgraded that are listed in the --ignores argument.  Also, authentication
    # will by default look for the environment variables OS_USERNAME,
    # OS_TENANT_NAME, OS_PASSWORD and OS_AUTH_URL, but these can also be given
    # on the command line via the --username, --tenant, --password, and
    # --auth-url arguments respectively.  The version to update will default to
    # 6 (juno)
    parser = argparse.ArgumentParser()
    parser.add_argument("--node",
                        help="Comma separated node(s) which are nodes")
    parser.add_argument("--ignores", help="Comma separated node(s) which will"
                                          "not be upgraded")
    parser.add_argument("--username", help="Username for project",
                        default=os.environ.get("OS_USERNAME"))
    parser.add_argument("--tenant-name", help="tenant name for the deployment",
                        default=os.environ.get("OS_TENANT_NAME"))
    parser.add_argument("--password", help="Password for username",
                        default=os.environ.get("OS_PASSWORD"))
    parser.add_argument("--auth-url", help="Keystone auth url",
                        default=os.environ.get("OS_AUTH_URL"))
    parser.add_argument("--version", help="Version to upgrade to",
                        default="6")
    parser.add_argument("--partial", help="Enforces that there must be at least"
                                          "one entry in --ignores",
                        default=False, type=bool)
    opts = parser.parse_args()

    class UpgradeException(Exception):
        pass

    # Argument validations
    if opts.node is None:
        raise UpgradeException("Must supply controllers nodes")
    else:
        # FIXME: Handle multiple controllers
        controller = opts.node.split(",")[0]

    if opts.ignores:
        ignores = opts.ignores.split(",")
    else:
        if opts.partial:
            raise UpgradeException("--partial was true but no --ignores given")
        ignores = []

    # TODO: unregister subscription-manager, install rhos-release, run rhos-release 6
    # TODO: what about subscription-manager for GA'ed releases?
    # TODO: configure_rhos_repos(controllers, version=opts.version)

    creds = read_rc_file(controller, "/root/keystonerc_admin")
    base = BaseStack(**creds)

    # Keystone first
    # ku = KeystoneUpgrade([controller])

    # Then swift
    su = SwiftUpgrade([controller])

    # Then cinder
    cu = CinderUpgrade([controller])

    # Then glance
    gu = GlanceUpgrade([controller])

    # Then heat
    hu = HeatUpgrade([controller])

    # Then horizon
    hz = HorizonUpgrade([controller])

    # Perform the actual Nova and Neutron upgrades
    nova_up = NovaUpgrade([controller], ignores, base, [controller])
    neutron_up = NeutronUpgrade([controller], ignores, base)

    # In our case, we want to ignore updating one of the compute nodes so
    # we can test cross version compatibility.  If you want to upgrade all
    # nodes, comment out this line
    nova_up.add_ignore(ignores)

    for updater in [ su, cu, gu, hu, hz, nova_up, neutron_up]:
        updater.upgrade()
