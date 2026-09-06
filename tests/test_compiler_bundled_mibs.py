#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Which copy of a module gets compiled when more than one source has it.

pysmi's bundled base MIBs are asked before every add_sources reader, so a
distribution's /usr/share/snmp/mibs cannot quietly substitute a base MIB
frozen years ago for the copy pinned to its RFC. See pysnmp/pysmi#113.

For a bundled name the newest MODULE-IDENTITY wins outright, and that order
only breaks the tie; for everything else source order is the whole rule. The
split is pysnmp/pysmi#133: pysmi may adjudicate between two copies of a module
it pins to an RFC, and must not between two copies of a vendor module, where
the caller's order is the only statement of which one they meant.
"""

import importlib.resources
import os
import tempfile
import time
import unittest

from pysmi.codegen import JsonCodeGen
from pysmi.compiler import (
    PRECEDENCE_EQUAL_REVISIONS,
    PRECEDENCE_NEWEST_REVISION,
    PRECEDENCE_NO_REVISION,
    PRECEDENCE_NOT_BUNDLED,
    MibCompiler,
    bundled_mib_names,
    revision_of,
)
from pysmi.mibinfo import source_digest
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader
from pysmi.searcher import AnyFileSearcher
from pysmi.writer import CallbackWriter, FileWriter
from scripts import update_bundled_mibs

BUNDLED_PACKAGE = "pysmi.mibs.asn1"

#: A bundled module carrying no MODULE-IDENTITY, so only source order can
#: decide between two copies of it.
UNSTAMPED = "SNMPv2-CONF"


def stamped(name, lastUpdated):
    """A one-module MIB whose only variable is its MODULE-IDENTITY revision."""
    return f"""{name} DEFINITIONS ::= BEGIN

IMPORTS
    MODULE-IDENTITY
        FROM SNMPv2-SMI;

testModule MODULE-IDENTITY
    LAST-UPDATED "{lastUpdated}"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "A module that exists to carry a revision."
    ::= {{ 1 3 6 1 4 1 99999 }}

END
"""


class RevisionOfTestCase(unittest.TestCase):
    """Reading LAST-UPDATED off the text, without parsing the module."""

    def testTheFourDigitYearFormIsReadAsWritten(self):
        self.assertEqual(
            "200605020000Z", revision_of(stamped("A-MIB", "200605020000Z"))
        )

    def testTheTwoDigitYearFormIsWidened(self):
        # RFC 2578 Section 2 reads 96 as 1996, so it has to sort below 2006
        # rather than above it on a plain string compare.
        self.assertEqual("199605270000Z", revision_of(stamped("A-MIB", "9605270000Z")))
        self.assertLess(revision_of(stamped("A-MIB", "9605270000Z")), "200605020000Z")

    def testAModuleWithNoModuleIdentityHasNoRevision(self):
        self.assertIsNone(revision_of("A-MIB DEFINITIONS ::= BEGIN\nEND\n"))


class SourceOrderTestCase(unittest.TestCase):
    """The bundle is asked first, and add_sources readers in the order given."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.written = {}
        self.compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda n, d, ctx: self.written.update({n: d})),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, directory, mibname, text):
        with open(os.path.join(directory, mibname), "w") as fp:
            fp.write(text)
        return text

    def testBundledMibsAreRegisteredAsAPrioritySourceByDefault(self):
        self.assertEqual(1, len(self.compiler._priority_sources))
        self.assertEqual([], self.compiler._sources)

    def testUseBundledMibsFalseRegistersNoPrioritySource(self):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *a: None),
            useBundledMibs=False,
        )
        self.assertEqual([], compiler._priority_sources)

    def testAUserSourceWithNothingFallsBackToTheBundledCopy(self):
        self.compiler.add_sources(FileReader(self._tmp.name))
        processed = self.compiler.compile(UNSTAMPED, ignoreErrors=True)
        self.assertEqual("compiled", processed[UNSTAMPED])

    def testWithoutBundlingAMissingBaseMibStaysMissing(self):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *a: None),
            useBundledMibs=False,
        )
        compiler.add_sources(FileReader(self._tmp.name))
        processed = compiler.compile(UNSTAMPED, ignoreErrors=True)
        self.assertEqual("missing", processed[UNSTAMPED])

    def testTheBundledCopyWinsOverAUserSourceWithNothingNewer(self):
        # Reversed from what this asserted before pysnmp/pysmi#133: a user
        # source used to win unconditionally. It no longer does, because the
        # copy a distribution ships is far more often years stale than
        # deliberately preferred, and SNMPv2-CONF carries no revision for the
        # newest-wins rule to consider.
        #
        # Every compiled module carries a "Source digest" comment of the exact
        # ASN.1 text it was read from (see pysnmp/pysmi#63) -- the one signal
        # that says which copy was used, since the symtable codegen adds the
        # same imports boilerplate to every module's output regardless.
        self.write(
            self._tmp.name, UNSTAMPED, f"{UNSTAMPED} DEFINITIONS ::= BEGIN\nEND\n"
        )
        bundled = (importlib.resources.files(BUNDLED_PACKAGE) / UNSTAMPED).read_text()

        self.compiler.add_sources(FileReader(self._tmp.name))
        self.compiler.compile(UNSTAMPED, ignoreErrors=True)

        self.assertIn(source_digest(bundled), self.written[UNSTAMPED])

    def testPrioritySourcesAreAskedBeforeEveryAddSourcesReader(self):
        calls = []

        class RecordingReader:
            def __init__(self, label):
                self.label = label

            def get_data(self, mibname, **options):
                calls.append(self.label)
                from pysmi import error

                raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=self)

            def clear_cache(self):
                pass

            def __str__(self):
                return self.label

        compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None)
        )
        compiler.add_priority_sources(RecordingReader("priority"))
        compiler.add_sources(RecordingReader("primary"))
        compiler.compile("NO-SUCH-MIB", ignoreErrors=True)

        self.assertEqual(["priority", "primary"], calls)

    def testTheFirstAddSourcesReaderThatHasAVendorModuleSupplesIt(self):
        second = tempfile.TemporaryDirectory()
        self.addCleanup(second.cleanup)

        first = self.write(
            self._tmp.name, "VENDOR-MIB", stamped("VENDOR-MIB", "200001010000Z")
        )
        self.write(second.name, "VENDOR-MIB", stamped("VENDOR-MIB", "202601010000Z"))

        self.compiler.add_sources(FileReader(self._tmp.name), FileReader(second.name))
        self.compiler.compile("VENDOR-MIB", ignoreErrors=True)

        # The newer revision in the second source does not win: pysmi bundles
        # no VENDOR-MIB, so it has no standing to call one copy the better.
        self.assertIn(source_digest(first), self.written["VENDOR-MIB"])


class NewestRevisionWinsTestCase(unittest.TestCase):
    """For a bundled name only, the newest MODULE-IDENTITY beats source order."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.written = {}
        # A bundled module that carries a MODULE-IDENTITY, so the newest-wins
        # rule has something to compare.
        self.mibname = "SNMPv2-MIB"
        self.compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda n, d, ctx: self.written.update({n: d})),
        )
        self.compiler.add_sources(FileReader(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text):
        with open(os.path.join(self._tmp.name, self.mibname), "w") as fp:
            fp.write(text)
        return text

    def testAUserSourceWithANewerRevisionWins(self):
        newer = self.write(stamped(self.mibname, "202601010000Z"))
        self.compiler.compile(self.mibname, ignoreErrors=True)
        self.assertIn(source_digest(newer), self.written[self.mibname])

    def testAUserSourceWithAnOlderRevisionLoses(self):
        self.write(stamped(self.mibname, "199001010000Z"))
        bundled = (
            importlib.resources.files(BUNDLED_PACKAGE) / self.mibname
        ).read_text()
        self.compiler.compile(self.mibname, ignoreErrors=True)
        self.assertIn(source_digest(bundled), self.written[self.mibname])

    def testTheLosingCopyIsNamedOnTheStatus(self):
        self.write(stamped(self.mibname, "199001010000Z"))
        processed = self.compiler.compile(self.mibname, ignoreErrors=True)
        # Readers report a URL, so the loser is named the way it was read.
        self.assertEqual(
            (f"file://{os.path.join(self._tmp.name, self.mibname)}",),
            processed[self.mibname].shadowed,
        )
        self.assertEqual(
            f"package://{BUNDLED_PACKAGE}/{self.mibname}", processed[self.mibname].path
        )

    def testOnlyOneSourceHavingItShadowsNothing(self):
        processed = self.compiler.compile(self.mibname, ignoreErrors=True)
        self.assertEqual((), processed[self.mibname].shadowed)

    def testStrictSourcesFailsTheMibInsteadOfChoosing(self):
        self.write(stamped(self.mibname, "199001010000Z"))
        processed = self.compiler.compile(
            self.mibname, ignoreErrors=True, strictSources=True
        )
        self.assertEqual("failed", processed[self.mibname])


class RecompileFromAChangedSourceTestCase(unittest.TestCase):
    """A source whose content changed is recompiled, whatever its mtime.

    Reproduces the review finding on pysnmp/pysmi#123: only the digest of what
    was actually compiled distinguishes two copies, so the freshness check has
    to consult it rather than trusting mtime. The module here is deliberately
    one pysmi does not bundle, so source precedence plays no part.
    """

    def testAChangedSourceIsRecompiledEvenWithAnOlderMtime(self):
        src = tempfile.TemporaryDirectory()
        dst = tempfile.TemporaryDirectory()
        self.addCleanup(src.cleanup)
        self.addCleanup(dst.cleanup)

        path = os.path.join(src.name, "TEST-DIGEST-MIB")
        first = stamped("TEST-DIGEST-MIB", "200001010000Z")
        with open(path, "w") as fp:
            fp.write(first)

        reader = FileReader(src.name)
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            FileWriter(dst.name).set_options(suffix=".json"),
        )
        compiler.add_sources(reader)
        compiler.add_searchers(AnyFileSearcher(dst.name).set_options(exts=[".json"]))

        processed = compiler.compile("TEST-DIGEST-MIB", ignoreErrors=True)
        self.assertEqual("compiled", processed["TEST-DIGEST-MIB"])

        output = os.path.join(dst.name, "TEST-DIGEST-MIB.json")
        with open(output) as fp:
            self.assertIn(source_digest(first), fp.read())

        second = stamped("TEST-DIGEST-MIB", "202601010000Z")
        with open(path, "w") as fp:
            fp.write(second)
        # Older than the compiled output: a source is under no obligation to
        # be freshly touched for its content to have changed.
        os.utime(path, (time.time() - 1000, time.time() - 1000))
        reader.clear_cache()

        processed = compiler.compile("TEST-DIGEST-MIB", ignoreErrors=True)
        self.assertEqual("compiled", processed["TEST-DIGEST-MIB"])

        with open(output) as fp:
            self.assertIn(source_digest(second), fp.read())


if __name__ == "__main__":
    unittest.main()


class PrecedenceIsReportedTestCase(unittest.TestCase):
    """Every choice between two copies says which rule made it.

    Reported on pysnmp/pysmi#155: the outcome was visible but the reason was
    not, so a module resolving to pysmi's own copy read as a defect rather
    than as the documented rule doing its job.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None)
        )
        self.compiler.add_sources(FileReader(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, mibname, text):
        with open(os.path.join(self._tmp.name, mibname), "w") as fp:
            fp.write(text)
        return text

    def bundled(self, mibname):
        return (importlib.resources.files(BUNDLED_PACKAGE) / mibname).read_text()

    def testTheNewestRevisionIsNamedAsTheReason(self):
        self.write("SNMPv2-MIB", stamped("SNMPv2-MIB", "199001010000Z"))
        processed = self.compiler.compile("SNMPv2-MIB", ignoreErrors=True)
        self.assertEqual(PRECEDENCE_NEWEST_REVISION, processed["SNMPv2-MIB"].precedence)

    def testAnUndatedCopyIsNamedAsTheReason(self):
        # Not "the bundled copy is better" but "nothing here can be compared":
        # SNMPv2-CONF carries no MODULE-IDENTITY, so source order decides and
        # the bundled copy is asked first.
        self.write(UNSTAMPED, f"{UNSTAMPED} DEFINITIONS ::= BEGIN\nEND\n")
        processed = self.compiler.compile(UNSTAMPED, ignoreErrors=True)
        self.assertEqual(PRECEDENCE_NO_REVISION, processed[UNSTAMPED].precedence)

    def testOneUndatedCopyDropsTheWholeModuleToSourceOrder(self):
        # The comparison needs a revision on every copy found, not just on the
        # bundled one -- an undated copy cannot be placed against a dated one.
        self.write("SNMPv2-MIB", "SNMPv2-MIB DEFINITIONS ::= BEGIN\nEND\n")
        processed = self.compiler.compile("SNMPv2-MIB", ignoreErrors=True)
        self.assertEqual(PRECEDENCE_NO_REVISION, processed["SNMPv2-MIB"].precedence)

    def testEqualRevisionsAreNamedAsTheReason(self):
        sameRevision = revision_of(self.bundled("SNMPv2-MIB"))
        self.write("SNMPv2-MIB", stamped("SNMPv2-MIB", sameRevision))
        processed = self.compiler.compile("SNMPv2-MIB", ignoreErrors=True)
        self.assertEqual(PRECEDENCE_EQUAL_REVISIONS, processed["SNMPv2-MIB"].precedence)

    def testAModulePysmiDoesNotBundleIsNamedAsSourceOrder(self):
        second = tempfile.TemporaryDirectory()
        self.addCleanup(second.cleanup)

        self.write("VENDOR-MIB", stamped("VENDOR-MIB", "200001010000Z"))
        with open(os.path.join(second.name, "VENDOR-MIB"), "w") as fp:
            fp.write(stamped("VENDOR-MIB", "202601010000Z"))

        self.compiler.add_sources(FileReader(second.name))
        processed = self.compiler.compile("VENDOR-MIB", ignoreErrors=True)

        self.assertEqual(PRECEDENCE_NOT_BUNDLED, processed["VENDOR-MIB"].precedence)

    def testNothingShadowedLeavesNoReasonToGive(self):
        processed = self.compiler.compile("SNMPv2-MIB", ignoreErrors=True)
        self.assertEqual("", processed["SNMPv2-MIB"].precedence)


class PreferConfiguredSourcesTestCase(unittest.TestCase):
    """preferConfiguredSources settles what the revisions do not.

    The bundle stays a source and the newest-wins rule stays authoritative;
    only the cases the revisions cannot decide -- an undated copy, or two
    copies carrying the same revision -- change hands. See pysnmp/pysmi#155.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.written = {}
        self.compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda n, d, ctx: self.written.update({n: d})),
            preferConfiguredSources=True,
        )
        self.compiler.add_sources(FileReader(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, mibname, text):
        with open(os.path.join(self._tmp.name, mibname), "w") as fp:
            fp.write(text)
        return text

    def bundled(self, mibname):
        return (importlib.resources.files(BUNDLED_PACKAGE) / mibname).read_text()

    def testAnUndatedModuleGoesToTheConfiguredSource(self):
        mine = self.write(UNSTAMPED, f"{UNSTAMPED} DEFINITIONS ::= BEGIN\nEND\n")
        self.compiler.compile(UNSTAMPED, ignoreErrors=True)
        self.assertIn(source_digest(mine), self.written[UNSTAMPED])

    def testTheBundledCopyStillWinsOnANewerRevision(self):
        self.write("SNMPv2-MIB", stamped("SNMPv2-MIB", "199001010000Z"))
        self.compiler.compile("SNMPv2-MIB", ignoreErrors=True)
        self.assertIn(
            source_digest(self.bundled("SNMPv2-MIB")), self.written["SNMPv2-MIB"]
        )

    def testAConfiguredSourceStillWinsOnANewerRevision(self):
        newer = self.write("SNMPv2-MIB", stamped("SNMPv2-MIB", "202601010000Z"))
        self.compiler.compile("SNMPv2-MIB", ignoreErrors=True)
        self.assertIn(source_digest(newer), self.written["SNMPv2-MIB"])

    def testTheBundleStillFillsAGapTheConfiguredSourceLeaves(self):
        processed = self.compiler.compile(UNSTAMPED, ignoreErrors=True)
        self.assertEqual("compiled", processed[UNSTAMPED])


class BundleShapeIsWhatTheDocsSayTestCase(unittest.TestCase):
    """The counts stated in mibdump's --help and guide, checked against the
    bundle itself.

    "34 of the 302 bundled modules carry no MODULE-IDENTITY" is load-bearing
    prose: it is why --prefer-mib-source exists. Adding to the bundle without
    updating pysmi/scripts/mibdump.py, docs/source/mibdump.rst and
    docs/source/bundled-mibs.rst would leave them quietly wrong, so the numbers
    are asserted rather than trusted.
    """

    def testTheBundleIsThreeHundredAndTwoModulesThirtyFourOfThemUndated(self):
        names = bundled_mib_names(BUNDLED_PACKAGE)
        undated = {
            name
            for name in names
            if revision_of(
                (importlib.resources.files(BUNDLED_PACKAGE) / name).read_text()
            )
            is None
        }

        self.assertEqual(302, len(names))
        self.assertEqual(34, len(undated))
        self.assertIn("SNMPv2-SMI", undated)

    def testEveryUndatedBundledModulePredatesModuleIdentity(self):
        """An undated module is used over the caller's copy, with no comparison.

        That is only safe while every one of them is text an RFC froze -- a
        pre-SMIv2 module, or an SMI module proper. One that is still revised
        upstream would shadow a caller's better copy for good, so the property
        is asserted here rather than left to the manifest reviewer.
        """
        manifest = update_bundled_mibs.manifest()

        for name in sorted(bundled_mib_names(BUNDLED_PACKAGE)):
            text = (importlib.resources.files(BUNDLED_PACKAGE) / name).read_text()
            if revision_of(text) is not None:
                continue

            with self.subTest(mib=name):
                # IANA and IEEE 802.1 revise their modules; an undated one from
                # either would be exactly the trap described above.
                self.assertIn(manifest[name]["source"], ("rfc", "local"))
