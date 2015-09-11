NUMA Overview
=============

This document will discuss all the NUMA related features, which includes NUMA topology definition, VCPU pinning,
VCPU topolpgy, SRIOV, Large Pages, PCI Passthrough, and how to set up a test environment to try out and verify those
features.

Note that some of these features aren't exactly NUMA features per-se.  For example, Large Page is independent of whether
your test environment has multiple NUMA nodes or not.  The same is true for PCI Passthrough.  However, these features
are often to be used along with NUMA enabled systems.

What is NUMA?
-------------

First off, here's some good reading:

- http://lse.sourceforge.net/numa/faq/   # Nice FAQ
- `NUMA for Dell PowerEdge servers <http://en.community.dell.com/cfs-file/__key/telligent-evolution-components-attachments/13-4491-00-00-20-26-69-46/NUMA-for-Dell-PowerEdge-12G-Servers.pdf>`_
- `Red Hat tuning guide <https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/7/html/Performance_Tuning_Guide/chap-Red_Hat_Enterprise_Linux-Performance_Tuning_Guide-CPU.html>`_


Before even explaining how to test NUMA, we need to understand what NUMA is and why people would want to configure it.
The first thing is to think of NUMA nodes as computers within computers.  You can think of CPU's, memory, and PCIe
devices as being best buddies with its parent NUMA node, and just acquaintances with other NUMA nodes.  This is because
of locality of memory and PCI devices.  CPU's, ram and PCI devices all on the same NUMA node dont have to travel far to
pass data back and forth.  On the other hand, if a CPU running on a core on NUMA node 1 needs to access memory on NUMA
node 2, it has to go across an extra bus which will degrade performance.  This is true for all interaction whether it's
a CPU servicing an interrupt for a non-local PCI device or 2 CPU's trying to update (shared) memory.

NUMA Topologies
===============

So, a user might want to define a NUMA topology that will most efficiently accomplish the workload his compute instances
need.  Often, a user will want to combine a NUMA topology with either a vcpu pinning, large pages, or with SRIOV/PCI
passthrough.

For example, say we have a 4 NUMA node system with the following specs:

- 4 sockets, 1 socket per node
- each socket has 8 cores
- Each NUMA node has 32GB of RAM
- NUMA nodes 0 and 1 each have a NIC attached to them

The end user has a workload that he believes will require 16 cpus for optimal efficiency.  Therefore he'd need to
request 2 NUMA nodes (that being said, an end user will not know the actual hardware characteristics of the system,
rather the cloud engineer would have created a flavor specifying this...but that takes away focus from what the end
user wants).

So, the cloud engineer creates a flavor with 2 NUMA nodes.  At this point, he can decide to make everything symmetrical
and create 4x1 NUMA node flavors, but that means someone who needs a bigger node will suffer in performance.  So the
engineer decides on creating 1 high performance flavor by giving it 2 NUMA nodes and therefore allowing up to 16 cores
to be used.

However, vcpus (by default) are allowed to float across NUMA nodes (and even across compute nodes).  Let's say for
example a user has an application that uses 8 threads, and thus, he would like to request at least 8 vcpus.  While a
simple 2 NUMA node topology will work, there's no guarantee that 4 of the VCPUs wont float across to the other NUMA
node.  If that happens, if the threads are sharing some data structures, there will be penalties due to more frequent
cache misses as well as actually having to go across an extra memory bus to DMA memory.  In that case, not only would
the user want a 2 NUMA node system, he would ideally want to pin 8 vcpus to a single NUMA node.


Setting up a NUMA Test Environment
----------------------------------

Actually creating or verifying that your hypervisor host is NUMA enabled is the hardest thing to do.  Especially
if you are creating "fake" multi-numa node test environments.  So before we even discuss what NUMA is, we need to
be able to create a test environment to do our tests.

Nested Virtualization
#####################

Nested virtualization describes the scenario where the compute nodes are themselves Virtual Machines.  To make things
easier, we will call the baremetal server the L0 machine (or hypervisor), the L1 machine (or hypervisor) is a VM that
is running on L0.  We will install a nova compute service node on the L1 machine.  The L2 machine is therefore any
virtual machine instance that was created on the L1 hypervisor.

You can follow the directions here to setup nested virtualization manually:

https://kashyapc.fedorapeople.org/virt/procedure-to-enable-nested-virt-on-intel-machines.txt

There's also an automated way to provision nested support using smog.  First, you will need to have a small yaml
file that looks something like this::

    computes:
        - name: rhel7-juno-1          # The libvirt name (as shown from virsh list run on the L0 host)
          host: 192.168.1.2           # The IP address of the L1 hypervisor
          parent: 192.168.1.1         # The L0 IP address that this L1 VM is running on
          user: root
          vtype: vm
          passthrough: host-model     # Must be one of host-model, passthrough or None
        - name: rhel7-juno-2
          host: 192.168.1.3
          parent: 192.168.1.1
          user: root
          vtype: vm
          passthrough: host-model

This defines a list of hosts that must be configured.  Each compute node that will be configured will define its
libvirt name (if you run virsh list on the baremetal host, you will see the actual names), the IP address of the compute
node, and the L0 (baremetal) IP address that this compute is running on.

Once you have a yaml file like this, you can setup nested virtualization with the smog.utils.nested_virt.nested
script.  You can run it like this::

    python -m smog.utils.nested_virt.nested --file /path/to/compute.yml

This will verify that the baremetal host and the L1 hypervisors have the necessary bits to do Nested VMs


How to tell if a system is NUMA enabled
---------------------------------------

The easiest way to do this is to use a utility called numactl.  You can run it like this::

    numactl -H

If you run this on a multiple NUMA system, you will see some hardware characteristics of the system displayed.  For the
SRIOV or PCI passthrough tests, you may also need to determine which PCIe devices belong to which numa node.  In that
case, you will need to use another tool called lstopo or lstopo-no-graphics (which come with the hwloc package)

Another useful utility, and required to ensure that your guest which does PCI passthrough or SRIOV was created on the
right node, is the lstopo utility.  This utility (which comes in the hwloc package) will display, among other things,
the NUMA layout of PCI devices.  This is how you can tell what node a PCI device "belongs" to.  You can run it like::

   lstopo-no-graphics

If you run lstopo, it will bring up a GUI, but I actually find the command line version easier to read and the GUI will
not be usable for automation.

Creating a fake multi-NUMA system
---------------------------------

The hard part about creating a NUMA topology is finding a real NUMA enabled system.  It is possible to create a "fake"
multiple NUMA node system, but it is preferable to use a real NUMA system.

To create a fake multiple NUMA node system you can do the following.  You can take a nested L1 hypervisor, and edit the
domain xml (from the baremetal machine) like this (make sure the L1 host is down first)::

  <cpu mode='host-passthrough'>
    <numa>
      <cell id='0' cpus='0,1'/>
      <cell id='1' cpus='2,3'/>
    </numa>
  </cpu>

The above would define the L1 hypervisor to have two cells (synonymous with a NUMA node).  The first node (cell 0)
would have 2 CPUs, and the 2nd node (cell 1) will have another 2 CPUs.  You may also specify memory if you wish to have
an "imbalanced" NUMA architecture.

Once the domain xml has been edited (with virsh edit or some other tool), restart the L1 host, and it will be a "fake"
multi-NUMA node host now.  Note that things like PCIe or memory affinity will be unaffected by this fake system.

Creating a NUMA topology
------------------------

Assuming you either have a real NUMA system, or a fake one created above, you can now define a NUMA topology.  To do
this, you create a flavor with a requested NUMA topology (or a glance image, with the image properties set).  There is
already a (simple) automated test case in smog which will create a single NUMA node.  Note that for this test, there is
a dependency of numactl on the system being tested.

Manual Creation of NUMA Topology
################################

If you need to do this manually, you can do it like this::

    nova flavor-create numa-topo-flv 100 4096 20 8
    nova flavor-key numa-topo-flv "hw:numa_nodes=2" "hw:numa_policy=preferred"
    nova boot --flavor 100 --image cirros numa-test

As you can see, the only real "trick" to creating a NUMA topology defined instance is in creating the Flavor.  However,
there are a couple of intricacies that should be considered.  The first is (for testing purposes) determining how many
NUMA nodes exist on a system, how many PCPUs each node has, and how much memory each node has.

Discussion of the test
######################

If you look at smog.tests.numa.NUMATopologyTest, you can see what is going on.  Despite the test case being simple, the
actual code is somewhat involved.  In essence, a function is run that calculates how many nodes and how much memory
is available for each NUMA node.

Once we know how many nodes and how much memory there is, we can create a flavor that defines the desired NUMA topology.
To actually create the flavor which does this, we set some extra specs:

.. code-block:: python

    @flavor_comp
    def create_numa_topo_extra_specs(self, flv=None, numa_nodes=1,
                                     numa_mempolicy="preferred",
                                     specs=None):
        extra_specs = {"hw:numa_nodes": numa_nodes,
                       "hw:numa_policy": numa_mempolicy}

        if specs is not None:
            extra_specs.update(specs)
        return extra_specs

create_numa_topo_extra_specs is a method in the NUMA class.  You pass it a Flavor object, the number of numa nodes you
want for the topology, and a memory policy which can be either "strict" or "preferred".  It can also take a specs dict
which is a dictionary for any other extra_specs key=value pairs you might want.  For example, you might want to chain
together a NUMA topology defined flavor with a vcpu pinned flavor, in which case, you can add the extra_specs defining
the pinning in the specs keyword argument.

This function is a little deceptive and sneaky though due to the decorator.  The flavor_comp decorator "intercepts"
this function call (like all decorators do).  Although this function by itself returns a dictionary of the extra_specs,
the decorator intercepts this return value, and instead returns the flavor itself.  It does this so the decorator
can handle the case where no Flavor object is passed in, and to chain together multiple calls.

.. code-block:: python

    # Create a 2 NUMA node topology with 8 pinned vcpus
    start_flv = numa.create_flavor(ram=4096, vcpus=8)
    final_flv = numa.create_vcpu_pin_flavor(flv=numa.create_numa_topo_extra_specs(flv=start_flv, numa_nodes=2)
                                            thread_policy="isolate")
    print(final_flv.get_keys())

If you need to do this manually, you can do it like this::

    nova flavor-create numa-topo-flv 100 4096 20 8
    nova flavor-key numa-topo-flv "hw:numa_nodes=2" "hw:numa_policy=preferred" "hw:cpu_policy=dedicated" "hw:cpu_thread_policy=isolated"

Booting an instance and verification
####################################

Booting an instance is like booting any other instance::

    nova boot --flavor 100 --image cirros numa-test

Or if you are doing it programmatically from smog

.. code-block:: python

    img = numa.get_image_name("cirros")
    guest = numa.boot_instance(flv=final_flv, img=img, name="numa-test")

Verification is fairly simple (once you know how to do it).  The smog.tests.numa.NUMATopologyTest.test_simple
already does the verification for you.  You can see the code snippet

.. code-block:: python

    # get the instance matching our NUMA topology, and get its domain
    # xml.  Look for the <cpu> element.  It should look something like this
    # for a single NUMA node::
    #   <cpu>
    #     <topology sockets='4' cores='1' threads='1'/>
    #       <numa>
    #         <cell id='0' cpus='0-3' memory='2097152'/>
    #       </numa>
    #   </cpu>
    for guest in guests:
        dump = guest.dumpxml()       # handy function that gets the libvirt domain xml
        root = et.fromstring(dump)   # convert this xml string into an XML data structure
        print(dump)

        # Look for the <numa> element inside <cpu>
        numa = [child for child in root.iter("cpu") if child.tag == "numa"]
        self.assertTrue(numa, msg="domain xml did not have <numa> element")
        cell = [child for child in numa[0].iter() if child.tag == "cell"]
        self.assertTrue(cell)

guests is a list of Instance objects in smog.  The Instance class is very useful, as it can determine for you what host
the instance is running on (very useful when you have more than one compute node) and also a lot of helper libvirt
functionality.  You can see the later in it's dumpxml() method call, which creates a string representation of the
libvirt domain xml.  The rest of the code is searching through the XML element (as shown by the comment section).
The comment shows what a single NUMA node representation (with 4 vcpus) would look like.  The <cell> element is really
what we want::

    <cell id='0' cpus='0-3' memory='2097152'/>

As this tells us we have (for NUMA node 0...cells and nodes are synonymous) that it has 4 vcpus and 2097152kb of memory.

VCPU pinning notes
==================

What is VCPU Pinning?
---------------------


By default, the nova scheduler can assign a vcpu used by an instance to "live" on any pcpu on the hypervisor host.
This can be undesirable for performance reasons.  For example, suppose you have an instance that defines 2 VCPUs, and
you have a NUMA enabled system.  It is possible for libvirt to have one vcpu "float" to a PCPU that is on a different
NUMA node than the other VCPU.  This can result in performance degradation as any shared memory (for example threads)
or interprocess communication will have to go through an extra bus.  Therefore, we'd like a way to specify that for
a flavor (or image property) to pin vcpu(s) to pcpu(s) and ideally on the same NUMA node.

Sometimes, VCPU pinning occurs implicitly.  For example, when making a VM with PCI Passthrough, the VM's cpus are pinned
to the node where the PCIe device resides.  There's no need to explicitly pin any instances in that case.

Use kvm as virt_type
--------------------

By default, /etc/nova/nova.conf has virt_type=qemu.  This should be changed to virt_type=kvm

If this is not done, you will see that trying to pin more than 2 vcpus will fail.  Note that smog tests will have
as part of their configuration file a field to specify what the virt_type should be.


Nested VM support
-----------------

If you do not have this set up, you might get an error booting even a regular instance with the latest libvirt.  The
error will be about an unsupported OS type 'hvm'


VM Compute hosts Setup
----------------------

Manual
######

If your compute host is itself a virtual machine, not only do you need to follow the nested vm document listed above,
you also need to make sure that the xml configuration for libvirt is correct.  The one created by virt-manager was
incorrect, and should be changed accordingly. First, get your bare metal host's native model type by running::

    virsh capabilities

Look the in the <cpu> section for a <model>.  That is the model you need.  Now, edit your compute host domain.  You can
run::

    virsh list

On the baremetal host to determine which one is your compute host.  Now you can edit that domain's xml configuration
like this::

    virsh edit X  # X is the domain id for your compute host node

This will open up (by default) a vi editor to edit the xml config.  Look for the <cpu> section.  It should look
something like this::

    <cpu mode='custom' match='exact'>
      <model fallback='allow'>SandyBridge</model>
      <feature policy='require' name='vmx'/>
    </cpu>

Where "SandyBridge" is whatever <model> you found from earlier.  Do this for all the compute hosts which are VM's on
your bare metal machine.  Then, reboot your bare metal system.

If you don't do this, then what I observed was that booting an instance, even without pinning, would bring down one of my
nova-compute services, but there would be no errors in the log and the instance state would just say BUILD, spawning.


Automated
#########

Because this is error prone, there is a way to automate this through smog.  If you take a look at the nested.py
script from smog.utils.nested_virt package, you will see how to do this.  There's also an example of how to do this
in the smog/scripts/simple_vcpu_pinning.py script.  If you wish to use the nested.py script, you should use a yaml
file that contains the information described in that script.  The yaml file is described much like test config files

.. code-block:: yaml

    computes:
        - host: 192.168.1.2         # IP address of the L1 compute node
          name: rhel7-juno-1        # The libvirt domain name of the L1 compute node (see virsh list)
          parent: 192.168.1.1       # The bare metal (L0) machine the hypervisor "lives" on
          user: root
          vtype: vm
          passthrough: passthrough  # can be none, passthrough, or host-model
        - parent: 192.168.1.1
          name: rhel7-juno-2
          host: 192.168.1.3
          user: root
          vtype: vm
          passthrough: passthrough  # passthrough sets libvirt mode=host-passthrough, host-model matches baremetal

This yaml file gets read in by the script, and the yaml is converted to a list of dictionaries, which in turn, each
dictionary describes a Compute object.  The compute.passthrough defines one of three choices: none, passthrough or
host-model.  If passthrough is chosen, the libvirt xml format is set to use cpu host-passthrough mode.  If it is set
to host-model, the libvirt domain xml for the L1 hypervisor is changed to match the libvirt capabilities of the bare
metal machine.

When doing large page tests, you should passthrough to passhtrough, and for vcpu-pinning tests, you should change it to
host-model.  If you don't, neither of these tests will work.

The script will then ensure that nested virtualization is enabled (both for the baremetal host, as well as the L1
compute nodes)::

    # Assuming you have your file in /tmp/compute.yml
    python3 -m smog.utils.nested_virt.nested --file=/tmp/compute.yml

The other way to do this is to look at the code in smog/scripts/simple_vcpu_pinning.py, which instead of using a yaml
files, gets answers from argparse, and then creates the Compute objects accordingly.

Setting up nova.conf
--------------------

**Manual Notes**
Make sure that you have the appropriate scheduler_default_filters enabled.  Make sure that the following are also
enabled::

  AggregateInstanceExtraSpecsFilter,NUMATopologyFilter

Add those to the scheduler_default_filters if they are not already there, and restart the nova scheduler service

Setting up an Aggregate group
-----------------------------

Aggregate groups are not necessary for testing NUMA features, but they are commonly used because they allow for a
relatively simple way to partition compute nodes into groups based on metadata.  This allows you to make sure that
a desired flavor type will only boot on a certain compute node.  This is useful when testing things like VCPU pinning
, large page support, or any test in which you want one category of an instance (say for same large page supported
instances) to boot on a known host(s) but not a flavor in which metadata for the flavor doesn't match the metadata for
the Aggregate Group

Manual-Notes: Booting a pinned instance
---------------------------------------

Setting up an aggregate group is an easy way to partition compute hosts so that you can match an aggregate group to a flavor.
In essence, you create an aggregrate group with some metadata, for exampled pinned=true.  Then, you add one or more compute
service nodes to this aggregate group.  Then, you can create a flavor that has matching extra_specs metadata.  When you boot
an instance with this flavor, the scheduler will match up the extra_specs metadata with the aggregate group metadata.  For
example::

  nova aggregate-create cpu_pinning                 # creates an aggregate group (defaults to nova availability zone
  nova aggregate-set-metadata 1 pinned=true         # set metadata for the aggregate
  nova aggregate-add-host 1 rhel71-kilo-1.lab.eng.rdu2.redhat.com  # add host to the aggregate group

  nova flavor-create pinned.medium 6 2048 20 2      # create a new flavor with id 6, 2048 RAM, 20GB disk, and 2 vcpus
  nova flavor-key 6 set "hw:cpu_policy"="dedicated" # add an extra_specs key of hw:cpu_policy=dedicated
  nova flavor-key 6 set "aggregate_instance_extra_specs:pinned"="true"  # use the aggregrate pinned=true

Make sure that you boot as a non-admin user.  Using the above created flavor with id 6::

  nova boot --image fedora --flavor 6 pinned_test

Verifying the instance is pinned
################################

To verify that the instance actually has pinned vcpus, check the <cputune> element from the domain xml.  The easiest
way to do this is to look at the libvirt instance::

  nova show pinned_test   # look at the OS-EXT-SRV-ATTR:instance_name field, and what host it's running on
  virsh dumpxml instance-00000021  # running this from the compute node the instance is running on

From the xml that is output, check the output of the <cputune> which may look something like this:

.. code-block:: xml

    <cputune>
      <shares>1024</shares>
      <vcpupin vcpu='0' cpuset='0-3'/>
      <emulatorpin cpuset='0-3'/>
    </cputune>

Automated-Notes: Booting a pinned instance
------------------------------------------

It is a fairly common need to create mutually opposing groups for testing (for example, pinned=true vs pinned=false) so
smog has a function to help automate this

.. code-block:: python

    from smog.tests.numa import NUMA
    import smog.nova
    numa = NUMA()     # assumes your environment variables are set
    pos_agg, neg_agg, pin_host = numa.create_aggregate_groups("pinned")

    base_flv = numa.create_flavor(ram=512, vcpus=2)
    pin_flavor = numa.create_vcpu_pin_flavor(flv=base_flv)
    guest = numa.boot_instance(flv=pin_flavor, name="pin-test")  # use cirros img default
    if not smog.nova.poll_for_status(guest, "ACTIVE"):
        sys.exit(1)    # failed
    # Make sure we booted on the pin_host ip address
    instance = numa.discover(guests=[guest])[0]
    assert instance.host.host == pin_host
    print(instance.dumpxml())  # check that we have the proper layout

NUMAVCPUPinningTest Notes
-------------------------

The example above is something you can do in the python shell.  However, there's already a smog test for this in
smog.tests.numa.NUMAVCPUPinningTest.test_simple_vcpu_pinning. However, smog already has a basic test for VCPU pinning
using nested virtualization.  It can be configured through the config file

**smog/tests/configs/numa_vcpu_config.yml**

Once you have created two nested VM's, and edited the configuration file appropriately, you can run it

VCPU Topology Notes
===================

Where vcpu pinning tests are about binding a guest's virtual CPU to a host hypervisor's physical
CPU, the VCPU topology tests are about how a guest's cpu topology is created.  For example, a real
host might have 2 sockets with 4 cores each yielding 8 CPU's.  Normally, libvirt will create 1 socket
with 1 core for each guest.  So in the host above, it would actually be creating 8 1 socket/1 core
virtual CPUs.  A guest that requested 4 vcpus would therefore get 4 1s/1c CPUS.  This is problematic
for licensing issues on some OS's.

virt type
---------

It appears that this will work on qemu virt-type, so nothing needs to change in nova.conf

filters
-------

There also does not appear to be a need to add the NUMATopologyFilter for this either.


Large Page Support
==================

Some good reading material:

https://lwn.net/Articles/374424/
http://duartes.org/gustavo/blog/post/page-cache-the-affair-between-memory-and-files/
http://linuxgazette.net/155/krishnakumar.html


To understand this feature, it's first necessary to understand how memory is used by the linux kernel.  The first
important concept to understand is the distinction between virtual memory addresses and physical memory addresses.
In order to provide isolation between processes running in the OS, each process believes that it has all the memory
available and doesn't know anything about the memory address space of any other process.  Moreover, it thinks it has
more memory than is physically available on the system.

However, in order to actually retrieve contents of memory, it's necessary to do a translation of virtual addresses to
physical addresses.  Since each process has it's own world view of memory (and therefore its own virtual address space)
there must be a per-process way of mapping virtual memory address to physical addresses.  This is where page tables
come in.

Because this is such a critical component (virtually all computer actions require loading or storing to memory) it must
be blazing fast.  The kernel can't do this alone in software.  It gets help from the MMU (Memory Management Unit).  This
specialized hardware works at a granularity of memory in terms of pages rather than bytes or words.  Typically, on 64bit
systems, the page size is 8k by default.  The kernel has a software reflection of the page tables and it uses typically
a 3-level page table lookup.  So page-tables are an in-memory representation of virtual address to physical addresses.
However, because these mappings are stored in-memory, they require going out to memory to fetch them!!  So another
enhancement is the use of TLB (Translation Lookaside Buffer) which is a memory cache on the CPU that holds a small
subset of the most recently looked up virtual addresses.  If a request for a virtual address is made, it will look in
this cache first.

So why would having pages larger than the default 8k be of any benefit?  Looking up the mapping from virtual address
to physical addresses through the page tables is still a (relatively) expensive affair, so the TLB is searched for
first.  By having a larger page size, because the page is larger, it holds a larger memory range.  Therefore TLB
misses are reduced.

Remember that almost all of the NUMA related features in nova are all about performance.  Large Page support in
particular tries to reduce memory access times.

..  code-block:: python

    from smog.tests.numa import NUMA
    from smog.nova import poll_status

    creds = {"username": "admin", "password": "5855e74ef8bb48c7", "tenant_name": "admin",
             "auth_url": "http://10.8.30.77:5000/v2.0/"}
    extra_specs_2_socks = {"hw:cpu_sockets": 2}
    numa = NUMA(**creds)
    flavor = numa.create_flavor(vcpus=2, name="2socket-guest", specs=extra_specs_2_socks)
    img = numa.get_image_name("cirros")

    name = "2sock-test"
    instance = numa.boot_instance(img, flavor, name=name)
    active = poll_status(instance, "ACTIVE", timeout=300)
    if not active:
        raise Exception("Instance did not boot successfully")

    discovered = numa.discover()
    for guest in discovered:
        if guest.instance.name == name:
           server = guest
           break
    else:
        raise Exception("Unknown error, could not find named guest"

    print server.dumpxml()  # inspect the <cpu> element

.. automodule:: smog.tests.numa
   :members:
