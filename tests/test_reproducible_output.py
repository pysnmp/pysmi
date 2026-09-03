#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Generated code depends only on the MIB source, not on when or where it ran."""

import subprocess
import sys
import textwrap
import unittest

from pysmi.mibinfo import source_digest

# Set iteration order for strings varies with the interpreter's hash seed, and
# the seed is fixed for the life of a process. Two compiles inside one test
# process would therefore agree even if the ordering bug were still present, so
# every determinism check here runs in a fresh interpreter under a chosen seed.
_COMPILE = textwrap.dedent(
    """
    import sys
    from pysmi import error
    from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
    from pysmi.compiler import MibCompiler
    from pysmi.parser import SmiV1CompatParser
    from pysmi.reader import CallbackReader
    from pysmi.writer import CallbackWriter

    SRC = sys.stdin.read()

    def read(mibname, context):
        if mibname != "REPRO-MIB":
            raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=None)
        return SRC

    written = {}
    codegen = PySnmpCodeGen() if sys.argv[1] == "pysnmp" else JsonCodeGen()
    compiler = MibCompiler(
        SmiV1CompatParser(),
        codegen,
        CallbackWriter(lambda name, data, ctx: written.update({name: data})),
    )
    compiler.add_sources(CallbackReader(read))
    compiler.compile("REPRO-MIB", ignoreErrors=True)
    sys.stdout.write(written["REPRO-MIB"])
    """
)

MIB = """\
REPRO-MIB DEFINITIONS ::= BEGIN

reproTable OBJECT-TYPE
    SYNTAX SEQUENCE OF ReproEntry
    ACCESS not-accessible
    STATUS mandatory
    DESCRIPTION "table"
    ::= { 1 3 6 1 4 1 99997 1 }

reproEntry OBJECT-TYPE
    SYNTAX ReproEntry
    ACCESS not-accessible
    STATUS mandatory
    DESCRIPTION "row"
    INDEX { reproAlpha }
    ::= { reproTable 1 }

ReproEntry ::= SEQUENCE {
    reproAlpha INTEGER,
    reproBravo OCTET STRING,
    reproCharlie INTEGER
}

reproAlpha OBJECT-TYPE
    SYNTAX INTEGER
    ACCESS read-only
    STATUS mandatory
    DESCRIPTION "alpha"
    ::= { reproEntry 1 }

reproBravo OBJECT-TYPE
    SYNTAX OCTET STRING
    ACCESS read-only
    STATUS mandatory
    DESCRIPTION "bravo"
    ::= { reproEntry 2 }

reproCharlie OBJECT-TYPE
    SYNTAX INTEGER
    ACCESS read-only
    STATUS mandatory
    DESCRIPTION "charlie"
    ::= { reproEntry 3 }

END
"""


def compileUnderSeed(backend, seed, source=MIB):
    """Compile *source* in a fresh interpreter running with *seed*."""
    result = subprocess.run(
        [sys.executable, "-c", _COMPILE, backend],
        input=source,
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": str(seed), "PATH": ""},
        check=True,
    )
    return result.stdout


class ReproducibleOutputTestCase(unittest.TestCase):
    """The same source compiles to the same bytes, whatever the hash seed."""

    def testPySnmpOutputIsSeedIndependent(self):
        outputs = {compileUnderSeed("pysnmp", seed) for seed in (0, 1, 7, 12345)}
        self.assertEqual(len(outputs), 1)

    def testJsonOutputIsSeedIndependent(self):
        outputs = {compileUnderSeed("json", seed) for seed in (0, 1, 7, 12345)}
        self.assertEqual(len(outputs), 1)

    def testImportedSymbolsKeepTheirOrder(self):
        # The emitted order is not alphabetical: sym_trans expands a single
        # source symbol into several, so OBJECT-TYPE contributes MibScalar,
        # MibTable, MibTableRow and MibTableColumn at the position OBJECT-TYPE
        # sorted to. What matters is that the order is the same every time.
        def importLines(seed):
            return [line for line in compileUnderSeed("pysnmp", seed).splitlines() if "importSymbols(" in line]

        reference = importLines(0)
        self.assertTrue(reference)
        for seed in (1, 7, 12345):
            self.assertEqual(importLines(seed), reference)

    def testExportedSymbolsAreSorted(self):
        for line in compileUnderSeed("pysnmp", 0).splitlines():
            if "exportSymbols(" not in line:
                continue
            args = line.split("(", 1)[1].rsplit(")", 1)[0].split(", ")
            names = [a.split("=")[0] for a in args[1:]]
            self.assertEqual(names, sorted(names), line)


class HeaderTestCase(unittest.TestCase):
    """The header identifies the source instead of the build."""

    def setUp(self):
        self.header = compileUnderSeed("pysnmp", 0).splitlines()[:5]

    def testHeaderCarriesSourceDigest(self):
        self.assertIn(f"# Source digest {source_digest(MIB)}", self.header)

    def testHeaderHasNoBuildTimestamp(self):
        # "Produced by pysmi-<version>" stays; the clock reading does not.
        produced = [line for line in self.header if line.startswith("# Produced by")]
        self.assertEqual(len(produced), 1)
        self.assertNotIn(" at ", produced[0])

    def testHeaderHasNoInterpreterVersion(self):
        self.assertFalse([line for line in self.header if "Using Python version" in line])

    def testDigestFollowsTheSource(self):
        changed = MIB.replace('DESCRIPTION "alpha"', 'DESCRIPTION "altered"')
        self.assertIn(
            f"# Source digest {source_digest(changed)}",
            compileUnderSeed("pysnmp", 0, source=changed).splitlines()[:5],
        )


class SourceDigestTestCase(unittest.TestCase):
    """The digest names the ASN.1 text, not one platform's copy of the bytes."""

    def testLineEndingsDoNotChangeTheDigest(self):
        lf = "MODULE ::= BEGIN\nEND\n"
        self.assertEqual(source_digest(lf.replace("\n", "\r\n")), source_digest(lf))
        self.assertEqual(source_digest(lf.replace("\n", "\r")), source_digest(lf))

    def testDifferentSourcesDigestDifferently(self):
        self.assertNotEqual(source_digest("A\n"), source_digest("B\n"))

    def testDigestIsAlgorithmPrefixed(self):
        digest = source_digest("A\n")
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), len("sha256:") + 64)


if __name__ == "__main__":
    unittest.main()
