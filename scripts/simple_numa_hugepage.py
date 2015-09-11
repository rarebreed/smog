"""
This is a simple script to show how to do huge page support.  It's also a useful
guide if your system is on baremetal, as the unittest assumes you have a nested
VM setup.

Here, we create a huge page flavor, and an any size page flavor. First, we create
"""

__author__ = 'stoner'

import argparse

from smog.tests.numa import NUMA
from smog.utils.rc_helper import read_rc_file
from smog.core.watcher import ExceptionHandler


parser = argparse.ArgumentParser()
parser.add_argument("-c", "--compute", action="append",
                    help="IP address for a compute node"
                         "Can be specified multiple times.  For example:"
                         "--compute=10.8.29.58 --compute=10.8.29.167")
parser.add_argument("--rc-host", help="IP address of the system where keystonerc file is")
parser.add_argument("--username", help="If --rc-host is not used, specify OS_USERNAME (if not in environment")
parser.add_argument("--tenant", help="If --rc-host is not used, the OS_TENANT_NAME")
parser.add_argument("--auth-url", help="If --rc-host is not used, the OS_AUTH_URL")
parser.add_argument("--password", help="If --rc-host is not used, the ")
parser.add_argument("--key", help="a key value pair that will be used for extra_specs"
                                  "EG hw:mem_policy=strict Can be specified multiple time",
                    nargs="+", action="append")


