#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Compile the bundled ASN.1 MIBs into pysnmp modules while the wheel is built.

pysmi keeps the ASN.1 because it is what the compiler reads: resolving an
IMPORTS clause means parsing the imported module's source, so the text cannot
be replaced by its compiled form. What it can be joined by is that compiled
form, so that a consumer wanting to *load* one of the 210 standard modules
rather than compile it does not have to run the compiler first.

The modules are generated here rather than committed, which is what makes the
answer to "do these match the ASN.1 they came from?" trivially yes: every
distribution carries the output of this tree's code generator over this tree's
ASN.1, produced seconds earlier. There is no checked-in copy to go stale and
no digest ledger to police one.

The compile itself is :py:class:`~pysmi.corpus.driver.CorpusDriver` -- the same
driver ``mibcorpus`` runs and the same one pysnmp/mibs builds its corpus with.
pysmi's bundle is a corpus of one namespace, so there is no reason for it to
have its own compile loop: a difference between how pysmi builds the base layer
and how everyone else builds on top of it would be a difference nobody chose.
What this file still owns is what is particular to a *wheel*: which modules
cannot be generated, the package ``__init__``, and refusing to ship if
anything failed. See pysnmp/pysmi#182.
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

#: Where the generated modules land inside the wheel.
DEST = "pysmi/mibs/pysnmp"

#: A malformed OID can send the code generator round a cycle; the default
#: limit turns that into a bare RecursionError far from the MIB that caused
#: it. Same value tests/test_bundled_mibs_compile.py uses.
RECURSION_LIMIT = 20000


def _ungeneratable():
    """Modules this code generator cannot render, from the generator itself."""
    from pysmi.codegen import PySnmpCodeGen

    return frozenset(PySnmpCodeGen.constImports) - frozenset(PySnmpCodeGen.fakeMibs)


class PrecompiledMibsHook(BuildHookInterface[Any]):
    """Render ``pysmi/mibs/asn1`` into ``pysmi/mibs/pysnmp`` for the wheel."""

    PLUGIN_NAME = "precompiled-mibs"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Generate the modules and force them into the wheel."""
        if self.target_name != "wheel":
            return

        self._tmp = build(Path(self.root))

        build_data["force_include"][str(self._tmp)] = DEST

    def finalize(self, version: str, build_data: dict[str, Any], artifact: str) -> None:
        """Drop the staging directory once the wheel holds a copy."""
        tmp = getattr(self, "_tmp", None)

        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def build(root: Path) -> Path:
    """Compile every bundled MIB under *root* into a fresh directory.

    Args:
        root: the repository root, holding ``pysmi/mibs/asn1``.

    Returns:
        A temporary directory holding one pysnmp module per bundled MIB, plus
        the ``__init__.py`` that makes it a package. The caller owns it.

    Raises:
        RuntimeError: if any bundled module failed to compile.
    """
    sys.path.insert(0, str(root))

    from pysmi.corpus import CorpusDriver, CorpusOutputs, Namespace

    asn1 = root / "pysmi" / "mibs" / "asn1"

    UNGENERATABLE = _ungeneratable()

    out = Path(tempfile.mkdtemp(prefix="pysmi-precompiled-"))

    driver = CorpusDriver(
        [Namespace(name="bundled", source=str(asn1), tier="standard")],
        CorpusOutputs(notexts=str(out)),
        # The bundle is the namespace. Registering it a second time as the
        # compiler's own resolution source would have it adjudicate a module
        # against itself.
        useBundledMibs=False,
        # A module the generator always imports *from* cannot be generated:
        # the unconditional import becomes an import from itself, which can
        # never resolve. constImports is that set, and subtracting the ASN.1
        # stand-ins leaves SNMPv2-SMI, SNMPv2-TC and SNMPv2-CONF -- the
        # modules whose symbols pysnmp implements in code rather than
        # deriving from the MIB.
        #
        # Derived rather than listed, so it stays right if constImports
        # changes. Deliberately *not* the driver's default, which is
        # PySnmpCodeGen.baseMibs -- a precedence rule covering 11 further
        # modules that generate perfectly well and that consumers want. See
        # pysnmp/pysmi#196.
        stubs={"pysnmp": sorted(UNGENERATABLE)},
    )

    limit = sys.getrecursionlimit()
    # A malformed OID can send the code generator round a cycle; the default
    # limit turns that into a bare RecursionError far from the MIB that
    # caused it.
    sys.setrecursionlimit(RECURSION_LIMIT)

    try:
        report = driver.run()
    finally:
        sys.setrecursionlimit(limit)

    # The driver keeps going past a defective module and reports it, which is
    # what a corpus of MIBs nobody controls needs. A wheel is the opposite
    # case: these 210 modules are pysmi's own, so one that will not compile is
    # a release blocker rather than an inventory item.
    #
    # Dependencies outside the bundle -- RFC-1213 and the other SMIv1 import
    # targets the parser satisfies on its own -- come back "missing" and are
    # not part of what is checked.
    failed = sorted(
        f"{name} (failed)" for name in report.failed.get("notexts", {})
    ) + sorted(
        f"{name} (unprocessed)" for name in report.unprocessed.get("notexts", [])
    )

    if failed:
        shutil.rmtree(out, ignore_errors=True)
        raise RuntimeError("bundled MIBs did not compile: " + ", ".join(failed))

    (out / "__init__.py").write_text(
        '"""pysnmp modules compiled from the ASN.1 MIBs pysmi bundles.\n\n'
        "Generated at build time by ``hatch_build.py`` from ``pysmi/mibs/asn1``,\n"
        "so what is here is always that directory's compiled form.\n"
        '"""\n'
    )

    return out
