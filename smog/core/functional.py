"""
This module will contain functions that help for functional style programming
"""

__author__ = 'stoner'


def add_to_map(m, kv):
    """Small helper function that can be used with accumulate

    Args:
        m: pmap
        kv: a 2 element sequence of key, value
    Returns:
        a new pmap with the added key,value pair
    """
    k, v = kv
    return m.set(k, v)


def bytes_iter():
    """returns a lazy sequence of KB, MB, GB, TB, PB, etc

    Why not just define these?  Why the trouble of building an iterator?

    A) They are more elegant
    B) It is future proof
    C) Because they arent globally defined, you cant accidentally mutate them
       (generate them)
    D) Because python needs to be more functional (less state)"""
    x = 1
    while True:
        x *= 1024
        yield x


def powers_two():
    """
    Lazy sequence to return powers of 2.
    :return:
    """
    x = 1
    while True:
        yield x
        x *= 2
