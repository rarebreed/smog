"""
Simple helper to read in the packstack keystonerc_* file0
"""

__author__ = 'stoner'

import re
from smog.tests.base import read_proc_file


def read_rc_file(host, rcpath):
    """
    Reads in the rcpath file on host, and gets the relevant information needed
    for keystone authentication

    :param host:
    :param rcpath:
    :return: dict with keys of
               - username
               - tenant_name
               - auth_url
               - password
    """
    res = read_proc_file(host, rcpath)
    patterns = {"auth_url": re.compile(r"OS_AUTH_URL=(.+)\s*"),
                "password": re.compile(r"OS_PASSWORD=(.+)\s*"),
                "username": re.compile(r"OS_USERNAME=(.+)\s*"),
                "tenant_name": re.compile(r"OS_TENANT_NAME=(.+)\s*")}
    lines = res.output.split("\n")

    def find(line):
        for k, v in patterns.items():
            m = v.search(line)
            if m:
                patterns.pop(k)
                return k, m.groups()[0]

    fltr = lambda x: x is not None
    final = dict(filter(fltr, map(find, lines)))

    if patterns:
        raise Exception("Could not find key for {}".format(patterns.keys()))

    if not final["auth_url"].endswith("/"):
        final["auth_url"] += "/"
    return final
