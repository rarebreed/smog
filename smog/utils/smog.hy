;; This is an ansible module that can be used to set up SR-IOV
;; Using the directions from https://wiki.openstack.org/wiki/SR-IOV-Passthrough-For-Networking

;; 1. Verify that we have an SR-IOV capable nic
;; 2. 

(import [smog.core.commander [Command]]
        re)

(defn get-pciinfo [host]
  """Retrieves lspci info from host"""
  (let [[kwds {"host" host "cmd" "lspci -nn"}]
        [cmd (apply Command [] kwds)]]
    (cmd)))


(defmacro for- [&rest body]
  """
  for comprehension like a real functional language.
  (for- [x (range 10)] (* x 2))
  [0l 2l 4l ...]
  """
  (let [[f (first body)]
        [s (second body)]]
    `(list-comp ~s ~f)))

    
    

