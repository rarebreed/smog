from setuptools import setup
import sys
import logging

if sys.version_info < (3, 3):
    logger = logging.getLogger(__name__)
    strm_handler = logging.StreamHandler(stream=sys.stdout)
    logger.addHandler(strm_handler)
    logger.error("The smog project will only work on python 3.3 or greater")
    logger.error("Come on, python 3's been out almost 7 years now.  Get with it!!")
    sys.exit()

setup(
    name='smog',
    version='0.0.3',
    install_requires=["hy", "untangle", "toolz", "pyrsistent", "pyyaml", "libvirt-python",
                      "python-novaclient", "python-glanceclient", "python-keystoneclient",
                      "python-neutronclient", "httplib2"],
    packages=['smog', 'smog.core', 'smog.core.xml', 'smog.tests', 'smog.utils',
              'smog.utils.log_analysis', 'smog.utils.live_migration', 'smog.config',
              'smog.utils.live_migration.unittests', 'smog.unittests', 'smog.utils.nested_virt',
              'smog.utils.pci', 'smog.utils.monitors', 'smog.tests.configs', 'smog.types'],
    package_data={"": ["*.yml", "*.hy"],
                  "tests": ['configs/*.yml']},
    url='https://github.com/rarebreed/smog',
    license='Apache2',
    author='Sean Toner',
    author_email='',
    description='A tool to help explore and test Openstack Nova'
)
