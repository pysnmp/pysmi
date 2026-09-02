"""PySMI, a pure-Python SNMP MIB parser and code generator."""

import logging

# http://www.python.org/dev/peps/pep-0396/
__version__ = "1.2.0"

# A library should not configure logging for the application embedding it, and
# should not emit "No handlers could be found" either.
logging.getLogger(__name__).addHandler(logging.NullHandler())
