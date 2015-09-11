__author__ = 'stoner'

import multiprocessing

from smog.core.logger import glob_logger
from smog.tests.sanity import NovaSanity
from smog.core.watcher import Handler
from smog.core.exceptions import ArgumentError


class RegexHandler(Handler):
    """
    This is an example class for using a Handler derived type that can be
    used by a Watchdog
    """
    def __init__(self, rdr, regexp):
        super(RegexHandler, self).__init__(rdr)
        self.line = None
        self.res_q = multiprocessing.Queue()
        self.pattern = regexp
        self.fn = getattr(self.pattern, "search")
        self.counts = None

    def __call__(self, line):
        m = self.fn(line)
        if m:
            self.found += 1
            self.res_q.put(("Success", line))
            glob_logger.info("Found a match: " + line)
            if self.counts is not None and self.found >= self.counts:
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


class Monitor(object):
    def __init__(self, host, lfile, creds, logger=glob_logger):
        self.logger = logger
        self.base = NovaSanity(**creds)
        self.file = lfile
        self.host = host

    def monitor(self, pattern, mon_name="default"):
        # Create a monitor that will look for when the config drive is created.
        # We need to know where our initial boot object is first
        self.logger.info("Creating log monitor")

        cmd = "tail -f {}".format(self.file)
        watcher = self.base.monitor(cmd, mon_name, self.host,
                                    RegexHandler, pattern)
        return watcher


if __name__ == "__main__":
    name = "admin"
    creds = {"username": name, "tenant_name": name,
             "password": "fc66d692ada14441", "auth_url": "http://10.8.29.108:5000/v.2.0/"}
    mon = Monitor("10.8.29.108", "/var/log/nova/nova-*.log", creds)
    mon2 = Monitor("10.8.29.108", "/var/log/nova/nova-api.log", creds)
    import re
    patt = re.compile(r"migrate|migration")
    watcher = mon.monitor(patt, mon_name="compute")
    #print "Starting second monitor"
    #watcher2 = mon2.monitor(patt, mon_name="api")
    import time
    now = time.time()
    end = now + 6000
    while time.time() < end:
        time.sleep(1)