Utilities
=========

Quite often, one of the biggest challenges in testing is simply setting up your test environment.  While Khaleesi is a
nice tool and could be used as a setup tool for configuring or provisioning the environment, smog chose to simply
write some helper scripts to do what needed to be done.

Live Migration
--------------

The original tool that was required was setting up a NFS environment for live migration testing.  It's currently limited
to setting up NFS, but hopefully in the future, a backend for ceph, gluster or iScsi can be made.  Using the script
is relatively straight forward::

    python3 -m smog.utils.live_migration.live_migration --controller=192.168.1.1 --computes=192.168.1.1,192.168.1.1

Nested Virtualization
---------------------

Another common requirement was being able to setup nested virtualization for a test system.


Log Monitoring
--------------

TODO: Talk about how to run a separate script that monitors a log file or the output of a process

Upgrading
---------

TODO:  This is changing in kilo, and what currently exists was never fully tested