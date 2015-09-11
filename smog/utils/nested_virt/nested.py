__author__ = 'stoner'

import smog
from smog.core.commander import Command
import smog.virt
import yaml


compute_factory = lambda kwargs: Compute(**kwargs)


def _read_config(yfile):
    """
    Takes in a config file.  The file defines the compute hosts like this::

      computes:
        - parent: 192.168.1.1
          name: rhel7-juno-1
          host: 192.168.1.2
          user: root
          vtype: vm
          passthrough: passthrough  # can be none, passthrough, or host-model
        - parent: 192.168.1.1
          name: rhel7-juno-2
          host: 192.168.1.3
          user: root
          vtype: vm
          passthrough: passthrough

    :param yfile:
    :return:
    """
    try:
        with open(yfile, "r") as st:
            cfg = yaml.load(st)
    except FileNotFoundError:
        cfg = yaml.load(yfile)

    return [compute_factory(c) for c in cfg["computes"]]


class Compute:
    def __init__(self, parent, name, host, user, vtype, passthrough):
        self.parent = parent
        self.name = name  # "rhel7-1-cve-1"
        self.host = host  # "10.8.30.223"
        self.user = user  # "root"
        self.type = vtype  # "vm"
        self.passthrough = passthrough


def _setup_nested_support(computes, permissive=True):
    """
    Ensures that the hypervisor host has nested virtualization support

    :param computes: A list of Compute instances

    :return:
    """

    bare_m = []
    for cmpt in computes:
        parent = cmpt.parent
        bare_m.append([parent, (cmpt.host, cmpt.name), cmpt])

    for bm, info_set, cmpt in bare_m:
        fnc = None
        if cmpt.passthrough == "passthrough":
            fnc = smog.virt.set_host_passthrough
        elif cmpt.passthrough == "host-model":
            fnc = smog.virt.set_host_model
        smog.virt.set_nested_vm_support(bm, info_set, fn=fnc)

        if permissive:
            host = info_set[0]
            res = Command("setenforce 0", host=host)()


def configure_nested(yfile):
    computes = _read_config(yfile)
    _setup_nested_support(computes)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Nested Virtualization setup")
    parser.add_argument("--file", type=str, help="Path to the yaml config file")
    opts = parser.parse_args()

    configure_nested(opts.file)