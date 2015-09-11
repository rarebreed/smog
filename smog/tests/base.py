"""
This is the base class from which all the fog.tests classes should inherit from.
"""
import time

__author__ = 'stoner'

from abc import ABCMeta
import unittest
import os
from collections import namedtuple
from functools import wraps, reduce
import re
import xml.etree.ElementTree as ET
import sys
import random

import libvirt
from novaclient.exceptions import NotFound

import smog.nova
from smog.core.logger import glob_logger, make_timestamped_filename
from smog.keystone import create_keystone
from smog.nova import create_nova_client, list_flavors, list_instances
from smog.glance import create_glance, glance_image_list, glance_images_by_name
from smog.neutron import create_neutron_client
from smog.core.exceptions import ReadOnlyException, BootException, ArgumentError
from smog.nova import boot_instance, poll_status
from smog.core.commander import Command, CommandException
from smog.core.watcher import Watcher, ExceptionHandler
import smog.core.exceptions as sce
import smog.virt
import smog.neutron

TRACE = 5
LOGGER = glob_logger
VM = 1
BARE_METAL = 2
PERMISSIVE = True  # FIXME: remove when BZ 1160343 is fixed

from smog.tests import get_yaml_file


class InvalidInjectorError(Exception):
    pass


def get_smog_dir(this=None):
    if this is None:
        this = __file__
    print(__file__)
    direcs = this.split("/")[1:]
    print(direcs)
    fn = lambda i: (direcs[i], direcs[i+1])
    pairs = map(fn, range(len(direcs) - 1))
    for i, pair in enumerate(pairs):
        print("Checking", pair)
        if pair == ("smog", "smog"):
            break
    else:
        raise Exception("Could not find smog directory")
    smog = os.path.join("/", "/".join(direcs[:i+2]))
    return smog


def injector(deps):
    """
    This decorator will inject some class level fields into the class it
    decorates.  The deps dictionary can contain the following

    :param deps:
    :return:
    """
    VALID_KEYS = ["config_dir", "config_file", "requires"]
    VALID_REQUIRES = ["multiple_compute", "shared_storage"]

    def factory(cls):
        conf_dir = __file__
        conf_file = None
        for k in deps.keys():
            if k not in VALID_KEYS:
                msg = "{} Not a proper key".format(k)
                raise InvalidInjectorError(msg)

        class NewClass(cls):
            config_dir = deps["config_dir"]
            config_file = deps["config_file"]

        return NewClass
    return factory


def declare(fn):
    @wraps(fn)
    def inner(*args, **kwargs):
        print("")
        print(fn.__name__)
        print(fn.__doc__)
        self = args[0]
        self._setup()
        log_name = make_timestamped_filename(fn.__name__)
        # Ughh, ugly hack.  First, look for self.base or self.numa.
        # Look for a BaseStack object
        base_ = [getattr(self, x) for x in ("base", "numa") if hasattr(self, x)]
        if base_:
            base_ = base_[0]
        else:
            for i in [fld for fld in dir(self) if not fld.startswith("__")]:
                obj = getattr(self, i)
                if isinstance(obj, BaseStack):
                    base_ = obj
                    break
        if base_:
            self._setup_monitor(base_, log_name)
        return fn(*args, **kwargs)
    return inner


def get_virt_connection(ip, user, driver="qemu+ssh"):
    drv_format = "{}://{}@{}/system".format(driver, user, ip)
    glob_logger.info("getting libvirt xml from {}".format(drv_format))

    conn = libvirt.open(drv_format)
    return conn


def get_hosts_from_uri(opts):
    """
    Takes a list of strings, and runs a regular expression to find something
    of the form user@hosts:/path/to/file

    :param opts:
    :return:
    """
    import re
    patt = re.compile(r"(\w+)@(.+):(.*)")

    def matcher(opt):
        m = patt.search(opt)
        if m:
            # tuple of form (user, hosts, path)
            return m.groups()

    # remove empty entries
    return filter(lambda x: x is not None, map(matcher, opts))


def scp(src, dest, options=""):
    """
    Wrapper around scp to send/receive files or folders.  This does away
    with the need for scpclient

    PreCondition:  To avoid prompts, the public ssh key must have already
    been copied to the remote hosts you are sending/getting

    :param src: Eg root@10.8.0.59:/etc/nova/nova.conf
    :param dest: Eg /root
    :param options: any options to pass to scp
    :return:
    """
    cmd = Command("scp {} {} {}".format(options, src, dest))
    res = cmd()
    if res != 0:
        raise CommandException("Copying from {} to {}".format(src, dest))

    return res


def get_remote_file(host, src, user="root", dest="."):
    """
    Convenience wrapper around scp() to get a file

    :param host: (str) host ip or hostname
    :param src: (str) path on remote host to file
    :return:
    """
    fname = os.path.basename(src)
    src = "{}@{}:{}".format(user, host, src)
    scp(src, dest)

    if not os.path.exists(os.path.join(dest, fname)):
        raise Exception("Did not copy {} to {}".format(src, dest))

    return os.path.join(dest, os.path.basename(src))


def get_nova_conf(host, user="root", dest="."):
    """
    Convenience wrapper around scp() to get the nova.conf file

    :param host:
    :return:
    """
    src = "/etc/nova/nova.conf".format(user, host)
    nova_conf = get_remote_file(host, src, dest=dest, user=user)

    if not os.path.exists(nova_conf):
        raise Exception("Did not copy the nova.conf file")

    return nova_conf


def get_libvirtd_conf(host, user="root", dest="."):
    """
    Convenience wrapper around scp() to get the libvirtd.conf file

    :param host:
    :return:
    """
    src = "/etc/libvirt/libvirtd.conf".format(user, host)
    libvirt_conf = get_remote_file(host, src, dest=dest, user=user)

    if not os.path.exists(libvirt_conf):
        raise Exception("Did not copy the libvirtd.conf file")
    return libvirt_conf


def make_backup_file(orig_f, backup_f, o_file):
    pristine_name = o_file + ".orig"
    try:
        if not os.path.exists(pristine_name):
            pristine_f = open(pristine_name, "w")
            pristine_f.write(orig_f.read())
            pristine_f.close()
            orig_f.seek(0, 0)

        txt = orig_f.read()
        backup_f.write(txt)
        backup_f.close()
        orig_f.close()
    except IOError:
        raise "Could not create requested file: {0}".format(orig_f)


def openstack_config(cfile, section, key, value="", opt="get", host=None):
    """
    Uses the openstack-config utility to change config files

    :param cfile: (str) path to cfile on hosts
    :param section: (str) section in cfile (eg DEFAULT)
    :param key: (str) the key to loop up
    :param value: (str) if opt="set", the value to set to goes here
    :param opt: (str) one of "get" or "set"
    :return:
    """
    if opt == "get":
        opt = "--get"
    else:
        opt = "--set"
    command = "openstack-config {} {} {} {} {}".format(opt, cfile, section,
                                                       key, value)
    cmd = Command(command, host=host)
    res = cmd(showout=False, throws=False)
    return res


def get_cfg(key, cfile):
    """
    Finds all occurrences of key in a file.  The key must be at the beginning
    of a line, and can possibly start with a comment (#).  It returns a tuple
    of the entire matching line, a possible comment, the key, delimiter, and
    lastly the value for the key

    :param key: (str) key to search for
    :param cfile: the config file to search
    :return: namedtuple of ['line', 'comment', 'key', 'delimiter', 'val']
    """
    s = r"^(#\s*)*\s*({0})(\s*[=:]\s*)(.*)".format(key)
    patt = re.compile(s)
    sect_patt = re.compile(r"^\[(\w+)\]")

    found = []
    fields = ['line', 'comment', 'key', 'delimiter', 'section', 'val']
    ConfigItem = namedtuple('ConfigItem', fields)
    section = None
    with open(cfile, "r") as cfg:
        for line in cfg:
            sect = sect_patt.search(line)
            if sect:
                section = sect.groups()[0]
            m = patt.search(line)
            if m:
                comment, key, delimiter, val = m.groups()
                found.append(ConfigItem(line, comment, key, delimiter, section,
                                        val))
    return found


def set_cfg(token, value, o_file, b_file, not_found="ignore", delim=None,
            section=None):
    """Change the value of the token in a given config file.

    This function was made to replace the ConfigParser class, because the
    parser object does not save any comments.  The disadvantage of this function
    is that multiple adjustments requires writing multiple times

    :param token: (str) key within the config file
    :param value: (str) value for token.  if None, return value of key
    :param o_file: (str) current configuration file which to read data.
    :param b_file: (str) backup configuration file to write out original data
        before changing the original file.
    :param not_found: (str) can be one of 'ignore', 'append', or 'fail'.
        ignore: if no match is found by the end of the file, dont write
        append: will append at the end of the file
        fail: will throw an exception if no match is found
    :param delim: If specified, use delim as the delimiter instead of
        what is found from the regex.
    :param section: The section the token|value should belong to.
    """
    # Write a backup before changing the original.
    msg = "Trying to set {} to {} in file {}".format(token, value, o_file)
    LOGGER.log(TRACE, msg)
    org_file = open(o_file, 'r')
    backup_file = open(b_file, 'w')
    make_backup_file(org_file, backup_file, o_file)

    try:
        # here is where we overwrite the original file after creating a backup.
        new_file = open(o_file, 'w')
        backup_file = open(b_file, 'r')
        new_lines = backup_file.readlines()

        # This is a regex to read a line, and see if we have a match.  If it
        # matches, match.groups() will return 4 capturing groups: a comment
        # key, delimiter, and value
        s = r"(#\s*)*\s*({0})(\s*[=:]\s*)(.*)".format(token)
        patt = re.compile(s)
        sect_patt = re.compile(r"\[(\w+)\]")

        found = []
        matched = False
        current_section = None
        for i, line in enumerate(new_lines):
            sect = sect_patt.search(line)
            if section and sect:
                new_sect = sect.groups()[0]
                if not_found == "append" and not found:
                    d = delim if delim is not None else "="
                    line = "{0}{1}{2}\n{3}\n".format(token, d, value, line)
                    msg = "Appending {} to section {}".format(line,
                                                              current_section)
                    LOGGER.log(TRACE, msg)
                    found.append(value)
                    matched = True
                current_section = new_sect
            if section is not None and section != current_section:
                continue

            m = patt.search(line)
            if m:
                comment, key, delimiter, val = m.groups()
                if delim == "strip":
                    delimiter = delimiter.strip()
                else:
                    delimiter = delim if delim is not None else delimiter
                # If we've already found the token, skip it
                if key in found:
                    msg = "Already found {0} in {1}".format(token, line)
                    LOGGER.log(TRACE, msg)
                    if comment is None:
                        # don't write out the line, since we already wrote it
                        continue
                else:
                    line = "{0}{1}{2}\n".format(token, delimiter, value)
                    msg = "Matched {0}->{1} on line {2}, setting to {3}"
                    msg = msg.format(token, key, i, line)
                    LOGGER.log(TRACE, msg)
                    found.append(key)
                    matched = True
            new_file.write(line)

        if not matched:
            if not_found == "fail":
                msg = "Could not find {0} in file {1}".format(token, o_file)
                raise Exception(msg)
            elif not_found == "append":
                delim = "=" if delim is None else delim
                line = "{0}{1}{2}\n".format(token, delim, value)
                msg = "{0} was not found in {1}. Appending {2}"
                msg = msg.format(token, o_file, line)
                LOGGER.log(TRACE, msg)
                new_file.write(line)

        new_file.close()
        backup_file.close()
    except IOError:
        print("Could complete requested file modification on: "
              "{0} and {1}".format(o_file, b_file))
        exit()

    return get_cfg(token, o_file)


def read_proc_file(host, mfile):
    """
    This function is meant to be called on small in-memory files

    It could in theory be used to get contents of regular files too
    :param host: (str) ip of host to run command
    :param mfile: (str) file path
    :return: result of cat on the file
    """
    res = Command("cat {}".format(mfile), host=host)(showout=False)
    return res


def echo_proc_file(host, mfile, content, append=True):
    """
    Counterpart to read_proc_file, this calls echo to

    :param host: str, IP address of remote host
    :param mfile: str, path on remote host
    :param content: str, content to write to mfile
    :param append: boolean, if true, append to existing file, else
                   creates mfile if it doesn't exist
    :return:
    """
    redirect = ">>" if append else ">"
    cmd = 'echo "{}" {} {}'.format(content, redirect, mfile)
    return Command(cmd, host=host)()


def get_free_hugepages(host):
    """
    Determine how many huge free pages lg_host_ip has
    :param host:
    :return:
    """
    res = read_proc_file(host, "/proc/meminfo")
    patt = re.compile(r"HugePages_Free:\s+(\d+)")

    for line in res.output.split("\n"):
        m = patt.search(line)
        if m:
            free_pages = m.groups()[0]
            break
    else:
        err = "{} has no free HugePages".format(host)
        raise sce.FreePageException(err)
    return int(free_pages.strip())


def set_hugepages(host, num_pages=256, persistent=False):
    """
    Sets up large page support on a bare metal host, so that a nested
    hypervisor can take advantage of it.

    :param host: IP address of the baremetal system
    :param num_pages: The number of huge pages to create
    :return: number of hugepages
    """
    # Check if we already have large page support
    result = read_proc_file(host, "/proc/sys/vm/nr_hugepages")
    curr_pages = int(result.output)
    set_cmd = "sysctl -w vm.nr_hugepages={}".format(num_pages)
    if curr_pages < num_pages:
        if persistent:
            fmt = 'echo "vm.nr_hugepages={}" >> /etc/sysctl.conf'
            command = fmt.format(num_pages)
            Command(command, host=host)()
            res = Command(set_cmd, host=host)()
        else:
            res = Command(set_cmd, host=host)()
        curr_pages = int(res.output.split()[-1])

    return curr_pages


# FIXME: Convert this to either a namedtuple, or subclass from tuple
class Host(object):
    """
    Represents a compute hosts node (where the nova guest instances "live").
    """

    Virt = namedtuple("Virt", ["domain", "connection"])

    def __init__(self, ip, name, user="root", pw=None, driver="qemu+ssh",
                 htype=VM, logger=glob_logger):
        self._host = ip
        self._hostname = name
        self._user = user
        self._pw = pw
        self._driver = driver
        self.logger = logger
        self._type = htype

    # FIXME: my DRY alarm is going off.  See if there's a way to encapsulate
    # all these read-only properties
    @property
    def host(self):
        return self._host

    @host.setter
    def host(self, _):
        raise AttributeError("Cant change value of hosts")

    @property
    def hostname(self):
        return self._hostname

    @hostname.setter
    def hostname(self, _):
        raise AttributeError("Cant change value of hostname")

    @property
    def user(self):
        return self._user

    @user.setter
    def user(self, _):
        raise AttributeError("Cant change value of user")

    @property
    def driver(self):
        return self._driver

    @driver.setter
    def driver(self, _):
        raise AttributeError("Cant change value of driver")

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, _):
        raise AttributeError("Cant change value of type")

    # FIXME:  This should become a Context Manager so that we can clean the
    # resources of the libvirt connection better
    def get_libvirt_conn(self):
        return get_virt_connection(self.host, self.user, driver=self.driver)

    def get_domain(self, lookup):
        """
        Returns the libvirt domain associated with this hosts and instance.

        :return:
        """
        conn = self.get_libvirt_conn()
        try:
            inst = conn.lookupByUUIDString(lookup)
        except libvirt.libvirtError:
            inst = conn.lookupByName(lookup)

        return Host.Virt(inst, conn)

    def power(self, action):
        """
        Can power on, power off, or reboot.  If type is VM, can also pause

        :param action:
        :return:
        """
        action_states = ["on", "off", "reboot"]
        if self.host.type == VM:
            action_states.append("pause")

        if action not in action_states:
            raise ArgumentError("action must be in {}".format(action_states))

    def _start(self, name):
        """
        Starts a domain

        :return:
        """
        virt = self.get_domain(name)
        dom = virt.domain

        start_time = time.time()
        end_time = start_time + 60
        while dom.info()[0] != libvirt.VIR_DOMAIN_RUNNING:
            time.sleep(1)
            if end_time > time.time():
                break

        virt.connection.close()
        return dom.info()[0]

    def _shutdown(self, name):
        virt = self.get_domain(name)
        dom = virt.domain

        dom.shutdown()
        start_time = time.time()
        end_time = start_time + 60
        while dom.info()[0] != libvirt.VIR_DOMAIN_SHUTOFF:
            time.sleep(1)
            if end_time > time.time():
                break

        virt.connection.close()
        return dom.info()[0]


class Instance(object):
    """
    A convenience container that holds a nova Image object, a libvirt Domain
    object, and a Host
    """
    def __init__(self, instance, host, base, logger=glob_logger):
        self.base = base
        self._host = host
        self._instance = instance
        self._domain = None
        self.logger = logger
        self._conn = None
        self._virt_name = getattr(instance, "OS-EXT-SRV-ATTR:instance_name")

        self._hyper = None
        self._hypername = None

    @property
    def host(self):
        return self._host

    @property
    def instance(self):
        return self._instance

    @instance.setter
    def instance(self, _):
        raise AttributeError("Can't change instance")

    # FIXME: this can change if we do a live migration or evacuate, so we need
    # to dynamically look up what the hypervisor is
    @property
    def hyper(self):
        filt = lambda x: x.host_ip == self.host.host
        self._hyper = smog.nova.list_hypervisors(self.base.nova, fn=filt)[0]
        return self._hyper

    @hyper.setter
    def hyper(self, _):
        raise AttributeError("Can't change hyper")

    @property
    def hypername(self):
        if self._hypername is None:
            self._hypername = self.hyper.hypervisor_hostname
        return self._hypername

    @hypername.setter
    def hypername(self, _):
        raise AttributeError("Can't set the hypervisor hostname")

    @property
    def virt_name(self):
        return self._virt_name

    @virt_name.setter
    def virt_name(self, _):
        raise AttributeError("Can't change viurt_name")

    def get_domain(self):
        return self.host.get_domain(self.instance.id)

    def dumpxml(self, flags=0):
        """
        Retrieves the XML dump for the given uuid on hosts.  If hosts is not None,
        requires ssh key to have been copied to remote machine for user

        :param uid: the uuid string of the instance to get xml dump from
        :param hosts: the ip address or hostname
        :param driver: (str) the libvirt driver to use
        :return: a string of the XML domain information
        """
        driver = self.host.driver
        user = self.host.user
        host = self.host.host
        drv_format = "qemu:///system"
        uid = self.instance.id

        if host is not None:
            drv_format = "{}://{}@{}/system".format(driver, user, host)
        self.logger.info("getting libvirt xml from {}".format(drv_format))
        conn = libvirt.open(drv_format)
        xml_desc = None
        try:
            inst = conn.lookupByUUIDString(uid)
            xml_desc = inst.XMLDesc(flags=flags)
        except libvirt.libvirtError as le:
            msg = "Unable to find instance with UUID: {}".format(uid)
            self.logger.error(msg)
            raise le
        finally:
            conn.close()
            return xml_desc

    def verify_hugepage(self):
        """
        This function will verify that the instance is backed by huge pages::

          <memoryBacking>
            <hugepages>
              <page size='2048' unit='KiB' nodeset='0'/>
            </hugepages>
          </memoryBacking>

        :return: boolean
        """
        xml_dump = self.dumpxml()
        root = ET.fromstring(xml_dump)
        mb = root.iter("memoryBacking")
        try:
            mb = next(mb)
        except StopIteration:
            return False

        pages = [child for child in mb.iter() if child.tag == "page"]
        for page in pages:
            if page.attrib["nodeset"] == "0" and page.attrib["size"] == "2048":
                tag, attrib, txt = page.tag, page.attrib, page.text
                self.logger.info("Verified huge page: {} {} {}".format(tag, attrib, txt))
                return True
        else:
            return False


def safe_delete(instances):
    for guest in instances:
        try:
            guest.delete()
        except NotFound:
            pass
        smog.nova.poll_status(guest, "deleted")


class BaseStack(object):
    def __init__(self, logger=glob_logger, **kwargs):
        """
        This class (and derived classes) should only contain immutable data.  It
        is a helper to set the extra specs and dumpxml to verify

        :param kwargs:
          -username: the user (in a tenant) in the Openstack deployment (eg same
                     as OS_USERNAME)
          -password: the password for the user (eg same as OS_PASSWORD)
          -tenant: the tenant in the Openstack deployment (eg same as OS_TENANT)
          -auth_url: the keystone authentication url (same as OS_AUTH_URL)

        :return:
        """
        self._kwargs = kwargs
        self._keystone = None
        self._nova = None
        self._glance = None
        self._neutron = None
        self.allow_negative = True
        self.logger = logger
        self.glance_version = "1"
        self.monitors = {}

    def make_demo(self, tenant_name, tenant_kw, user_name, user_kw):
        tenant = smog.keystone.create_tenant(self.keystone, tenant_name,
                                             **tenant_kw)
        user = smog.keystone.create_user(self.keystone, tenant.id, user_name,
                                         **user_kw)
        creds = {"username": user_name, "tenant_name": tenant.id,
                 "password": user_kw["password"],
                 "auth_url": self.keystone.auth_url}
        nova = smog.nova.create_nova_client(self.keystone, creds)
        return {"tenant": tenant, "user": user, "nova": nova}

    @property
    def keystone(self):
        if self._keystone is None:
            self._keystone = create_keystone(**self._kwargs)
        return self._keystone

    @keystone.setter
    def keystone(self, val):
        msg = "Can't change value of keystone to {}".format(val)
        raise ReadOnlyException(msg)

    @property
    def nova(self):
        if self._nova is None:
            self._nova = create_nova_client(self.keystone)
        return self._nova

    @nova.setter
    def nova(self, val):
        msg = "Cant change the value of nova to {}".format(val)
        raise ReadOnlyException(msg)

    @property
    def glance(self):
        if self._glance is None:
            self._glance = create_glance(self.keystone, self.glance_version)
        return self._glance

    @glance.setter
    def glance(self, val):
        msg = "Cant change the value of glance to {}".format(val)
        raise ReadOnlyException(msg)

    @property
    def neutron(self):
        if self._neutron is None:
            self._neutron = create_neutron_client(key_cl=self.keystone)
        return self._neutron

    def refresh(self):
        """
        If keystone token expires, set clients with refreshed keystone client

        :return:
        """
        self._keystone = create_keystone(**self._kwargs)
        self._nova = create_nova_client(self.keystone)
        self._glance = create_glance(self.keystone, self.glance_version)
        return self.keystone

    def boot_instance(self, img=None, flv=None, name="test", nic_list=None,
                      **kwargs):
        """

        :param img:
        :param flv:
        :param name:
        :param net: a smog.neutron.NIC object
        :param kwargs:
        :return:
        """
        if img is None:
            img = self.get_image_name("cirros")
        if flv is None:
            flv = self.get_flavor("1")

        # For Kilo, convert the nic object to a dict
        if nic_list is None:
            # By default we will use the private network
            pvt_net_pred = smog.neutron.has_network_field("private")
            nets = smog.neutron.list_neutron_nets(self.neutron,
                                                  filter_fn=pvt_net_pred)
            pvt_net = nets[0]
            if pvt_net["status"] != "ACTIVE":
                raise Exception("Private network is not active")
            nic = smog.neutron.NIC(net_id=pvt_net["id"])
            if "nic" not in kwargs:
                kwargs["nics"] = [nic.to_dict()]
            else:
                assert type(kwargs["nics"]) == list
                kwargs["nics"].append(nic.to_dict())
        else:
            tmp_nic = []
            for nic in nic_list:
                tmp_nic.append(nic.to_dict())
            if "nic" not in kwargs:
                kwargs["nics"] = tmp_nic
            else:
                assert type(kwargs["nics"]) == list
                kwargs["nics"].extend(tmp_nic)

        instance = boot_instance(self.nova, name, img, flv, **kwargs)
        return instance

    def boot_instances(self, images, flavors, name="test", poll=True, **kwargs):
        """
        Allows a nova instance to boot up given a sequence of images and flavors

        This function takes two equal sized sequences of images and flavors,
        and one by one it boots up a nova instance from the pair

        :param images: A sequence of Glance image objects
        :param flavors: A sequence of Flavor objects
        :return: A sequence of instances
        """
        data = []
        i_id = 0
        for img, flavor in zip(images, flavors):
            name = "{}-{}".format(name, i_id)

            self.logger.debug("Booting up instance {}".format(name))
            instance = boot_instance(self.nova, name, img, flavor, **kwargs)
            if instance is None:
                raise BootException("Unable to boot up new instance")
            if instance.status == "error":
                msg = "Error booting instance: {}".format(instance.fault)
                raise BootException(msg)

            # Wait for the instance(s) to be in ACTIVE state
            if poll:
                active = poll_status(instance, "ACTIVE", timeout=300)
                if not active:
                    msg = "Problem bringing up instance {}: {}"
                    try:
                        fault = instance.status
                        msg = msg.format(name, fault)
                    except NotFound:
                        msg = msg.format(name, "")
                    raise BootException(msg)
            data.append(instance)
            i_id += 1
        return data

    def discover(self, guests=None, user="root", htype=VM):
        """
        For each instance, create an Instance object

        :param guests: optional list of guests to pass in (no discovery)
        :param user: (str) user to gain libvirt access
        :param htype:

        :return: list of Instance objects
        """
        # Get the hypervisor and hosts for each instance.
        # FIXME: we will assume all hosts have the same user,pw
        if guests is None:
            filt = lambda x: x.status != "ERROR"
            guests = list_instances(self.nova, fn=filt)
        hypervisors = self.nova.hypervisors.list()
        instances = []
        for guest in guests:
            guest.get()  # refresh any data
            host = getattr(guest, "OS-EXT-SRV-ATTR:host")

            # Match instance to the hypervisor
            for hv in hypervisors:
                if host == hv.hypervisor_hostname:
                    ip, name = hv.host_ip, hv.hypervisor_hostname
                    host = Host(ip, name, user=user, htype=htype)
                    inst = Instance(guest, host, self, logger=self.logger)
                    instances.append(inst)
                    break
        return instances

    def get_hypervisors(self):
        """
        Returns a sequence of hypervisors for a given Openstack deployment
        :return:
        """
        return smog.nova.list_hypervisors(self.nova)

    def get_hypervisor_hosts(self):
        """
        Returns a list of compute nodes hostnames for a deployment
        :return:
        """
        for hv in self.nova.hypervisors.list():
            yield hv.host_ip, hv.hypervisor_hostname

    def get_image_name(self, name):
        """
        Convenience function to get a cirros image
        :param name: a name to look up (not by ID)
        :return:
        """
        images = glance_image_list(self.glance)
        img = glance_images_by_name(name, images)
        return img[0]

    def get_flavor(self, name):
        """
        Convenience function to get a flavor object

        :param name:
        :return:
        """
        flv = list_flavors(self.nova, filt=smog.nova.get_by_name(name))
        if not flv:
            flv = list_flavors(self.nova, filt=smog.nova.get_by_id(name))
        return flv[0]

    def create_flavor(self, name, ram=1024, vcpus=1, disksize=10, specs=None):
        """
        Creates a flavor object.

        Since vcpu pinning and NUMA topology are defined by extra specs that
        are injected into the flavor, this function is useful

        :param name: A human friendly name for the flavor
        :param ram: The amount of ram (in MB) for the flavor
        :param vcpus:  The number of vcpus
        :param disksize: disk size in GB
        :return: Flavor object
        """
        flavor = self.nova.flavors.create(name, ram, vcpus, disksize)
        if specs is not None:
            flavor.set_keys(specs)
        return flavor

    def delete_flavors(self, filt=None):
        """
        Delete all flavors
        :param name:
        :return:
        """
        if filt is None:
            filt = lambda x: not x.name.startswith("m1.")
        flaves = smog.nova.list_flavors(self.nova, filt=filt)
        for flv in flaves:
            flv.delete()

    def delete_instances(self, filt=None):
        # Delete all instances
        vms = smog.nova.list_instances(self.nova, fn=filt)
        safe_delete(vms)

    def delete_server_groups(self, filt=None):
        # Delete all servergroups
        groups = self.nova.server_groups.list()
        if filt is not None:
            groups = [g for g in groups if filt(g)]
        for group in groups:
            self.nova.server_groups.delete(group.id)

    def delete_aggregates(self, filt=None):
        aggregates = self.nova.aggregates.list()
        if filt is not None:
            aggregates = filter(filt, aggregates)
        for agg in aggregates:
            for host in agg.hosts:
                agg.remove_host(host)
            self.nova.aggregates.delete(agg)

    def monitor(self, cmd, name, host, hcls, *args, log=None, **kwargs):
        """
        Creates a Watcher and Handler, and adds the Watcher object to self

        :param cmd: The command to run which will be watched
        :param name: a name to give the monitor
        :param host: the hosts to run cmd on
        :param hcls: a Handler class (not object)
        :param log: defaults to sys.stdout, but can be a file-like object
        :param args: passed through to hcls(*args, **kwargs)
        :param kwargs: passed through to hcls(*args, **kwargs)
        :return: Watcher object
        """
        if log is None:
            log = sys.stdout

        cmd = Command(cmd, host=host)
        res = cmd(block=False, remote=True)
        watcher = Watcher(res, log=log)
        rdr_proc = watcher.start_reader()

        if "log" in kwargs:
            kwargs.pop("log")
        handler = hcls(rdr_proc, *args, **kwargs)

        # start the consumer that will read from the que
        mntr_proc = watcher.start_monitor(handler, watcher.queue)
        rdr_proc.start()
        mntr_proc.start()
        mon = {name: watcher}
        if name in self.monitors:
            raise ArgumentError("{} already in self.monitors".format(name))
        self.monitors.update(mon)
        return watcher

    def create_host_aggregate(self, name, metadata=None, host=None,
                              zone="nova"):
        """
        Creates a hosts aggregate that we can bind an instance to

        :param name: (str) name to give to Aggregate
        :param metadata: (dict|str) metadata to supply to the aggregate
        :param host: (str) the hostname of the compute host
        :param zone:
        :return:
        """
        aggregates = self.nova.aggregates
        agg = aggregates.create(name, zone)
        if metadata is not None:
            if isinstance(metadata, dict):
                agg.set_metadata(metadata)
            elif isinstance(metadata, str):
                mdata = reduce(lambda k, v: {k: v}, metadata.split("="))
                agg.set_metadata(mdata)
            else:
                err = "metadata must be a dictionary or a k=v pair"
                raise ArgumentError(err)
        if host is not None:
            agg.add_host(host)
        return agg

    def get_aggregate_by_name(self, name):
        aggregates = self.nova.aggregates.list()
        agg = list(filter(lambda x: x.name == name, aggregates))
        if not agg:
            raise Exception("Could not find Aggregate")
        if len(agg) > 1:
            raise Exception("Ambiguity, more than one Aggregate found")
        return agg[0]

    def add_host_to_aggregate(self, agg, hostname):
        """
        Adds compute host to an aggregate
        :param agg: (str|Aggregate) the aggregate's name or Aggregate object
        :param hostname: hostname of the compute host to add
        :return:
        """
        if isinstance(agg, str):
            agg = self.get_aggregate_by_name(agg)
        agg.add_host(hostname)
        return agg.get()

    def delete_host_from_aggregate(self, agg, hostname):
        if isinstance(agg, str):
            agg = self.get_aggregate_by_name(agg)
        agg.remove_host(hostname)
        return agg.get()

    def create_aggregate_groups(self, meta_name):
        """
        Creates a pair of aggregates, where meta_name is a key.  One of the
        aggregates will be set to meta_name=true, and the other to
        meta_name=false

        This is useful when you want to test pairs of opposite things.  For
        example one aggregrate can be for pinned=true which allows for vcpu
        pinning, and another aggregate of pinned=false.  Same for hugepage
        support, or pci_passthrough, etc

        :param meta_name: (str) name for the metadata key
        :return: a pair
        """
        # Get the compute hosts on the deployment.  One of them will be in
        # pinned=true aggregate, the rest in pinned=false
        hosts = list(self.get_hypervisor_hosts())
        index = random.randint(0, len(hosts)-1)
        _host = hosts.pop(index)
        _ip = _host[0]

        # Create a meta_name=true and meta_name=false host aggregate.
        create_agg = self.create_host_aggregate
        meta = "{}=true".format(meta_name)
        # Overkill perhaps, but let's do functional when we can :)
        names = list(map(lambda x: "{}_{}".format(meta_name, x), ["true", "false"]))
        true_agg = create_agg(names[0], metadata=meta, host=_host[1])
        meta = "{}=false".format(meta_name)
        false_agg = create_agg(names[1], metadata=meta)
        for _, host in hosts:
            false_agg.add_host(host)

        return true_agg, false_agg, _ip

    def create_new_user(self, name):
        pass

    def clean(self):
        """
        Clean up
        :return:
        """
        self.logger.info("Cleaning up...")
        self.delete_instances()
        self.delete_flavors()
        self.delete_server_groups()
        self.delete_aggregates()


class FilterVerifier(object):
    def __init__(self, base):
        self.base = base

    @staticmethod
    def verify_filter_support(host, filter_name):
        """
        Checks the nova.conf file and determines if filter_name is one of the
        items in scheduler_default_filters

        :param filter_name: (str) name of filter (eg NUMATopologyFilter)
        :return: True if filter_name is included, else False
        """
        get_nova_conf(host)
        vals = get_cfg("scheduler_default_filters", "nova.conf")
        for v in vals:
            if v['comment'] is None:
                line = v['line']
                break
        else:
            raise Exception("Unable to find filters in nova.conf")

        return filter_name in [val.strip() for val in line.split(",")]

    @staticmethod
    def verify_host_aggregate_support(host):
        """
        Gets values from libvirtd.conf and looks for
        :return:
        """
        flt = "AggregateInstanceExtraSpecsFilter"
        # Because of https://bugs.launchpad.net/nova/+bug/1279719 we cant have
        # both the ComputeCapabilitiesFilter _and_ the Aggregrate filter.  So
        # let's remove the ComputeCapabilitiesFilter
        get_nova_conf(host)
        vals = get_cfg("scheduler_default_filters", "nova.conf")

        filters = [v["val"] for v in vals if v["comment"] is None]
        filters_clean = [f for f in filters if f != "ComputeCapabilitiesFilter"]

        return FilterVerifier.verify_filter_support(host, flt)

    @staticmethod
    def verify_numa_topology_filter(host):
        return FilterVerifier.verify_filter_support(host, "NUMATopologyFilter")

    @staticmethod
    def verify_affinity_filter(host):
        flt = "ServerGroupAffinityFilter"
        return FilterVerifier.verify_filter_support(host, flt)

    @staticmethod
    def verify_anti_affinity_filter(host):
        flt = "ServerGroupAntiAffinityFilter"
        return FilterVerifier.verify_filter_support(host, flt)


def filter_check_and_set(filter_names):
    """
    Decorator which can be used to check for and set a nova.conf filter.

    This decorator should be used on BaseTest derived test cases
    :param filter_name:
    :return:
    """
    def outer(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            # Read in the nova.conf file
            self = args[0]
            host = self.config["hosts"]["controller"]

            return fn(*args, **kwargs)
        return inner
    return outer


class Info(object):
    """
    A container of information about a test environment
    """
    def __init__(self, **kwargs):
        self.hosts = kwargs["hosts"]
        self.controller = kwargs["controllers"]
        self.master = kwargs["master"]
        self.name = kwargs["name"]
        self.comp_host = kwargs["comp_host"]
        self.instance = kwargs["instance"]
        self.orig_hostname = kwargs["orig_hostname"]
        self.hypervisor = kwargs["hypervisor"]


class BaseTest(unittest.TestCase):

    __metaclass__ = ABCMeta
    config_file = ""
    config_dir = __file__

    @classmethod
    def setUpClass(cls):
        """
        Reads in the configuration file for our parameters which will be available
        in the cls.config variable

        :param cls:
        :return:
        """
        config = get_yaml_file(cls.config_dir, cls.config_file)
        cls.config = config
        return cls.config

    def same_host(self, guests, check="compute1"):
        for guest in guests:
            host = guest.host
            should_host = self.config["hosts"][check]["hosts"]
            if host.host != should_host:
                raise Exception("instance is on {}".format(host.host))
            self.assertEquals(host.host, should_host,
                              "Instance should be on same")

    @classmethod
    def verify_config(cls, host, conf_f, key, valid, section="DEFAULT"):
        """
        Verify that key has valid key,value pair in config file

        :param conf_f: Configuration file to use (eg /etc/nova/nova.conf)
        :param key: the key to look up
        :param valid: (str) compare this to what is found in file
        :param computes: a list of ip addresses to check
        :param section: section to look up key
        :return: hosts where
        """
        res = openstack_config(conf_f, section, key, host=host)
        current = res.output
        return current.strip() == valid.strip()

    @classmethod
    def set_base_config(cls):
        """
        Verify that we have the filters from our config enabled.  Make sure that
        virt_type specified in the config is set

        :param cls:
        :return:
        """

        # Get the necessary info from numa_config.yml
        filters = cls.config["nova"]["filters"]
        computes = [c["host"] for c in cls.config["hosts"]["computes"]]
        virt_type = cls.config["nova"]["virt_type"]

        # verify we have the nova filters
        def_filters = "scheduler_default_filters"
        default = "RetryFilter,AvailabilityZoneFilter,RamFilter,ComputeFilter," \
                  "ComputeCapabilitiesFilter,ImagePropertiesFilter," \
                  "ServerGroupAntiAffinityFilter,ServerGroupAffinityFilter\n"
        nova_conf = "/etc/nova/nova.conf"

        for host in computes:
            # Get the current filters.  Check to see if what we need is already
            # in, and if not, add it
            res = openstack_config(nova_conf, "DEFAULT", def_filters,
                                   opt="get", host=host)
            if res != 0:
                current = default
            else:
                current = res.output
            curr_items = current.strip().split(",")
            final_items = curr_items[:]  # hack to get a copy
            changed = False

            for fltr in filters:
                if fltr not in curr_items:
                    final_items.append(fltr)
                    changed = True

            # Due to https://bugs.launchpad.net/nova/+bug/1279719, we can't
            # have both the ComputeCapabilities and Aggregate filter.  If both
            # of these are in fltr_val, remove ComputeCapabilitiesFilter
            if "ComputeCapabilitiesFilter" in final_items and \
                "AggregateInstanceExtraSpecsFilter" in final_items:
                final_items.remove("ComputeCapabilitiesFilter")
                changed = True

            fltr_val = ",".join(final_items) + "\n"

            # fltr_val has the final filters, set it to this
            if (len(final_items) != len(curr_items)) or changed:
                openstack_config(nova_conf, "DEFAULT", def_filters,  opt="set",
                                 value=fltr_val, host=host)

            success = cls.verify_config(host, nova_conf, def_filters, fltr_val)
            if not success:
                err = "Could not set {} {} to {}".format(nova_conf, def_filters,
                                                         fltr_val)
                cls.fail(err)

            # restart openstack services
            if changed:
                cmd = Command("openstack-service restart openstack-nova", host=host)
                cmd()

            if cls.verify_config(host, nova_conf, "virt_type", virt_type,
                                 section="libvirt"):
                pass
            else:
                openstack_config(nova_conf, "libvirt", "virt_type", opt="set",
                                 value=virt_type, host=host)

    def _setup_monitor(self, base, name, cmd=None, log_path=None,
                       hdlr=ExceptionHandler):
        # Startup a watcher process with an ExceptionHandler handler.  Also
        # create a log file for each test method
        controller = self.config["hosts"]["controllers"]
        if cmd is None:
            cmd = "tail -f /var/log/nova/nova-*"
        if log_path is None:
            log_path = os.path.join(smog.config["log_dir"], name)
        self.log_file = open(log_path, "w")
        self.watcher = base.monitor(cmd, name, controller["host"], hdlr,
                                    log=self.log_file)


class NovaTest(BaseTest):

    config_file = "numa_config.yml"
    config_dir = __file__

    def initialize(self, name, **kwargs):
        """
        Meant to be used when at the shell.  This function will create a BaseStack object
        :param kwargs:
        :return:
        """
        base = BaseStack(**kwargs)
        setattr(self, name, base)

    @classmethod
    def setup_nested_support(cls):
        """
        Ensures that the hypervisor host has nested virtualization support
        :return:
        """
        computes = cls.config["hosts"]["computes"]
        nested_support = cls.config["nova"]["nested_vm"]
        passthrough = cls.config["nova"]["cpu_mode"]

        if not nested_support:
            return

        bare_m = []
        for cmpt in computes:
            if cmpt["type"] == "vm":
                parent = cmpt["parent"]
                bare_m.append([parent, (cmpt["host"], cmpt["name"])])

        for bm, info_set in bare_m:
            fnc = None
            if passthrough == "passthrough":
                fnc = smog.virt.set_host_passthrough
            elif passthrough == "host-model":
                fnc = smog.virt.set_host_model
            smog.virt.set_nested_vm_support(bm, info_set, fn=fnc)

            if PERMISSIVE:
                host = info_set[0]
                res = Command("setenforce 0", host=host)()

        # TODO: Make sure if we're doing huge pages that the virt_type in
        # nova.conf is set to virt_type=kvm.  If virt_type=qemu, large page
        # support may fail.

    def _base_setup(self, base_):
        self.data = {}
        self.logger = base_.logger

        # Clean up
        self.logger.info("Cleaning up:")
        self.logger.info("\tdeleting instances...")
        base_.delete_instances()
        self.logger.info("\tdeleting non-default flavors...")
        base_.delete_flavors()
        flt = lambda x: "m1" not in x.name
        flavors = smog.nova.list_flavors(base_.nova, filt=flt)
        self.assertFalse(flavors)
        self.logger.info("\tdeleting server affinity groups...")
        base_.delete_server_groups()
        self.assertFalse(base_.nova.server_groups.list())
        self.logger.info("\tdeleting server aggregate groups...")
        base_.delete_aggregates()
        self.assertFalse(base_.nova.aggregates.list())

    def verify_nested_support(self):
        # Get the masters host
        computes = self.config["hosts"]["computes"]
        for cmpt in computes:
            bm = cmpt["parent"]
            name = (cmpt["host"], cmpt["name"])
            user = cmpt["user"]
            smog.virt.set_nested_vm_support(bm, name, user=user)

    def dont_run(self, base_, data):
        """
        Creates an instance, and a hosts
        :return:
        """
        img = base_.get_image_name("cirros")
        self.assertTrue(img)
        flv = base_.get_flavor("m1.tiny")
        self.assertTrue(flv)
        serv = base_.boot_instances([img], [flv])
        self.assertTrue(serv)

        instances = base_.discover()
        self.assertTrue(instances)
        data["instances"] = instances

        virts = []
        for inst in instances:
            virt = inst.get_domain()
            domain = virt.domain
            self.assertTrue(domain)
            virts.append(virt)
            print(inst.dumpxml())
        data["virts"] = virts

    def update_info(self, info_, base_):
        """
        Updates info after a live migration

        :param info_:
        :return:
        """
        glob_logger.info("Getting new master hosts info_...")
        info_.instance = base_.discover()[0]
        info_.comp_host = info_.instance.host.host
        msg = "instance({}) is now on compute hosts {}"
        glob_logger.info(msg.format(info_.instance.instance.id,
                                    info_.comp_host))
        filt = lambda x: "compute" in x[0]
        hosts = filter(filt, info_.hosts.items())
        host_info = None
        for _, vals in hosts:
            for val in vals:
                if val["host"] == info_.comp_host:
                    host_info = val
        if host_info is None:
            raise Exception("Can't find matching hosts")

        info_.master = host_info["parent"]
        info_.name = host_info["name"]
        msg = "Parent hosts of {} is {}, {}".format(info_.comp_host,
                                                    info_.master, info_.name)
        glob_logger.info(msg)
        return info_

    def get_info(self, base_, data):
        """
        Creates an Info object
        :param base_: A BaseStack object
        :param data: a dictionary containing test data
                     keys- master: the masters hypervisor ip
                           compute_name: the domain name
                           compute_host: the ip of the compute instance
        :return: Info object
        """
        hosts = self.config["hosts"]
        controller = hosts["controllers"]["host"]
        master = data["master"]
        name = data["compute_name"]
        comp_host = data["compute_host"]

        glob_logger.info("Discovering nova instances on {}".format(comp_host))
        instances = base_.discover()
        if not instances:
            raise Exception("Could not find any instances")

        instance = instances[0]
        orig_hostname = instance.host.hostname

        fltr = lambda x: x.host_ip == comp_host
        hv = smog.nova.list_hypervisors(base_.nova, fn=fltr)[0]

        info = {"hosts": hosts, "controllers": controller, "master": master,
                "name": name, "comp_host": comp_host, "instance": instance,
                "orig_hostname": orig_hostname, "hypervisor": hv,
                "instances": instances}

        return Info(**info)

    def _get_xml(self, instances):
        for instance in instances:
            if instance.instance.name != "dummy":
                yield instance.dumpxml()

    def create_instance(self, base, **kwargs):
        flv = base.get_flavor("m1.tiny")
        img = base.get_image_name("cirros")
        instance = base.boot_instance(img, flv, **kwargs)
        active = smog.nova.poll_status(instance, "ACTIVE", timeout=300)
        return instance

    def setup_affinities(self, base_, anti=None, aff=None):
        """

        :param base_: BaseStack object
        :param anti: A 2 element sequence of name to give AntiAffinityGroup
                     and name to give anti-affinity instance
        :param aff:  A 2 element sequence of name to give AffinityGroup and
                     name to give affinity instance
        :return:
        """
        if anti is None:
            anti = ("anti-group", "aa-test")
        if aff is None:
            aff = ("aff-group", "aff-test")

        # Create a ServerGroupAntiAffinity.
        group_create = smog.nova.server_group_create
        self.group = group_create(base_.nova, anti[0],
                                  policies="anti-affinity")
        self.group_id = {"group": self.group.id}
        self.data["group"] = self.group

        # Create a ServerGroupAffinity, so that we can ensure a hosts is created
        # on a particular hosts ("compute1")
        group_create = smog.nova.server_group_create
        self.agroup = group_create(base_.nova, aff[0],
                                   policies="affinity")
        self.agroup_id = {"group": self.agroup.id}
        self.data["agroup"] = self.agroup

        # Boot one instance into the affinity group
        a_instance = base_.boot_instance(name=aff[1],
                                         scheduler_hints=self.agroup_id)
        self.data["aff_instance"] = a_instance

        # Boot another instance into the anti-affinity group
        anti_instance = base_.boot_instance(name=anti[1],
                                            scheduler_hints=self.group_id)
        self.data["anti_instance"] = anti_instance

        # Make sure that both instances do not belong to the same host
        # FIXME: assumes 2 compute nodes only
        discovered = base_.discover()
        fn = lambda x: x.host
        hosts = list(map(fn, discovered))
        initial = hosts[0].hostname
        is_same = all(map(lambda x: x.hostname == initial, hosts))
        self.assertFalse(is_same)

        return self.data


if __name__ == "__main__":
    from smog.utils.rc_helper import read_rc_file
    creds = read_rc_file("10.12.20.128", "/root/keystonerc_admin")
    base = BaseStack(**creds)

    guest = base.boot_instance(name="simple")
    active = smog.nova.poll_status(guest, "ACTIVE")


