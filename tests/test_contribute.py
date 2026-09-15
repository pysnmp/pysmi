#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Deciding which of somebody's MIBs a distribution would be better for having.

The comparison is the compiler's own, so what is pinned here is not the
ranking but the four answers a scan gives with it: a copy worth offering, a
copy not worth offering, a module nothing here carries, and a file that is not
a MIB at all.

The rest is about what reaches a public issue. A report is composed from files
on the scanning machine, and the paths of those files name that machine; an
issue body holds 65,536 characters and a MIB set holds more; and an issue for
a module somebody already reported costs a maintainer the time this is meant
to save.
"""

import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

from pysmi import contribute, error
from pysmi.reader import FileReader


def module(name, revision, description="a module"):
    """One module at a given revision."""
    return textwrap.dedent(
        f"""\
        {name} DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, enterprises FROM SNMPv2-SMI;

        theModule MODULE-IDENTITY
            LAST-UPDATED "{revision}"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "{description}"
            REVISION     "{revision}"
            DESCRIPTION  "{description}"
            ::= {{ enterprises 99999 }}

        END
        """
    )


class ScanTestCase(unittest.TestCase):
    """What a directory of MIBs is worth offering."""

    def setUp(self):
        """A directory to offer and a corpus to offer it to."""
        self.directory = tempfile.mkdtemp()
        self.offered = Path(self.directory) / "mine"
        self.corpus = Path(self.directory) / "corpus"
        self.offered.mkdir()
        self.corpus.mkdir()

    def tearDown(self):
        """Take the directories away again."""
        shutil.rmtree(self.directory, ignore_errors=True)

    def scan(self, **options):
        """Scan the offered directory against the corpus."""
        return contribute.scan([self.offered], FileReader(str(self.corpus)), **options)

    def test_a_newer_copy_is_offered(self):
        """The finding the tool exists for: the corpus is behind."""
        (self.offered / "A-MIB").write_text(module("A-MIB", "202106020000Z"))
        (self.corpus / "A-MIB").write_text(module("A-MIB", "201103040000Z"))

        found = self.scan()

        self.assertEqual(["A-MIB"], [x.module for x in found])
        self.assertEqual(contribute.NEWER, found[0].verdict)
        self.assertEqual("202106020000Z", found[0].offered.revision)
        self.assertEqual("201103040000Z", found[0].published.revision)

    def test_an_older_copy_is_not(self):
        """A copy a build would pass over is not a contribution."""
        (self.offered / "A-MIB").write_text(module("A-MIB", "201103040000Z"))
        (self.corpus / "A-MIB").write_text(module("A-MIB", "202106020000Z"))

        self.assertEqual([], self.scan())

    def test_an_identical_copy_is_not(self):
        """Nothing to offer where the two texts are the same text."""
        (self.offered / "A-MIB").write_text(module("A-MIB", "202106020000Z"))
        (self.corpus / "A-MIB").write_text(module("A-MIB", "202106020000Z"))

        self.assertEqual([], self.scan())

    def test_a_module_the_corpus_lacks_is_offered(self):
        """The half a shadowing report cannot see, and the larger half."""
        (self.offered / "NEW-MIB").write_text(module("NEW-MIB", "202402010000Z"))

        found = self.scan()

        self.assertEqual([contribute.NOT_CARRIED], [x.verdict for x in found])
        self.assertIsNone(found[0].published)
        self.assertEqual("", found[0].precedence)
        self.assertEqual([], self.scan(skip_new=True))

    def test_a_tie_is_offered_only_when_asked_for(self):
        """Two copies of one name are as often two modules as two revisions."""
        (self.offered / "A-MIB").write_text(module("A-MIB", "202106020000Z", "ours"))
        (self.corpus / "A-MIB").write_text(module("A-MIB", "202106020000Z", "theirs"))

        self.assertEqual([], self.scan())

        found = self.scan(include_differing=True)

        self.assertEqual(["A-MIB"], [x.module for x in found])
        self.assertEqual("same revision, different text", found[0].verdict)

    def test_the_module_is_what_the_text_declares(self):
        """A MIB is named inside the file, and vendors name the files anything."""
        (self.offered / "vendor-42.my").write_text(module("REAL-MIB", "202402010000Z"))

        found = self.scan()

        self.assertEqual(["REAL-MIB"], [x.module for x in found])
        self.assertEqual("vendor-42.my", found[0].offered.file)

    def test_a_file_that_is_not_a_mib_is_passed_over(self):
        """A directory of MIBs holds a README, and reading it is not an error."""
        (self.offered / "README").write_text("This directory holds MIBs.\n")
        (self.offered / "A-MIB").write_text(module("A-MIB", "202402010000Z"))
        skipped = []

        found = self.scan(on_skip=lambda path, why: skipped.append(path.name))

        self.assertEqual(["A-MIB"], [x.module for x in found])
        self.assertEqual(["README"], skipped)

    def test_only_reports_what_it_was_asked_for(self):
        """Offering some of a directory rather than all of it."""
        (self.offered / "A-MIB").write_text(module("A-MIB", "202402010000Z"))
        (self.offered / "B-MIB").write_text(module("B-MIB", "202402010000Z"))

        self.assertEqual(["B-MIB"], [x.module for x in self.scan(only=("B-MIB",))])


class SeveralCopiesTestCase(unittest.TestCase):
    """A collection holding one module more than once, or several in one file."""

    def setUp(self):
        """A directory to offer and a corpus to offer it to."""
        self.directory = tempfile.mkdtemp()
        self.offered = Path(self.directory) / "mine"
        self.corpus = Path(self.directory) / "corpus"
        (self.offered / "old").mkdir(parents=True)
        (self.offered / "new").mkdir(parents=True)
        self.corpus.mkdir()

    def tearDown(self):
        """Take the directories away again."""
        shutil.rmtree(self.directory, ignore_errors=True)

    def scan(self, **options):
        """Scan the offered directory against the corpus."""
        return contribute.scan([self.offered], FileReader(str(self.corpus)), **options)

    def test_the_newest_copy_in_the_tree_is_the_one_offered(self):
        """A tree with a copy per release must not offer whichever sorts first."""
        (self.offered / "old" / "A-MIB").write_text(module("A-MIB", "201103040000Z"))
        (self.offered / "new" / "A-MIB").write_text(module("A-MIB", "202106020000Z"))

        found = self.scan()

        self.assertEqual(["A-MIB"], [x.module for x in found])
        self.assertEqual("202106020000Z", found[0].offered.revision)
        self.assertEqual(f"new{os.sep}A-MIB", found[0].offered.file)

    def test_an_older_copy_beside_a_newer_one_does_not_hide_it(self):
        """The corpus comparison must see the best copy, not the first."""
        (self.corpus / "A-MIB").write_text(module("A-MIB", "201506010000Z"))
        (self.offered / "old" / "A-MIB").write_text(module("A-MIB", "201103040000Z"))
        (self.offered / "new" / "A-MIB").write_text(module("A-MIB", "202106020000Z"))

        found = self.scan()

        self.assertEqual([contribute.NEWER], [x.verdict for x in found])
        self.assertEqual("202106020000Z", found[0].offered.revision)

    def test_every_module_in_a_file_is_considered(self):
        """A second module in a file is a module this distribution may lack."""
        both = module("FIRST-MIB", "202106020000Z") + module(
            "SECOND-MIB", "202106020000Z"
        )
        (self.offered / "vendor.my").write_text(both)
        (self.corpus / "FIRST-MIB").write_text(both)

        found = self.scan()

        self.assertEqual(["SECOND-MIB"], [x.module for x in found])
        self.assertEqual(contribute.NOT_CARRIED, found[0].verdict)
        self.assertEqual(both, found[0].text)

    def test_only_matches_any_module_the_file_declares(self):
        """--module names a module, and a module is not always first in its file."""
        both = module("FIRST-MIB", "202106020000Z") + module(
            "SECOND-MIB", "202106020000Z"
        )
        (self.offered / "vendor.my").write_text(both)

        self.assertEqual(
            ["SECOND-MIB"],
            [x.module for x in self.scan(only=("SECOND-MIB",))],
        )

    def test_a_symlink_out_of_the_tree_is_not_scanned(self):
        """What a scan reads it may publish, so it reads what it was pointed at."""
        outside = Path(self.directory) / "elsewhere"
        outside.mkdir()
        (outside / "OUTSIDE-MIB").write_text(module("OUTSIDE-MIB", "202106020000Z"))

        try:
            (self.offered / "OUTSIDE-MIB").symlink_to(outside / "OUTSIDE-MIB")
        except (OSError, NotImplementedError):
            self.skipTest("this platform does not make symlinks")

        (self.offered / "A-MIB").write_text(module("A-MIB", "202106020000Z"))

        self.assertEqual(["A-MIB"], [x.module for x in self.scan()])

    def test_a_symlink_within_the_tree_is_scanned(self):
        """A collection that links its own files together is still one directory."""
        (self.offered / "old" / "A-MIB").write_text(module("A-MIB", "202106020000Z"))

        try:
            (self.offered / "new" / "A-MIB").symlink_to(self.offered / "old" / "A-MIB")
        except (OSError, NotImplementedError):
            self.skipTest("this platform does not make symlinks")

        self.assertEqual(["A-MIB"], [x.module for x in self.scan()])


class IssueTestCase(unittest.TestCase):
    """What the issue says, and what it must not say."""

    def setUp(self):
        """One finding of each kind."""
        self.directory = tempfile.mkdtemp()
        self.better = contribute.Finding(
            module="A-MIB",
            verdict=contribute.NEWER,
            precedence="newest MODULE-IDENTITY revision",
            offered=contribute.Copy("mine", "A-MIB", "202106020000Z", "sha256:a", 40),
            published=contribute.Copy(
                "corpus", "A-MIB", "201103040000Z", "sha256:b", 30
            ),
            text=module("A-MIB", "202106020000Z"),
            raw=module("A-MIB", "202106020000Z").encode(),
        )
        self.new = contribute.Finding(
            module="NEW-MIB",
            verdict=contribute.NOT_CARRIED,
            precedence="",
            offered=contribute.Copy("mine", "NEW-MIB", "202402010000Z", "sha256:c", 40),
            published=None,
            text=module("NEW-MIB", "202402010000Z"),
            raw=module("NEW-MIB", "202402010000Z").encode(),
        )

    def tearDown(self):
        """Take the directory away again."""
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_the_body_carries_the_marker_and_the_data(self):
        """A maintainer finds the set by the marker; an agent reads the JSON."""
        body = contribute.compose([self.better, self.new], "contribution.zip")

        self.assertIn(contribute.MARKER, body)
        self.assertIn("| `A-MIB` |", body)
        self.assertIn("not carried", body)

        data = json.loads(body.split("```json\n")[1].split("\n```")[0])

        self.assertEqual(["A-MIB", "NEW-MIB"], [x["module"] for x in data["modules"]])
        self.assertIsNone(data["modules"][1]["published"])

    def test_the_body_carries_no_path_from_this_machine(self):
        """A build's paths name the host it ran on. An issue is public."""
        body = contribute.compose([self.better], "contribution.zip")

        self.assertNotIn(tempfile.gettempdir(), body)
        self.assertNotIn(os.sep + "home" + os.sep, body)
        self.assertNotIn("file://", body)

    def test_a_module_too_long_to_inline_is_named_instead(self):
        """An issue body holds 65,536 characters and a MIB set holds more."""
        self.better.text = "-- " + "x" * contribute.BODY_LIMIT

        body = contribute.compose([self.better], "contribution.zip")

        self.assertLessEqual(len(body), contribute.BODY_LIMIT)
        self.assertIn("too long", body)
        self.assertIn("`contribution.zip`", body)

    def test_the_bundle_holds_the_mibs(self):
        """What a reporter attaches, and what a pull request is cut from."""
        out = Path(self.directory) / "out"

        archive = contribute.write_bundle(out, "contribution", [self.better, self.new])

        self.assertTrue((out / "issue.md").is_file())
        self.assertEqual(self.better.raw, (out / "mibs" / "A-MIB").read_bytes())

        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(["A-MIB", "NEW-MIB"], sorted(bundle.namelist()))

        data = json.loads((out / "findings.json").read_text())

        self.assertEqual("mib-contribution v1", data["report"])

    def test_the_url_carries_the_report(self):
        """The path for somebody who will not hand a token to a script."""
        url = contribute.issue_url(
            "pysnmp/mibs", contribute.title_for([self.better]), "body text"
        )

        self.assertTrue(url.startswith("https://github.com/pysnmp/mibs/issues/new?"))
        self.assertIn("A-MIB", url)
        self.assertIn("body+text", url)

    def test_an_offer_that_does_not_fit_at_all_is_refused(self):
        """`gh issue create` refuses a body over the limit, so this refuses first."""
        many = [
            contribute.Finding(
                module=f"BIG-{x:05}-MIB",
                verdict=contribute.NOT_CARRIED,
                precedence="",
                offered=contribute.Copy(
                    "mine", f"BIG-{x:05}-MIB", "202402010000Z", "sha256:" + "c" * 64, 40
                ),
                published=None,
                text="-- text\n",
                raw=b"-- text\n",
            )
            for x in range(3000)
        ]

        with self.assertRaises(error.PySmiError) as refused:
            contribute.compose(many, "contribution.zip")

        self.assertIn("--per-module", str(refused.exception))

    def test_a_long_offer_drops_the_per_module_sections_first(self):
        """Between everything and nothing there is the table and the data."""
        many = [
            contribute.Finding(
                module=f"MID-{x:04}-MIB",
                verdict=contribute.NOT_CARRIED,
                precedence="",
                offered=contribute.Copy(
                    "mine", f"MID-{x:04}-MIB", "202402010000Z", "sha256:d", 40
                ),
                published=None,
                text="-- text\n",
                raw=b"-- text\n",
            )
            for x in range(300)
        ]

        body = contribute.compose(many, "contribution.zip")

        self.assertLessEqual(len(body), contribute.BODY_LIMIT)
        self.assertIn("| `MID-0000-MIB` |", body)
        self.assertNotIn("#### MID-0000-MIB", body)

    def test_what_the_body_leaves_out_can_be_asked_for_in_advance(self):
        """A caller that cannot attach an archive has to know before it submits."""
        self.better.text = "-- " + "x" * contribute.BODY_LIMIT

        self.assertEqual(
            set(),
            contribute.inline_choice([self.better], "contribution.zip"),
        )
        self.assertEqual(
            {"NEW-MIB"},
            contribute.inline_choice([self.new], "contribution.zip"),
        )

    def test_the_title_says_which_kind(self):
        """A reader scanning the tracker should not have to open the issue."""
        self.assertIn("newer copy", contribute.title_for([self.better]))
        self.assertIn("does not carry", contribute.title_for([self.new]))
        self.assertIn("2 modules", contribute.title_for([self.better, self.new]))


class DuplicateTestCase(unittest.TestCase):
    """Not reporting what somebody has reported already."""

    def test_an_issue_is_recognised_by_its_data_and_its_title(self):
        """One this tool filed names its modules exactly; one filed by hand does not."""
        self.assertEqual(
            {"A-MIB"},
            contribute.modules_named({"title": "x", "body": '"module": "A-MIB"'}),
        )
        self.assertEqual(
            {"B-MIB"},
            contribute.modules_named({"title": "Please add B-MIB", "body": ""}),
        )

    def test_the_search_is_matched_back_to_the_modules(self):
        """Every issue the tool filed is found by one search, then matched locally."""
        issues = [
            {"number": 7, "state": "open", "title": "", "body": '"module": "A-MIB"'}
        ]
        original = contribute.search_issues

        try:
            contribute.search_issues = lambda repository, query, pages=1: (
                issues if contribute.MARKER_TEXT in query else []
            )
            found = contribute.existing_contributions("pysnmp/mibs", ["A-MIB", "B-MIB"])

        finally:
            contribute.search_issues = original

        self.assertEqual(["A-MIB"], sorted(found))
        self.assertEqual(7, found["A-MIB"][0]["number"])

    def test_an_existing_issue_is_described_for_a_reader(self):
        """The line that says not to file another."""
        self.assertEqual(
            "issue #7 (open): Add A-MIB",
            contribute.describe_duplicate(
                {"number": 7, "state": "open", "title": "Add A-MIB"}
            ),
        )
        self.assertIn(
            "pull request",
            contribute.describe_duplicate(
                {"number": 8, "state": "open", "title": "", "pull_request": {}}
            ),
        )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
