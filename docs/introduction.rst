Introduction
============

Smog is a both a library to explore OpenStack, and a testing tool.  It is designed to be a lower-level toolbox than
Tempest, and reuses the python-*client API rather than trying to come up with its own REST API. It should be suitable
for testing and development at the python shell, as well as any kind of whitebox or functional type of testing.

Rationale
=========

Why not Tempest?

Tempest has many shortcomings, including poor or non-existent documentation, inflexibility of configuring test cases,
and tightly coupled libraries with the tests.  The latter point has been recognized, and the community is pushing to
make tempest-lib, but until this is done, smog will step in.

It is this author's opinion that 1) too much emphasis is placed on fully automated test cases and 2) there is little
to no attention paid to white box testing.  Too many test frameworks (like Tempest) do many bad things:

- Couple the tests with the framework
- Write it so that to do anything, you must derive unittest.TestCase (or something similar)
- Focus only on black box publicly exposed API and end-to-end testing
- Don't provide developer-friendly features like log monitoring

The point of smog is that this is a toolkit used to explore nova's functionality.  Rather than require a tester to
build a derived unittest.TestCase (or some other test framework), smog is essentially a library in which a Test Engineer
or developer can use as building blocks to build their test Classes.  However, the focus of smog is that you first try
things out on the REPL.  Rather than Test Driven Development, this is kind of like Development Driven Testing.  You
explore at the python shell using smog.  But instead of using commands like:

``nova boot --flavor 1 --image cirros simple``

You instead do this

.. code-block:: python

    from smog.tests.numa import NUMA
    import smog.nova

    numa = NUMA()
    instance = numa.boot_instance(name="simple")
    if not smog.nova.poll_status(instance, "ACTIVE"):
        print("Failed to boot instance")

So, why is the more verbose python option better?  For starters, you don't need to screen scrape any output.  Secondly,
python is a lot more developer-friendly than writing bash for automation (ever debug or write log files in bash?).
And lastly, you can do a lot more than the code snippet above

.. code-block::

    discovered = numa.discover()  # discovers all instances in your deployment
    for guest in discovered:
        print(guest.host.hostname)  # prints the compute host the instance is on
        print(guest.instance.status)  # prints the status of the guest
        print(guest.dumpxml())        # gets the libvirt domain xml

Try doing that in your commands in bash.

How to install it
-----------------

There are 2 basic ways you can run smog.  The first is to clone smog somewhere on your filesystem::

    git clone https://github.com/rarebreed/smog.git

Then you can cd into the smog directory and use it directly.  For example, you can start a python shell and import
packages or modules

.. code-block:: python

    from smog.tests.numa import NUMA
    from smog.core.commander import Command

    numa = NUMA()   # assumes you have sourced your keystonerc_admin
    simple_guest = numa.boot_instance(name="simple")
    simple = numa.discover(guests=[simple_guest])
    print(simple.host.hostname)
    print(simple.dumpxml())
    simple.live_migrate()
    simple = numa.discover(guests=[simple_guest])
    print(simple.host.hostname)

When used this way, you must make sure that you are in the initial top-level smog directory.  That's so that python can
find and load all the modules and packages.  You must also make sure that you have not installed smog into your normal
site-packages directory.  A nice advantage of using it this way is during development because everything is just in
the normal smog directory.

The second way to use smog is to install it into a virtual environment.  Once you have python3 you can use smog in a
virtual environment like this::

    pyvenv vsmog
    source vsmog/bin/activate
    cd vsmog
    git clone https://github.com/rarebreed/smog.git
    cd smog
    pip install -r requirements.txt
    python setup.py install

This will setup your virtual environment in a folder called vsmog.  Clone smog into that directory, cd into the smog,
directory, and pip install the requirements file for dependencies.  Finally you can run the setup.py script to install
smog into the virtual environment.  In this case, smog will be installed to::

    vmsog/lib/python34/site-packages/smog-0.0.3-py3.4.egg/smog

That's important to know, as that's where your config files will also live.

How to use it
-------------

smog is just a set of libraries, though it has 2 main use cases

- Exploration and ad-hoc testing
- Execution of included test cases

In both cases, you will need to either setup environment variables or configure
the smog_config.yml file appropriately.

Test Configuration
------------------

Although smog is meant primarily as a low-level set of helper functions and classes, there's also some already
preconfigured tests which can be used.  These are simple unittest.TestCase derived classes which are pretty much
agnostic for what testing tool to use.

All derived unittest.TestCase classes will (or should) inherit from BaseStack. The class must define a yaml config file
name and the directory this yaml file exists in.  The yaml file will be read in by the TestCase class, and used for
any configuration.

Organization is based around a TestCase class.  One might wonder why there is a configuration file per TestCase class,
rather than one global config file.  While this can be tedious, this was done in order to allow greater granularity.
For example, some NUMA tests may require domain host-passthrough while others may not.  This would have made
a global config file that ran one test that required it and another test that didn't require it very difficult.

On the other hand, it also is burdensome to have to edit all the changing things like the compute host IP addresses over
and over again.  Work in progress is done to allow a universal config file which will be looked up by the per-test
config file.  If you look at the smog/tests/configs/skeleton.yml file, most of fields have description as to what they
are used for.

By default, smog uses the smog/config/smog_config.yml file in order to know to know general things about the
environment.  It takes this form::

    log_dir: /tmp/smog
    rdo_clones:
      base: /home/stoner/Projects/rdo
    credentials: # FIXME: This is for keystone v2
      OS_USERNAME: admin
      OS_TENANT_NAME: admin
      OS_PASSWORD: 4b6b6e5db1054988
      OS_AUTH_URL: "http://10.8.29.30:5000/v2.0/"

log_dir
  specifies where smog will place its log files
rdo_clones:
  Optional, declares the base folder where the git checked out repos of the python SDK clients are.
credentials:
  These are the same environment variables used by the python CLI tools (and are shown in the keystonerc_admin file
  created by packstack)

.. note::

    The user may also specify system environment variables rather than include them in the smog_config.yml file.
    Simply export environment variables with the same name and values.  For example::

      export OS_USERNAME=admin
      export OS_TENANT_NAME=admin
      export OS_PASSWORD=4b6b6e5db1054988
      export OS_AUTH_URL="http://10.8.29.30:5000/v2.0/"

Tests also contain their own config files, contained in smog/tests/configs.  Each TestCase class will declare a config
file that gets read in.  There is a common notation for all config files, but a TestCase is free to add additional
settings::

    baremetal:
      master1: &master1
        10.8.0.59
      master2: &master2
        10.8.0.60
    hosts:
      controller:  &controller
        parent: *master1    # If this node is a VM, parent is the baremetal host
        name: rhel7-beta-1  # If this node is a VM, The libvirt name or ID
        host: 10.8.29.30
        user: root
      compute1: *controller
      compute2:
        parent: *master2
        name: rhel7-beta-2
        host: 10.8.30.197
        user: root
    credentials: master
    cirros:
      location: "http://download.cirros-cloud.net/0.3.3/cirros-0.3.3-x86_64-disk.img"
      name: cirros-0.3.3-x86_64-disk.img
      disk_format: qcow2
    nova:
      filters:
        - NUMATopologyFilter
        - ServerGroupAffinityFilter
        - ServerGroupAntiAffinityFilter
        - AggregateInstanceExtraSpecsFilter
      nested_vm: True
      host_passthrough: True    # If using nested VM, otherwise can set this to false
      virt_type: qemu
      large_page: True
      large_page_num: 256
      large_page_persist: False
    libvirt_conf:  &libvirt_conf
      listen_tls: 0
      listen_tcp: 1
      auth_unix_ro: "none"
      auth_unix_rw: "none"
      auth_tcp: "none"
      auth_tls: "none"
    live_migration:
      enabled: True
      type: NFS
      conf: *libvirt_conf

This is a regular YAML file that also uses YAML's anchors and references.

baremetal:
  If the openstack nodes are VMs, these are the baremetal hosts the VM's live on.  They are also anchors that can be
  references in the hosts sub-dictionary
hosts:
  These are any openstack nodes that you wish to define.  They should contain the following key-value pairs:
  - parent: the baremetal master this VM lives on (set to none if this is a baremetal machine)
  - name: the short or long hostname (not IP)
  - host: the ip address of the node
  - user: the default user to be used (smog often needs to run remote commands on these nodes)
credentials:
  Have the same field as the credentials defined from smog_config.  You can also use the word smog, and it will look up and reuse the
  main smog/config/smog_config.yml credentials
cirros:
  location- this field defines a URL where a cirros image can be downloaded from
  name- the file name the downloaded file will be given
  disk_format- the format of the cirros image.
nova:  This section describes various configurations required for nova (mostly in nova.conf)
  filters- a list of filters that must be included in scheduler_default_filters
  nested_vm- If true, smog will verify that the baremetal host all the computes are running on is enabled
  host_passthrough- If true, the L1 hypervisor will have the <cpu mode='host-passthrough'> set
  virt_type- Some tests need to have the virt_type in nova set to 'kvm'
  large_page- If true, smog will enable large pages on the baremetal host
  large_page_num- How many large pages to set (only used if large_page=true)
  large_page_persist- Whether to persist the large page usage across reboots

Note that the libvirt and live_migration sections are currently unused.


What the config file is used for
--------------------------------

So what does all that configuration do?

One of the biggest problems with running a test is configuring your environment to actually run a test.  Unfortunately,
there's no really good way of separating these concerns short of assuming that the test environ is already configured
the way the test expects.

The first part of the yaml file up through credentials essentially describes your compute environment.  We need this
information so that we can run nested virtualization configuration if necessary.  It also allows us to setup large page
support, and set the libvirt xml <cpu> information, which needs to be configured properly depending on the test.  For
example, large page tests using nested virtualization requires the L1 hypervisor XML domain to have the <cpu> attribute
of mode='host-passthrough', but for vcpu pinning tests, the <cpu> node has to match exactly what the bare metal host's
libvirt capabilities shows.

Another common configuration requirement is making sure that nova.conf filters are set.  The NUMA tests pretty much
all require the NUMATopologyFilter (that includes actual NUMA topology creation, vcpu pinning, large page support and
VCPU topology creation).  For SRIOV and PCI passthrough, you need the PCIPassthroughFilter set.  That's what the nova
section of the yaml file describes under the filters key.  It is a yaml list, and any filters declared here will be
searched for in the nova.conf of all your compute nodes, and edited accordingly

Test and Development Exploration
--------------------------------

Smog was designed first around the concept of "playing in the shell".  In other words, I want to open up a python REPL,
and start experimenting.  Just like most developers welcome with fresh air the ability to avoid the edit-compile-test
cycle in python, why not do the same with testing and development?  Requiring users to come up with a derived TestCase
class and shove data or fixtures into it means that you can't really do experimental or ad-hoc testing.

The idea is that a user should be able to fire up a python REPL, and then load the modules that would be of use and
experiment.  In other words, development could proceed interactively, rather than statically while writing a test.

So smog can be used dynamically by firing up python, and importing the smog modules.  I tend to do
it like this::

    python -i -m smog.tests.numa

Doing the above will give you access to the smog.test.base classes, including the BaseStack class from which many other
classes are derived.

Two of the most useful tools in smog's toolbox are the NUMA class and the Command class.  The NUMA class is derived
from a BaseStack class, and is basically a wrapper around some of the python-*client API's, as well as some useful
functions like creating flavors, images, and booting instances.

.. code-block:: python

    from smog.tests.numa import NUMA
    import smog.nova
    from smog.core.watcher import make_watcher, ExceptionHandler
    from smog.core.logger import glob_logger as logger

    creds = {"username": "admin", "tenant_name": "admin", "auth_url": "http://192.168.1.10", "password": "smogrules"}
    numa = NUMA(**creds)
    # If OS_USERNAME, OS_TENANT_NAME, OS_AUTH_URL, and OS_PASSWORD are in your environment yuou can simply create like
    # numa = NUMA()

    # Start a log monitor.  This will run tail -f /var/log/nova/nova-* in a separate thread
    # and if it sees any python exceptions, it will close.  Log file saved
    logfile = open("nova.log", "w")
    cmd = "tail -f /var/log/nova/nova-*
    watcher = numa.monitor(cmd, "logwatcher", "192.168.1.5", ExceptionHandler, log=logfile)

    # create a large page flavor
    base_flavor = numa.create_flavor(ram=512, vcpus=1)
    lp_flavor = numa.create_large_page_flavor(flv=base_flavor, size="large")
    print(lp_flavor.get_keys())
    guest = numa.boot_instance(flv=lp_flavor, name="lp-test")  # defaults to cirros image
    if not smog.nova.poll_instance(guest, "ACTIVE"):
        logger.error("Instance did not boot successfully")
    else:
        instance = numa.discover(guests=[guest])
        logger.info(instance.host.hostname)
        logger.info(instance.dumpxml())

    logfile.close()
    watcher.close()

Running test cases
------------------

There is currently no tox or other python test discovery mechanisms in smog (eg
testrunner, nose, etc).  However, running a test case is pretty simple::

    python -m unittest smog.tests.numa

The above command would run the numa TestCase. Specifically the test runner will search for all unittest.TestCase
derived classes, and run every test method in the class.  If you want to be more specific, for example, to run only the
NUMALargePage tests, you can do this::

    python -m unittest smog.tests.numa.NUMALargePage

And you can get even more specific by specifying only the test method you wish to run::

    python -m unittest smog.tests.numa.NUMALargePage.test_large_page

Example of a Test Run using smog
--------------------------------

I'll describe from beginning to end setting up a Packstack deployment with 2 compute nodes running in a nested setup,
cloning smog, and running the NUMA tests.

The first step will be to setup a simple Packstack deployment.  This can be done by choosing a relatively beefy bare
metal system and provisioning 2 VM's (using virt-manager or some other tool like Vagrant).  I usually test with 4GB of
RAM and 4 vcpus.  Create 2 of these VM's on the baremetal machine.  Once they are deployed, give them a good hostname
with something like::

    hostnamectl set-hostname  rhel71-kilo-1.lab.scl.tlv.redhat.com

Chose one of your VM's to be the main controller node (for example rhel7-kilo-1).  From this machine, you should install
packstack::

    sudo yum install openstack-packstack
    packstack --gen-answer-file=pack.txt

Then, you can edit the answer file.  The only thing you'll need to change is the CONFIG_COMPUTE_HOST line.  Just add
the IP address of your other VM there (eg CONFIG_COMPUTE_HOSTS=10.8.29.58,10.8.29.167).  Then, run packstack with your
edited answer file::

    packstack --answer-file=pack.txt

Once you answer the root password for each system, let packstack do it's work.  Once it's done, you are ready to edit
the smog tests config files.  Every smog test class has a configuration file that it uses to get information about the
deployment under test as mentioned above for the config files.

Let's assume that the 2 IP Addresses of your VM's are 10.8.29.58 for the controller/compute node 1 and 10.8.29.167
for the 2nd compute node.  Both of these VM's are on a bare metal server whose address is 10.8.0.58

Now we can actually clone smog so that we can edit the configuration files.  First, remember that we need python3 to run
smog.  I recommend python 3.3+ as that will give you pip and pyvenv automatically.  I often just download the source
for python and compile it (just remember to install bzip2-devel and maybe readline-devel).  If you compile from source
unless you export your LIB_PREFIX differently, by default, the new python3 will install to /usr/local/bin.

Once you have python3 up and running, I recommend you use a virtual environment (especially with smog).  This is because
you do not want to clutter up your PYTHONPATH and site-packages with developmental libraries.  A virtual environment
separates your "real" python site-packages from the virtual one.  You can do this easily::

    pyvenv vsmog
    source vsmog/bin/activate
    cd vsmog
    git clone https://github.com/rarebreed/smog.git
    cd smog
    pip install -r requirements.txt
    python setup.py install

The first command will create your virtual environment.  If you have python3.3 or better, you will get pyvenv
automatically.  The second line "activates" your virtual environment.  Then we clone smog inside of the vsmog directory
and install libvirt-python.  There appears to be a bug with setuptools, because when specifying libvirt-python as a
dependency, it throws an error, but when installing from pip, it does not.  But after that, on the last line we install
smog itself.  From this point, smog is now installed in your virtual environment.  You can now run a python repl, for
example::

    python
    import smog
    from smog.tests.numa import NUMA
    numa = NUMA()

However, if you close this shell, you will need to re-activate the virtual environment again.  All you need to do is
re-run the source vsmog/bin/activate to activate the virtual environment.

Let's configure the smog/tests/config/numa_lp_config.yml file which controls the NUMALargePage class test.  How do I
know that?  If we look at the smog.tests.numa.NUMALargePage class, there is a class variable called config_file.

.. code-block:: python

    class NUMALargePage(base.NovaTest):
        """
        Tests large page NUMA support.  This test will ensure that the hypervisor
        has large memory page backing, proper scheduler filters, and host aggregates
        to ensure we can pin the correct host with the memory requirement we need
        of it.  It uses libvirt to extract an instance's domain XML to verify that
        the memory pinning was proper, as well as check the hypervisor host's
        /proc/meminfo, and the qemu process is using large pages
        """
        config_file = "numa_lp_config.yml"
        config_dir = __file__

As we can see, config_file is "numa_lp_config.yml".  The config_dir variables tells us where a folder by the name of
"config" lives.  When the test class is created, it will search for and read in path/to/config_dir/numa_lp_config.yml

So, let's edit numa_lp_config.yml with the info we need.  Because we installed smog through setuptools, it got placed
in the virtual environment.  So you can find the config files here::

    vsmog/lib/python3.4/site-packages/smog-0.0.2-py3.4.egg/smog/tests/configs/numa_lp_config.yml

.. code-block:: yaml

    baremetal:
      master1: &master1
        10.8.0.58                 # This is our bare metal server address
    hosts:
      controllers:  &controller   # The &controller is yaml's way of defining a variable name
        parent: *master1          # If this node is a VM, parent is the baremetal
        name: rhel71-kilo-1       # If this node is a VM, The libvirt name or ID (_not_ the hostname, but libvirt name)
        host: 10.8.29.58          # this is our IP Address of the controller/compute node
        user: root                # this will almost always be root
        type: vm                  # since we have a nested virtualization, put vm here, otherwise put baremetal
      computes:
        - *controller             # Here, we say that the first element in computes is the &controller we defined above
        - parent: *master1        # This is the second compute node.  It's parent is the value of &master1
          name: rhel71-kilo-2     # Again, this is the libvirt _not_ hostname (get from virsh list)
          host: 10.8.29.167       # The IP Address of the second compute noe
          user: root
          type: vm
    credentials: master           # by putting master here, we are saying look at smog/config/smog_config.yml
    cirros:                       # don't worry about this section.
      location: "http://download.cirros-cloud.net/0.3.3/cirros-0.3.3-x86_64-disk.img"
      name: cirros-0.3.3-x86_64-disk.img
      disk_format: qcow2
    nova:                         # The nova key defines a dictionary of nova configuration settings
      filters:                    # filters is a list of filter names we need to add to nova.conf
        - NUMATopologyFilter
        - ServerGroupAffinityFilter
        - ServerGroupAntiAffinityFilter
        - AggregateInstanceExtraSpecsFilter
      nested_vm: True
      cpu_mode: host-model        # large page requires the nested domain uses host model match
      virt_type: kvm              # large page requires the kvm type, qemu will not work
    libvirt_conf:  &libvirt_conf  # This section is only used if doing live-migration testing as well
      listen_tls: 0
      listen_tcp: 1
      auth_unix_ro: "none"
      auth_unix_rw: "none"
      auth_tcp: "none"
      auth_tls: "none"
    live_migration:               # and this is for live migration only as well
      enabled: True
      type: NFS
      conf: *libvirt_conf

Now that we have the configuration file setup, let's actually run the test!!  Since smog is now installed in your
(virtual environment's) site-packages, you can run it like this::

    python -m unittest smog.tests.numa.NUMALargePage.test_large_pages

Which will (only) run the test_large_pages() test method from the NUMALargePage class.  It will read in the config file
and run the test.

What happens if it fails?
-------------------------

Failure is what we want!!  In order to help make finding bugs easier, smog can automatically tail the nova log files
and look for any python exceptions.  By default smog will place the tailed log file in /tmp/smog, and it will time stamp
a file with the name of the test method being run.  For example, the above ran with the test_large_pages() test method
so smog created a time stamped log file of /tmp/smog/test_large_pages-2015-6-1-8-56-45.log

If you are curious how this mechanism works (it is much fancier than simply tailing a log file) look at the
smog/core/watcher.py file.

Currently, this feature only works for the NUMALargePage and NUMAVCPUPinningTest classes.

Documenting Tests
-----------------

Another big motivating factor to work on smog was the horrific documentation in Tempest.  There are few methods with
good docstrings, nor did the tests really document what they were doing.  Therefore, a requirement in smog is to
actually write docstrings for both the derived unittest.TestCase classes, as well as each test method in that class.
This will help developers and other users know what is going on with the test.

There is a decorator in the base module called declare() that will display the test method's docstring when it is
called.  As mentioned before, smog is meant to be useful for humans as well as for automation purposes.  Having the docs
run while the test is running makes it clear what is going on.
