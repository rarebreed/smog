.. automodule:: smog.tests.sanity
   :members:

Sanity Overview
===============

A collection of TestCases and some helper classes for basic sanity tests (short
execution tests with basic testing)

Live Migration
--------------

One of the most important parts to the sanity test plan is doing live migration testing, as this is considered to be
a often used feature that customers would want to do.  In essence, a live migration is transferring a running guest
on one compute node hypervisor, to another hypervisor on another host.

There are 2 basic ways to perform a live migration.  The first is to not specifically specify a host, and the nova
scheduler will determine the best fit host for the requested guest to move to.  This is the preferred mode to test
because generally, an end user will not know the hostname or IP address of a specific physical host to transfer a guest
to, and secondly, because this mode is a test of the scheduler to determine if it can correctly chose an appropriate
host given the requirements of the guest VM.  The second mode is to specify the actual physical host to move the guest
to (and if the host is incapable of hosting the VM due to memory constraints, or other requirements like NUMA, then the
migration will fail).

Configuring a live migration test environment
---------------------------------------------

As long as there is network shared storage, then nova can do live migrations.  It will support NFS, gluster, iscsi and
ceph storage systems at the moment.  Smog currently has only worked with NFS as a backend.  Creating a shared NFS
system is not trivial, and therefore one of the utils packages does just this.

If you look at the smog.utils.live_migration package, you will see a module inside also called live_migration.  This
module can be run as a script itself.  It can be run like this::

    python3 -m smog.utils.live_migration.live_migration --controller=xxx.xxx.xxx.xxx --domain=some.domain.com \
    --computes=xxx.xxx.xxx,yyy.yyy.yyy.yyy

The script does have a limitation in that the NFS server will always be the controller, and the controller is also
assumed to be a compute node.  In other words, there's no way as of yet, to specify a 3rd system to be used only as the
NFS server itself.  That means you need at least 2 compute nodes for this setup.

Note that it is also important to give the compute nodes meaningful hostnames.  When you do a default install of RHEL 7
for example, you will get a hostname like dhcp-8-20-129 which is no good.  So, when preparing your compute nodes, make
sure that they have a good hostname (I tend to give mine a name like rhel71-kilo-1.some.domain.com and
rhel71-kilo-2.some.domain.com).  You can do this using::

    hostnamectl set-hostname rhel71-kilo-1.some.domain.com

The "some.domain.com" is important and is your domain.  When you run the live_migration module, make sure that the
--domain option matches this part of your hosts (and as another limitation, all compute node hosts must therefore be on
the same domain).

Performing a live migration
---------------------------

Actually performing a live migration is trivial.  All you need to do is boot an instance, and then run a live migration
command

.. code-block:: python

    import sys
    from smog.nova import poll_status
    from smog.tests.base import BaseStack
    from smog.utils.rc_helper import read_rc_file
    creds = read_rc_file("192.169.10.10", "/root/keystonerc_admin")
    base = BaseStack(**creds)

    guest = base.boot_instance(name="lm_test")  # use tiny flavor and cirros image
    if not poll_status(guest, "ACTIVE"):
        print("something happened to guest")
        sys.exit(1)

    current = base.discover(guests=[guest])[0]
    print(current.host.hostname)   # the current host
    guest.live_migrate()           # let the scheduler decide where to go to
    if not poll_status(guest, "ACTIVE"):
        print("got stuck migrating")
        sys.exit(1)

    current = base.discover(guests=[guest])
    print(current.host.hostname)   # make sure that the guest is on a new hostname now

The only real trick to live migration is setting up your test environment.  Whether you are using NFS, gluster, ceph or
iscsi, the live migration is the same.

Verifying it was successful
---------------------------

To ensure the migration was successful, we should make sure that

- The instance actually migrated to a new host
- The host can actually support the VM's requirements

Checking if the VM is on a new host is easy in smog.  The smog.tests.base.Instance class was designed around the idea
to know what host a VM is residing on.  The easiest way to create Instance objects is to use the BaseStack object's
discover() method.  This function will query openstack for the instances on the tenant (much like nova list), but it
will generate a list of Instance objects.  These Instance objects know what physical host they are on and also have a
helper function to generate the domain XML.  Note that once you perform a migration (or evacuation) the Instance object
is not updated.  That's why the sample code above runs the discover() method twice and checks the hostname each time.

The second aspect, to check if the host is capable of handling the VM instance, is more tricky.  For example, let's say
you have a VM on one instance on a very large system that has 32 cores.  The instance uses 16 of them and they are
pinned.  If the only other compute host node is a machine with 8 physical cores, then this migration should fail.
That's just one example, so trying to think up all the permutations is difficult and should be done as individual tests
where you can constrain your test environment.