(import [smog.core.commander [Command]]
        [smog.tests.base :as sbase]
        re
        os)
(require smog.utils.macros
         hy.contrib.loop)
(import [smog.utils.macros [not= isnt]])

(import [pyrsistent [v pvector]])

;;  Checks to see if we have virtual functions set up.  Unfortunately, the igb
;;  driver does not seem to have a /sys/module/igb/parameters section, so we
;;  will use a regex to look for Virtual in the output of lspci -nn | grep Ether
(defn get-lspci-info [host &optional [pattern None]]
  (let [[cmd (apply Command ["lspci -nnvvv | grep Ether"] {"host" host})]
        [res (apply cmd [] {"showout" false})]
        [patt (if (is pattern None)
                (.compile re r"Virtual ")
                pattern)]
        [lines (.split res.output "/n")]
        [flt (fn [x] (not (is x None)))]
        [l (list-comp (.search patt line) [line lines])]
        [matches (list (filter flt l))]]
    (if matches
      matches
      False)))


;; Uses route -n to determine what the default gateway is for a given interface
(defn get-gateway [host iface]
  (let [[cmd (apply Command ["route -n"] {"host" host})]
        [result (cmd)]
        [lines (-> (. result output) (.split "\n"))]
        [iface-lines (filter (fn [x] (in iface x)) lines)]
        [split-lines (list-comp (.split line) [line iface-lines])]
        [fltfn (lambda [x] (and
                             (not= (get x 1) "0.0.0.0")
                             (= "UG" (get x 3))))]]
    (-> (filter fltfn split-lines) (first) (get 1))))


;; This is probably what we want instead of get-gateway
;; Uses ip route show to determine what the default interface is connected to our gateway
;; This is useful if for example, we need to start dhclient eno1
(defn get-default-iface [host]
  (let [[cmd "ip route show"]
        [patt (.compile re r"(\w+)$")]
        [command (apply Command [cmd] {"host" host})]
        [result (apply command [] {"showout" False "showerr" False})]
        [line (first (.split result.output "\n"))]   ;; we're only interested in the first line
        [match (.search patt (.strip line))]]
    (if match
      (first (.groups match))
      match)))


;; sets the intel_iommu=on in the kernel command line parameter
;; Note that this function only works on intel based systems
(defn set-grub-cmdline [host &optional [grub-path "/etc/sysconfig/grub"]
                        [user "root"]
                        [dest "."]]
  (let [[get-remote-file (. sbase get_remote_file)]
        [grub-file (apply get-remote-file [host grub-path] {"user" user "dest" dest})]
        [found (sbase.get_cfg "GRUB_CMDLINE_LINUX" grub-file)]
        [cfg-item (first (filter (lambda [x] (is (. x comment) None)) found))]
        [line (let [[l (-> (. cfg-item val) (.strip))]]
                (if (not-in "intel_iommu=on" l)
                  (let [[nl (slice l 0 -1)]]
                    (.format "{} {}\"" nl " intel_iommu=on"))
                  l))]
        [set-res (sbase.set_cfg "GRUB_CMDLINE_LINUX" line grub-file (.format "{}.bak" grub-file))]
        [final (. (first set-res) line)]]
    (if (not-in "intel_iommu=on" final)
      (raise (Exception "Could not set grub cmdline"))
      (let [[dest (.format "{}@{}:{}" user host grub-path)]
            [src grub-file]
            [remote-scp (sbase.scp src dest)]]
        {:set-result set-res :scp-result remote-scp}))))


(defn remote-path? [host path]
  (let [[cmd (apply Command [(.format "ls {}" path)] {"host" host})]
        [result (apply cmd [] {"throws" false})]]
    (= result 0)))


;; Calls the grub2-mkconfig command.  The optional grub-cfg is set by default to use
;; an EFI setting for Red Hat.  If you are using BIOS or on another distro, this
;; needs to be changed accordingly
(defn grub2-mkconfig [host &optional [grub-cfg "/boot/efi/EFI/redhat/grub.cfg"]]  
  (let [[grub-cfg2 (if (remote-path? host grub-cfg)
                     grub-cfg
                     "/boot/grub2/grub.cfg")]  ;; it's not a EFI system
        [grub-cmd (.format "grub2-mkconfig -o {}" grub-cfg2)]
        [cmd (apply Command [grub-cmd] {"host" host})]]
    (cmd)))


;; Verifies that the remote host has the iommu settings set.  By default this
;; looks for the intel iommu param in /proc/cmdline
(defn verify-cmdline [host &optional [iommu "intel_iommu=on"]]
  (in iommu (. (sbase.read-proc-file host "/proc/cmdline") output)))
    

;; This function must run locally
;; Checks that the necessary bits for enabling PCI passthrough is there.  Note that
;; this can not check the BIOS/UEFI settings for VT-d (on Intel) or AMD IOMMU for AMD
;;         
;; This function only works on setting Intel based NIC cards capable of SR-IOV. This
;; is the easiest way of doing either SRIOV or PCI passthrough.
;;
;; http://dpdk.org/doc/guides/nics/intel_vf.html
;;
;; Currently, this function supports the following drivers:
;; [igb, ixgbe, i40e]
;;
;; Note that this step should be performed before any Openstack installation, since
;; Openstack installers (like packstack) might change configurations around.
;;
;; First, check to see if we already have a Virtual function setup.  If not, stop
;; the network service and dhclient.  Then remove the driver.  modprobe the driver
;; with max_vfs=1.  Then restart network and dhclient to original interface (usually
;; eno1
;; TODO: it sucks hy doesn't do docstrings.  Make a macro defn+ that inserts the first
;; element after the args into fn.__doc__.  While we're at it, add a condition like
;; clojure has for :pre and :post condition tests.
(defn enable-vfs [num-vfs &optional
                  [driver "igb"]
                  [iface "eno1"]
                  [host None]
                  [startnet "systemctl start network"]]
  (let [[rmmod ((apply Command [(.format "modprobe -r {}" driver)] {}))]
        [modprobe ((Command (.format "modprobe {} max_vfs={}" driver num-vfs)))]
        [netstart ((Command startnet))]
        [dhclient ((Command (.format "dhclient {}" iface)))]
        [host (if (is host None)
                "localhost"
                host)]]
    (get-lspci-info host)))


(defclass PCIeInfo [object]
  [[--init--
    ;; Instantiates a PCIeInfo object 
    (fn [self prod-id vend-id desc caps module]
      (setv self.prod-id prod-id)
      (setv self.vend-id vend-id)
      (setv self.desc desc)
      (setv self.caps caps)
      (setv self.module module)
      None)]])


;; Wrapper to get the lspci information on a host.  If this command fails, you might
;; need to install pci-utils on the remote machine
(defn get-lspci [host]
  (-> (apply Command ["lspci -nnvvv"] {"host" host}) (apply [] {"showout" false})))


;; The way that lspci dumps its output, we can read until we come to a blank newline
;; When we see that, we have a new chunk that can be passed to the parser.  So this
;; function returns a vector of vectors (a vector of chunks of text)
;; Runs lspci -nnvvv on the remote host, and creates blocks of text
(defn lspci-parser [text]
  (loop [[lines (.split text "\n")]
         [block (v)]    ;; a block of text
         [bcoll (v)]]   ;; a collection of blocks
     (let [[line (first lines)]
           [r (list (rest lines))]
           [blank-patt (.compile re r"^\s*$")]]
      (cond
       [(is line None) (list (butlast bcoll))]  ;; not sure why I have one extra
       [(isnt (.search blank-patt line) None)
          (recur r (v) (.append bcoll block))]
       [True (recur r (.append block line) bcoll)]))))


;; Extracts the bus device function, vendor id and produdct id
;; Takes the first line from a block and returns a map of the above or None
(defn get-bdf-id [first-line]
  (let [[first-patt (.compile re r"([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.\d+)(.*)\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\](.*)")]
        [matches (.search first-patt first-line)]]
    (if matches
      (let [[groups (.groups matches)]
            [bdf (get groups 0)]
            [vendor (get groups 2)]
            [product (get groups 3)]]
        {:groups groups :bdf bdf :vendor vendor :product product :line first-line})
      matches)))


;; Given a vector of strings (which is a block from lspci output), create a map
;; of these.  The first line in the block will always contain the following:
;; PCIe bus:device.function and the [vendor-id:product-id]
;; The last string in each block contains the driver in use
(defn block-parser [block]
  (let [[firstl (first block)]]
    (get-bdf-id firstl)))


;; Filter out just PCIe devices we want based on the first line in a block
;; Usage
;;   (def output (-> (get-lspci "192.168.1.1") (. output)))
;;   (def eths (-> (lspci-parser output) (collect)))
;;   (list (map block-parser eths))
(defn collect [coll &optional [key "Ethernet"]]
  (list-comp block [block coll] (in key (first block))))


;; Edit the nova.conf file to set the pci_alias
;; We now have the means to to determine what the product and vendor ids are using a
;; combination of the above functions.  This function will only scp the nova.conf
;; from the remote host and keep a local copy.  The function does not scp the modified
;; file back to the remote machine (use smog.tests.base.scp() to do that
;;
;; Args
;;   host(str): ip address of host to issue command to
;;   name(str): a name to give the pci_alias (this will be used in the flavor as well)
;;   vid(str): the vendor id of the PCI device (Intel is "8086")
;;   pid(str): the product id of the device (NB: the VF for igb device is 1520)
;;   nova-cfg(str): If given, the path to the already copied nova.conf file
;; Return: ProcessResult object
(defn set-pci-alias [host name vid pid &optional [nova-cfg None]]
  (let [[alias "\"name\": \"{}\", \"vendor_id\": \"{}\", \"product_id\": \"{}\""]
        [pci-alias (+ "{" (.format alias name vid pid) "}")]
        [nova-conf (if (is nova-cfg None)
                     (sbase.get-nova-conf host)
                     nova-cfg)]]
    (apply sbase.set-cfg ["pci_alias" pci-alias nova-conf (+ nova-conf ".bak")] {"delim" "="})))


;; As the set-pci-alias function above, this will set the pci_passthrough_whitelist
;; key in nova.conf.  The arguments match set-pci-alias
(defn set-pci-whitelist [host vid pid &optional [nova-cfg None] [net None]]
  (let [[form "\"vendor_id\": \"{}\", \"product_id\": \"{}\", \"physical_network\": \"{}\""]
        [netw (if (is net None)
                "physnet1"
                net)]
        [whitelist (+ "{" (.format form vid pid netw) "}")]
        [nova-conf (if (is nova-cfg None)
                     (sbase.get-nova-conf host)
                     nova-cfg)]
        [args ["pci_passthrough_whitelist" whitelist nova-conf (+ nova-conf ".bak")]]]
    (apply sbase.set-cfg args {"delim" "="})))


;; Adds the PciPassthroughFilter if it isn't already there
(defn set-pci-filter [host &optional [nova-cfg None]]
  (let [[nova-conf (if (is nova-cfg None)
                     (sbase.get-nova-conf host)
                     nova-cfg)]
        [filters (sbase.get-cfg "scheduler_default_filters" nova-conf)]
        [default (+ "RetryFilter,AvailabilityZoneFilter,RamFilter,ComputeFilter,ComputeCapabilitiesFilter,"
                    "ImagePropertiesFilter,ServerGroupAntiAffinityFilter,ServerGroupAffinityFilter")]
        [def-filter (-> (filter (fn [x] (is (. x comment) None)) filters) (list) (first))]
        [line (if (is def-filter None)
                default
                (. def-filter val))]
        [final (if (in "PciPassthroughFilter" line)
                 line
                 (+ line ",PciPassthroughFilter"))]
        [args ["scheduler_default_filters" final nova-conf (+ nova-conf ".bak")]]]
    (apply sbase.set-cfg args {"delim" "="})))


;; Wrapper that calls openstack-service command
(defn openstack-service [host cmd service]
  (let [[cmd_ (.format "openstack-service {} {}" cmd service)]]
    ((apply Command [cmd_] {"host" host}))))


(defn get-args [&optional [args None]]
  (import argparse)
  (let [[parser (argparse.ArgumentParser)]]
    (apply parser.add-argument ["--grub-type"] {"help" "One of bios or efi"
                                                "default" "efi"})
    (apply parser.add-argument ["--bm"] {"help" "ip address of bare metal to setup"})
    (apply parser.add-argument ["--compute"] {"help" "IP address of compute node(s)."
                                              "nargs" "+"})
    (apply parser.add-argument ["--scheduler"] {"help" "IP address of node(s) with scheduler service"
                                                "nargs" "+"})
    {:parser parser
     :args (if args
             (.parse-args parser args)
             (.parse-args parser))}))