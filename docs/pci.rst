PCI Passthrough
###############

Setting up a system for PCI passthrough can be a bit challenging.  Although smog has automated some parts of this,
a lot of it is still unfinished.  The most important thing (as always) is to make sure that your test environment
is suitable.


Manually setting up PCI Passthrough
===================================

The following is how you can manually setup a system for PCI passthrough testing and verifying if the hypervisor host
is properly passing through the PCI device to a guest booted up with a pci passthrough enabled flavor.

Set up kernel boot parameter to enable PCI passthrough
------------------------------------------------------

Make sure that VT-d extensions are enabled in the BIOS/UEFI

Edit the /etc/sysconfig/grub so that the GRUB_CMDLINE_LINUX has intel_iommu=on.  For example::

    GRUB_CMDLINE_LINUX="rd.lvm.lv=rhel/swap crashkernel=auto rd.lvm.lv=rhel/root rhgb quiet intel_iommu=on"

If your system boots off of BIOS, you can do this::

    grub2-mkconfig -o /boot/grub2/grub.cfg

If your system boots off of UEFI, you can do this::

    grub2-mkconfig -o /boot/efi/EFI/redhat/grub.cfg 

Reboot your system.  When it comes back up, make sure it has intel_iommu=on::

    cat /proc/cmdline

Also, you can check for iommu support with this::

    dmesg | grep -e DMAR -e IOMMU


Look for the ethernet driver and PCI info
-----------------------------------------

lspci -nn | grep Ether

If you already see some listings for "Ethernet Controller Virtual Function", you are already set
and can skip to Create a flavor with pci passthrough.  Otherwise, run a full listing on lspci

lspci -nnvvv

Here is a sample of what this looks like::

    06:00.0 Ethernet controller [0200]: Intel Corporation I350 Gigabit Network Connection [8086:1521] (rev 01)
        Subsystem: Intel Corporation I350 Gigabit Network Connection [8086:1521]
        Control: I/O+ Mem+ BusMaster+ SpecCycle- MemWINV- VGASnoop- ParErr+ Stepping- SERR- FastB2B- DisINTx+
        Status: Cap+ 66MHz- UDF- FastB2B- ParErr- DEVSEL=fast >TAbort- <TAbort- <MAbort- >SERR- <PERR- INTx-
        Latency: 0, Cache Line Size: 64 bytes
        Interrupt: pin A routed to IRQ 16
        Region 0: Memory at 90580000 (32-bit, non-prefetchable) [size=128K]
        Region 2: I/O ports at 3f80 [size=32]
        Region 3: Memory at 90570000 (32-bit, non-prefetchable) [size=16K]
        Capabilities: [40] Power Management version 3
                Flags: PMEClk- DSI+ D1- D2- AuxCurrent=0mA PME(D0+,D1-,D2-,D3hot+,D3cold+)
                Status: D0 NoSoftRst+ PME-Enable- DSel=0 DScale=1 PME-
        Capabilities: [50] MSI: Enable- Count=1/1 Maskable+ 64bit+
                Address: 0000000000000000  Data: 0000
                Masking: 00000000  Pending: 00000000
        Capabilities: [70] MSI-X: Enable+ Count=10 Masked-
                Vector table: BAR=3 offset=00000000
                PBA: BAR=3 offset=00002000
        Capabilities: [a0] Express (v2) Endpoint, MSI 00
                DevCap: MaxPayload 512 bytes, PhantFunc 0, Latency L0s <512ns, L1 <64us
                        ExtTag- AttnBtn- AttnInd- PwrInd- RBE+ FLReset+
                DevCtl: Report errors: Correctable+ Non-Fatal+ Fatal+ Unsupported+
                        RlxdOrd+ ExtTag- PhantFunc- AuxPwr- NoSnoop+ FLReset-
                        MaxPayload 128 bytes, MaxReadReq 4096 bytes
                DevSta: CorrErr+ UncorrErr- FatalErr- UnsuppReq+ AuxPwr+ TransPend-
                LnkCap: Port #0, Speed 5GT/s, Width x4, ASPM L0s L1, Exit Latency L0s <4us, L1 <32us
                        ClockPM- Surprise- LLActRep- BwNot-
                LnkCtl: ASPM Disabled; RCB 64 bytes Disabled- CommClk+
                        ExtSynch- ClockPM- AutWidDis- BWInt- AutBWInt-
                LnkSta: Speed 5GT/s, Width x4, TrErr- Train- SlotClk+ DLActive- BWMgmt- ABWMgmt-
                DevCap2: Completion Timeout: Range ABCD, TimeoutDis+, LTR+, OBFF Not Supported
                DevCtl2: Completion Timeout: 260ms to 900ms, TimeoutDis-, LTR-, OBFF Disabled
                LnkCtl2: Target Link Speed: 5GT/s, EnterCompliance- SpeedDis-
                         Transmit Margin: Normal Operating Range, EnterModifiedCompliance- ComplianceSOS-
                         Compliance De-emphasis: -6dB
                LnkSta2: Current De-emphasis Level: -6dB, EqualizationComplete-, EqualizationPhase1-
                         EqualizationPhase2-, EqualizationPhase3-, LinkEqualizationRequest-
        Capabilities: [100 v2] Advanced Error Reporting
                UESta:  DLP- SDES- TLP- FCP- CmpltTO- CmpltAbrt- UnxCmplt- RxOF- MalfTLP- ECRC- UnsupReq- ACSViol-
                UEMsk:  DLP- SDES- TLP- FCP- CmpltTO- CmpltAbrt- UnxCmplt- RxOF- MalfTLP- ECRC- UnsupReq+ ACSViol-
                UESvrt: DLP+ SDES+ TLP+ FCP+ CmpltTO+ CmpltAbrt- UnxCmplt- RxOF+ MalfTLP+ ECRC+ UnsupReq- ACSViol-
                CESta:  RxErr- BadTLP- BadDLLP- Rollover- Timeout- NonFatalErr+
                CEMsk:  RxErr+ BadTLP+ BadDLLP+ Rollover+ Timeout+ NonFatalErr+
                AERCap: First Error Pointer: 00, GenCap+ CGenEn- ChkCap+ ChkEn-
        Capabilities: [140 v1] Device Serial Number 6c-ae-8b-ff-ff-61-07-4a
        Capabilities: [150 v1] Alternative Routing-ID Interpretation (ARI)
                ARICap: MFVC- ACS-, Next Function: 1
                ARICtl: MFVC- ACS-, Function Group: 0
        Capabilities: [160 v1] Single Root I/O Virtualization (SR-IOV)
                IOVCap: Migration-, Interrupt Message Number: 000
                IOVCtl: Enable+ Migration- Interrupt- MSE+ ARIHierarchy-
                IOVSta: Migration-
                Initial VFs: 8, Total VFs: 8, Number of VFs: 1, Function Dependency Link: 00
                VF offset: 384, stride: 4, Device ID: 1520
                Supported Page Size: 00000553, System Page Size: 00000001
                Region 0: Memory at 0000000090100000 (64-bit, prefetchable)
                Region 3: Memory at 0000000090120000 (64-bit, prefetchable)
                VF Migration: offset: 00000000, BIR: 0
        Capabilities: [1a0 v1] Transaction Processing Hints
                Device specific mode supported
                Steering table in TPH capability structure
        Capabilities: [1c0 v1] Latency Tolerance Reporting
                Max snoop latency: 0ns
                Max no snoop latency: 0ns
        Capabilities: [1d0 v1] Access Control Services
                ACSCap: SrcValid- TransBlk- ReqRedir- CmpltRedir- UpstreamFwd- EgressCtrl- DirectTrans-
                ACSCtl: SrcValid- TransBlk- ReqRedir- CmpltRedir- UpstreamFwd- EgressCtrl- DirectTrans-
        Kernel driver in use: igb


And look for the Ethernet controller with the same vendor_id:product_id.  Amongst all the information
you should see something about SR-IOV in the Capabilities::

    Capabilities: [160 v1] Single Root I/O Virtualization (SR-IOV)


Note also the kernel driver in use: igb  This indicates this PCI device uses the igb kernel module.


Set up Virtual functions for your ethernet
------------------------------------------

Note, for this part, you will need to have local access to your machine.  Since we need to stop the network services,
you will not be able to run this commands over SSH for example.

Find your iface bound to the default gateway using route -n::

    [root@rhos-compute-node-06 ~(keystone_admin)]# route -n
    Kernel IP routing table
    Destination     Gateway         Genmask         Flags Metric Ref    Use Iface
    0.0.0.0         10.8.31.254     0.0.0.0         UG    0      0        0 eno1
    10.8.0.0        0.0.0.0         255.255.224.0   U     0      0        0 eno1
    169.254.0.0     0.0.0.0         255.255.0.0     U     1022   0        0 br-ex

So in this case, my iface is eno1.  

Stop network service (using systemctl stop network) and kill dhclient

Setup the ethernet driver to use VF
-----------------------------------

Remove your ethernet driver, and make it use max_vfs parameter::

    modprobe -r igb  # or ixgbe if that's what was in your lspci's output of "Kernel driver in use"
    modprobe igb max_vfs=1

Rerun lspci -nnvvv, and note the new virtual functions for the ethernet.  You will need the [vendor_id:product_id] later

Restart the network service and the dhclient given the default iface.  For example::

    systemctl start network
    dhclient eno1

Make sure that you can ping and ssh into the host.

Install packstack
-----------------

You can run this with an --allinone

Set up the nova.conf with the proper values
-------------------------------------------

Edit the pci_alias.  It is a dictionary with 3 keys: name, vendor_id, and product_id.  You can make
the value of name key anything, the vendor_id is the PCI device's vendor id (for example Intel is
8086), and the product_id is the PCI device product id. After loading the igb driver with the
max_vfs=1, and re-running the lspci -nnvvv command, we might find something like this::

    07:10.3 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)

The [8086:1520] is the [vendor_id:product_id].  So edit the pci_alias like this::

    pci_alias={"name": "igbnic", "vendor_id": "8086", "product_id": "1520"}


The pci_passthrough_whitelist needs to be edited almost the same, but without the name key.  Also, it is a list of
dictionaries.  It has an extra key called "physical_network" and the value for this can be arbirtary.
So it would look like this::

    pci_passthrough_whitelist=[{"vendor_id": "8086", "product_id": "1520", "physical_network": "physnet1"}]

The above should be done for all the nodes running compute service.

Also on any node(s) running the scheduler service, add to the scheduler_default_filters and the
scheduler_available_filters::

    scheduler_available_filters=nova.scheduler.filters.pci_passthrough_filter.PciPassthroughFilter
    scheduler_default_filters=RetryFilter,AvailabilityZoneFilter,RamFilter,ComputeFilter,ComputeCapabilitiesFilter,ImagePropertiesFilter,CoreFilter,PciPassthroughFilter


Restart nova services::

    openstack-service restart nova


Create a flavor with pci passthrough
------------------------------------

Create a new flavor with extra_specs using the same name given in the pci_alias.  For example, I set my pci_alias
to igbnic::

    nova flavor-create pci-pass 100 1024 20 2
    nova flavor-key pci-pass set pci_passthrough:alias=igbnic:1

The igbnic:1 means use the pci_alias["name"] = "igbnic", and the :1 means assign 1 PCI device of that type::

    [root@rhos-compute-node-06 ~(keystone_admin)]# nova flavor-show pci-pass
    +----------------------------+---------------------------------------+
    | Property                   | Value                                 |
    +----------------------------+---------------------------------------+
    | OS-FLV-DISABLED:disabled   | False                                 |
    | OS-FLV-EXT-DATA:ephemeral  | 0                                     |
    | disk                       | 20                                    |
    | extra_specs                | {"pci_passthrough:alias": "igbnic:1"} |
    | id                         | 100                                   |
    | name                       | pci-pass                              |
    | os-flavor-access:is_public | True                                  |
    | ram                        | 1024                                  |
    | rxtx_factor                | 1.0                                   |
    | swap                       |                                       |
    | vcpus                      | 2                                     |
    +----------------------------+---------------------------------------+

Getting the network ID
----------------------

In Kilo, you will need to specify the network ID to use::

    [root@rhos-compute-node-10 ~(keystone_admin)]# neutron net-list
    +--------------------------------------+---------+------------------------------------------------------+
    | id                                   | name    | subnets                                              |
    +--------------------------------------+---------+------------------------------------------------------+
    | f759ea60-be84-43ab-8c97-fc0ca9fa2d50 | public  | 1d0f89b0-cd85-431a-a071-6c955b5af86a 172.24.4.224/28 |
    | efd5f682-7ba1-4eb9-b853-b174bc21c822 | private | ab827b7a-8b38-434c-9f2d-dd5da1564b18 10.0.0.0/24     |
    +--------------------------------------+---------+------------------------------------------------------+


Boot an instance using this flavor
----------------------------------

Here, we actually boot up the instance using the pci passthrough enabled flavor we just specified::

    [root@rhos-compute-node-10 ~(keystone_admin)]# nova boot --flavor pci_small --image cirros --nic net-id=efd5f682-7ba1-4eb9-b853-b174bc21c822 pci-test
    +--------------------------------------+--------------------------------------------------+
    | Property                             | Value                                            |
    +--------------------------------------+--------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                           |
    | OS-EXT-AZ:availability_zone          | nova                                             |
    | OS-EXT-SRV-ATTR:host                 | -                                                |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                                |
    | OS-EXT-SRV-ATTR:instance_name        | instance-00000001                                |
    | OS-EXT-STS:power_state               | 0                                                |
    | OS-EXT-STS:task_state                | scheduling                                       |
    | OS-EXT-STS:vm_state                  | building                                         |
    | OS-SRV-USG:launched_at               | -                                                |
    | OS-SRV-USG:terminated_at             | -                                                |
    | accessIPv4                           |                                                  |
    | accessIPv6                           |                                                  |
    | adminPass                            | acpYw67QxHWb                                     |
    | config_drive                         |                                                  |
    | created                              | 2015-06-03T14:48:52Z                             |
    | flavor                               | pci_small (27204784-ee5e-49fd-9436-89b020f17caa) |
    | hostId                               |                                                  |
    | id                                   | 573bb201-10db-4c48-87f9-c08985bd7d0f             |
    | image                                | cirros (e1fa2236-e728-4c6c-91a1-0a4477d5da1d)    |
    | key_name                             | -                                                |
    | metadata                             | {}                                               |
    | name                                 | pci-test                                         |
    | os-extended-volumes:volumes_attached | []                                               |
    | progress                             | 0                                                |
    | security_groups                      | default                                          |
    | status                               | BUILD                                            |
    | tenant_id                            | 04ce7763bfce4fce926d08b304d13297                 |
    | updated                              | 2015-06-03T14:48:52Z                             |
    | user_id                              | 2e16af569a394fd982c2236289040625                 |
    +--------------------------------------+--------------------------------------------------+



    [root@rhos-compute-node-10 ~(keystone_admin)]# nova show pci-test
    +--------------------------------------+----------------------------------------------------------+
    | Property                             | Value                                                    |
    +--------------------------------------+----------------------------------------------------------+
    | OS-DCF:diskConfig                    | MANUAL                                                   |
    | OS-EXT-AZ:availability_zone          | nova                                                     |
    | OS-EXT-SRV-ATTR:host                 | rhos-compute-node-10.lab.eng.rdu2.redhat.com             |
    | OS-EXT-SRV-ATTR:hypervisor_hostname  | rhos-compute-node-10.lab.eng.rdu2.redhat.com             |
    | OS-EXT-SRV-ATTR:instance_name        | instance-00000001                                        |
    | OS-EXT-STS:power_state               | 1                                                        |
    | OS-EXT-STS:task_state                | -                                                        |
    | OS-EXT-STS:vm_state                  | active                                                   |
    | OS-SRV-USG:launched_at               | 2015-06-03T14:50:26.000000                               |
    | OS-SRV-USG:terminated_at             | -                                                        |
    | accessIPv4                           |                                                          |
    | accessIPv6                           |                                                          |
    | config_drive                         |                                                          |
    | created                              | 2015-06-03T14:48:52Z                                     |
    | flavor                               | pci_small (27204784-ee5e-49fd-9436-89b020f17caa)         |
    | hostId                               | 46747eb935019fb076329a5a09c8a19161496d5a285603c5df275ddd |
    | id                                   | 573bb201-10db-4c48-87f9-c08985bd7d0f                     |
    | image                                | cirros (e1fa2236-e728-4c6c-91a1-0a4477d5da1d)            |
    | key_name                             | -                                                        |
    | metadata                             | {}                                                       |
    | name                                 | pci-test                                                 |
    | os-extended-volumes:volumes_attached | []                                                       |
    | private network                      | 10.0.0.3                                                 |
    | progress                             | 0                                                        |
    | security_groups                      | default                                                  |
    | status                               | ACTIVE                                                   |
    | tenant_id                            | 04ce7763bfce4fce926d08b304d13297                         |
    | updated                              | 2015-06-03T14:50:26Z                                     |
    | user_id                              | 2e16af569a394fd982c2236289040625                         |
    +--------------------------------------+----------------------------------------------------------+

Verify that the host is passing through the PCI device
------------------------------------------------------

Now we have a nova guest running on our host.  However, we need to check that libvirt is actually honoring that the
device is being passed through.  To check this, we look at what libvirt is telling us about this instance.  We can
see from the nova show above, that the instance name is instance-00000001.  Let's see what the xml domain looks like

.. code-block:: xml

    [root@rhos-compute-node-10 ~(keystone_admin)]# virsh list
     Id    Name                           State
    ----------------------------------------------------
     2     instance-00000001              running

    [root@rhos-compute-node-10 ~(keystone_admin)]# virsh dumpxml 2
    <domain type='kvm' id='2'>
      <name>instance-00000001</name>
      <uuid>573bb201-10db-4c48-87f9-c08985bd7d0f</uuid>
      <metadata>
        <nova:instance xmlns:nova="http://openstack.org/xmlns/libvirt/nova/1.0">
          <nova:package version="2015.1.0-4.el7ost"/>
          <nova:name>pci-test</nova:name>
          <nova:creationTime>2015-06-03 14:50:15</nova:creationTime>
          <nova:flavor name="pci_small">
            <nova:memory>512</nova:memory>
            <nova:disk>10</nova:disk>
            <nova:swap>0</nova:swap>
            <nova:ephemeral>0</nova:ephemeral>
            <nova:vcpus>1</nova:vcpus>
          </nova:flavor>
          <nova:owner>
            <nova:user uuid="2e16af569a394fd982c2236289040625">admin</nova:user>
            <nova:project uuid="04ce7763bfce4fce926d08b304d13297">admin</nova:project>
          </nova:owner>
          <nova:root type="image" uuid="e1fa2236-e728-4c6c-91a1-0a4477d5da1d"/>
        </nova:instance>
      </metadata>
      <memory unit='KiB'>524288</memory>
      <currentMemory unit='KiB'>524288</currentMemory>
      <vcpu placement='static' cpuset='0-11'>1</vcpu>
      <cputune>
        <shares>1024</shares>
      </cputune>
      <resource>
        <partition>/machine</partition>
      </resource>
        <sysinfo type='smbios'>
          <system>
            <entry name='manufacturer'>Red Hat</entry>
            <entry name='product'>OpenStack Compute</entry>
            <entry name='version'>2015.1.0-4.el7ost</entry>
            <entry name='serial'>3935e47c-029c-49e2-b2b0-ee04c0e036f3</entry>
            <entry name='uuid'>573bb201-10db-4c48-87f9-c08985bd7d0f</entry>
          </system>
        </sysinfo>
      <os>
        <type arch='x86_64' machine='pc-i440fx-rhel7.1.0'>hvm</type>
        <boot dev='hd'/>
        <smbios mode='sysinfo'/>
      </os>
      <features>
        <acpi/>
        <apic/>
      </features>
      <cpu mode='host-model'>
        <model fallback='allow'/>
        <topology sockets='1' cores='1' threads='1'/>
      </cpu>
      <clock offset='utc'>
        <timer name='pit' tickpolicy='delay'/>
        <timer name='rtc' tickpolicy='catchup'/>
        <timer name='hpet' present='no'/>
      </clock>
      <on_poweroff>destroy</on_poweroff>
      <on_reboot>restart</on_reboot>
      <on_crash>destroy</on_crash>
      <devices>
        <emulator>/usr/libexec/qemu-kvm</emulator>
        <disk type='file' device='disk'>
          <driver name='qemu' type='qcow2' cache='none'/>
          <source file='/var/lib/nova/instances/573bb201-10db-4c48-87f9-c08985bd7d0f/disk'/>
          <backingStore type='file' index='1'>
            <format type='raw'/>
            <source file='/var/lib/nova/instances/_base/061274fb8b0049962451cd8cdac45594d6ee1838'/>
            <backingStore/>
          </backingStore>
          <target dev='vda' bus='virtio'/>
          <alias name='virtio-disk0'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x04' function='0x0'/>
        </disk>
        <controller type='usb' index='0'>
          <alias name='usb0'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x01' function='0x2'/>
        </controller>
        <controller type='pci' index='0' model='pci-root'>
          <alias name='pci.0'/>
        </controller>
        <interface type='bridge'>
          <mac address='fa:16:3e:0b:65:fc'/>
          <source bridge='qbr6ba6b8e7-f4'/>
          <target dev='tap6ba6b8e7-f4'/>
          <model type='virtio'/>
          <alias name='net0'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x03' function='0x0'/>
        </interface>
        <serial type='file'>
          <source path='/var/lib/nova/instances/573bb201-10db-4c48-87f9-c08985bd7d0f/console.log'/>
          <target port='0'/>
          <alias name='serial0'/>
        </serial>
        <serial type='pty'>
          <source path='/dev/pts/2'/>
          <target port='1'/>
          <alias name='serial1'/>
        </serial>
        <console type='file'>
          <source path='/var/lib/nova/instances/573bb201-10db-4c48-87f9-c08985bd7d0f/console.log'/>
          <target type='serial' port='0'/>
          <alias name='serial0'/>
        </console>
        <input type='tablet' bus='usb'>
          <alias name='input0'/>
        </input>
        <input type='mouse' bus='ps2'/>
        <input type='keyboard' bus='ps2'/>
        <graphics type='vnc' port='5900' autoport='yes' listen='0.0.0.0' keymap='en-us'>
          <listen type='address' address='0.0.0.0'/>
        </graphics>
        <video>
          <model type='cirrus' vram='16384' heads='1'/>
          <alias name='video0'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x02' function='0x0'/>
        </video>
        <hostdev mode='subsystem' type='pci' managed='yes'>
          <driver name='vfio'/>
          <source>
            <address domain='0x0000' bus='0x07' slot='0x10' function='0x7'/>
          </source>
          <alias name='hostdev0'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x05' function='0x0'/>
        </hostdev>
        <memballoon model='virtio'>
          <alias name='balloon0'/>
          <address type='pci' domain='0x0000' bus='0x00' slot='0x06' function='0x0'/>
          <stats period='10'/>
        </memballoon>
      </devices>
      <seclabel type='dynamic' model='selinux' relabel='yes'>
        <label>system_u:system_r:svirt_t:s0:c16,c759</label>
        <imagelabel>system_u:object_r:svirt_image_t:s0:c16,c759</imagelabel>
      </seclabel>
    </domain>

The important part to look for is under the <devices> section.  The import piece is to look for the pci type, and try
to find the a matching PCI bus:slot:function address.  We can find it in this section


.. code-block:: xml

    <hostdev mode='subsystem' type='pci' managed='yes'>
      <driver name='vfio'/>
      <source>
        <address domain='0x0000' bus='0x07' slot='0x10' function='0x7'/>
      </source>
      <alias name='hostdev0'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x05' function='0x0'/>
    </hostdev>

How did I know this was the right section?  This line <address domain='0x0000' bus='0x07' slot='0x10' function='0x7'/>
gives us the PCI address for this host device.  The bus = 0x07, the slot = 0x10, and function = 0x7.  This is important
because it matches what lspci told us our Virtual Function address was on.  Recall the output from lspci -nnvvv::

    [root@rhos-compute-node-10 ~(keystone_admin)]# lspci -nnvvv | grep "Virtual Function"
    07:10.0 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.1 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.2 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.3 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.4 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.5 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.6 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)
    07:10.7 Ethernet controller [0200]: Intel Corporation I350 Ethernet Controller Virtual Function [8086:1520] (rev 01)

The first part of the line is bus:slot.function.  For example, the last line shows 07:10.7.  That means we have bus=0x07
slot = 0x10, and device=0x07.  That's how we know this is our managed pci device.  So now that we know the PCI Address,
let's see what virsh nodedev-dumpxml shows.  We need to use special format as the argument::

    [root@rhos-compute-node-10 ~(keystone_admin)]# virsh nodedev-dumpxml pci_0000_07_10_7
    <device>
      <name>pci_0000_07_10_7</name>
      <path>/sys/devices/pci0000:00/0000:00:1c.0/0000:07:10.7</path>
      <parent>pci_0000_00_1c_0</parent>
      <driver>
        <name>vfio-pci</name>
      </driver>
      <capability type='pci'>
        <domain>0</domain>
        <bus>7</bus>
        <slot>16</slot>
        <function>7</function>
        <product id='0x1520'>I350 Ethernet Controller Virtual Function</product>
        <vendor id='0x8086'>Intel Corporation</vendor>
        <capability type='phys_function'>
          <address domain='0x0000' bus='0x06' slot='0x00' function='0x3'/>
        </capability>
        <iommuGroup number='40'>
          <address domain='0x0000' bus='0x07' slot='0x10' function='0x7'/>
        </iommuGroup>
        <numa node='0'/>
        <pci-express>
          <link validity='cap' port='0' speed='5' width='4'/>
          <link validity='sta' width='0'/>
        </pci-express>
      </capability>
    </device>

Note that the argument for this command was pci_0000_07_10_7.  You now know what the 07_10_7 is (the bus, slot and
function), and the 0000 is the domain (PCI root complexes can be one different domains).  If you think your system
might have multiple PCI domains, you can run the virsh nodedev-list command to print all the addresses out.

But looking at the output, we can see that this is indeed the VF that we requested and it shows which Physical Function
on the PCI device the VF is mapped to.  Additionally, if this was a multi-numa node system (say for example, this machine
had 2 NUMA nodes), this output tells us that the PCI VF is attached to numa node 0.  This is important if you are
requesting a multi-numa node topology and wish to also do VCPU pinning + PCI Passthrough.  For performance reasons,
you would want your pinned VCPUs to also be on NUMA node 0 because node 0 is where the PCI device resides.

Automated Setup
===============

So all the manual preparation above can be error prone.  Because of this, some parts can be automated with smog.  I have
included a script which still needs some work.  I have heavily commented what is going on here (and what still needs
to be done)

I am also including this here to give you an idea of how you can use smog.  Notice, that none of this is inside of a
unittest.TestCase derived class (for example NUMATest).  In other words, everything you see below, you could be doing
inside a python shell.  This is IMHO, what frameworks like Tempest or even Khaleesi lacks.  Sometimes, you need more
control than what a framework or playbook gives you.

.. code-block:: python

    import argparse
    import time
    import os
    import threading
    import sys

    import hy
    import smog.utils.pci.pci_passthrough as pci
    from smog.tests.base import scp
    from smog.tests.numa import NUMA
    from smog.core.logger import glob_logger
    from smog.core.commander import Command
    from smog.core.watcher import make_watcher, ReaderHandler
    import smog.virt as virt

    DO_PACKSTACK = True

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--server", help="IP address of bare metal server")
    parser.add_argument("-d", "--driver", help="Driver to modify", default="igb")
    parser.add_argument("--vfs", default=2, type=int, help="Number of max_vfs")
    parser.add_argument("-c", "--compute", action="append",
                        help="IP address for a compute node"
                             "Can be specified multiple times.  For example:"
                             "--compute=10.8.29.58 --compute=10.8.29.167")
    if DO_PACKSTACK:
        parser.add_argument("-u", "--username", help="Project username (or OS_USERNAME)", default="admin")
        parser.add_argument("-p", "--password", help="password for username (or OS_PASSWORD)")
        parser.add_argument("-t", "--tenant", help="Tenant name (or OS_TENANT_NAME)", default="admin")
        parser.add_argument("--auth", help="Auth URL (or OS_AUTH_URL)")

    args = parser.parse_args()

    if DO_PACKSTACK:
        username = os.environ.get("OS_USERNAME") or args.username
        tenant = os.environ.get("OS_TENANT_NAME") or args.tenant
        password = os.environ.get("OS_PASSWORD") or args.password
        auth_url = os.environ.get("OS_AUTH_URL") or args.auth

        creds = {"username": username, "password": password, "auth_url": auth_url, "tenant": tenant}
        for k, v in creds.items():
            if not v:
                msg = "Must have {} defined in environment or passed as --{}".format(k)
                raise Exception(msg)

    # let's see if we already have a VFS setup and we have the right kernel params
    host = args.server
    is_vfs_here = pci.get_lspci_info(host)     # Check if we have VF's
    is_grub_set = pci.verify_cmdline(host)     # Check if intel_iommu=on

    # I have noticed that when I install RHEL, the default interface script does
    # not have the ON_BOOT=yes.  That becomes a problem when we restart the network
    # because otherwise we will need to manually specify dhclient def_iface
    # TODO: either edit the /etc/sysconfig/network-scripts/ifcfg-{def_iface}
    # to use ON_BOOT=yes, or add in change_modprobe, to call dhclient def_iface
    # at the end of the script
    def_iface = pci.get_default_iface(host)

    change_modprobe = """
    from subprocess import Popen, PIPE, STDOUT
    import sys

    keys = {"stdout": PIPE, "stderr": STDOUT}
    driver = sys.argv[1]
    vfs = sys.argv[2]

    # take down networking
    proc = Popen("systemctl stop network".split(), **keys)
    proc.communicate()

    # remove the igb driver
    cmd = "modprobe -r {}".format(driver).split()
    proc = Popen(cmd, stdout=PIPE, stderr=STDOUT)
    pout, _ = proc.communicate()

    # set igb to use max_vfs=2
    cmd = "modprobe {} max_vfs={}".format(driver, vfs).split()
    proc = Popen(cmd, **keys)
    proc.communicate()

    # bring up networking
    proc = Popen("systemctl start network".split(), **keys)
    proc.communicate()

    with open("completed.txt", "w") as complete:
        complete.write("Got to the end of the script")
    """

    # IF we dont have intel_iommu=on in /proc/cmdline, we need to set it
    # and reboot the system
    if not is_grub_set:
        glob_logger.info("Setting intel_iommu=on")
        pci.set_grub_cmdline(host)
        pci.grub2_mkconfig(host)

        # reboot the host
        virt.rebooter(host)
        virt.pinger(host, timeout=600)

    # This is really only needed for SRIOV or PCI Passthrough with an ethernet
    # device (PCI passthrough and SRIOV only works on VF's not PF's)
    if not is_vfs_here:
        # So there's a bug with using /etc/modprobe.d and setting max_Vfs
        # in a conf file.  So we have to do this ugly hack.
        # scp the change_modprobe.py to remote machine and run it.
        # poll until system is back up
        glob_logger.info("Setting up igb driver to use max_vfs")
        with open("change_modprobe.py", "w") as script:
            script.write(change_modprobe)
        src = "./change_modprobe.py"
        dest = "root@{}:/root".format(host)
        cp_res = scp(src, dest)
        os.unlink("change_modprobe.py")

        # Now, run the script and wait for networking to come back up
        cmd = Command("python /root/change_modprobe.py igb 2", host=host)

        # Ughh, we need to throw this in a separate thread because the Command object
        # is using ssh.  Since the script cuts the network, ssh is left hanging
        mp_thr = threading.Thread(target=cmd, kwargs={"throws": False},
                                  daemon=True)
        mp_thr.start()
        virt.pinger(host, timeout=600)
        time.sleep(5)  # give a bit of time for system services to come up

    # Determine what the vendor and product ID are.  intel is always 8086,
    # and that's all we have tested on, but there may be others for other
    # SRIOV or PCI passthrough devices
    lspci_info = pci.get_lspci(host)
    lspci_txt = lspci_info.output
    parsed = pci.lspci_parser(lspci_txt)
    vfs = pci.collect(parsed, "Virtual Function")
    parsed_vfs = list(map(pci.block_parser, vfs))

    # Get the product and vendor ids
    v_id = parsed_vfs[0]['\ufdd0:vendor']
    p_id = parsed_vfs[0]['\ufdd0:product']

    # At this point, we can install packstack.  The reason we should do this
    # _after_ installing packstack, is that if we install packstack first,
    # neutron might get confused by the new VFS (and new ethernet ifaces)
    if DO_PACKSTACK:
        res = Command("which packstack", host=host)(throws=False)
        if res != 0:
            glob_logger.info("You must yum install openstack-packstack first")
            sys.exit()
        watcher = make_watcher("packstack --allinone", host, ReaderHandler, sys.stdout)

        # Periodically check to see if we're done.  This is one of the nicer features
        # of smog if I do say so myself.  We can watch the output of a long running
        # process.  Sometimes you need this, even for automation.  What if you have a
        # 72hr test.  Do you really want to wait 3 days to find out it failed in the
        # first 5 minutes?  And yes, 72 and even week long stress tests are not
        # uncommon.
        while watcher.poll() is None:
            time.sleep(1)
        watcher.close()  # close all our threads (TODO: close automatically)

    # Now set the nova.conf pci_alias on our compute nodes.  Copy the remote
    # nova.conf file locally, edit it, then copy it back to the remote machine
    alias_name = "pci_pass_test"
    for cmpt in args.compute:
        alias_res = pci.set_pci_alias(cmpt, alias_name, v_id, p_id)
        white_res = pci.set_pci_whitelist(cmpt, v_id, p_id, "./nova.conf")
        filter_res = pci.set_pci_filter(cmpt, "./nova.conf")
        src = "./nova.conf"
        dest = "root@{}:/etc/nova/nova.conf".format(cmpt)
        res = scp(src, dest)

        # restart nova
        pci.openstack_service(cmpt, "restart", "nova")

    # Now, we create a PCI flavor and attempt to boot
    numa = NUMA(**creds)
    flv = numa.create_flavor("pci_small", ram=512)
    pci_pass_flv = numa.create_pci_flavor(alias_name, flv=flv)
    glob_logger.info(str(pci_pass_flv.get_keys()))

    if False:
        # Get the private neutron ID (smog doesn't have any helpers for neutron)
        # TODO: use a ugly shelled out hack with a regex for now

        # Boot an instance with this flavor
        guest = numa.boot_instance(flv=pci_pass_flv, name="pci-testing")
        instance = numa.discover(guests=[guest])[0]
