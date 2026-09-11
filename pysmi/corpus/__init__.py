#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Building a MIB corpus from many source namespaces.

A corpus is what a whole collection of MIBs compiles to: the ASN.1 as
published, the compiled modules in each format that is wanted, and an index
saying which module owns which OID. :py:class:`~pysmi.corpus.driver.CorpusDriver`
builds one from a declared, ordered set of source namespaces, deterministically
-- the same inputs give the same bytes out, with no network and no directory
that is both read and written.
"""

from pysmi.corpus.driver import (
    CorpusDriver,
    CorpusOutputs,
    CorpusReport,
    Destination,
    check_disjoint,
    check_expectations,
)
from pysmi.corpus.namespace import (
    DEFAULT_TIER,
    EXPECTATIONS,
    TIERS,
    Manifest,
    Namespace,
    load_manifest,
    read_manifest,
)

__all__ = [
    "DEFAULT_TIER",
    "EXPECTATIONS",
    "TIERS",
    "CorpusDriver",
    "CorpusOutputs",
    "CorpusReport",
    "Destination",
    "Manifest",
    "Namespace",
    "check_disjoint",
    "check_expectations",
    "load_manifest",
    "read_manifest",
]
