"""PySMI, a pure-Python SNMP MIB parser and code generator."""

import logging

# http://www.python.org/dev/peps/pep-0396/
# Read by hatchling at build time, which does not accept an annotation here,
# so this deliberately stays a bare assignment.
__version__ = "2.0.1"

# A library should not configure logging for the application embedding it, and
# should not emit "No handlers could be found" either.
logging.getLogger(__name__).addHandler(logging.NullHandler())
