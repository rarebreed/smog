__author__ = 'stoner'

from functools import wraps
from subprocess import Popen, PIPE, STDOUT
from smog.core.commander import Command

def require_remote(progname, valid=None):
    """
    Decorator that validates some system command exists on the remote system.
    The wrapped function must contain a kwargs dictionary with the following
    keys:

    hosts: The ip address of the machine we are executing remote command on
    username: the user of the remote machine we wish to run command on

    this requires passwordless authentication using public ssh keys beforehand

    :param progname: program name to check (passed to which)

    :return:
    """
    if valid is None:
        valid = [0]

    def outer(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            cmd = "which {}".format(progname)

            if not kwargs:
                outer = require_local(progname)
                inner = outer(fn)
                return inner(*args, **kwargs)

            ip = kwargs["host"]
            if "username" not in kwargs:
                kwargs["username"] = "root"
            user = kwargs["username"]

            command = Command(cmd, host=ip, user=user)
            res = command()

            if res.returncode not in valid:
                # Try to install
                cmd = "yum install -y {}".format(progname)
                res = Command(cmd, host=ip, user=user)()
                if res.returncode not in valid:
                    msg = "{} is not on the remote machine".format(progname)
                    raise Exception(msg)
            return fn(*args, **kwargs)
        return wrapper
    return outer


def require_local(progname, valid=None):
    """
    Checks that a command exists on the local system
    :param progname: The executable name (checks which against the progname)
    :param valid: If None, use [0] as possible successes
    :return:
    """
    # Since this is a closure, the returned function will still have valid in
    # its scope
    if valid is None:
        valid = [0]

    def outer(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            cmd = "which {}".format(progname)
            proc = Popen(cmd, shell=True, stdout=PIPE, stderr=STDOUT)
            out, _ = proc.communicate()
            if proc.returncode not in valid:
                # TODO: Add ability to install this (yum whatprovides and
                #  then install)
                raise Exception("{} is not on this machine".format(progname))
            return fn(*args, **kwargs)
        return inner
    return outer


# not a decorator, but it does return a modified function
def prepartial(func, *args, **keywords):
    def newfunc(*fargs, **fkeywords):
        newkeywords = keywords.copy()
        newkeywords.update(fkeywords)
        return func(*(fargs + args), **newkeywords)
    newfunc.func = func
    newfunc.args = args
    newfunc.keywords = keywords
    return newfunc