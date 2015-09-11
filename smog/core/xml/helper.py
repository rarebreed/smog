"""
Simple XML helping utility functions
"""

__author__ = 'Sean Toner'


def get_xml_children(root, tag_list):
    """
    Takes an xml element node, and uses iter() to walk through all
    children nodes.

    :param root: The root element to begin with
    :param tag_list: an ordered sequence of tags to descend into.  The last
      item in this sequence is the basis for the return value
    :return: A dictionary of the last element in tag_list
    """
    elem = root
    for tag in tag_list:
        elem = elem.find(tag)
        print(elem)
    return {"tag": elem.tag, "attrib": elem.attrib, "text": elem.text}


def filter_xml(root, tag=None, filter_fn=None):
    """
    Returns an iterator for a given xml element tree.  It will yield whatever
    the filter_fn returns

    By default, the filter_fn will return from each element it is given, the
    tag, text, and

    :param root: an xml.etree.ElementTree object
    :param tag: An xml element tag (str)
    :param filter_fn: A function that takes an Element and returns whatever is
                      needed
    :return:
    """
    if filter_fn is None:
        def filter_fn(i):
            return i.tag, i.text, i.attrib
    for x in root.iter(tag):
        yield filter_fn(x)