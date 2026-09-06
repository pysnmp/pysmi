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
form, so that a consumer wanting to *load* one of the 299 standard modules
rather than compile it does not have to run the compiler first.

The modules are generated here rather than committed, which is what makes the
answer to "do these match the ASN.1 they came from?" trivially yes: every
distribution carries the output of this tree's code generator over this tree's
ASN.1, produced seconds earlier. There is no checked-in copy to go stale and
no digest ledger to police one.
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

    from pysmi.codegen import PySnmpCodeGen
    from pysmi.compiler import MibCompiler
    from pysmi.parser import SmiV1CompatParser
    from pysmi.reader import FileReader
    from pysmi.writer import PyFileWriter

    asn1 = root / "pysmi" / "mibs" / "asn1"
    names = sorted(
        entry.name
        for entry in asn1.iterdir()
        if entry.is_file() and not entry.name.startswith("__")
    )

    out = Path(tempfile.mkdtemp(prefix="pysmi-precompiled-"))

    writer = PyFileWriter(str(out))
    # Wheels do not ship bytecode: pip compiles on install, against the
    # interpreter that will import it.
    writer.pyCompile = False

    compiler = MibCompiler(
        SmiV1CompatParser(),
        PySnmpCodeGen(),
        writer,
        useBundledMibs=False,
    )
    compiler.add_sources(FileReader(str(asn1)))

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(RECURSION_LIMIT)

    try:
        # ignoreErrors so that one broken module reports itself by name below
        # rather than aborting the run at whichever one the compiler reached
        # first. Dependencies outside the bundle -- RFC-1213 and the other
        # SMIv1 import targets the parser satisfies on its own -- come back
        # "missing" and are not part of what is checked.
        processed = compiler.compile(*names, ignoreErrors=True)
    finally:
        sys.setrecursionlimit(limit)

    failed = sorted(
        f"{name} ({processed.get(name, 'absent')})"
        for name in names
        if str(processed.get(name)) not in ("compiled", "untouched")
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
