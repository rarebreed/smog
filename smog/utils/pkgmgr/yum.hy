"""
This module will contain functionality related to installing packages on RHEL based distros
ie Centos, Fedora, and RHEL.  This will include not only yum package management, but also use of
the subscription manager.

Any helper functionality such as copying public keys will be covered here as well.
"""

(import [smog.core.commander [Command]])


(defn ssh-agent []
  """

  """
  (let [[cmds ["ssh-agent" "ssh-add"]]
        [results (list-comp ((apply Command [c] {})) [c cmds])]]
    results))

(defn copy-ssh-key [host passfile]
  (let [[base-cmd  "sshpass -f {} ssh-copy-id -i -o StrictHostKeyChecking=no {}@{}"]
        [base (.format base-cmd pass-text username host)]
        [cmd (apply Command [base] {"host" host})]]
    (cmd)))


(defn yum-install [host pkgs]
  """
  Yum installs a list of packages
  """
  (let [[base-cmd "yum install -y {}"]
        [full-cmd (.format base-cmd (.join " " pkgs))]
        [res ((apply Command [] {}))]]
    res))