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

The mode is the one the kernel gives any new file -- 0666 less the umask --
because :py:func:`~pysmi.writer.base.open_new_file` asks for it and lets the
umask subtract, rather than choosing a mode on the caller's behalf. So these
tests set a umask and assert what a file created under it comes out as.
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest

from pysmi.writer import FileWriter, PyFileWriter
from pysmi.writer.base import open_new_file


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
        # No mode is chosen for the caller: a build into a directory it does
        # not want group-readable keeps that.
        os.umask(0o077)

        FileWriter(self.path).set_options(suffix=".json").put_data("TEST-MIB", "{}")

        self.assertEqual(0o600, self.mode("TEST-MIB.json"))

    def testTheModeFollowsTheUmaskInEffectWhenTheFileIsCreated(self):
        for umask, expected in ((0o022, 0o644), (0o077, 0o600), (0o002, 0o664)):
            with self.subTest(umask=oct(umask)):
                os.umask(umask)

                fd, path = open_new_file(self.path)
                os.close(fd)

                try:
                    self.assertEqual(expected, stat.S_IMODE(os.stat(path).st_mode))
                finally:
                    os.unlink(path)

    def testTheUmaskIsNotTouched(self):
        # The mode used to be derived by reading the umask, which means
        # setting it: a window in which another thread creating a file saw a
        # mask this library installed. Asking the kernel for 0666 and letting
        # it subtract removes the window rather than narrowing it.
        os.umask(0o027)

        fd, path = open_new_file(self.path)
        os.close(fd)
        os.unlink(path)

        current = os.umask(0o022)

        self.assertEqual(0o027, current)


class NewFileTestCase(unittest.TestCase):
    """What open_new_file gives back, on every platform."""

    def setUp(self):
        self.path = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def testItReturnsAWritableDescriptorAndItsPath(self):
        fd, path = open_new_file(self.path)

        try:
            os.write(fd, b"content")
        finally:
            os.close(fd)

        with open(path, "rb") as fileObj:
            self.assertEqual(b"content", fileObj.read())

    def testTheFileIsInsideTheDirectoryAsked(self):
        fd, path = open_new_file(self.path)
        os.close(fd)

        self.assertEqual(self.path, os.path.dirname(path))

    def testEachCallGetsItsOwnFile(self):
        first, firstPath = open_new_file(self.path)
        second, secondPath = open_new_file(self.path)
        os.close(first)
        os.close(second)

        self.assertNotEqual(firstPath, secondPath)

    def testNewlinesAreNotTranslated(self):
        # The descriptor is opened binary. Without that the C runtime rewrites
        # every newline written through it on Windows, so one MIB would
        # compile to different bytes there than anywhere else -- which
        # tests/test_reproducible_output.py exists to prevent.
        fd, path = open_new_file(self.path)

        try:
            os.write(fd, b"one\ntwo\n")
        finally:
            os.close(fd)

        with open(path, "rb") as fileObj:
            self.assertEqual(b"one\ntwo\n", fileObj.read())


if __name__ == "__main__":
    unittest.main()
