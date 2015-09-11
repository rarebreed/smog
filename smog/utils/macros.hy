"""
Contains useful macros and helper functions that are missing in the core hy implementation
"""

(import [pyrsistent :as pyr]
        [pyrsistent [pvector pmap pset PRecord field]])

(defn isnt [x y]
  (-> (is x y) not))

(defmacro iv [&rest args]
  `(pyr.v ~@args))

(defmacro im [&rest args]
  `(pyr.m ~@args))

(defmacro iset [&rest args]
  `(pyr.s ~@args))


(defn last [s]
  (get s -1))


(defn not= [l r]
  (not (= l r)))

(defn not-is [x]
  (not (is x None)))

;; This reader is a short-hand for (apply foo [args] kwargs)
;; Usage:
;;   #@(Command ["ls -al"] {"host"
(defreader a [body]
  (let [[[fn-name args kwargs] body]]
    `(apply ~fn-name ~args ~kwargs)))


(defn split [s]
  """Splits a sequence into (head tail)"""
  (pyr.v (first s) (pvector (rest s))))


(defn set-meta- [obj meta]
  """A more useful macro that returns a defn.  However, you can also specify
     immediately after the docstring a dictionary with keywords :pre and :post
     whose values are a list of functions to apply for preconditions and
     post conditions respectively.

     Also, this macro allows for type hints.  The dictionary may also include
     a keyword :types, whose value is a dictionary of argument names to types.
     For example:

     (defn foo [age]
       {:types {'age' int}}
       ...)
  """
  (setattr obj meta))


(defmacro defn+ [&rest body]
  """
  This macro will create a new defn with some additional features.  After the
  docstring, an optional metadata map (actually a MetaData object) can be
  given.  The metadata map consists of the following:

  - :pre a plist of functions that can be called against arguments
  - :post a plist of functions that can be called against the return value
  - :args a PRecord of argname->type
  - :ret the type of the return value
  - :meta a free form pmap that can contain whatever the user wants

  The list form is therefore:
    defn+
    name
    arguments
    docstring?
    metadata?
    body
  """)
(defmacro defn+ [&rest body]
  (with-gensyms [fname args]
    `(let [[~fname ~(first body)]
           [~args ~(second body)]]
       (print fname ~args))))
