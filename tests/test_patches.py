#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""A patch travels with the MIB, so every caller's copy gets the fix.

The patches used to be applied by the bundle-refresh script, which reached
pysmi's own copies and nothing else. These pin the behaviour that replaced that:
a reader offers every module the patch for it, whatever source the text came
from, and says on the module's :py:class:`~pysmi.mibinfo.MibInfo` what happened.

The interesting cases are the ones that are *not* a clean forward apply --
text that already carries the patch, text the patch was never cut against, and
a patch that is not a diff at all -- because those are what applying at read
time introduces and applying at refresh time never had to face.
"""

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from pysmi import error
from pysmi.compiler import revision_of
from pysmi.mibinfo import MibInfo
from pysmi.patches import (
    ALREADY_APPLIED,
    APPLIED,
    NOT_APPLICABLE,
    UNPATCHED,
    PatchSet,
    apply_patch,
    parse_patch,
)
from pysmi.reader import FileReader
from pysmi.reader.base import AbstractReader

BUNDLED_ASN1 = Path(__file__).resolve().parent.parent / "pysmi" / "mibs" / "asn1"
BUNDLED_FUTURE = Path(__file__).resolve().parent.parent / "pysmi" / "mibs" / "future"

#: A whole small module, so a patch can be offered real MIB text rather than a
#: fragment that happens to line up.
SAMPLE = """\
TEST-MIB DEFINITIONS ::= BEGIN

IMPORTS
    OBJECT-TYPE
        FROM RFC1212;

testObject OBJECT-TYPE
    SYNTAX      INTEGER
    ACCESS      read-only
    STATUS      mandatory
    DESCRIPTION "A test."
    ::= { test 1 }

END
"""

#: Repairs SAMPLE's IMPORTS the way ``SMUX-MIB.patch`` repairs the real one.
SAMPLE_PATCH = """\
--- a/TEST-MIB
+++ b/TEST-MIB
@@ -3,7 +3,7 @@
 IMPORTS
     OBJECT-TYPE
-        FROM RFC1212;
+        FROM RFC-1212;

 testObject OBJECT-TYPE
"""


def _published(mibname: str) -> str:
    """The module as its publisher printed it, which is what the tree holds."""
    source = BUNDLED_ASN1 / mibname

    if not source.exists():
        source = BUNDLED_FUTURE / mibname

    return source.read_text(encoding="utf-8", errors="replace")


def _repaired(mibname: str) -> str:
    """The module as the wheel ships it: the tree's copy with its patch on."""
    text, status = PatchSet.bundled().apply(mibname, _published(mibname))

    if status != APPLIED:
        raise RuntimeError(f"{mibname}: its patch did not apply ({status})")

    return text


class PatchParsingTestCase(unittest.TestCase):
    """Reading a unified diff, and refusing one that is not."""

    def testHunkSidesAreSeparated(self):
        """A hunk keeps both sides, so it can be tried either way."""
        (hunk,) = parse_patch(SAMPLE_PATCH, "TEST-MIB")

        self.assertEqual(2, hunk.old_start)
        self.assertEqual(2, hunk.new_start)
        self.assertIn("        FROM RFC1212;", hunk.before)
        self.assertIn("        FROM RFC-1212;", hunk.after)
        self.assertNotIn("        FROM RFC-1212;", hunk.before)
        self.assertNotIn("        FROM RFC1212;", hunk.after)

    def testEmptyContextLineIsALine(self):
        """An empty line in a diff is context, not something to skip.

        A context line that is blank is written as a single space, and editors
        eat trailing whitespace. Dropping such a line rather than counting it
        would misalign every hunk after it, and the misalignment would show up
        as a patch that quietly stopped applying.
        """
        patch = "--- a/M\n+++ b/M\n@@ -1,3 +1,3 @@\n one\n\n-three\n+THREE\n"

        (hunk,) = parse_patch(patch, "M")

        self.assertEqual(("one", "", "three"), hunk.before)
        self.assertEqual(("one", "", "THREE"), hunk.after)

    def testUnreadableLineIsRefused(self):
        """A line that is not a diff line is a malformed patch."""
        patch = "--- a/M\n+++ b/M\n@@ -1,1 +1,1 @@\n?what\n"

        with self.assertRaises(error.PySmiPatchError):
            parse_patch(patch, "M")

    def testHunksMustRunForwards(self):
        """Hunks that overlap cannot both be applied, so the patch is refused."""
        patch = (
            "--- a/M\n+++ b/M\n"
            "@@ -5,2 +5,2 @@\n-five\n+FIVE\n six\n"
            "@@ -1,2 +1,2 @@\n-one\n+ONE\n two\n"
        )

        with self.assertRaises(error.PySmiPatchError):
            parse_patch(patch, "M")

    def testTrailingNewlineIsNotAHunkLine(self):
        """The empty string split() leaves behind is not counted as context."""
        (with_newline,) = parse_patch(SAMPLE_PATCH, "TEST-MIB")
        (without,) = parse_patch(SAMPLE_PATCH.rstrip("\n"), "TEST-MIB")

        self.assertEqual(with_newline, without)


class ApplyPatchTestCase(unittest.TestCase):
    """What happens when a patch meets text."""

    def testForwardApply(self):
        """Text the patch was cut against comes back patched."""
        out, status = apply_patch(SAMPLE, SAMPLE_PATCH, "TEST-MIB")

        self.assertEqual(APPLIED, status)
        self.assertIn("FROM RFC-1212;", out)
        self.assertNotIn("FROM RFC1212;", out)

    def testApplyingTwiceIsDetectedRatherThanRepeated(self):
        """Offering the patch to its own output reports already-applied.

        This is the case that applying at read time introduces: pysmi's bundled
        copies were patched when they were fetched, so the same patch is offered
        to text that already carries it on every single read.
        """
        once, _ = apply_patch(SAMPLE, SAMPLE_PATCH, "TEST-MIB")
        twice, status = apply_patch(once, SAMPLE_PATCH, "TEST-MIB")

        self.assertEqual(ALREADY_APPLIED, status)
        self.assertEqual(once, twice)

    def testTextThePatchWasNotCutAgainstIsLeftAlone(self):
        """Context that does not match is the ordinary case, not an error."""
        other = SAMPLE.replace("FROM RFC1212;", "FROM SNMPv2-SMI;")

        out, status = apply_patch(other, SAMPLE_PATCH, "TEST-MIB")

        self.assertEqual(NOT_APPLICABLE, status)
        self.assertEqual(other, out)

    def testAlreadyPatchedIsNotConfusedWithNotApplicable(self):
        """The two non-applying outcomes are told apart, not merged.

        They call for opposite things -- one means the module is fixed, the
        other means it is not -- so a reader that reported both the same way
        would make a patched bundle indistinguishable from a source pysmi could
        not help with.
        """
        patched, _ = apply_patch(SAMPLE, SAMPLE_PATCH, "TEST-MIB")
        foreign = SAMPLE.replace("FROM RFC1212;", "FROM SNMPv2-SMI;")

        self.assertEqual(ALREADY_APPLIED, apply_patch(patched, SAMPLE_PATCH, "M")[1])
        self.assertEqual(NOT_APPLICABLE, apply_patch(foreign, SAMPLE_PATCH, "M")[1])

    def testCrlfTextIsPatchedAndKeepsItsLineEndings(self):
        """Line endings say nothing about whether a patch applies.

        A MIB checked out on Windows is the same MIB, so it gets the same fix --
        and it goes back with the endings it arrived with, since patching a
        module should not also rewrite the shape of the file it came from.
        """
        lf, _ = apply_patch(SAMPLE, SAMPLE_PATCH, "TEST-MIB")
        crlf, status = apply_patch(SAMPLE.replace("\n", "\r\n"), SAMPLE_PATCH, "M")

        self.assertEqual(APPLIED, status)
        self.assertEqual(lf.replace("\n", "\r\n"), crlf)
        self.assertNotIn("\r", lf)


class BundledPatchSetTestCase(unittest.TestCase):
    """The patches pysmi ships, against the copies pysmi ships."""

    def setUp(self):
        self.patches = PatchSet.bundled()

    def testBundleShipsPatches(self):
        """The set is package data, so an installed pysmi has it.

        The patches used to live in ``scripts/``, which is not in the wheel. A
        reader cannot apply what was not installed.
        """
        self.assertTrue(len(self.patches))
        self.assertIn("HPR-MIB", self.patches)

    def testEveryBundledPatchParses(self):
        """A patch that does not parse would be found only when a MIB is read."""
        for mibname in self.patches.modules():
            with self.subTest(mib=mibname):
                self.assertTrue(parse_patch(self.patches.patch_for(mibname), mibname))

    def testEveryPatchAppliesToTheTextInTheTree(self):
        """The tree holds the published text, so every patch applies to it.

        This is the offline half of the bundle refresh. It cannot tell whether
        the publisher's text has moved -- only the network can -- but it does
        catch a bundled file edited by hand past what its patch accounts for,
        which would leave bytes in the tree that no patch and no publisher
        explains.

        Both tiers: a held module's patch is a claim about its bytes just as a
        carried one's is, and checking it costs nothing.
        """
        for mibname in self.patches.modules():
            with self.subTest(mib=mibname):
                published = _published(mibname)

                out, status = apply_patch(
                    published, self.patches.patch_for(mibname), mibname
                )

                self.assertEqual(APPLIED, status)
                self.assertNotEqual(published, out)

    def testEveryPatchRoundTripsBackToTheTree(self):
        """Applying a patch and offering it again reports already-applied.

        Which is what the wheel's copies do, since they are exactly this text.
        """
        for mibname in self.patches.modules():
            with self.subTest(mib=mibname):
                repaired = _repaired(mibname)

                out, status = self.patches.apply(mibname, repaired)

                self.assertEqual(ALREADY_APPLIED, status)
                self.assertEqual(repaired, out)

    def testUnpatchedModuleReportsNothing(self):
        """A module with no patch is not reported as having been left alone."""
        text = (BUNDLED_ASN1 / "SNMPv2-SMI").read_text(encoding="utf-8")

        self.assertEqual(UNPATCHED, self.patches.apply("SNMPv2-SMI", text)[1])

    def testMalformedPatchDoesNotStopTheModuleBeingRead(self):
        """A broken patch is logged and the text passes through.

        A reader's job is to produce the module. Refusing to read a MIB at all
        because the patch for it is broken would be a worse failure than handing
        back what the source holds.
        """
        broken = PatchSet({"TEST-MIB": "--- a/M\n+++ b/M\n@@ -1,1 +1,1 @@\n?what\n"})

        with self.assertLogs("pysmi.patches", level="ERROR"):
            out, status = broken.apply("TEST-MIB", SAMPLE)

        self.assertEqual(UNPATCHED, status)
        self.assertEqual(SAMPLE, out)


class PatchSetSourceTestCase(unittest.TestCase):
    """Where a reader's patches come from."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def testFromDirectoryKeysOnTheFileName(self):
        """``<MODULE>.patch`` names the module, so lookup opens nothing."""
        (Path(self.tmp) / "TEST-MIB.patch").write_text(SAMPLE_PATCH)
        (Path(self.tmp) / "notes.txt").write_text("ignored")

        found = PatchSet.from_directory(self.tmp)

        self.assertEqual(("TEST-MIB",), found.modules())
        self.assertEqual(SAMPLE_PATCH, found.patch_for("TEST-MIB"))

    def testMissingDirectoryIsEmptyRatherThanAnError(self):
        """A caller naming a directory that is not there gets no patches."""
        self.assertEqual(0, len(PatchSet.from_directory(Path(self.tmp) / "nope")))

    def testBundledSetIsSharedRatherThanReread(self):
        """Every reader wants the same set, and it does not change."""
        self.assertIs(PatchSet.bundled(), PatchSet.bundled())


class ReaderPatchingTestCase(unittest.TestCase):
    """The point of all of it: a caller's own copy gets the fix."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

        self.published = _published("HPR-MIB")
        self.patched = _repaired("HPR-MIB")

        (self.tmp / "HPR-MIB").write_text(self.published)

    def testCallersOwnCopyComesBackPatched(self):
        """A source pointed at the published text yields the fixed text.

        This is the whole issue: before, the fix reached pysmi's bundled copies
        and nothing else, so a caller with their own ``HPR-MIB`` got the
        published text and the failure the patch exists to prevent.
        """
        info, data = FileReader(str(self.tmp)).get_data("HPR-MIB")

        self.assertEqual(APPLIED, info.patch)
        self.assertEqual(self.patched, data)

    def testUnpatchedCopyNoLongerOutranksThePatchedOne(self):
        """The precedence hazard the issue named is closed.

        Source precedence takes the newest MODULE-IDENTITY revision. HPR-MIB's
        published ``LAST-UPDATED "970514000000Z"`` is what the patch repairs, so
        while the fix reached only the bundle, a caller's published copy and
        pysmi's patched one disagreed about the module's revision. Read through
        a reader they now agree, because they are the same text.
        """
        _info, fromCaller = FileReader(str(self.tmp)).get_data("HPR-MIB")
        _info, fromBundle = FileReader(str(BUNDLED_ASN1)).get_data("HPR-MIB")

        self.assertEqual(revision_of(fromBundle), revision_of(fromCaller))

    def testWheelCopyIsRecognisedAsAlreadyPatched(self):
        """The wheel ships the repaired text, and reading it does not re-patch.

        The tree holds the published text; ``hatch_build.patch_asn1`` repairs it
        into the wheel, so an installed pysmi reads what this stages.
        """
        wheel = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, wheel)
        (wheel / "HPR-MIB").write_text(self.patched)

        info, data = FileReader(str(wheel)).get_data("HPR-MIB")

        self.assertEqual(ALREADY_APPLIED, info.patch)
        self.assertEqual(self.patched, data)

    def testTreeCopyIsPatchedOnTheWayOut(self):
        """Reading pysmi's own tree gives the same text the wheel ships."""
        info, data = FileReader(str(BUNDLED_ASN1)).get_data("HPR-MIB")

        self.assertEqual(APPLIED, info.patch)
        self.assertEqual(self.patched, data)

    def testUsePatchesOffShowsWhatTheSourceHolds(self):
        """Turning patching off is how the bundle refresh sees a moved source."""
        reader = FileReader(str(self.tmp)).set_options(usePatches=False)

        info, data = reader.get_data("HPR-MIB")

        self.assertEqual(UNPATCHED, info.patch)
        self.assertEqual(self.published, data)

    def testCallerSuppliedPatchSetReplacesTheBundledOne(self):
        """``patchSet`` is how a caller brings patches pysmi does not ship."""
        (self.tmp / "TEST-MIB").write_text(SAMPLE)

        reader = FileReader(str(self.tmp)).set_options(
            patchSet=PatchSet({"TEST-MIB": SAMPLE_PATCH})
        )

        info, data = reader.get_data("TEST-MIB")

        self.assertEqual(APPLIED, info.patch)
        self.assertIn("FROM RFC-1212;", data)

        # ... and only those: the bundled set is replaced, not added to.
        info, _data = reader.get_data("HPR-MIB")

        self.assertEqual(UNPATCHED, info.patch)

    def testUnpatchedModuleIsUntouched(self):
        """A module pysmi has no patch for reads exactly as it is stored."""
        text = (BUNDLED_ASN1 / "SNMPv2-SMI").read_text(encoding="utf-8")

        info, data = FileReader(str(BUNDLED_ASN1)).get_data("SNMPv2-SMI")

        self.assertEqual(UNPATCHED, info.patch)
        self.assertEqual(text, data)

    def testPatchIsKeyedOnTheModuleNotTheFileName(self):
        """A patch is cut against a module, so the file's spelling is not it.

        Readers find a module under several file names, so keying on the name
        the file happened to use would leave ``hpr-mib.txt`` unpatched.
        """
        odd = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, odd)
        (odd / "hpr-mib.txt").write_text(self.published)

        info, data = FileReader(str(odd)).get_data("HPR-MIB")

        self.assertEqual(APPLIED, info.patch)
        self.assertEqual(self.patched, data)


class ReaderContractTestCase(unittest.TestCase):
    """Patching sits in the base reader, so every source gets it alike."""

    def testEveryShippedReaderImplementsFetchData(self):
        """A reader that overrode *get_data* would silently skip patching."""
        from pysmi.reader.callback import CallbackReader
        from pysmi.reader.httpclient import HttpReader
        from pysmi.reader.localfile import FileReader as _FileReader
        from pysmi.reader.package import PackageReader
        from pysmi.reader.zipreader import ZipReader

        for cls in (CallbackReader, HttpReader, _FileReader, PackageReader, ZipReader):
            with self.subTest(reader=cls.__name__):
                self.assertNotIn("get_data", vars(cls))
                self.assertIn("fetch_data", vars(cls))

    def testPatchingAppliesToAnySource(self):
        """A reader that is not a directory is patched the same way."""

        class _Reader(AbstractReader):
            def fetch_data(self, mibname, **options):
                return MibInfo(name=mibname, path="test://x"), SAMPLE

        reader = _Reader().set_options(patchSet=PatchSet({"TEST-MIB": SAMPLE_PATCH}))

        info, data = reader.get_data("TEST-MIB")

        self.assertEqual(APPLIED, info.patch)
        self.assertIn("FROM RFC-1212;", data)


class CompilerReportsPatchesTestCase(unittest.TestCase):
    """A patched module is not what its publisher printed, so the build says so."""

    def testCompiledStatusCarriesThePatch(self):
        from pysmi.codegen import JsonCodeGen
        from pysmi.compiler import MibCompiler
        from pysmi.parser import SmiV1CompatParser
        from pysmi.writer import CallbackWriter

        compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *args: None)
        )
        compiler.add_sources(FileReader(str(BUNDLED_ASN1)))

        processed = compiler.compile("SNMPv2-MIB")

        self.assertEqual("", getattr(processed["SNMPv2-MIB"], "patch", ""))


class WheelShipsRepairedTextTestCase(unittest.TestCase):
    """The tree holds the publisher's text; the wheel holds the repaired text."""

    def testEveryPatchedModuleIsStagedForTheWheel(self):
        """``patch_asn1`` repairs exactly the bundled modules that have a patch.

        A consumer reading ``pysmi/mibs/asn1`` straight off an installed pysmi
        -- the ``pysnmp/mibs`` mirror, a build that copies the directory -- is
        not going through a reader and cannot apply anything, so the wheel has
        to carry the text already repaired.
        """
        from hatch_build import patch_asn1

        root = Path(__file__).resolve().parent.parent
        staged = patch_asn1(root)
        self.addCleanup(lambda: shutil.rmtree(next(iter(staged.values())).parent, True))

        carried = {
            name
            for name in PatchSet.bundled().modules()
            if (BUNDLED_ASN1 / name).exists()
        }

        self.assertEqual(carried, set(staged))

        for mibname, path in staged.items():
            with self.subTest(mib=mibname):
                text = path.read_text(encoding="utf-8")

                self.assertEqual(_repaired(mibname), text)
                self.assertNotEqual(_published(mibname), text)
                self.assertEqual(
                    ALREADY_APPLIED, PatchSet.bundled().apply(mibname, text)[1]
                )

    def testHeldModulesAreNotStaged(self):
        """``future/`` is not in the wheel, so nothing stages its patches."""
        from hatch_build import patch_asn1

        root = Path(__file__).resolve().parent.parent
        staged = patch_asn1(root)
        self.addCleanup(lambda: shutil.rmtree(next(iter(staged.values())).parent, True))

        for mibname in ("CLNS-MIB", "Modem-MIB", "SMUX-MIB"):
            with self.subTest(mib=mibname):
                self.assertTrue((BUNDLED_FUTURE / mibname).exists())
                self.assertNotIn(mibname, staged)


class PatchDocumentationTestCase(unittest.TestCase):
    """The patches are data about MIBs, so they say what they repair."""

    def testEveryPatchNamesItsModule(self):
        """The diff headers name the module the file is named for."""
        patches = PatchSet.bundled()

        for mibname in patches.modules():
            with self.subTest(mib=mibname):
                header = textwrap.dedent(patches.patch_for(mibname)).split("\n")[0]

                self.assertEqual(f"--- a/{mibname}", header)


if __name__ == "__main__":
    unittest.main()
