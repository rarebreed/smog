__author__ = 'stoner'

import os
import platform
import yaml
from smog.core.logger import glob_logger
from smog.tests import get_smog_dir


def get_path(f_wanted, curr_dir=None):
    if curr_dir is None:
        curr_dir = os.path.dirname(__file__)
    listing = os.listdir(curr_dir)
    if f_wanted in listing:
        return os.path.join(curr_dir, f_wanted)
    else:
        full = [os.path.join(curr_dir, d) for d in listing]
        dirs = filter(lambda x: os.path.isdir(x), full)
        for d in dirs:
            fullpath = os.path.join(curr_dir, d)
            res = get_path(f_wanted, curr_dir=fullpath)
            if res:
                return res


class Config(object):
    fields = ["masters", "hosts", "smog", "cirros", "nova",
              "libvirt_conf", "live_migration"]

    def __init__(self, opts, **kwargs):
        # I could have looped through fields and setattr, but I'm doing it this
        # way to help the IDE know what the fields are
        print("In Config init: ", kwargs)
        if set(kwargs.keys()) != set(self.fields):
            raise AttributeError("keys must be in {}".format(self.fields))

        # Set a field in self, so that there is eg
        # self.masters = kwargs["masters"]
        for fld in self.fields:
            setattr(self, fld, kwargs[fld])

        # Derived
        self.controllers = self.hosts["controllers"]
        self.computes = self.hosts["computes"]
        self.nova_filters = self.nova["filters"]
        self.smog = None
        # master credentials
        if self.smog and "smog_config.yml" in self.smog:
            # Load this file from ../../config
            self.smog = yaml.load(self.smog)

        self.finish(opts)

    def __repr__(self):
        fn = lambda x: "{}={}".format(x, getattr(self, x))
        flds = ",".join(fn(fld) for fld in self.fields)
        form = "{}({})".format(self.__class__, flds)
        return form

    def finish(self, opts):
        """
        In the skeleton.yml file, we have placeholders like <host>.  We will
        fill these in according to the opts object
        """
        def fn(field):
            opt = getattr(opts, field)
            if opt is None:
                return
            info = opt.split(",")
            for i, host_pair in enumerate(info):
                h_name, h_ip = host_pair.split(":")
                obj = getattr(self, field)
                if isinstance(obj, list):
                    obj[i]["name"] = h_name
                    obj[i]["host"] = h_ip
                else:
                    obj["name"] = h_name
                    obj["host"] = h_ip

        for fld in self.fields:
            glob_logger.info("Setting {}".format(fld))
            if fld == "masters":
                if opts.masters is not None:
                    masters = opts.masters.split(",")
                    mstr = "master{}"
                    master_d = {mstr.format(i): master
                                for i, master in enumerate(masters, 1)}
                    self.masters = master_d
            elif fld == "hosts":
                print("Getting controllers info...")
                fn("controllers")
                print("Getting computes info ...")
                fn("computes")
            elif fld == "smog":
                if opts.smog is not None:
                    self.smog = yaml.load(opts.smog)
            elif fld == "nova":
                self.nova["nested_vm"] = opts.nova_nested
                self.nova["host_passthrough"] = opts.nova_passthrough
                self.nova["virt_type"] = opts.nova_virt_type
                if opts.nova_filters is not None:
                    self.nova_filters = opts.nova_filters.split(",")
        print(self)


def get_args(args=None):
    major, minor, micro = platform.python_version_tuple()
    if minor == '6':
        from optparse import OptionParser as Parser
        desc = 'YAML Config Setup Util.  All of the command line ' \
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
    add_opt("--config", help="Mandatory. must be supplied.  Path to config")
    add_opt("--controllers",
            help="comma separated list of IP address of the controllers/compute"
                 " nodes")
    add_opt("--computes",
            help="a comma separated list of domain_name:ip_address.  For ex."
                 "--computes=rh7-juno1:192.168.10.1,rh7-juno-2:192.168.10.2"
                 "Note that domain name is the libvirt domain name, not the"
                 "host name")
    add_opt("--masters", help="comma separated ip addresses of hypervisors")
    add_opt("--nova-filters", help="comma separated list of filters to apply")
    add_opt("--nova-passthrough", type=bool, default=False,
            help="boolean, choose to set domain xml to use pass through mode "
                 "defaults to False")
    add_opt("--nova-nested", default=True, type=bool,
            help="boolean to enable nested support on the")
    add_opt("--nova-virt-type", default="qemu", choices=["kvm", "qemu"],
            help="one of qemu|kvm.  Defaults to qemu")
    add_opt("--smog", help="The absolute path to the smog_config.yml")
    add_opt("--output", help="Where to generate the new yaml file")
    add_opt("--auth-url", help="The keystone auth url")
    add_opt("--password", help="keystone admin password")
    opts = parse_args(parser)

    def check_env(field, key):
        val = getattr(opts, field)
        glob_logger.info("Value of opts.{} is {}".format(field, val))
        if val is None and key in os.environ:
            msg = "Setting opts.{} to {}".format(field, os.environ[key])
            glob_logger.info(msg)
            setattr(opts, field, os.environ[key])

    for fld, key in zip(["controllers", "computes", "masters", "auth_url",
                         "password"],
                        ["SMOG_CONTROLLERS", "SMOG_COMPUTES", "SMOG_MASTERS"
                         "OS_AUTH_URL", "OS_PASSWORD"]):
        check_env(fld, key)

    print("========================")
    print(opts)
    print("========================")
    return opts


def config_factory(opts):
    glob_logger.info("Creating Config object")
    with open(opts.config) as cfg:
        txt = cfg.read()
        config = yaml.load(txt)
    cfg = Config(opts, **config)
    return cfg


def generate_yaml():
    opts = get_args()
    config = config_factory(opts)

    output_dir = "./testing.yml"
    if opts.output is not None:
        output_dir = opts.output

    form = yaml.dump(config)
    with open(output_dir, "w") as yml:
        yml.write(form)

    return config


if __name__ == "__main__":
    generate_yaml()

