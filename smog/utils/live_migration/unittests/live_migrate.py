__author__ = 'stoner'

from smog.utils.live_migration.live_migration import distro_factory
import unittest

host = "10.35.163.59"


class TestLiveMigration(unittest.TestCase):
    def test_factory(self):
        info = distro_factory(host=host)
