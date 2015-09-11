Things to clean up
==================

Unfortunately, smog was written by one author under a serious time crunch and without any kind of code review.
As such, the design and architecture of smog was rather haphazard, and I wish I could have done things a bit
differently had I been able to spend more

Unit testing
------------

smog itself has no unit tests.  I know I know.  I miss actually having a suite of tests that I could use as a
sanity check when I would refactor code, but unfortunately, I was usually so pressed for time that I didn't
have time to write unit tests.  I've never really followed the "write your unit tests first" mantra, but I do
think unit tests are a good idea.  smog needs unit tests

Organization of code
--------------------

smog grew "organically", and not a whole heck of a lot of thought went into the package namespace layout. I
don't think the packages are all that bad, but the actually Class hierarchies are pretty bad.  I started out
with the smog.tests.base.BaseStack class, and just started shoving more and more functionality in that class.

It probably would have been better to create a few mixins instead and then compose them as needed.  For example,
the NUMA class inherits from BaseStack, and I started putting more and more functionality in NUMA that probably
really didn't belong there (like SRIOV or PCI passthrough related stuff).

Tight coupling of test cases to provisioning
--------------------------------------------

This is probably the hugest mistake of all.  My original thought was the yaml configuration files would describe
not just what the test did, but how to bring up the virtual machines into a state that could perform the test.
For example, for huge pages it would use information in the configuration files to change the L1 domain xml
in order for the L2 guests to utilize the huge pages.

What that did though was create a lot of complexity that could have been handled by specialized tools (for
example Ansible).  The provisioning and environment configuration should have been kept separate from the
actual testing.  At most, the test should have checked if the necessary bits were in place, but not actually
perform any provisioning itself.

Better way to do configuration
------------------------------

I decided on a configuration file per unittest.TestCase derived class, figuring that having a higher level of
granularity would be better.  In some ways it is, but it is also very tedious to have to change

- The main smog/config/smog_config.yml file to get keystone credentials
- Put all the compute and controller nodes in each test yaml file

What I had started working on (and never finished) was a command line utility tool that would in essence override
only the parts of the file you needed.  I'm still not sure if that's a better approach or not.  Another possibility
would have been a web interface.

Better documentation
--------------------

smog has a lot of documentation, but it's been rather rambling.  It needs to be a bit more focused and organized
and there also needs to be more inline documentation (especially Usage for functions).


Python3 annotations using mypy-lang
-----------------------------------

I only discovered PEP 484 about 2 months ago, but I should have started writing more statically type checked code
using the mypy-lang library.  I can't stand having to look at other people's python code and wondering what
kind of argument I am supposed to pass to a function.  I don't want to be a hypocrite and have other people
suffer while reading through smog's code.