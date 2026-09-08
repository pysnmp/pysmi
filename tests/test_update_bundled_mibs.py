#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""scripts/update_bundled_mibs.py stages every fetch and the compile-verify
of the refreshed set before touching pysmi/mibs/asn1/ -- a network failure
partway through a fetch, or an upstream MIB that no longer compiles, must
leave the existing bundle exactly as it was rather than a mix of old and
new files. See the review discussion on pysnmp/pysmi#123.

The patch applier is exercised here too. It is what keeps a module whose
published text does not compile honest -- the bundled bytes are the
publisher's plus a patch that is in the repository to be read -- so it has to
refuse a patch whose context has moved rather than fuzz it into place.
"""

import pathlib
import re
import tempfile
import unittest
from unittest import mock

from scripts import update_bundled_mibs

VALID_MIB = "TEST-MIB DEFINITIONS ::= BEGIN\nEND\n"
UNCOMPILABLE_MIB = "this is not valid ASN.1\n"


def _addBaseMibs(dest, manifest):
    """Copy the modules every compile pulls in into a fixture bundle.

    Taken from the real bundle rather than stubbed: the point is that verify()
    now demands a bundle nothing dangles out of, and faking these would just
    move the dangle somewhere else.
    """
    from importlib import resources

    from pysmi.codegen import JsonCodeGen

    installed = resources.files("pysmi.mibs.asn1")

    for mibname in sorted(set(JsonCodeGen.baseMibs)):
        candidate = installed.joinpath(mibname)
        if candidate.is_file():
            (dest / mibname).write_bytes(candidate.read_bytes())
            manifest[mibname] = {"source": "rfc", "rfc": 0}


class UpdateBundledMibsAtomicityTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = pathlib.Path(self._tmp.name) / "asn1"
        self.dest.mkdir()

        self.bundled = {
            "ALPHA-MIB": {"source": "rfc", "rfc": 1},
            "BETA-MIB": {"source": "rfc", "rfc": 2},
        }

        for mibname in self.bundled:
            (self.dest / mibname).write_bytes(VALID_MIB.encode())

        self._patches = [
            mock.patch.object(update_bundled_mibs, "DEST", self.dest),
            mock.patch.object(
                update_bundled_mibs, "manifest", return_value=self.bundled
            ),
            # update() finishes by regenerating the inventory page; that is not
            # what these tests are about.
            mock.patch.object(update_bundled_mibs, "docs", return_value=0),
        ]

        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self._tmp.cleanup()

    def _stubVerify(self, code):
        """Make verify() return *code* without compiling anything.

        These four tests are about what ends up on disk -- that a partway
        failure leaves the old bundle intact, that a dropped manifest entry
        takes its file with it. Compiling a real bundle for each would be slow
        and would test verify() over again, which the two tests below do
        directly.
        """
        patch = mock.patch.object(update_bundled_mibs, "verify", return_value=code)
        patch.start()
        self.addCleanup(patch.stop)

    def _existingBundleContents(self):
        return {mibname: (self.dest / mibname).read_bytes() for mibname in self.bundled}

    def testASuccessfulUpdateReplacesEveryFile(self):
        self._stubVerify(0)
        fresh = {
            mibname: f"-- fresh {mibname}\n{VALID_MIB}".encode()
            for mibname in self.bundled
        }

        with mock.patch.object(
            update_bundled_mibs, "fetch", side_effect=lambda name, _entry: fresh[name]
        ):
            code = update_bundled_mibs.update()

        self.assertEqual(0, code)
        self.assertEqual(fresh, self._existingBundleContents())

    def testAFetchFailurePartwayLeavesTheExistingBundleUntouched(self):
        self._stubVerify(0)
        before = self._existingBundleContents()

        def flakyFetch(mibname, _entry):
            if mibname == sorted(self.bundled)[-1]:
                raise TimeoutError("network unreachable")
            return f"-- fresh {mibname}\n{VALID_MIB}".encode()

        with (
            mock.patch.object(update_bundled_mibs, "fetch", side_effect=flakyFetch),
            self.assertRaises(TimeoutError),
        ):
            update_bundled_mibs.update()

        self.assertEqual(before, self._existingBundleContents())

    def testAnUncompilableRefreshLeavesTheExistingBundleUntouched(self):
        self._stubVerify(1)
        before = self._existingBundleContents()

        broken = {
            "ALPHA-MIB": UNCOMPILABLE_MIB.encode(),
            "BETA-MIB": VALID_MIB.encode(),
        }

        with mock.patch.object(
            update_bundled_mibs, "fetch", side_effect=lambda name, _entry: broken[name]
        ):
            code = update_bundled_mibs.update()

        self.assertEqual(1, code)
        self.assertEqual(before, self._existingBundleContents())

    def testAModuleDroppedFromTheManifestIsDroppedFromTheBundle(self):
        self._stubVerify(0)
        """Otherwise a removed entry leaves a file nothing re-checks any more."""
        (self.dest / "GAMMA-MIB").write_bytes(VALID_MIB.encode())

        with mock.patch.object(
            update_bundled_mibs,
            "fetch",
            side_effect=lambda _name, _entry: VALID_MIB.encode(),
        ):
            self.assertEqual(0, update_bundled_mibs.update())

        self.assertFalse((self.dest / "GAMMA-MIB").exists())

    def testVerifyDefaultsToCheckingDestInPlace(self):
        _addBaseMibs(self.dest, self.bundled)

        self.assertEqual(0, update_bundled_mibs.verify())

    def testVerifyChecksTheGivenDirectoryNotDest(self):
        _addBaseMibs(self.dest, self.bundled)

        staging = pathlib.Path(self._tmp.name) / "staging"
        staging.mkdir()
        (staging / "ALPHA-MIB").write_bytes(UNCOMPILABLE_MIB.encode())
        (staging / "BETA-MIB").write_bytes(VALID_MIB.encode())
        _addBaseMibs(staging, dict(self.bundled))

        self.assertEqual(1, update_bundled_mibs.verify(staging))
        # DEST's own (valid) copies are untouched by checking a different directory.
        self.assertEqual(0, update_bundled_mibs.verify())


ORIGINAL = "alpha\nbeta\ngamma\n"
PATCH = """\
--- a/TEST-MIB
+++ b/TEST-MIB
@@ -1,3 +1,3 @@
 alpha
-beta
+BETA
 gamma
"""


class ApplyPatchTestCase(unittest.TestCase):
    def testAPatchIsAppliedWhereItsContextMatches(self):
        patched = update_bundled_mibs.apply_patch(ORIGINAL.encode(), PATCH, "TEST-MIB")

        self.assertEqual("alpha\nBETA\ngamma\n", patched.decode())

    def testAPatchWhoseContextHasMovedIsRefused(self):
        """A moved context means the publisher's text changed under the patch.

        Fuzzing it into place would bundle a module nobody has reviewed in its
        new form, and the whole point of keeping the patch separate is that
        somebody can see what was changed and why.
        """
        moved = "alpha\nbeta and more\ngamma\n"

        with self.assertRaises(SystemExit) as raised:
            update_bundled_mibs.apply_patch(moved.encode(), PATCH, "TEST-MIB")

        self.assertIn("no longer applies", str(raised.exception))

    def testEveryBundledPatchRoundTripsAgainstTheBundledCopy(self):
        """Each bundled file must be exactly its patch applied to something.

        This is the offline half of ``--check``. It cannot tell whether the
        publisher's text has moved -- only the network can -- but it does catch
        a bundled file edited by hand past what its patch accounts for, which
        would leave bytes in the package that no patch and no publisher
        explains.
        """
        modules = {
            name: entry
            for name, entry in update_bundled_mibs.manifest().items()
            if "patch" in entry
        }

        for mibname, entry in sorted(modules.items()):
            with self.subTest(mib=mibname):
                patch = (update_bundled_mibs.PATCHES / entry["patch"]).read_text()
                bundled = (update_bundled_mibs.DEST / mibname).read_bytes()

                # Reversing the patch off the bundled copy recovers the
                # publisher's text; re-applying it has to give the bundled copy
                # back, byte for byte.
                published = update_bundled_mibs.apply_patch(
                    bundled, _invert(patch), mibname
                )

                self.assertEqual(
                    bundled,
                    update_bundled_mibs.apply_patch(published, patch, mibname),
                )


class IeeeIndexTestCase(unittest.TestCase):
    """The IEEE 802.1 source is the newest file in the directory, not a pin.

    An immutable dated URL would make --check useless for those forty modules:
    it would compare equal forever while IEEE published revision after
    revision, and nothing would be able to say the bundle had fallen behind.
    """

    LISTING = b"""
      <a href="IEEE8021-CFM-MIB-200810150000Z.mib">old</a>
      <a href="IEEE8021-CFM-MIB-202211080000Z.mib">new</a>
      <a href="IEEE8021-AS-MIB-201011110000.mib">no trailing Z</a>
      <a href="IEEE8021-CFM-MIB.mib">undated, ignored</a>
    """

    def setUp(self):
        update_bundled_mibs.ieee_index.cache_clear()
        self.addCleanup(update_bundled_mibs.ieee_index.cache_clear)

    def testTheNewestPublishedRevisionIsTheOneResolved(self):
        with mock.patch.object(
            update_bundled_mibs, "download", return_value=self.LISTING
        ):
            revision, url = update_bundled_mibs.ieee_current("IEEE8021-CFM-MIB")

        self.assertEqual("202211080000", revision)
        self.assertTrue(url.endswith("IEEE8021-CFM-MIB-202211080000Z.mib"))

    def testARevisionWithoutTheTrailingZStillResolves(self):
        with mock.patch.object(
            update_bundled_mibs, "download", return_value=self.LISTING
        ):
            revision, _url = update_bundled_mibs.ieee_current("IEEE8021-AS-MIB")

        self.assertEqual("201011110000", revision)

    def testAModuleIeeeNoLongerPublishesIsAnError(self):
        with (
            mock.patch.object(
                update_bundled_mibs, "download", return_value=self.LISTING
            ),
            self.assertRaises(SystemExit) as raised,
        ):
            update_bundled_mibs.ieee_current("IEEE8021-GONE-MIB")

        self.assertIn("no longer published", str(raised.exception))

    def testAnEmptyListingIsAnErrorRatherThanAnEmptyBundle(self):
        """A directory that fails to parse must not read as "nothing to fetch"."""
        with (
            mock.patch.object(update_bundled_mibs, "download", return_value=b"<html/>"),
            self.assertRaises(SystemExit),
        ):
            update_bundled_mibs.ieee_current("IEEE8021-CFM-MIB")

    def testEveryIeeeEntryRecordsTheRevisionItWasTakenFrom(self):
        """No URL to read it off, so the manifest is where that answer lives.

        Only for the entries the directory actually carries. Three IEEE 802.1
        modules are in no revision of it, so they are bundled ``archived`` and
        there is no published revision to record.
        """
        entries = {
            name: entry
            for name, entry in update_bundled_mibs.manifest().items()
            if entry["source"] == "ieee802.1" and not entry.get("archived")
        }

        self.assertTrue(entries)

        for mibname, entry in sorted(entries.items()):
            with self.subTest(mib=mibname):
                self.assertNotIn("url", entry)
                self.assertRegex(entry["revision"], r"^\d{12}$")


class CheckMirrorTestCase(unittest.TestCase):
    """--check-mirror is what keeps pysmi and pysnmp/mibs from drifting apart.

    pysmi is the source of truth for the modules it bundles, but the mirror is
    also what mibdump and mibcopy reach for by default -- so a disagreement
    means a caller can be served pysmi's copy of one module and the mirror's
    copy of something that imports it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.bundled = {"ALPHA-MIB": {"source": "rfc", "rfc": 1}}
        (self.dest / "ALPHA-MIB").write_bytes(_stamped("200001010000Z"))

        for patch in (
            mock.patch.object(update_bundled_mibs, "DEST", self.dest),
            mock.patch.object(
                update_bundled_mibs, "manifest", return_value=self.bundled
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def testAMirrorThatMatchesPasses(self):
        with mock.patch.object(
            update_bundled_mibs, "download", return_value=_stamped("200001010000Z")
        ):
            self.assertEqual(0, update_bundled_mibs.check_mirror())

    def testAMirrorServingAnotherRevisionIsReported(self):
        with mock.patch.object(
            update_bundled_mibs, "download", return_value=_stamped("201501010000Z")
        ):
            self.assertEqual(1, update_bundled_mibs.check_mirror())

    def testAMirrorServingDifferentTextAtTheSameRevisionIsReported(self):
        """The case a revision comparison alone would wave through.

        Two copies stamped identically but differing in body is precisely the
        drift that went unnoticed for years, so it has to fail rather than
        being treated as agreement.
        """
        edited = _stamped("200001010000Z").replace(b"END", b"-- edited\nEND")

        with mock.patch.object(update_bundled_mibs, "download", return_value=edited):
            self.assertEqual(1, update_bundled_mibs.check_mirror())

    def testAnUnreachableMirrorFailsRatherThanReadingAsAgreement(self):
        with mock.patch.object(
            update_bundled_mibs, "download", side_effect=TimeoutError("no route")
        ):
            self.assertEqual(1, update_bundled_mibs.check_mirror())


def _stamped(revision: bytes | str) -> bytes:
    return (
        b"ALPHA-MIB DEFINITIONS ::= BEGIN\n"
        b'alpha MODULE-IDENTITY LAST-UPDATED "' + str(revision).encode() + b'"\n'
        b"END\n"
    )


def _invert(patch: str) -> str:
    """Turn a unified diff around, so it undoes what it would have done."""
    header = re.compile(r"^@@ -(\d+(?:,\d+)?) \+(\d+(?:,\d+)?) @@(.*)$")
    flipped = {"+": "-", "-": "+"}
    out = []

    for chunk in patch.split("\n"):
        found = header.match(chunk)
        if chunk.startswith(("--- ", "+++ ")):
            out.append(chunk)
        elif found:
            out.append(f"@@ -{found.group(2)} +{found.group(1)} @@{found.group(3)}")
        elif chunk[:1] in flipped:
            out.append(flipped[chunk[0]] + chunk[1:])
        else:
            out.append(chunk)

    return "\n".join(out)


if __name__ == "__main__":
    unittest.main()


class DepaginationTestCase(unittest.TestCase):
    """Page furniture comes off whether or not the form feeds survived.

    Every RFC the bundle cuts from carries form feeds, and the page break is
    read off those. The IETF's Internet-Draft archive serves text that has had
    them stripped, leaving only the ``[Page n]`` footer and the running header
    below it, so a document with no form feed in it is depaginated on the
    footer line instead. Both paths have to leave the module's own text alone.
    """

    #: One page break, written the way an RFC writes it.
    FED = (
        "SOME-MIB DEFINITIONS ::= BEGIN\n"
        "\n"
        "first\n"
        "\n\n"
        "Author                       Standards Track                 [Page 1]\n"
        "\f"
        "RFC 9999                       Some MIB                    August 2001\n"
        "\n\n"
        "second\n"
        "END\n"
    )

    #: The same document as the draft archive serves it: no form feed.
    UNFED = FED.replace("\f", "")

    def testAFormFeedDocumentIsDepaginatedOnItsFormFeeds(self):
        body = update_bundled_mibs.unpaginate(self.FED)

        self.assertNotIn("[Page 1]", body)
        self.assertNotIn("August 2001", body)
        self.assertIn("first\nsecond", body)

    def testADocumentWithoutFormFeedsIsDepaginatedOnItsFooters(self):
        self.assertEqual(
            update_bundled_mibs.unpaginate(self.FED),
            update_bundled_mibs.unpaginate(self.UNFED),
        )

    def testADocumentThatNeverPaginatedKeepsEveryLine(self):
        """Both paths drop the blank line a text ends on; nothing else moves."""
        text = "SOME-MIB DEFINITIONS ::= BEGIN\n\nonly\nEND\n"

        self.assertEqual(
            text.splitlines(), update_bundled_mibs.unpaginate(text).splitlines()
        )

    def testADraftModuleIsCutAtTheLeftMargin(self):
        """A draft indents its module; the bundle holds it as an RFC prints it.

        Left indented, the same module would diff against every other copy of
        itself on whitespace alone.
        """
        draft = (
            b"   Some prose about the module.\n"
            b"\n"
            b"   SOME-MIB DEFINITIONS ::= BEGIN\n"
            b"\n"
            b"   IMPORTS\n"
            b"      MODULE-IDENTITY FROM SNMPv2-SMI;\n"
            b"\n"
            b"   END\n"
        )

        with mock.patch.object(update_bundled_mibs, "download", return_value=draft):
            cut = update_bundled_mibs.extract_draft("SOME-MIB", "draft-example-00")

        self.assertEqual(
            "SOME-MIB DEFINITIONS ::= BEGIN\n\nIMPORTS\n   MODULE-IDENTITY FROM SNMPv2-SMI;\n\nEND\n",
            cut.decode(),
        )

    def testNoBundledModuleCarriesPageFurniture(self):
        """The whole bundle, not just the entry that prompted the check.

        A footer left in a module is not a compile error -- it lands inside a
        comment or between declarations often enough to go unnoticed -- so
        nothing else in the suite would report one.
        """
        for path in sorted(update_bundled_mibs.DEST.iterdir()):
            if not path.is_file() or path.name.startswith("__"):
                continue

            with self.subTest(module=path.name):
                offenders = [
                    line
                    for line in path.read_text(errors="replace").splitlines()
                    if update_bundled_mibs.PAGINATION_FOOTER.search(line)
                ]

                self.assertEqual([], offenders)
