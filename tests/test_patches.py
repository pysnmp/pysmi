#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""The repository holds the publisher's text; the distribution holds the repair.

Twelve published MIBs do not compile, and the fix for each is a diff in
``scripts/mib-patches``. The repository stores each module unmodified, so a
bundle refresh diffs against the publisher and the repairs are reviewable on
their own; ``hatch_build.py`` applies them as a distribution is built, to both
the ASN.1 the wheel carries and the pysnmp modules rendered from it.

These pin that split. The engine ships -- :py:mod:`pysmi.patches` and the
``mibpatch`` tool are there for anyone with MIBs of their own -- but pysmi's
twelve diffs do not, being already applied to the ASN.1 the wheel carries. So
what is checked here is the engine's behaviour, that every patch still applies
cleanly to the published text in the tree, and that a build produces one
repaired bundle rather than a repaired half and a published half.
"""

import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.patches import (
    ALREADY_APPLIED,
    APPLIED,
    NOT_APPLICABLE,
    UNPATCHED,
    PatchSet,
    PySmiPatchError,
    apply_patch,
    bundled_patches,
    parse_patch,
)

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
    text, status = bundled_patches().apply(mibname, _published(mibname))

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

        with self.assertRaises(PySmiPatchError):
            parse_patch(patch, "M")

    def testHunksMustRunForwards(self):
        """Hunks that overlap cannot both be applied, so the patch is refused."""
        patch = (
            "--- a/M\n+++ b/M\n"
            "@@ -5,2 +5,2 @@\n-five\n+FIVE\n six\n"
            "@@ -1,2 +1,2 @@\n-one\n+ONE\n two\n"
        )

        with self.assertRaises(PySmiPatchError):
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
        self.patches = bundled_patches()

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
    """Where the repairs are read from."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def testFromDirectoryKeysOnTheFileName(self):
        """``<MODULE>.patch`` names the module, so lookup opens nothing.

        This is also how a fork supplies its own opinion: point a build at a
        different directory of diffs rather than configure anything at runtime.
        """
        (Path(self.tmp) / "TEST-MIB.patch").write_text(SAMPLE_PATCH)
        (Path(self.tmp) / "notes.txt").write_text("ignored")

        found = PatchSet.from_directory(self.tmp)

        self.assertEqual(("TEST-MIB",), found.modules())
        self.assertEqual(SAMPLE_PATCH, found.patch_for("TEST-MIB"))

    def testMissingDirectoryIsEmptyRatherThanAnError(self):
        """Naming a directory that is not there gets no patches."""
        self.assertEqual(0, len(PatchSet.from_directory(Path(self.tmp) / "nope")))

    def testBundledSetIsSharedRatherThanReread(self):
        """The set does not change while a build runs."""
        self.assertIs(bundled_patches(), bundled_patches())


class DistributionShipsRepairedTextTestCase(unittest.TestCase):
    """The tree holds the publisher's text; the distribution holds the repair."""

    def setUp(self):
        from hatch_build import patch_asn1

        self.root = Path(__file__).resolve().parent.parent
        self.staged = patch_asn1(self.root)
        self.addCleanup(shutil.rmtree, self.staged, True)

    def testTheWholeBundleIsStagedNotOnlyTheRepairedModules(self):
        """Staging is a complete ASN.1 tree, because the compile reads it.

        The pysnmp modules the wheel carries are rendered from this directory,
        so it has to hold every module the wheel does -- not only the twelve
        that changed.
        """
        tree = {path.name for path in BUNDLED_ASN1.iterdir() if path.is_file()}

        self.assertEqual(tree, {path.name for path in self.staged.iterdir()})

    def testEveryPatchedModuleIsRepairedForTheDistribution(self):
        """``patch_asn1`` repairs exactly the bundled modules that have a patch.

        pysmi does not patch anything at read time, so a module that ships
        unrepaired stays unrepaired for everyone who reads it -- through a
        reader, or straight off disk.
        """
        carried = {
            name
            for name in bundled_patches().modules()
            if (BUNDLED_ASN1 / name).exists()
        }

        self.assertTrue(carried)

        for mibname in sorted(carried):
            with self.subTest(mib=mibname):
                text = (self.staged / mibname).read_text(encoding="utf-8")

                self.assertEqual(_repaired(mibname), text)
                self.assertNotEqual(_published(mibname), text)
                self.assertEqual(
                    ALREADY_APPLIED, bundled_patches().apply(mibname, text)[1]
                )

    def testUnpatchedModulesAreStagedUnchanged(self):
        """Staging repairs the twelve and copies the rest byte for byte."""
        for mibname in ("SNMPv2-SMI", "IF-MIB", "SNMPv2-TC"):
            with self.subTest(mib=mibname):
                self.assertNotIn(mibname, bundled_patches())
                self.assertEqual(
                    (BUNDLED_ASN1 / mibname).read_bytes(),
                    (self.staged / mibname).read_bytes(),
                )

    def testHeldModulesAreNotStaged(self):
        """``future/`` is not in the wheel, so nothing stages its patches."""
        for mibname in ("CLNS-MIB", "Modem-MIB", "SMUX-MIB"):
            with self.subTest(mib=mibname):
                self.assertTrue((BUNDLED_FUTURE / mibname).exists())
                self.assertFalse((self.staged / mibname).exists())

    def testAPatchThatNoLongerAppliesFailsTheBuild(self):
        """A publisher who moved the repaired lines stops the build.

        Fuzzing it into place would ship a module nobody has reviewed in its
        new form, which is the whole reason the repair is kept as a diff.
        """
        from hatch_build import patch_asn1

        fake = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fake, True)

        (fake / "pysmi" / "mibs" / "asn1").mkdir(parents=True)
        (fake / "scripts").mkdir()
        shutil.copy(self.root / "scripts" / "patches.py", fake / "scripts")
        shutil.copytree(
            self.root / "scripts" / "mib-patches", fake / "scripts" / "mib-patches"
        )

        # HPR-MIB as the publisher prints it, with the line the patch repairs
        # changed under it.
        moved = _published("HPR-MIB").replace('"970514000000Z"', '"9705140000Z"')
        (fake / "pysmi" / "mibs" / "asn1" / "HPR-MIB").write_text(moved)

        with self.assertRaises(RuntimeError) as raised:
            patch_asn1(fake)

        self.assertIn("HPR-MIB", str(raised.exception))
        self.assertIn("did not apply", str(raised.exception))


class RenderedModulesComeFromRepairedTextTestCase(unittest.TestCase):
    """The two halves of the wheel are compiled from the same text."""

    def testTheBuildHookCompilesWhatItStages(self):
        """``build`` is handed the staging directory, not the tree.

        The tree holds the published text, so compiling it would render pysnmp
        modules carrying the very defects the patches repair while the ASN.1
        beside them in the wheel was repaired. Nothing downstream would notice:
        both halves would be present and only one of them right.
        """
        from unittest import mock

        import hatch_build

        root = Path(__file__).resolve().parent.parent
        hook = hatch_build.PrecompiledMibsHook(
            str(root), {}, None, None, str(root), "wheel"
        )

        rendered = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, rendered, True)

        build_data = {"force_include": {}}

        with mock.patch.object(hatch_build, "build", return_value=rendered) as compiled:
            hook.initialize("1.0", build_data)

        self.addCleanup(shutil.rmtree, hook._asn1, True)

        staged = compiled.call_args.args[1]

        self.assertEqual(hook._asn1, staged)

        # And what was forced into the wheel came out of that same directory,
        # so the ASN.1 and the modules rendered from it cannot disagree.
        sources = {
            Path(source).parent
            for source, target in build_data["force_include"].items()
            if target.startswith(f"{hatch_build.ASN1}/")
        }

        self.assertEqual({staged}, sources)
        self.assertEqual(
            _repaired("HPR-MIB"), (staged / "HPR-MIB").read_text(encoding="utf-8")
        )


class PysmisOwnRepairsAreNotShippedTestCase(unittest.TestCase):
    """The engine ships; the repairs pysmi makes to its own bundle do not.

    Those are two different things, and only the second is an opinion. The
    engine and ``mibpatch`` are a capability any consumer has MIBs of their own
    to point at. The twelve diffs under ``scripts/mib-patches`` are pysmi's
    answer for pysmi's bundle, already applied to the ASN.1 the wheel carries,
    so shipping them would be shipping the same repair twice.
    """

    def testTheDiffsLiveOutsideThePackage(self):
        """``scripts/`` is outside ``pysmi``, so the wheel cannot pick them up.

        The wheel packages ``pysmi`` alone, which makes "not shipped" a property
        of the layout rather than of an exclude list somebody has to maintain.
        """
        package = Path(__file__).resolve().parent.parent / "pysmi"

        self.assertEqual([], sorted(package.rglob("*.patch")))
        self.assertFalse((package / "mibs" / "patches").exists())

    def testTheEngineIsImportableFromTheInstalledPackage(self):
        """A consumer patching their own tree needs it at runtime, not at build."""
        from pysmi.patches import PatchSet, apply_patch, make_patch  # noqa: F401
        from pysmi.scripts import mibpatch  # noqa: F401

    def testTheBundledSetIsReadFromOutsideThePackage(self):
        """Where pysmi's own diffs come from is a build-time path, not a package one."""
        from scripts.patches import PATCHES

        self.assertEqual("mib-patches", PATCHES.name)
        self.assertEqual("scripts", PATCHES.parent.name)

    def testReadersDoNotPatch(self):
        """Reading a MIB gives back what the source holds, defects and all."""
        from pysmi.reader import FileReader

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)

        published = _published("HPR-MIB")
        (tmp / "HPR-MIB").write_text(published, newline="")

        _info, data = FileReader(str(tmp)).get_data("HPR-MIB")

        self.assertEqual(published, data)
        self.assertNotEqual(_repaired("HPR-MIB"), data)


class PatchDocumentationTestCase(unittest.TestCase):
    """The patches are data about MIBs, so they say what they repair."""

    def testEveryPatchNamesItsModule(self):
        """The diff headers name the module the file is named for."""
        patches = bundled_patches()

        for mibname in patches.modules():
            with self.subTest(mib=mibname):
                header = textwrap.dedent(patches.patch_for(mibname)).split("\n")[0]

                self.assertEqual(f"--- a/{mibname}", header)


if __name__ == "__main__":
    unittest.main()
