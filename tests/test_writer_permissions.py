#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""A module a writer stores can be read by someone other than the builder.

``tempfile.mkstemp`` creates a file readable by its owner alone, and both file
writers rename that file into place, so every module a build stored came out
0600. Invisible while the output is read back by the user who wrote it, and not
invisible at all when it is published: pysnmp/mibs serves its corpus from a
container running as another uid, and every module in it answered 403.

The mode follows the umask, which is what says how permissive a new file should
be -- so these tests set one and assert against it rather than against a
hard-coded 0644.
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest

from pysmi.writer import FileWriter, PyFileWriter
from pysmi.writer.base import readable_mode


@unittest.skipIf(
    sys.platform[:3] == "win", "POSIX mode bits do not describe Windows files"
)
class WriterPermissionsTestCase(unittest.TestCase):
    """What a stored module's mode is."""

    def setUp(self):
        self.path = tempfile.mkdtemp()
        self.umask = os.umask(0o022)

    def tearDown(self):
        os.umask(self.umask)
        shutil.rmtree(self.path, ignore_errors=True)

    def mode(self, filename):
        """The permission bits of one file in the destination."""
        return stat.S_IMODE(os.stat(os.path.join(self.path, filename)).st_mode)

    def testTheJsonWriterStoresAReadableFile(self):
        FileWriter(self.path).set_options(suffix=".json").put_data("TEST-MIB", "{}")

        self.assertEqual(0o644, self.mode("TEST-MIB.json"))

    def testThePythonWriterStoresAReadableFile(self):
        PyFileWriter(self.path).set_options(pyCompile=False).put_data(
            "TEST-MIB", "# nothing\n"
        )

        self.assertEqual(0o644, self.mode("TEST-MIB.py"))

    def testAStricterUmaskIsHonoured(self):
        # The mode is not hard-coded: a caller building into a directory it
        # does not want group-readable keeps that.
        os.umask(0o077)

        FileWriter(self.path).set_options(suffix=".json").put_data("TEST-MIB", "{}")

        self.assertEqual(0o600, self.mode("TEST-MIB.json"))

    def testTheUmaskIsLeftAsItWasFound(self):
        # Reading the umask means setting it. Anything that left it changed
        # would silently alter every file the calling program writes after.
        before = os.umask(0o027)
        os.umask(before)

        readable_mode()

        after = os.umask(0o027)
        os.umask(after)

        self.assertEqual(before, after)

    def testTheModeFollowsTheUmask(self):
        for umask, expected in ((0o022, 0o644), (0o077, 0o600), (0o002, 0o664)):
            with self.subTest(umask=oct(umask)):
                os.umask(umask)

                self.assertEqual(expected, readable_mode())


if __name__ == "__main__":
    unittest.main()
