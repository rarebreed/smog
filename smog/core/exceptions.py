__author__ = 'stoner'


class ArgumentError(Exception):
    pass


class ReadOnlyException(Exception):
    pass


class BootException(Exception):
    pass


class ConfigException(Exception):
    pass


class FreePageException(Exception):
    pass


class AmbiguityException(Exception):
    """
    Exception that is thrown when code can not determine what the correct
    choice should be from the given information
    """
    pass