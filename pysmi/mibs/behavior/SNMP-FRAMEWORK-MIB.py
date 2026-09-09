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

# A fragment runs after the module built its objects, so the syntax the scalar
# already holds was constructed while defaultValue was unset and is valueless.
# Rebuild it, now that the class states a default. pysnmp reads this one as a
# value rather than as a schema -- MibScalarInstance takes snmpEngineID.syntax
# in pysnmp/smi/mibs/instances/__SNMP-FRAMEWORK-MIB.py, and config.py answers
# with it for contextEngineId.
snmpEngineID.syntax = SnmpEngineID()


# RFC 3411's snmpEngineTime DESCRIPTION makes the object the seconds elapsed
# since snmpEngineBoots last changed, so what an engine stores is the instant
# it booted and what it answers with is the difference. SMIv2 states the range
# and the units; that the read is relative to the stored value is prose, and
# the arithmetic belongs to whatever holds the value.
#
# pysnmp puts it in clone(), which is where it reads the object -- see the
# SnmpEngineTime of its own hand-edited copy of this module. That class is not
# exported and exists only as this scalar's syntax, so it is private here.

import time as _time


def _clone(self, *args, **kwargs):
    if not args:
        try:
            args = (_time.time() - self,)
        except Exception:  # noqa: BLE001, S110 - no value stored yet, so clone bare
            pass

    return Integer32.clone(self, *args, **kwargs)


_SnmpEngineTime = type("SnmpEngineTime", (Integer32,), {"clone": _clone})

# Carry the constraints the ASN.1 stated rather than restating them: the range
# is the module's to say, and a fragment that repeated it here would be a copy
# to keep in step. Re-seeding is required for the same reason as above -- the
# scalar was built before this ran.
snmpEngineTime.syntax = _SnmpEngineTime().subtype(
    subtypeSpec=snmpEngineTime.syntax.subtypeSpec
)
