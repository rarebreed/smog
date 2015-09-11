__author__ = 'stoner'

from abc import ABCMeta, abstractmethod
import re
import os
import copy
import platform
import yaml

from smog import load_config
from smog.tests.base import get_remote_file, set_cfg
from smog.core.commander import Command
from smog.core.exceptions import ArgumentError
from smog.core.logger import glob_logger, banner
import smog.tests.base

py_version = """'python -c "from platform import linux_distribution\n\
print linux_distribution()"'"""


def distro_factory(host, command=py_version):
    """
    :return: RHEL release version number.
    """
    cmd = Command(command, host=host)
    res = cmd()
    lines = res.output

    res = eval(lines.strip())
    flavor, version, codename = res
    patt = re.compile(r"(\d+(\.\d+)?)")
    m = patt.search(version)
    if not m:
        raise Exception("Could not get version info")
    version = float(m.groups()[0])
    return _factory(host, flavor, version, codename)


def _factory(host, flavor, version, name):
    nfs_ver = "nfs4"
    if "Red Hat" in flavor or "CentOS" in flavor:
        family = "CentOS" if "CentOS" in flavor else "RHEL"
        if version >= 7.0:
            family = family
            return OSInfo7(host, flavor, version, name, nfs_ver, family)
        elif version < 6.0:
            raise Exception("This version of RHEL is not supported")
        else:
            nfs_ver = "nfs"
            return OSInfo6(host, flavor, version, name, nfs_ver, family)
    elif "Fedora" in flavor:
        if version >= 18.0:
            family = "Fedora"
            return Fedora(host, flavor, version, name, nfs_ver, family)
        else:
            raise Exception("This version of Fedora is not supported")
    else:
        raise Exception("{0} is not a supported linux distro".format(flavor))


class OSInfo(object):
    __metaclass__ = ABCMeta

    def __init__(self, host, flavor, ver, name, nfs_ver, family):
        self.host = host
        self.flavor = flavor
        self.version = ver
        self.name = name
        self.family = family
        self.nfs_ver = nfs_ver
        self.service_cmd = ""  # "systemctl {command} {name}"
        self.service_enable = ""  # "systemctl {command} {name}"

    @abstractmethod
    def service_control(self, srv_name, command):
        return self.service_cmd.format(name=srv_name, command=command)


class OSInfo6(OSInfo):
    def __init__(self, host, flavor, version, name, nfs_ver, family):
        super(OSInfo6, self).__init__(host, flavor, version, name, nfs_ver,
                                      family)
        self.service_cmd = "service {name} {command}"
        self.service_enable = "chkconfig {name} {command}"

    def service_enabler(self, srv_name, mode="on"):
        if mode not in ("on", "off"):
            raise ArgumentError("mode must be 'on' or 'off'")
        command = "chkconfig {} {}".format(mode, srv_name)
        return Command(command, host=self.host)(throws=False)

    def service_control(self, srv_name, srv_cmd):
        command = "service {} {}".format(srv_name, srv_cmd)
        return Command(command, host=self.host)(throws=False)


class OSInfo7(OSInfo):
    def __init__(self, host, flavor, version, name, nfs_ver, family):
        super(OSInfo7, self).__init__(host, flavor, version, name, nfs_ver,
                                      family)
        self.service_cmd = "systemctl {command} {name}"
        self.service_enable = "systemctl {command} {name}"

    def service_enabler(self, srv_name, mode="on"):
        if mode not in ("on", "off", "enable", "disable"):
            raise ArgumentError("mode must be one of [on,off,enable,disable]")
        if mode == "enable":
            mode = "enable"
        elif mode == "disable":
            mode = "disable"
        return self.service_control(srv_name, mode)

    def service_control(self, srv_name, srv_cmd):
        # Due to the change between rhel6 and rhel7 service names, but the
        # changes here
        if srv_name == "nfs":
            srv_name = "nfs-server"

        command = "systemctl {} {}".format(srv_cmd, srv_name)
        return Command(command, host=self.host)(throws=False)


class Fedora(OSInfo7):
    def __init__(self, host, flavor, version, name, nfs_ver, family):
        super(Fedora, self).__init__(host, flavor, version, name, nfs_ver,
                                     family)


class Configure(object):
    def __init__(self, logger=glob_logger):
        self.logger = logger
        self.scp = smog.tests.base.scp

    def firewall_setup(self):
        pass

    def args_override(self):
        pass

    @staticmethod
    def gen_file(filename, value):

        """gen_file will create a new file according to the input provided.

        :param filename: output name for the configuration file to be written.
        :param value: is a list of data to be written to the given config file.
        """
        try:
            fh = open(filename, 'w')
        except IOError as e:
            print("Couldn't create {0}: {1}".format(filename, e.strerror))
            raise e

        for i in value:
            fh.write('%s   ' % i)

        try:
            fh.close()
            return filename
        except IOError as ie:
            print("Couldn't close {0} do to: {1}".format(filename, ie.strerror))
            print(ie.message)


class ConfigureNFS(Configure):
    def __init__(self, logger=glob_logger):
        super(ConfigureNFS, self).__init__(logger=logger)
        # Ughhh dynamic languages.  Put this here to help the IDE
        self.system_info_cfg = None
        self.share_storage_cfg = {}
        self.nova_cfg = None
        self.libvirtd_cfg = None
        self.firewall_cfg = None

        conf_files = ["system_info.yml", "share_storage.yml", "nova.yml",
                      "libvirtd.yml", "firewall.yml"]
        names = [x.replace(".yml", "_cfg") for x in conf_files]
        fn = lambda x: load_config(__file__, x, extra_paths=["configs"])
        cfgs = map(fn, conf_files)
        make = lambda y, z: setattr(self, y, z)
        res = list(map(make, names, cfgs))

        # For those not familiar with functional programming, the above is
        # equivalent to this:
        # self.system_info_cfg = load_config(__file__, "system_info.yml",
        #                                    extra_paths=["configs"])
        # self.share_storage_cfg = load_config(__file__, "share_storage.yml",
        #                                     extra_paths=["configs"])
        # ...

        self.opts = self.get_args()
        self.args_override()
        self.nfs_server = None
        self.nfssrv_info = None
        self.computes = self.system_info_cfg["hosts"]["computes"].split(",")
        controllers = self.system_info_cfg["hosts"]["controllers"]
        self.controllers = controllers.split(",")
        self.comp_info = {ip: distro_factory(ip) for ip in self.computes}

        self.setup_system_info()
        self.configure_nfs()

    @staticmethod
    def get_args(args=None):
        major, minor, micro = platform.python_version_tuple()
        if minor == '6':
            from optparse import OptionParser as Parser
            desc = 'Live Migration Setup Util.  All of the command line ' \
                   'options are optional, and if none are used, then the ' \
                   'files in the config folder will be used.  If any options ' \
                   'are given on the command line, they will override the ' \
                   'config files, and those settings will be used instead'
            parser = Parser(description=desc)
            add_opt = parser.add_option
            parse_args = lambda x: x.parse_args(args)[0]
        else:
            from argparse import ArgumentParser as Parser
            parser = Parser(description='Live Migration Setup Util.')
            add_opt = parser.add_argument
            parse_args = lambda x: x.parse_args(args)

        add_opt("--controllers",
                help="IP address of the controllers/compute 1 node")
        add_opt("--computes",
                help="IP address of all the compute nodes (comma separated)")
        add_opt("--domain", help="domain address for system")
        add_opt("--functions",
                help="Optional: a list of function names to call.  If specified"
                     " then regular setup() will not be called")
        add_opt("--nfs-server", help="IP Address of the nfs server "
                                     "(Defaults to the first controllers)")
        add_opt("--gen-sys-info", help="generate a new system_info config")
        add_opt("--gen-storage",
                help="Generate a new share_storage config file")
        add_opt("--gen-only", action="store_true", default=False,
                help="Only generate the new config file(s) the quit")
        opts = parse_args(parser)
        return opts

    def args_override(self):
        """
        This will replace the items in the dictionary used for config settings.

        This module uses the various dictionaries (eg self.system_info_cfg,
        self.nova_cfg, etc) for values to use at runtime.  First the Configure
        class loads the yml file and stores it into the aforementioned dicts.
        This function will then take any command line args, and override the
        appropriate values.  This way, command line wins.

        TODO:  environment variables (order is yml, env, cmdline)
        :return:
        """
        # Check to see if user overriding controllers and compute nodes
        syscfg = self.system_info_cfg
        if self.opts.controllers is not None:
            syscfg["hosts"]["controllers"] = self.opts.controllers
        if self.opts.computes is not None:
            syscfg["hosts"]["computes"] = self.opts.computes
        self.system_info_cfg = syscfg

        # Check to see if user is overriding NFS server (default is the same
        # as the controllers
        storage_cfg = self.share_storage_cfg["nfs"]
        if self.opts.nfs_server is not None:
            storage_cfg["nfs_export"]["nfs_server"] = self.opts.nfs_server
        else:
            storage_cfg["nfs_export"]["nfs_server"] = \
                syscfg["hosts"]["controllers"].split(",")[0]
        self.share_storage_cfg["nfs"] = storage_cfg

        # Check to see if user is overriding the domain name
        if self.opts.domain is not None:
            domain = self.opts.domain
            self.share_storage_cfg["nfs"]["nfs_idmapd"]["Domain"] = domain

        def write_out(f_name, val):
            txt = yaml.dump(val)
            with open(f_name, "w") as yml:
                yml.write(txt)

        # Write out config to file if asked for
        if self.opts.gen_sys_info:
            write_out(self.opts.gen_sys_info, self.system_info_cfg)
        if self.opts.gen_storage:
            write_out(self.opts.gen_storage, self.share_storage_cfg)

    def setup(self):
        self.firewall_setup()
        self.libvirtd_setup()
        self.nova_setup()
        self.nfs_server_setup()
        self.nfs_client_setup()
        self.configure_etc_hosts()
        self.finalize_services()

    def setup_system_info(self):
        config = self.share_storage_cfg
        nfs_server = config["nfs"]["nfs_export"]["nfs_server"]
        self.nfs_server = nfs_server
        self.nfssrv_info = distro_factory(self.nfs_server)

    def configure_nfs(self, nfs_ver=None):
        """
        This ensures
        :return:
        """
        ending = ":/"
        attr = 'defaults,context="system_u:object_r:nova_var_lib_t:s0"'

        if nfs_ver is None:
            nfs_ver = self.nfssrv_info.nfs_ver
        if nfs_ver == "nfs":
            ending = ":/var/lib/nova"
            attr = 'defaults,nfsvers=3,' \
                   'context="system_u:object_r:nova_var_lib_t:s0"'

        self.system_info_cfg["fstab"]["nfs_server"] = self.nfs_server + ending
        self.system_info_cfg["fstab"]["attribute"] = attr

    def firewall_setup(self):
        """Firewall setup will open necessary ports on all compute nodes to
        allow libvirtd, nfs_server to communicate with their clients.

        FIXME: this function should be idempotent

        :return: upon success True is returned if not an exception is raised.
        """
        nfs_tcp = self.firewall_cfg['nfs rules']['tcp_ports'].split(",")
        nfs_udp = self.firewall_cfg['nfs rules']['udp_ports'].split(",")
        libvirtd_tcp = self.firewall_cfg['libvirtd rules']['tcp_ports']
        nfs_tcp.append(str(libvirtd_tcp))
        proto_match = {"tcp": nfs_tcp, "udp": nfs_udp}

        # In iptables, find where the first REJECT rule is.  We need to insert
        # at this line number. If the REJECT rule doesn't exist, just start at
        # the last line in the INPUT chain
        def get_line(host):
            res = Command("iptables -n -L INPUT --line-numbers", host=host)()
            out = res.output.split("\n")

            patt = re.compile(r"(\d+)\s+(\w+)")
            for i, lineout in enumerate(out, -1):
                # To make these rules idempotent, we will check if our port is
                # already in the iptables rules.  If it is, remove from our list
                # of ports to add
                if lineout == "":
                    continue

                n = lineout.rfind("/*")
                if n != -1:
                    lineout = lineout[:n]
                splitted = lineout.split()
                first, proto, last = splitted[0], splitted[2], splitted[-1]
                try:
                    int(first)
                except ValueError:
                    continue
                if "," in last:
                    last = last.split(",")
                    newlast = []
                    for l in last:
                        if ":" in l:
                            f, l = map(int, l.split(":"))
                            newlast.extend(list(range(f, l+1)))
                        else:
                            newlast.append(l)
                    last = newlast
                elif ":" in last:
                    last = last.split(":")[1:]
                for port in last:
                    if proto in proto_match and port in proto_match[proto]:
                        proto_match[proto].remove(port)

                m = patt.search(lineout)
                if not m:
                    continue
                line, chain = m.groups()
                msg = "line = {0}, chain = {1}, i={2}".format(line, chain, i)
                self.logger.info(msg)
                if chain == "REJECT":
                    # this line needs to be deleted.
                    Command("iptables -D INPUT {0}".format(i), host=host)()
                    line = i - 1
                    break
            else:
                line = i

            self.logger.info("Final line = {0}".format(line))
            return line

        host = self.nfs_server
        self.logger.info("=" * 20)
        self.logger.info("Setting up firewall rules on {0}".format(host))

        line = int(get_line(host))
        for proto, ports in proto_match.items():
            for port in ports:
                cmd = "iptables -I INPUT {0} -m state --state NEW -m {1} -p " \
                      "{1} --dport {2:s} -j ACCEPT".format(line, proto, port)
                line += 1
                res = Command(cmd, host=host)()
                self.logger.info("Issued: {0}".format(cmd))
                if res == 0:
                    continue
                else:
                    raise EnvironmentError('The remote command failed')

        ipsave_cmd = "service iptables save"
        Command(ipsave_cmd, host=host)()
        self.logger.info("+" * 20)
        return True

    def make_tmp_path(self, path):
        if os.path.isdir(path):
            os.chdir(path)
        else:
            os.mkdir(path)
            os.chdir(path)
        return path

    def make_conf_fn(self, tmp_path, key_excludes=None):
        """
        Returns a closure that retrieves a file from the remote host, modifies
        it according to our yaml config file, and then copies the modified
        file back to the remote host.

        :param tmp_path: The path to the (local) file to modify
        :param key_excludes: (list) of keys in rules to remove
        :param kwargs: keyword args which gets passed to set_cfg()

        :return: A closure, which takes the following arguments
        :param host: (str) host to get file from
        :param rules: (dict) a dict of k/v pairs to set in the config file
        :param rpath: (str) path to the remote config file to adjust
        :param tpath: (str) path to local copy
        :param kwargs: keyword args passed down to set_cfg

        The closure will copy rpath to tpath, and use the key-value pairs in the
        rules to set any parameters (if the key doesn't already exist it will
        """
        def configure_file(host, rules, rpath, tpath=None, **kwargs):
            self.logger.info("Getting {} from {}".format(rpath, host))
            get_remote_file(host, rpath, dest=tmp_path)

            base_name = os.path.basename(rpath)
            local_path = os.path.join(tmp_path, base_name)
            temp_bak = local_path + ".bak"

            if tpath is None:
                tpath = local_path

            # Edit the rules dictionary.  Make a copy of it, and take out
            # any k/v pairs from key_excludes
            newcfg = copy.copy(rules)
            if key_excludes is not None:
                for key in key_excludes:
                    newcfg.pop(key)

            # Set the config file (tpath) with the new k/v values as specified
            # in the rules dictionary
            for key, val in newcfg.items():
                msg = "Setting {} to {} in {}".format(key, val, tpath)
                self.logger.info(msg)
                set_cfg(key, val, local_path, temp_bak, **kwargs)

            # Copy the now modified file back to the host
            dest = "root@{}:{}".format(host, rpath)
            self.logger.info("Copying {} to {}".format(tpath, dest))
            self.scp(tpath, dest)
        return configure_file

    def libvirtd_setup(self):
        """ libvirtd setup will configure libvirtd to listen on the external
        network interface.

        :return: upon success zero is returned if not an exception is raised.
        """
        tmp_path = self.make_tmp_path("/tmp/libvirtd_conf")
        _libvirtd_cfg = self.libvirtd_cfg['libvirtd_conf']
        _libvirtd_syscfg = self.libvirtd_cfg['libvirtd_sysconfig']
        libvirtd_path = _libvirtd_cfg["filepath"]
        libvirtd_syscfg_path = _libvirtd_syscfg['filepath']

        banner(self.logger, ["_libvirtd_conf: {0}".format(_libvirtd_cfg),
                             "_libvirtd_sysconf: {0}".format(_libvirtd_syscfg)])

        configure_file = self.make_conf_fn(tmp_path, key_excludes=["filepath"])

        # Copy the remote libvirtd from each compute node
        for cmpt in self.computes:
            configure_file(cmpt, _libvirtd_cfg, libvirtd_path)
            configure_file(cmpt, _libvirtd_syscfg, libvirtd_syscfg_path)

    def nova_setup(self):
        """
        Nova setup will configure all necessary files for nova to enable live
        migration.
        """
        banner(self.logger, ["Doing nova.conf configuration"])
        tmp_path = self.make_tmp_path("/tmp/nova_conf")
        configure_nova = self.make_conf_fn(tmp_path, key_excludes=["filepath"])

        _nova_conf = self.nova_cfg['nova_conf']

        for comp in self.computes:
            cmd = "mkdir -p {0}".format(_nova_conf['state_path'])
            Command(cmd, host=comp)()

        def nova_adjust(nova_configs_list):
            head, tail = nova_configs_list[0], nova_configs_list[1:]

            def conf_adjust(conf_list, targets):
                for _conf in conf_list:
                    fpath = _conf["filepath"]
                    msg = "Copying {0} to {1}".format(fpath, tmp_path)
                    self.logger.debug(msg)

                    # Create the state_path directory and configure nova
                    for target in targets:
                        configure_nova(target, _conf, fpath)

            # For the computes, we only need to adjust the nova.conf (which is head)
            conf_adjust([head], self.computes)

            # For controllers we need to adjust the openstack service files
            conf_adjust(tail, self.controllers)


        main_compute = self.controllers[0]
        info = self.comp_info[main_compute]
        _nova_configs_list = [_nova_conf]
        if info.family in ["RHEL", "CentOS", "Fedora"] and \
           info.version >= 7:
            msg = "Doing nova setup for {0} {1} on {2}"
            msg = msg.format(info.family, info.version, main_compute)
            self.logger.info(msg)
            _nova_api_service = self.nova_cfg['nova_api_service']
            _nova_cert_service = self.nova_cfg['nova_cert_service']
            _nova_comp_service = self.nova_cfg['nova_compute_service']
            _nova_configs_list = [_nova_conf, _nova_api_service,
                                  _nova_cert_service, _nova_comp_service]
        else:
            self.logger.info("Doing nova setup for RHEL 6")

        # Now we know which files to adjust
        nova_adjust(_nova_configs_list)

    def nfs_server_setup(self):
        """ NFS_Server setup will create an export file and copy this file to
        the nfs server, it will also
        determine the release of RHEL and configure version 3 or 4 nfs service.

        """
        banner(self.logger, ["Doing NFS server setup"])
        tmp_path = self.make_tmp_path("/tmp/nfs_conf")

        nfs = self.share_storage_cfg["nfs"]
        nfs_server = nfs["nfs_export"]["nfs_server"]

        # Configure nfs port settings
        fpath = nfs["nfs_ports"]["filepath"]
        configure_port = self.make_conf_fn(tmp_path, key_excludes=["filepath"])
        configure_port(nfs_server, nfs["nfs_ports"], fpath, not_found="append")

        # configure /etc/idmapd.conf
        if self.nfssrv_info.family in ["RHEL", "CentOS"] and \
           self.nfssrv_info.version >= 7:
            rules = nfs['nfs_idmapd']
            fpath = nfs["nfs_idmapd"]["filepath"]
            configure_idmapd = self.make_conf_fn(tmp_path,
                                                 key_excludes=["filepath"])
            configure_idmapd(nfs_server, rules, fpath)

        # configure nfs_exports file
        nfs_export = nfs['nfs_export']['export']
        nfs_export_attribute = nfs['nfs_export']['attribute']
        nfs_export_net = nfs['nfs_export']['network']
        nfs_exports_info = [nfs_export, nfs_export_net + nfs_export_attribute]
        basename = os.path.join(tmp_path, os.path.basename(fpath))
        self.gen_file(basename, nfs_exports_info)
        self.scp(basename, "root@{}:/etc/exports".format(nfs_server))

        return True

    def nfs_client_setup(self):
        """NFS client function will append mount option for live migration to
        the compute nodes fstab file.

        """
        banner(self.logger, ["Doing NFS client setup"])

        fstab = self.system_info_cfg["fstab"]
        _fstab_filename = fstab['filepath']
        _nfs_server = fstab["nfs_server"]
        _nfs_mount_pt = fstab['nfs_client_mount']
        _nfs_fstype = fstab['fstype']
        _mnt_opts = fstab['attribute']
        _fsck_opt = fstab['fsck']

        # Build up the command to be run on each compute node
        fstab_entry = [_nfs_server, _nfs_mount_pt, _nfs_fstype, _mnt_opts,
                       _fsck_opt]
        fstab_entry = "    ".join(fstab_entry)
        system_util = 'echo '
        system_util_operator = ' >> '

        cmd = [system_util, fstab_entry, system_util_operator, _fstab_filename]
        rmt_cmd = " ".join(cmd)
        tmp_path = self.make_tmp_path("/tmp/fstab")

        # Before we execute the command, let's make sure we don't have this
        # entry in /etc/fstab already
        def check_fstab(host, entry):
            self.scp("root@{}:{}".format(host, _fstab_filename), tmp_path)
            base_name = os.path.basename(_fstab_filename)
            fstab_path = os.path.join(tmp_path, base_name)
            found = False
            with open(fstab_path, "r") as fstab:
                for line in fstab:
                    items = set(line.split())
                    s_entry = set(entry.split())
                    if s_entry == items:
                        found = True
            os.unlink(fstab_path)
            return found

        for host in self.computes:
            if check_fstab(host, fstab_entry):
                continue
            ret = Command(rmt_cmd, host=host)()
            if ret != 0:
                err = 'The remote command failed {0}'.format(ret.output)
                raise EnvironmentError(err)

    def finalize_services(self):
        """Looks at the [services] section of system_info,
        and performs any necessary operations"""
        banner(self.logger, ["Finalizing services"])

        svcs = self.system_info_cfg["system_services"]
        for info in self.comp_info.values():
            for svc, cmds in svcs.items():
                for cmd in cmds.split(","):
                    self.logger.info("Calling {} on {}".format(cmd, svc))
                    info.service_control(svc, cmd)

        self.selinux()
        self.mount_fstab()

    def selinux(self):
        # Check if we should enable|disable selinux
        if self.system_info_cfg["selinux"]["setenforce"] == 0:
            for cmpt in self.computes:
                msg = "Setting selinux to permissive on {}".format(cmpt)
                self.logger.info(msg)
                _ = Command("setenforce 0", host=cmpt)()

            # TODO: verify sestatus

    def mount_fstab(self):
        for cmpt in self.computes:
            self.logger.info("Mounting all file systems on {}".format(cmpt))
            _ = Command("mount -a", host=cmpt)()

            # TODO: verify /openstack is mounted

    def configure_etc_hosts(self):
        """Sets the /etc/hosts file on both the controllers and compute2 nodes

        It copies the /etc/hosts file locally, edits it, then copies the edited
        file back.  The function will also run the hostname command remotely in
        order to get the hostname from the nodes.  It compares this with the
        cdomain name from the nfs_idmapd section.  If there is a discrepancy or
        it can't retrieve the hostname, it will raise an error

        Returns a tuple of the short hostname and the full hostname
        """
        banner(self.logger, ["Setting /etc/hosts"])
        tmp_path = self.make_tmp_path("/tmp/etc_hosts")
        configure_hosts = self.make_conf_fn(tmp_path)

        # Helper to retrieve the short and long names.
        def get_host_names(hst, domain):
            res = Command("hostname", host=hst)()
            out = res.output

            try:
                hostname = out.split('\n')[0].strip()
            except Exception as e:
                self.logger.error("Unable to get the hostname from {0}".format(hst))
                raise e

            ind = hostname.find(domain)
            if ind == -1:
                msg = "host {0}: discrepancy between found domain name: {1} "\
                      "and domain in config file: {2}".format(hst, hostname,
                                                              domain)
                self.logger.error(msg)
                raise Exception(msg)

            short = hostname[:ind]
            if any(map(short.endswith, [".", "-", "_"])):
                short = short[:-1]  # remove the .,- or _

            return short, hostname

        # Get the domain from the share_storage config file
        domain_name = self.share_storage_cfg["nfs"]["nfs_idmapd"]["Domain"]

        # Get the /etc/hosts file from all the remote machines
        entries = {}
        for comp in self.computes:
            compute_entry = "{0} {1}".format(*get_host_names(comp,
                                                             domain_name))
            entries.update({comp: compute_entry})

        for comp in self.computes:
            configure_hosts(comp, entries, "/etc/hosts", not_found="append",
                            delim=" ")

        return True


if __name__ == "__main__":
    cnfs = ConfigureNFS()

    if cnfs.opts.functions:
        for fn_name in cnfs.opts.functions.split(","):
            glob_logger.info("Calling {}".format(fn_name))
            fn = getattr(cnfs, fn_name)
            fn()
    else:
        cnfs.setup()