(import [smog.core.commander [Command]])
(import [smog.core.downloader [Downloader]])
(import [smog.glance :as glance])

(defn make-centos-image [host stack]
  """
  Downloads and installs a centos 6 qcow image, creating a glance image with it
  """
  ;; Download the centos image
  (let [[img-name "CentOS-6-x86_64-GenericCloud.qcow2"]
        [url "http://cloud.centos.org/centos/6/images/CentOS-6-x86_64-GenericCloud.qcow2"]
        [cmd (apply Command [(.format "wget {}" url)] {"host" host})]   ;; Create Command object
        [res (cmd)]                                                     ;; execute command
        [img-res (glance.create-image stack.glance img-name "centos6")]] ;; create a glance image
    img-res))


(defn get-img [stack &optional [name "centos6"]]
  """
  Tries to boot a qcow image larger than flavor size.  It should fail because
  the flavor chosen will use a disk size smaller than the image itself.
  """
  ;; Get a list of images, look for
  (let [[flt (fn [x] (= name (. x name)))]
        [img (filter flt (glance.glance-image-list stack.glance))]]
    img))


(defn boot-bad-instance [stack &optional [flv "1"] [img "centos6"]]
  """Boots an instance with a tiny flavor, which is too small for the given image
  """)

