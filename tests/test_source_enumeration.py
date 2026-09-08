#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Asking a source what it holds, and compiling all of it.

A collection is compiled by listing its files and passing the names in,
which is what every build script around pysmi has had to write for
itself. Two things make that list wrong: a file named for something other
than the module inside it, and a file holding more than one module. Both
are settled by reading the module headers rather than the file names, so
that is what enumeration does -- and ``--build-all`` is the same list
handed straight to the compiler.
"""

import builtins
import importlib.resources
import io
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from pysmi import error
from pysmi.codegen import NullCodeGen
from pysmi.compiler import MibCompiler
from pysmi.mibinfo import module_names
from pysmi.parser import SmiStarParser
from pysmi.reader import FileReader, HttpReader, ZipReader
from pysmi.reader.package import PackageReader
from pysmi.scripts import mibdump
from pysmi.writer import CallbackWriter


def mibText(name, oid):
    """A minimal but complete module, so the compiler accepts it."""
    return f"""{name} DEFINITIONS ::= BEGIN

IMPORTS
    OBJECT-TYPE FROM SNMPv2-SMI;

{name.lower().replace("-", "")}Scalar OBJECT-TYPE
    SYNTAX  INTEGER
    MAX-ACCESS  read-only
    STATUS  current
    DESCRIPTION "a scalar"
    ::= {{ {oid} }}

END
"""


@contextmanager
def refusingToOpen(basename):
    """Make :py:func:`open` fail for one file, as a permission denial would.

    Chmod would do it, but not as a test: the run is often root, where the
    mode is ignored, and Windows does not take read access away at all.
    """
    realOpen = builtins.open

    def refusing(file, *args, **kwargs):
        if os.path.basename(str(file)) == basename:
            raise PermissionError(13, "Permission denied", str(file))

        return realOpen(file, *args, **kwargs)

    with mock.patch.object(builtins, "open", refusing):
        yield


def runMibdump(*args):
    """Run the mibdump entry point, returning its exit code and output."""
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["mibdump", *args]

    try:
        with redirect_stdout(out), redirect_stderr(err):
            mibdump.start()
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
    finally:
        sys.argv = argv

    return code, out.getvalue() + err.getvalue()


class ModuleNamesTestCase(unittest.TestCase):
    """Reading the module headers out of MIB text."""

    def testTheDeclaredName(self):
        self.assertEqual(
            ["TEST-ONE-MIB"],
            module_names(mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")),
        )

    def testEveryModuleInAFileHoldingSeveral(self):
        """One file, two modules -- and both have to be built."""
        text = mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1") + mibText(
            "TEST-TWO-MIB", "1 3 6 1 4 1 99991 2"
        )

        self.assertEqual(["TEST-ONE-MIB", "TEST-TWO-MIB"], module_names(text))

    def testALowerCaseModuleName(self):
        """Vendors ship ``companyMIB``; the lexer hands those back lower case."""
        self.assertEqual(
            ["proware-SNMP-MIB"],
            module_names(mibText("proware-SNMP-MIB", "1 3 6 1 4 1 99991 3")),
        )

    def testAHeaderBrokenAcrossLinesWithACommentInIt(self):
        """Which is why this is lexed and not matched with an expression."""
        text = """TEST-AWKWARD-MIB
    -- REVISION 2019-01-01, and a comment right here
    DEFINITIONS ::= BEGIN
END
"""
        self.assertEqual(["TEST-AWKWARD-MIB"], module_names(text))

    def testTextThatIsNotAMibAtAll(self):
        """A login wall served as 200 is how this turns up in practice."""
        self.assertEqual([], module_names("<html><body>Sign in</body></html>"))

    def testAnEmptyFile(self):
        self.assertEqual([], module_names(""))


class FileReaderListTestCase(unittest.TestCase):
    """What a directory tree reports holding."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def testEveryModuleInTheTree(self):
        (self.root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "TEST-TWO-MIB").write_text(
            mibText("TEST-TWO-MIB", "1 3 6 1 4 1 99991 2")
        )

        self.assertEqual(
            ["TEST-ONE-MIB", "TEST-TWO-MIB"],
            sorted(FileReader(str(self.root)).list_mibs()),
        )

    def testTheDeclaredNameNotTheFileName(self):
        """The whole reason this reads the text: the two need not agree."""
        (self.root / "whatever.txt").write_text(
            mibText("TEST-DECLARED-MIB", "1 3 6 1 4 1 99991 4")
        )

        self.assertEqual(
            ["TEST-DECLARED-MIB"], list(FileReader(str(self.root)).list_mibs())
        )

    def testAFileHoldingTwoModulesReportsBoth(self):
        (self.root / "PAIR").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
            + mibText("TEST-TWO-MIB", "1 3 6 1 4 1 99991 2")
        )

        self.assertEqual(
            ["TEST-ONE-MIB", "TEST-TWO-MIB"],
            sorted(FileReader(str(self.root)).list_mibs()),
        )

    def testAFileThatIsNotAMibContributesNothing(self):
        (self.root / "README.md").write_text("# what is in here\n")
        (self.root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )

        self.assertEqual(["TEST-ONE-MIB"], list(FileReader(str(self.root)).list_mibs()))

    def testDotFilesAreSkipped(self):
        """``.index`` names modules; reading it as one would invent a name."""
        (self.root / ".index").write_text("TEST-ONE-MIB TEST-ONE-MIB\n")
        (self.root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )

        self.assertEqual(["TEST-ONE-MIB"], list(FileReader(str(self.root)).list_mibs()))

    def testEnumeratingDoesNotMoveAnExistingLookup(self):
        """A name a file name already leads to keeps resolving the same way.

        Indexing every module the scan sees would let the copy that happened
        to be read first answer for a name that another directory holds under
        its own name -- changing which copy the tree resolves to as a side
        effect of having been listed.
        """
        first = self.root / "a"
        first.mkdir()
        (first / "oddly-named.txt").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )
        second = self.root / "b"
        second.mkdir()
        (second / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 7")
        )

        reader = FileReader(str(self.root))
        self.assertEqual(["TEST-ONE-MIB"], list(reader.list_mibs()))

        _info, text = reader.get_data("TEST-ONE-MIB")

        self.assertIn("99991 7", text)

    def testAModuleNoFileNameLeadsToBecomesFetchable(self):
        """The case the scan is allowed to index: nothing else finds it."""
        (self.root / "oddly-named.txt").write_text(
            mibText("TEST-HIDDEN-MIB", "1 3 6 1 4 1 99991 8")
        )

        reader = FileReader(str(self.root))

        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            reader.get_data("TEST-HIDDEN-MIB")

        self.assertEqual(["TEST-HIDDEN-MIB"], list(reader.list_mibs()))

        _info, text = reader.get_data("TEST-HIDDEN-MIB")

        self.assertIn("99991 8", text)

    def testAFileTooLargeToBeAMibIsSkipped(self):
        """``maxMibSize`` bounds what is read; it has to bound this read too."""
        (self.root / "HUGE").write_text("x" * 20000)
        (self.root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )

        reader = FileReader(str(self.root))
        reader.maxMibSize = 10000

        self.assertEqual(["TEST-ONE-MIB"], list(reader.list_mibs()))

    def testAFileThatCannotBeReadIsSkipped(self):
        """One unreadable file is that file's problem, not the tree's."""
        (self.root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )
        (self.root / "LOCKED").write_text(
            mibText("TEST-LOCKED-MIB", "1 3 6 1 4 1 99991 9")
        )

        with refusingToOpen("LOCKED"):
            listed = list(FileReader(str(self.root)).list_mibs())

        self.assertEqual(["TEST-ONE-MIB"], listed)

    def testAFileThatCannotBeReadIsRaisedWhenErrorsAreNotIgnored(self):
        """``ignoreErrors=False`` means the caller wants to hear about it."""
        (self.root / "LOCKED").write_text(
            mibText("TEST-LOCKED-MIB", "1 3 6 1 4 1 99991 9")
        )

        reader = FileReader(str(self.root), ignoreErrors=False)

        with refusingToOpen("LOCKED"), self.assertRaises(error.PySmiError) as raised:
            list(reader.list_mibs())

        self.assertIn("LOCKED", str(raised.exception))

    def testAnEmptyTree(self):
        self.assertEqual([], list(FileReader(str(self.root)).list_mibs()))

    def testTheSameModuleInTwoDirectoriesIsNamedOnce(self):
        """The compiler decides which copy wins; the list just names it once."""
        for sub in ("a", "b"):
            directory = self.root / sub
            directory.mkdir()
            (directory / "TEST-ONE-MIB").write_text(
                mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
            )

        self.assertEqual(["TEST-ONE-MIB"], list(FileReader(str(self.root)).list_mibs()))


class OtherReadersListTestCase(unittest.TestCase):
    """Sources that are not a directory."""

    def testAZipArchive(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "mibs.zip")

            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(
                    "whatever.txt", mibText("TEST-ZIP-MIB", "1 3 6 1 4 1 99991 5")
                )
                zf.writestr("README", "not a mib\n")

            self.assertEqual(["TEST-ZIP-MIB"], list(ZipReader(archive).list_mibs()))

    def testAZipMemberThatCannotBeReadIsSkipped(self):
        """One broken member does not stop the archive being enumerated."""
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "mibs.zip")

            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("BROKEN", "whatever")
                zf.writestr(
                    "TEST-ZIP-MIB", mibText("TEST-ZIP-MIB", "1 3 6 1 4 1 99991 5")
                )

            reader = ZipReader(archive)
            realRead = reader._readZipFile

            def refusingBroken(refs):
                if refs is reader._members["BROKEN"]:
                    raise zipfile.BadZipFile("member is corrupt")

                return realRead(refs)

            with mock.patch.object(reader, "_readZipFile", refusingBroken):
                listed = list(reader.list_mibs())

            self.assertEqual(["TEST-ZIP-MIB"], listed)

    def testAZipMemberThatReadsAsEmptyContributesNothing(self):
        """``_readZipFile`` reports an unreadable member as ``""``, not by raising."""
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "mibs.zip")

            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("EMPTY", "whatever")
                zf.writestr(
                    "TEST-ZIP-MIB", mibText("TEST-ZIP-MIB", "1 3 6 1 4 1 99991 5")
                )

            reader = ZipReader(archive)
            reader._members["EMPTY"] = [[None, "EMPTY", None]]

            self.assertEqual(["TEST-ZIP-MIB"], list(reader.list_mibs()))

    def testAZipDotMemberIsSkipped(self):
        """Same reason the directory reader skips them: an index is not a MIB."""
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "mibs.zip")

            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(".index", "TEST-ZIP-MIB TEST-ZIP-MIB\n")
                zf.writestr(
                    "TEST-ZIP-MIB", mibText("TEST-ZIP-MIB", "1 3 6 1 4 1 99991 5")
                )

            self.assertEqual(["TEST-ZIP-MIB"], list(ZipReader(archive).list_mibs()))

    def testAZipMemberTooLargeToBeAMibIsSkipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "mibs.zip")

            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("HUGE", "x" * 20000)
                zf.writestr(
                    "TEST-ZIP-MIB", mibText("TEST-ZIP-MIB", "1 3 6 1 4 1 99991 5")
                )

            reader = ZipReader(archive)
            reader.maxMibSize = 10000

            self.assertEqual(["TEST-ZIP-MIB"], list(reader.list_mibs()))

    def testAPackageResourceThatCannotBeReadIsSkipped(self):
        """One unreadable resource does not stop the package being enumerated."""
        reader = PackageReader(MibCompiler.bundledMibsPackage)
        realFiles = importlib.resources.files

        def refusingOne(package):
            root = realFiles(package)
            realJoin = root.joinpath

            class Refusing:
                def __init__(self, wrapped):
                    self._wrapped = wrapped
                    self.name = wrapped.name

                def is_file(self):
                    return self._wrapped.is_file()

                def read_bytes(self):
                    if self.name == "IF-MIB":
                        raise PermissionError(13, "Permission denied", self.name)

                    return self._wrapped.read_bytes()

            class Wrapper:
                def iterdir(self):
                    return [Refusing(x) for x in root.iterdir()]

                def joinpath(self, *args):
                    return realJoin(*args)

            return Wrapper()

        with mock.patch.object(importlib.resources, "files", refusingOne):
            listed = list(reader.list_mibs())

        self.assertIn("SNMPv2-SMI", listed)
        self.assertNotIn("IF-MIB", listed)

    def testAPackageResourceTooLargeToBeAMibIsSkipped(self):
        reader = PackageReader(MibCompiler.bundledMibsPackage)
        reader.maxMibSize = 2000

        listed = list(reader.list_mibs())

        self.assertNotIn("IF-MIB", listed)
        self.assertLess(len(listed), 485)

    def testAPackageThatIsNotInstalledReportsNothing(self):
        """Same answer :py:meth:`get_data` gives: the source has no modules."""
        self.assertEqual([], list(PackageReader("no.such.package.at.all").list_mibs()))

    def testTheBundledPackage(self):
        """Every module the bundle carries, and nothing that is not one."""
        bundled = list(PackageReader(MibCompiler.bundledMibsPackage).list_mibs())

        self.assertIn("SNMPv2-SMI", bundled)
        self.assertIn("IF-MIB", bundled)
        self.assertNotIn("__init__", bundled)
        self.assertEqual(len(bundled), len(set(bundled)))

    def testASourceThatCannotBeListedReportsNothing(self):
        """A web server answers for a name; it cannot be asked what it has.

        Reporting nothing is not the same as being empty, and is why
        ``--build-all`` is documented as covering the local sources.
        """
        reader = HttpReader("https://pysnmp.github.io:443/mibs/asn1/@mib@")

        self.assertEqual([], list(reader.list_mibs()))


class CompilerListTestCase(unittest.TestCase):
    """The union across a compiler's configured sources."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )

    def tearDown(self):
        self.tmp.cleanup()

    def compiler(self, **kwargs):
        compiler = MibCompiler(
            SmiStarParser(), NullCodeGen(), CallbackWriter(lambda *x: None), **kwargs
        )
        compiler.add_sources(FileReader(str(self.root)))
        return compiler

    def testTheSourcesTheCallerAdded(self):
        self.assertEqual(["TEST-ONE-MIB"], self.compiler().list_mibs())

    def testTheBundleIsNotSomethingToBuild(self):
        """It resolves what the built modules import; it is not the collection."""
        self.assertNotIn("SNMPv2-SMI", self.compiler().list_mibs())

    def testTheBundleWhenItIsAskedFor(self):
        listed = self.compiler().list_mibs(includeBundled=True)

        self.assertIn("TEST-ONE-MIB", listed)
        self.assertIn("SNMPv2-SMI", listed)

    def testWithoutTheBundleConfiguredAtAll(self):
        compiler = self.compiler(useBundledMibs=False)

        self.assertEqual(["TEST-ONE-MIB"], compiler.list_mibs())
        self.assertEqual(["TEST-ONE-MIB"], compiler.list_mibs(includeBundled=True))


class BuildAllTestCase(unittest.TestCase):
    """``--build-all`` end to end."""

    def setUp(self):
        self.sources = tempfile.TemporaryDirectory()
        self.output = tempfile.TemporaryDirectory()
        root = Path(self.sources.name)
        (root / "TEST-ONE-MIB").write_text(
            mibText("TEST-ONE-MIB", "1 3 6 1 4 1 99991 1")
        )
        (root / "misnamed.txt").write_text(
            mibText("TEST-TWO-MIB", "1 3 6 1 4 1 99991 2")
        )

    def tearDown(self):
        self.sources.cleanup()
        self.output.cleanup()

    def written(self):
        return sorted(p.stem for p in Path(self.output.name).glob("*.json"))

    def testEveryModuleTheTreeHoldsIsBuilt(self):
        code, _output = runMibdump(
            "--build-all",
            f"--mib-source={self.sources.name}",
            "--destination-format=json",
            f"--destination-directory={self.output.name}",
        )

        self.assertEqual(0, code)
        self.assertIn("TEST-ONE-MIB", self.written())

    def testAModuleInAFileNamedForSomethingElseIsBuiltToo(self):
        """A build driven by file names would have compiled this as ``misnamed``."""
        code, _output = runMibdump(
            "--build-all",
            f"--mib-source={self.sources.name}",
            "--destination-format=json",
            f"--destination-directory={self.output.name}",
        )

        self.assertEqual(0, code)
        self.assertIn("TEST-TWO-MIB", self.written())

    def testNamingModulesAsWellIsRefused(self):
        """The two say different things about what to build."""
        code, output = runMibdump(
            "--build-all",
            f"--mib-source={self.sources.name}",
            "--destination-format=json",
            f"--destination-directory={self.output.name}",
            "TEST-ONE-MIB",
        )

        self.assertEqual(mibdump.EX_USAGE, code)
        self.assertIn("--build-all", output)

    def testAnUnusableSourceUrlIsStillReportedNotRaised(self):
        """The sources are built earlier now; the error still has to read as one."""
        code, output = runMibdump(
            "--build-all",
            "--mib-source=gopher://example.invalid/mibs",
            "--destination-format=json",
            f"--destination-directory={self.output.name}",
        )

        self.assertEqual(mibdump.EX_SOFTWARE, code)
        self.assertIn("Unsupported URL scheme", output)

    def testSourcesHoldingNothingAreReported(self):
        """Silently succeeding here would publish an empty distribution."""
        with tempfile.TemporaryDirectory() as empty:
            code, output = runMibdump(
                "--build-all",
                f"--mib-source={empty}",
                "--destination-format=json",
                f"--destination-directory={self.output.name}",
            )

        self.assertEqual(mibdump.EX_MIB_MISSING, code)
        self.assertIn("no MIB modules", output)


if __name__ == "__main__":
    unittest.main()
