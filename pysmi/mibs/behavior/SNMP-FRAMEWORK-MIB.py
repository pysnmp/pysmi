# RFC 3411 section 5 and the SnmpEngineID DESCRIPTION clause give an algorithm
# for an engine to derive its own identifier when an operator configures none:
# pysnmp's enterprise number, then whatever local properties distinguish this
# engine from another on the same host. An initial value an implementation
# computes at import time is not something the module states, so it is written
# here.

import os as _os

_defaultValue = [128, 0, 79, 184, 5]

try:
    # Base the engine ID on the local system name.
    _defaultValue += [ord(x) for x in _os.uname()[1][:16]]
except Exception:  # noqa: BLE001, S110 - a platform without uname() contributes nothing
    pass

try:
    # ...and on the process, so two engines on one host still differ.
    _defaultValue += [_os.getpid() >> 8 & 0xFF, _os.getpid() & 0xFF]
except Exception:  # noqa: BLE001, S110 - best-effort seed, as above
    pass

# ...and on an address, so two engines in one process still differ.
_defaultValue += [id(_defaultValue) >> 8 & 0xFF, id(_defaultValue) & 0xFF]

SnmpEngineID.defaultValue = OctetString(_defaultValue).asOctets()
