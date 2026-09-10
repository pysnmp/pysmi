#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Repair and compile the bundled ASN.1 MIBs while the wheel is built.

Two things happen here, in order. First the repairs in ``scripts/mib-patches``
are applied to the bundled ASN.1: the repository holds each module as its
publisher printed it, and the distribution holds pysmi's opinion of it. Then
that repaired ASN.1 is compiled into pysnmp modules, so the two halves of what
a consumer installs are the same text.

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

#: Where the ASN.1 lives, in the tree and in the wheel alike.
ASN1 = "pysmi/mibs/asn1"

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

        self._asn1 = patch_asn1(Path(self.root))

        # Every module, not only the twelve that changed, so that what the
        # wheel carries and what was compiled below are the same bytes by
        # construction rather than by the two agreeing about which files the
        # patches touched.
        for staged in sorted(self._asn1.iterdir()):
            build_data["force_include"][str(staged)] = f"{ASN1}/{staged.name}"

        self._tmp = build(Path(self.root), self._asn1)

        build_data["force_include"][str(self._tmp)] = DEST

    def finalize(self, version: str, build_data: dict[str, Any], artifact: str) -> None:
        """Drop the staging directories once the wheel holds a copy."""
        for attr in ("_asn1", "_tmp"):
            staged = getattr(self, attr, None)

            if staged:
                shutil.rmtree(staged, ignore_errors=True)


def patch_asn1(root: Path) -> Path:
    """Stage the bundled ASN.1 with pysmi's repairs applied.

    The tree holds each module as its publisher printed it, so that ``git diff``
    on a bundle refresh is a diff against the publisher and the repairs pysmi
    makes are visible as a diff of their own. The distribution holds the
    repaired text, because that is what a consumer installs: pysmi does not
    patch anything at read time, so a module that ships unrepaired stays
    unrepaired for everyone who reads it.

    The repairs are ``scripts/mib-patches``, which is build tooling and is not
    itself shipped. A consumer wanting a different set of them rebuilds from
    source with their own diffs there.

    Args:
        root: the repository root, holding ``pysmi/mibs/asn1``.

    Returns:
        A directory holding every bundled module, the patched ones repaired.
        The caller owns it.

    Raises:
        RuntimeError: a patch did not apply to the text in the tree, which
            means the publisher's copy and the repair have gone out of step.
    """
    sys.path.insert(0, str(root))

    from scripts.patches import APPLIED, PatchSet

    patches = PatchSet.bundled()
    out = Path(tempfile.mkdtemp(prefix="pysmi-patched-asn1-"))

    # Files only. The bundle is a flat directory of modules, and anything else
    # that has appeared in it -- a stale __pycache__, an editor's backup -- is
    # not part of it and must not be staged, since every staged entry is forced
    # into the wheel as a file.
    for source in sorted((root / ASN1).iterdir()):
        if source.is_file():
            shutil.copy2(source, out / source.name)

    for mibname in patches.modules():
        target = out / mibname

        if not target.exists():
            # A patch for a module the bundle does not carry -- one held in
            # pysmi/mibs/future, which the wheel excludes.
            continue

        text = target.read_text(encoding="utf-8", errors="replace")
        patched, status = patches.apply(mibname, text)

        if status != APPLIED:
            shutil.rmtree(out, ignore_errors=True)
            raise RuntimeError(
                f"{mibname}: its patch did not apply to the bundled text "
                f"({status or 'no patch found'}); the tree should hold the "
                "published text and scripts/mib-patches the repair"
            )

        target.write_text(patched, encoding="utf-8", newline="")

    return out


def build(root: Path, asn1: Path) -> Path:
    """Compile every bundled MIB in *asn1* into a fresh directory.

    Args:
        root: the repository root, for importing pysmi itself.
        asn1: the ASN.1 to compile -- the staging directory
            :py:func:`patch_asn1` produced, so the modules are rendered from
            the same repaired text the wheel ships.

    Returns:
        A temporary directory holding one pysnmp module per bundled MIB, plus
        the ``__init__.py`` that makes it a package. The caller owns it.

    Raises:
        RuntimeError: if any bundled module failed to compile.
    """
    sys.path.insert(0, str(root))

    from pysmi.corpus import CorpusDriver, CorpusOutputs, Namespace

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
