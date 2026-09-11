#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Published registries a corpus can be annotated from.

Each one is **taken as an input and never fetched**. A corpus build opens on
the property that it resolves nothing over the network -- a build with the
network unplugged produces the same corpus as one without -- and a registry
that changes daily, fetched at build time, would end that.

Nothing here is bundled either. These are other people's data, they are large,
and they move on their own schedule; what pysmi provides is the parsing, which
every downstream distribution otherwise writes for itself.

:py:mod:`pysmi.registry.tree` is the exception that proves it: a small table of
arcs no registry publishes, cited to the standard that defines them, and
labelled as a citation rather than as a registration so that nothing mistakes
one for the other.
"""

from pysmi.registry.pen import (
    AUTHORITY,
    ENTERPRISES,
    FIELDS,
    Registrant,
    authority_url,
    load_registry,
    parse_registry,
    reduce_registry,
)
from pysmi.registry.smi import ArcName, parse_smi_numbers
from pysmi.registry.tree import CITED, CitedArc

__all__ = [
    "AUTHORITY",
    "CITED",
    "ENTERPRISES",
    "FIELDS",
    "ArcName",
    "CitedArc",
    "Registrant",
    "authority_url",
    "load_registry",
    "parse_registry",
    "parse_smi_numbers",
    "reduce_registry",
]
