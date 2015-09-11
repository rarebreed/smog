"""
This module creates a class that can essentially duplicate a tail command.  A
Handler class (which is meant to be overridden) is used for any kind of logic.
For example, you might want to tail /var/log/nova/nova-compute.log
to look for a specific pattern, and if it finds it, do something like fail it
"""
from abc import abstractmethod

__author__ = 'stoner'

import sys
import threading
import multiprocessing
from abc import ABCMeta
import re
from functools import wraps

from smog.core.exceptions import ArgumentError
from smog.core.commander import Command, ProcessResult
from smog.core.logger import glob_logger

con_type = "thread"
if con_type == "thread":
    concurrency = threading.Thread
else:
    concurrency = multiprocessing.Process

magic = "==magic-fail=="


def freader(watched, que, seek_end=True, log=sys.stdout, fail=magic):
    """
    Opens up the watched object for reading.  This object must have an open,
    close, and readline method. This function will be run in a separate process

    :param watched: (str) Path to a file that will be opened read-only
    :param que: (multiprocessing.Queue) Queue that will be used to communicate
                between freader and monitor
    :param seek_end: If true, seek to the end of the file before reading
    :param log: A file object or something with a write method
    :return:
    """
    def _read(fobj):
        if seek_end:
            try:
                fobj.seek(0, 2)
            except:
                pass

        keep_going = True
        while keep_going:
            if fobj.closed:
                try:
                    line = fobj.read()   # get the last bit from the file
                except ValueError:
                    break
            else:
                try:
                    line = fobj.readline()
                except ValueError:
                    break

            if line:
                if isinstance(line, bytes):
                    line = line.decode()

                # Check to see if we need to break the reader thread
                if line == fail:
                    break

                if log:
                    try:
                        log.write(line)
                    except ValueError:
                        pass
                try:
                    que.put(line)
                except BrokenPipeError:
                    break
                except Exception as ex:
                    print(ex)
                    break

            if fobj.closed:
                # Try to open up again, in case we have a rotated log file
                sys.stdout.write("Reopening {}".format(watched))
                # hmmm, recursion
                freader(watched, que, seek_end=seek_end, log=log)

    if isinstance(watched, str) or isinstance(watched, bytes):
        with open(watched, "r") as tailed:
            _read(tailed)
    else:
        _read(watched)

    glob_logger.info("reader loop is finished")


def monitor(handler, que_r):
    """
    This function will consume items from the queue.  The handler callable will
    be called on each item pulled from the queue and do something accordingly.
    To break out of the loop, the handler function will raise a special
    exception of MonitoredException

    The handler is a callable that returns True if the monitor should continue
    or False if the monitor should stop.  The callable takes a single arg,
    which is a line that will be examined to determine whether it returns True
    or False

    :param handler: a predicate that takes a single string as an argument
    :param que: a multiprocessing.Queue
    :return:
    """
    keep_going = True
    while keep_going:
        try:
            empty = que_r.empty()
        except OSError:
            glob_logger.info("queue is closed")
            break
        if not empty:
            try:
                line = que_r.get()
                keep_going = handler(line)
            except OSError:
                glob_logger.debug("queue is closed")
                break
            except MonitoredException:
                break
            except Exception as ex:
                glob_logger.debug("queue error type: {}".format(ex))
                break
    glob_logger.info("monitor loop is finished")


def finish(fn):
    """

    :param fn:
    :return:
    """
    @wraps(fn)
    def inner(*args):
        self = args[0]
        line = args[1]
        if line == "==magic-fail==":
            glob_logger.info("Handler is terminating")
            self.rdr.terminate()
            return False
        return fn(*args)
    return inner


def setup_concurrent(thread):
    """
    Ugly hack to make threading.Thread look the same as multiProcessing.Process

    :return:
    """
    if not hasattr(thread, "terminate"):
        thread.terminate = lambda: None
        thread.daemon = True
    return thread


class Handler(object):
    """
    Example handler.  It takes a single argument to its init function which
    is a reader process/thread.

    This is a callable class that takes a string as an arg.  If the word 'error'
    is in the argument, it will mark itself as failed, and terminate the reader
    process

    To subclass Handler, overwrite the __call__ method in the derived Handler
    class.  The __call__ method is what searches line by line, and if a match
    is found, it will normally terminate the reader process and mark something
    in the self._result field.  The __call__ method should either return a bool
    or a MonitoredException
    """
    def __init__(self, rdr):
        self._result = None
        self.rdr = rdr
        self.counts = 1
        self.found = 0

    def check_reader(self):
        """
        Makes sure that the Handler's reader process/thread is still going.
        No point in reading if the process/thread isn't emitting any more data.
        """
        keep_going = True
        if hasattr(self.rdr, "is_alive"):
            if not self.rdr.is_alive():
                glob_logger.info("Thread has died")
                keep_going = False
        if hasattr(self.rdr, "poll"):
            if self.rdr.poll() is not None:
                glob_logger.info("Process has terminated")
                keep_going = False
        return keep_going

    @finish
    def __call__(self, line):
        if not self.check_reader():
            return False

        if "FOO" in line:
            self.result = "failed"
            sys.stdout.write("Found a match")
            self.rdr.terminate()
            return False
        return True

    @property
    def result(self):
        return self._result

    @result.setter
    def result(self, val):
        if self._result is None:
            self._result = val
        else:
            raise ArgumentError("Can only set self.result once")


class ReaderHandler(Handler):
    """
    A Handler that never quits.  Useful to get info for a long running process
    """
    def __init__(self, rdr, out):
        super(ReaderHandler, self).__init__(rdr)
        self._out = out

    @finish
    def __call__(self, line):
        self._out.write(line)
        print(self.rdr)
        return self.check_reader()


class MonitoredException(Exception):
    """
    Thrown when a Handler finds an Exception from a monitored log
    """
    pass


class ExceptionHandler(Handler):
    """
    A more sophisticated Handler that uses regexes to go through a log to find
    any python Exceptions
    """
    def __init__(self, rdr, fail=True, count=1, die=True):
        super(ExceptionHandler, self).__init__(rdr)
        self._patterns = self.base_patterns()
        self._fail = fail
        self._count = count
        self._found = 0
        self._exceptions = {}
        self._die = die
        self.base_patterns()
        self.in_q = multiprocessing.Queue()

    def base_patterns(self):
        ptn = re.compile(r"((?:\w+\.)*((?:[A-Z][a-z0-9_]+)+(Exception|Error)))")
        ptn2 = re.compile(r"raise exceptions\.(\w+)")
        return [ptn, ptn2]

    @finish
    def __call__(self, line):
        for ptn in self._patterns:
            m = ptn.search(line)
            if m:
                full, ex_type, _ = m.groups()
                if full in self._exceptions:
                    self._exceptions[full].append(line)
                else:
                    self._exceptions[full] = [line]
                self.in_q.put(self._exceptions)
                self._found += 1

                if self._fail and (self._found >= self._count):
                    self.rdr.terminate()
                    return False
                if self._die:
                    msg = "Found the following: {}".format(self._exceptions)
                    self.rdr.terminate()
                    raise MonitoredException(msg)
        return True

    @property
    def result(self):
        return self._exceptions

    @result.setter
    def result(self, val):
        if self._result is None:
            self._result = val
        else:
            raise ArgumentError("Can only set self.result once")


class _Watcher:
    __metaclass__ = ABCMeta

    def __init__(self, watched, log=None):
        self._process = None
        if isinstance(watched, ProcessResult):
            self._watched = watched.proc.stdout
            self._process = watched.proc
        else:
            self._watched = watched
        self._queue = multiprocessing.Queue()
        self._handler = None
        self._reader_proc = None
        self._monitor_proc = None
        self._log = log

    @abstractmethod
    def start_reader(self, seek_end):
        """
        This method will start off a freader
        :param seek_end:
        :param log:
        :return:
        """
        pass

    @abstractmethod
    def start_monitor(self, handler, que):
        pass

    @property
    def queue(self):
        return self._queue

    @queue.setter
    def queue(self, val):
        raise ArgumentError("Can't set queue")

    @property
    def handler(self):
        return self._handler

    @handler.setter
    def handler(self, val):
        if self._handler is None:
            self._handler = val
        else:
            raise ArgumentError("handler can only be assigned once")

    def poll(self):
        if self._process:
            return self._process.poll()


# This is where a hy macro would be nice.  We can unroll the exceptions list
# Handling every
def catcher(exceptions):
    def outer(fn):
        @wraps(outer)
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as ex:
                if ex in exceptions:
                    glob_logger.warning("Caught a {}".format(type(ex)))
                else:
                    raise ex
        return inner
    return outer


class Watcher(_Watcher):
    """
    This class will monitor a log file or a ProcessResult object like from
    Command("journalctl -f")()

    It takes one argument, which can be a file-like object or a ProcessResult object.
    If a ProcessResult object is used, the stdout must use PIPE (which is default).
    Otherwise, you must pass
    """
    __metaclass__ = ABCMeta

    def __init__(self, watched, log=None):
        super(Watcher, self).__init__(watched, log=log)

    def start_reader(self, que=None, seek_end=True, log=None):
        """
        This method will start off a freader process that will produce lines
        for the que.  This is the thread/process that produces items for the queue

        :param seek_end:
        :param log:
        :return:
        """
        if log is None:
            log = self._log
        if que is None:
            que = self._queue
        # Kick off the freader process
        rdr = concurrency(target=freader, args=(self.watched, que),
                          kwargs={"seek_end": seek_end, "log": log})
        self._reader_proc = setup_concurrent(rdr)
        return rdr

    @property
    def watched(self):
        return self._watched

    @watched.setter
    def watched(self, val):
        msg = "Can not change read-only value of watched to {}".format(val)
        raise ArgumentError(msg)

    def start_monitor(self, handler, que):
        """
        This will kick off a monitor() process that will consume items from the
        que, and call handler from each item in the que.  This is the thread
        or process that consumes from the queue

        :param handler: A Handler object
        :param que: a multiprocessing.queue object
        :return:
        """
        self.handler = handler
        mntr = concurrency(target=monitor, args=(handler, que))
        self._monitor_proc = setup_concurrent(mntr)
        return mntr

    @catcher(BrokenPipeError)
    def close(self, que=None):
        line = "==magic-fail=="
        if que is None:
            que = self.queue
        try:
            glob_logger.info("putting ==magic-fail== in queue")
            que.put(line)
        except AssertionError:
            glob_logger.debug("queue got AssertionError")
            pass
        except Exception as ex:
            glob_logger.debug("queue got {}".format(ex))

        glob_logger.info("closing queue")
        que.close()

        if self._process:
            glob_logger.debug("terminating watcher process")
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

            # Apparently, when the subprocess ends, the PIPE'd stdout
            # doesn't close.  So we need to shut it down so that the
            # reader thread closes
            if not self._process.stdout.closed:
                self._process.stdout.close()

        if self._log:
            glob_logger.info("closing log file")
            self._log.close()

    def __del__(self):
        if self._reader_proc:
            self._reader_proc.terminate()
        if self._monitor_proc:
            self._monitor_proc.terminate()
        if self._log:
            glob_logger.info("closing log file")
            self._log.close()


class JournalWatcher(_Watcher):
    def __init__(self, watched):
        """
        JournalWatcher does not take a file for watched, but rather a Command
        object which will run journalctl -f

        :param watched: Command object (of journalctl -f)
        :return:
        """
        super(JournalWatcher, self).__init__(watched)

    def start_reader(self, seek_end=False, log=None):
        # get the input from the ResultProcess object
        cmd = Command("journalctl -f")
        res = cmd(block=False)
        return res.proc.stdout


def make_watcher(cmd_, hcls, *args, host=None, cmd_kw=None, log=None, **kwargs):
    """
    Creates a Watcher and Handler, and adds the Watcher object to self

    :param cmd_: The command to run which will be watched
    :param hcls: a Handler class (not object)
    :param args: passed through to hcls(*args, **kwargs)
    :param host: the host to run cmd on (defaults to localhost)
    :param cmd_kw: a dict applied to Command object
    :param log: defaults to sys.stdout, but can be a file-like object
    :param kwargs: passed through to hcls(*args, **kwargs)
    :return: Watcher object
    """
    if isinstance(cmd_, str):
        if host is None:
            cmd_ = Command(cmd_)
        else:
            cmd_ = Command(cmd_, host=host)

    default = {"block": False}
    if cmd_kw is None:
        cmd_kw = default
    else:
        cmd_kw.update(default)

    res = cmd_(**cmd_kw)
    watcher = Watcher(res, log=log)
    rdr_proc = watcher.start_reader()

    # yuck, side effects
    _ = [kwargs.pop(arg) for arg in ["log", "cmd_kw", "host"] if arg in kwargs]
    handler = hcls(rdr_proc, *args, **kwargs)

    # start the consumer that will read from the que
    mntr_proc = watcher.start_monitor(handler, watcher.queue)
    rdr_proc.start()
    mntr_proc.start()
    return watcher

if __name__ == "__main__":
    cmd = Command("python -u /home/stoner/dummy.py", host="10.13.57.47", user="stoner")
    logf = open("testlog.log", "w")
    watcher = make_watcher(cmd, ReaderHandler, logf, host="10.13.57.47")
    import time
    i = 1
    while watcher.poll() is None:
        print("second = ", i)
        time.sleep(1)
        i += 1
    logf.close()

    # FIXME: replace this with a proper unittest
    # Monitor the system logs.
    # There are 6 steps for creating monitors

    if 0:
        # 1. Create the reader process
        cmd = Command("journalctl -f", host="10.8.29.58")
        res = cmd(block=False)

        # 2. Create the Watcher class
        watcher = Watcher(res)

        # 3. Create a producer process that will produce lines into the queue
        rdr_proc = watcher.start_reader(log=sys.stdout)

        # 4. Create a handler and plug it into the reader (producer) process
        # remember, the reader is subprocess 'journalctl -f' which is producing
        # lines of output to be consumed
        handler = ExceptionHandler(rdr_proc)
        #handler = Handler(rdr_proc)

        # 5. start the consumer that will read from the que
        mntr_proc = watcher.start_monitor(handler, watcher.queue)

        # 6. Kick off the reader(producer) and consumer processes
        rdr_proc.start()
        mntr_proc.start()
        import time
        time.sleep(5)
        watcher.close()