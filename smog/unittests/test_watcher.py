__author__ = 'stoner'


import unittest

from smog.core.watcher import Watcher, Handler
from smog.core.commander import Command


class WatcherTest(unittest.TestCase):


    def test_watcher(self):
        cmd = Command("journalctl -f")
        res = cmd(block=False)
        watcher = Watcher("/var/log/messages")

        # start the freader that will put items into the que
        rdr_proc = watcher.start_reader()
        handler = Handler(rdr_proc)

        # start the consumer that will read from the que
        mntr_proc = watcher.start_monitor(handler, watcher.queue)
        rdr_proc.start()
        mntr_proc.start()
        mntr_proc.join(600)