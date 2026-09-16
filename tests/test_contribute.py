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

from pysmi import contribute, error, mibinfo
from pysmi.reader import (
    DEFAULT_MIB_SOURCES,
    FileReader,
    PackageReader,
)


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
        return contribute.scan(
            [self.offered], [FileReader(str(self.corpus))], **options
        )

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
        return contribute.scan(
            [self.offered], [FileReader(str(self.corpus))], **options
        )

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
        second = module("SECOND-MIB", "202106020000Z")
        both = module("FIRST-MIB", "202106020000Z") + second
        # newline="" so that the bytes on disk are the bytes written, on a
        # platform whose text mode would otherwise turn them into CRLF. The
        # finding carries text cut from those bytes, which is asserted below.
        (self.offered / "vendor.my").write_text(both, newline="")
        (self.corpus / "FIRST-MIB").write_text(both, newline="")

        found = self.scan()

        self.assertEqual(["SECOND-MIB"], [x.module for x in found])
        self.assertEqual(contribute.NOT_CARRIED, found[0].verdict)
        self.assertEqual(second, found[0].text)

    def test_a_module_is_offered_without_the_others_in_its_file(self):
        """What is offered is committed, and a repository stores one per file.

        A vendor bundle offered whole is offered once per module it declares,
        so a distribution that stored what it was given would hold as many
        copies of the bundle as it has modules, each under a name that is not
        its own. Offering the module alone is what makes the offer storable.
        """
        both = module("FIRST-MIB", "202106020000Z") + module(
            "SECOND-MIB", "202106020000Z"
        )
        (self.offered / "vendor.my").write_text(both, newline="")

        found = sorted(self.scan(), key=lambda x: x.module)

        self.assertEqual(["FIRST-MIB", "SECOND-MIB"], [x.module for x in found])

        for one in found:
            self.assertEqual([one.module], mibinfo.module_names(one.text))
            self.assertEqual([one.module], mibinfo.module_names(one.raw.decode()))
            self.assertLess(len(one.raw), len(both.encode()))

    def test_a_file_holding_one_module_is_offered_byte_for_byte(self):
        """Cutting a file into modules must not rewrite a file already one.

        A MIB is bytes a publisher served, and a scan that re-encoded them
        would offer something nobody published.
        """
        (self.offered / "A-MIB").write_bytes(
            module("A-MIB", "202106020000Z").encode("utf-8").replace(b"\n", b"\r\n")
        )

        found = self.scan()

        self.assertEqual((self.offered / "A-MIB").read_bytes(), found[0].raw)

    def test_a_module_that_is_not_utf8_survives_being_cut_out(self):
        """Vendors ship Latin-1, and the bytes offered are the bytes on disk."""
        both = module("FIRST-MIB", "202106020000Z", "caf\xe9").encode(
            "latin-1"
        ) + module("SECOND-MIB", "202106020000Z").encode("latin-1")
        (self.offered / "vendor.my").write_bytes(both)

        found = sorted(self.scan(), key=lambda x: x.module)

        self.assertEqual(["FIRST-MIB", "SECOND-MIB"], [x.module for x in found])
        self.assertIn(b"caf\xe9", found[0].raw)
        self.assertNotIn(b"caf\xe9", found[1].raw)

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


class CorpusTestCase(unittest.TestCase):
    """What a module is compared against, and what is refused as a comparison."""

    def setUp(self):
        """A directory to name as a corpus."""
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        """Take it away again."""
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_the_default_is_the_bundle_then_the_published_sources(self):
        """No --corpus reads pysmi's own modules first, then the remote tree."""
        readers = contribute.default_corpus()

        self.assertEqual(len(DEFAULT_MIB_SOURCES) + 1, len(readers))
        self.assertIsInstance(readers[0], PackageReader)
        self.assertIn(contribute.BUNDLED_PACKAGE, str(readers[0]))

        for source, reader in zip(DEFAULT_MIB_SOURCES, readers[1:]):
            self.assertIn(source, str(reader))

    def test_the_bundled_modules_answer_without_a_request(self):
        """A standard module is settled locally, so a scan of one needs no network."""
        found = contribute.published_copy(
            [contribute.default_corpus()[0]], "SNMPv2-MIB"
        )

        self.assertIsNotNone(found)
        self.assertIn("SNMPv2-MIB DEFINITIONS", found[0])

    def test_the_sources_are_tried_in_order(self):
        """The first source holding a module answers for it, as a compile would."""
        first = Path(self.directory) / "first"
        second = Path(self.directory) / "second"
        first.mkdir()
        second.mkdir()
        (first / "A-MIB").write_text(module("A-MIB", "202106020000Z"), newline="")
        (second / "A-MIB").write_text(module("A-MIB", "201103040000Z"), newline="")
        (second / "B-MIB").write_text(module("B-MIB", "201103040000Z"), newline="")
        corpus = [FileReader(str(first)), FileReader(str(second))]

        self.assertIn("202106020000Z", contribute.published_copy(corpus, "A-MIB")[0])
        self.assertIn("201103040000Z", contribute.published_copy(corpus, "B-MIB")[0])
        self.assertIsNone(contribute.published_copy(corpus, "C-MIB"))

    def test_a_corpus_that_is_not_there_is_refused(self):
        """Every lookup would miss, and a whole collection would read as missing."""
        with self.assertRaises(error.PySmiError) as refused:
            contribute.require_corpus(str(Path(self.directory) / "typo"))

        self.assertIn("is not there", str(refused.exception))

    def test_an_empty_corpus_directory_is_refused(self):
        """A directory holding nothing is not a distribution carrying nothing."""
        empty = Path(self.directory) / "empty"
        empty.mkdir()

        with self.assertRaises(error.PySmiError) as refused:
            contribute.require_corpus(str(empty))

        self.assertIn("holds no files", str(refused.exception))

    def test_a_remote_corpus_without_the_placeholder_is_refused(self):
        """Without @mib@ every module is looked up at one URL."""
        with self.assertRaises(error.PySmiError) as refused:
            contribute.require_corpus("https://data.mibsdepot.com/asn1/")

        self.assertIn("@mib@", str(refused.exception))

    def test_a_file_that_is_not_an_archive_is_refused(self):
        """--corpus takes the tree a distribution publishes, not one of its files."""
        loose = Path(self.directory) / "IF-MIB"
        loose.write_text(module("IF-MIB", "202106020000Z"), newline="")

        with self.assertRaises(error.PySmiError) as refused:
            contribute.require_corpus(str(loose))

        self.assertIn("not a .zip", str(refused.exception))

    def test_a_corpus_that_is_a_distribution_is_accepted(self):
        """The directory and archive cases a caller actually uses."""
        tree = Path(self.directory) / "asn1"
        tree.mkdir()
        (tree / "A-MIB").write_text(module("A-MIB", "202106020000Z"), newline="")

        self.assertEqual(1, len(contribute.require_corpus(str(tree))))

        archive = Path(self.directory) / "mibs-asn1.zip"

        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("A-MIB", module("A-MIB", "202106020000Z"))

        self.assertEqual(1, len(contribute.require_corpus(str(archive))))
        self.assertEqual(
            1, len(contribute.require_corpus("https://example.net/asn1/@mib@"))
        )


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
