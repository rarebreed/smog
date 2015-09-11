"""
This module contains the python3 type hinting using the mypy library

Because of syntax limitations in hy, we will use wrapper functions that return the
type.
"""

from typing import Iterable, Sequence, Callable, Union, TypeVar
import pyrsistent as pyr


def make_iterable(type_):
    return Iterable[type_]


def make_sequence(type_):
    return Sequence[type_]


class MetaData(pyr.PRecord):
    """
    This is the class that represents metadata for a class (usually a function).

    Args:
      - pre: a list of functions that will be called against a particular argument
      - post: a list of functions that will be called on the return value or some other in scope data
      - args: a dictionary of argument name->type
      - ret: the type of the return value
      - source: the actual source code of the function or class
    """
    pre = pyr.field(type=list)
    post = pyr.field(type=list)
    args = pyr.field(type=(dict, type(None)), mandatory=True)
    ret = pyr.field()
    source = pyr.field()
    meta = pyr.field()