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

__all__ = [
    "AUTHORITY",
    "ENTERPRISES",
    "FIELDS",
    "Registrant",
    "authority_url",
    "load_registry",
    "parse_registry",
    "reduce_registry",
]
