#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A MIB name too long to be a filename is missing, not a crash.

``get_mib_variants`` appends extensions to the requested name, so a module
name approaching the filesystem's ``NAME_MAX`` produces candidate spellings
that cross it. ``PackageReader`` stats those candidates through
``Path.is_file()``, which swallows only ENOENT, ENOTDIR, EBADF and ELOOP --
ENAMETOOLONG escaped, and since the bundled package is consulted by default,
``mibdump`` exited 1 with a traceback where the same name against a
``file://`` source was reported cleanly as a missing source.

See pysnmp/pysmi#163.
"""

import errno
import io
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from pysmi import error
from pysmi.reader import package as package_module
from pysmi.reader.localfile import FileReader
from pysmi.reader.package import PackageReader
from pysmi.reader.zipreader import ZipReader
from pysmi.scripts import mibdump

# Longer than NAME_MAX on every filesystem pysmi is tested against (255 on
# ext4, APFS and NTFS alike), so every spelling get_mib_variants produces is
# unstattable rather than merely absent.
OVERLONG_MIB = "A" * 300


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


class PackageReaderTestCase(unittest.TestCase):
    def setUp(self):
        self.reader = PackageReader("pysmi.mibs.asn1")

    def testOverLongNameIsReportedMissing(self):
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            self.reader.get_data(OVERLONG_MIB)

    def testUnstattableCandidateIsTreatedAsAbsent(self):
        # Whether a name is too long is the platform's call, and Windows
        # reports an over-long path as ENOENT, which is swallowed already.
        # Raising ENAMETOOLONG outright pins the handler everywhere.
        candidate = mock.Mock()
        candidate.is_file.side_effect = OSError(
            errno.ENAMETOOLONG, "File name too long"
        )

        root = mock.Mock()
        root.joinpath.return_value = candidate

        with (
            mock.patch.object(
                package_module.importlib.resources, "files", return_value=root
            ),
            self.assertRaises(error.PySmiReaderFileNotFoundError),
        ):
            self.reader.get_data("SNMPv2-SMI")

        # Every variant was tried and none of them read.
        self.assertTrue(candidate.is_file.called)
        candidate.read_bytes.assert_not_called()


class LocalReaderParityTestCase(unittest.TestCase):
    """The local readers agree on what not-found means for such a name."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

        self.src = self.tmp / "src"
        self.src.mkdir()
        (self.src / "TEST-MIB").write_text("TEST-MIB DEFINITIONS ::= BEGIN\nEND\n")

        self.archive = self.tmp / "mibs.zip"
        with zipfile.ZipFile(self.archive, "w") as zf:
            zf.writestr("TEST-MIB", "TEST-MIB DEFINITIONS ::= BEGIN\nEND\n")

    def tearDown(self):
        self._tmp.cleanup()

    def testFileReaderReportsMissing(self):
        reader = FileReader(str(self.src))
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            reader.get_data(OVERLONG_MIB)

    def testZipReaderReportsMissing(self):
        reader = ZipReader(str(self.archive))
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            reader.get_data(OVERLONG_MIB)


class MibDumpTestCase(unittest.TestCase):
    """The name reaches mibdump's report rather than a traceback."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def testOverLongNameIsReportedAsAMissingSource(self):
        # No --no-bundled-mibs: the bundled package reader is what used to
        # raise, and it is in the default source list.
        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--destination-format=json",
            OVERLONG_MIB,
        )

        # mibdump's own EX_MIB_MISSING, the status the file:// source
        # already produced for this name.
        self.assertEqual(79, code)
        self.assertIn("Missing source MIBs", output)
        self.assertIn(OVERLONG_MIB, output)
        self.assertNotIn("Traceback", output)


if __name__ == "__main__":
    unittest.main()
