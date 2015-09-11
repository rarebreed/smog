;; Helper to create a iscsi volume and target
;; mostly taken from: https://fedoraproject.org/wiki/Scsi-target-utils_Quickstart_Guide

(import [smog.core.commander [Command]])


(defn install-deps-scsitgt [host]
  """yum installs dependencies for the scsi target"""
  (let [[deps ["scsi-target-utils" "policycoreutils-python" "targetcli"]]
        [yum (.format "yum install -y {}" (.join " " deps))]
        [cmd #a(Command [yum] {"host" host})]]
    cmd))


(defn install-deps-scsihost [host]
  """Installs dependencies for the scsi host like iscsiadm"""
  (let [[deps ["iscsi-initiator-utils"]]
        [cmd #@(Command [] {"host" host})]]


