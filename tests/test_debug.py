#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import logging
import sys
import unittest
import warnings

from pysmi import debug, error


class LoggingStateTestCase(unittest.TestCase):
    """Restore the levels and handlers these tests change."""

    def setUp(self):
        self.records = []

        names = [debug.PACKAGE_LOGGER, __name__, *debug.DEBUG_CATEGORIES.values()]
        self.levels = {name: logging.getLogger(name).level for name in names}
        self.handlers = list(logging.getLogger(debug.PACKAGE_LOGGER).handlers)

        self.handler = logging.Handler()
        self.handler.setLevel(logging.DEBUG)
        self.handler.emit = self.records.append

    def tearDown(self):
        for name, level in self.levels.items():
            logging.getLogger(name).setLevel(level)
        logging.getLogger(debug.PACKAGE_LOGGER).handlers = self.handlers

    def enable(self, *categories):
        debug.enableDebugLogging(*categories, handler=self.handler)

    def loggedBy(self, name):
        return [r for r in self.records if r.name == name]


class EnableDebugLoggingTestCase(LoggingStateTestCase):
    def testOnlyRequestedCategoryIsEnabled(self):
        self.enable("compiler")

        self.assertTrue(logging.getLogger("pysmi.compiler").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("pysmi.reader").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("pysmi.codegen").isEnabledFor(logging.DEBUG))

    def testSubmodulesInheritTheirCategory(self):
        self.enable("reader")

        self.assertTrue(logging.getLogger("pysmi.reader.localfile").isEnabledFor(logging.DEBUG))

    def testAllEnablesEveryCategory(self):
        self.enable("all")

        for name in debug.DEBUG_CATEGORIES.values():
            self.assertTrue(logging.getLogger(name).isEnabledFor(logging.DEBUG), name)

    def testCategoryCanBeTurnedOffAgain(self):
        self.enable("all", "!reader")

        self.assertTrue(logging.getLogger("pysmi.compiler").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("pysmi.reader").isEnabledFor(logging.DEBUG))

    def testUnknownCategoryRaises(self):
        self.assertRaises(error.PySmiError, self.enable, "nosuchcategory")

    def testRepeatedCallDoesNotDuplicateOutput(self):
        packageLogger = logging.getLogger(debug.PACKAGE_LOGGER)
        before = len(packageLogger.handlers)

        debug.enableDebugLogging("compiler")
        debug.enableDebugLogging("compiler")

        self.assertEqual(len(packageLogger.handlers), before + 1)


class StructuredLoggingTestCase(LoggingStateTestCase):
    def testMessageIsFormattedLazily(self):
        self.enable("compiler")

        logging.getLogger("pysmi.compiler").debug("MIB %s already parsed", "IF-MIB", extra={"mib": "IF-MIB"})

        (record,) = self.loggedBy("pysmi.compiler")
        # The message is still a template plus its arguments, so a handler that
        # is never reached costs nothing to skip.
        self.assertEqual(record.msg, "MIB %s already parsed")
        self.assertEqual(record.args, ("IF-MIB",))
        self.assertEqual(record.getMessage(), "MIB IF-MIB already parsed")

    def testStructuredFieldsReachTheRecord(self):
        self.enable("compiler")

        logging.getLogger("pysmi.compiler").debug("compiling %s", "IF-MIB", extra={"mib": "IF-MIB", "path": "/x"})

        (record,) = self.loggedBy("pysmi.compiler")
        self.assertEqual(record.mib, "IF-MIB")
        self.assertEqual(record.path, "/x")

    def testNoStructuredKeyShadowsARecordAttribute(self):
        # logging raises KeyError when extra= collides with a LogRecord field,
        # and only on the line that does it, so check them all up front.
        import ast
        import pathlib

        reserved = set(vars(logging.LogRecord("n", 1, "p", 1, "m", None, None)))
        reserved |= {"message", "asctime", "taskName"}

        collisions = []
        for path in sorted(pathlib.Path(debug.__file__).parent.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg == "extra" and isinstance(keyword.value, ast.Dict):
                        collisions += [
                            (path.name, node.lineno, key.value)
                            for key in keyword.value.keys
                            if isinstance(key, ast.Constant) and key.value in reserved
                        ]

        self.assertEqual(collisions, [])


class DeprecatedDebugTestCase(LoggingStateTestCase):
    def makeDebug(self, *flags):
        # A real Printer, because constructing one is what puts the package
        # logger at DEBUG; a stub printer would hide the very interaction
        # these tests are about.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return debug.Debug(*flags, printer=debug.Printer(handler=self.handler))

    def testDebugIsDeprecated(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            debug.Debug("compiler", printer=lambda msg: None)

        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))

    def testFlagsStillSupportBitwiseGuards(self):
        d = self.makeDebug("compiler")

        # Third-party code still guards its calls with `debug.logger & flag`.
        self.assertTrue(d & debug.flagCompiler)
        self.assertTrue(debug.flagCompiler & d)
        self.assertFalse(d & debug.flagReader)

    def testSetLoggerInstallsTheSwitch(self):
        previous = debug.logger
        try:
            d = self.makeDebug("compiler")
            debug.setLogger(d)
            self.assertTrue(debug.logger & debug.flagCompiler)
        finally:
            debug.setLogger(previous)

    def testFlagsDriveTheModuleLoggers(self):
        self.makeDebug("compiler")

        self.assertTrue(logging.getLogger("pysmi.compiler").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("pysmi.reader").isEnabledFor(logging.DEBUG))

    def testAllFlagDrivesEveryModuleLogger(self):
        self.makeDebug("all")

        for name in debug.DEBUG_CATEGORIES.values():
            self.assertTrue(logging.getLogger(name).isEnabledFor(logging.DEBUG), name)

    def testInverseFlagDisablesOneModuleLogger(self):
        self.makeDebug("all", "!reader")

        self.assertTrue(logging.getLogger("pysmi.compiler").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("pysmi.reader").isEnabledFor(logging.DEBUG))

    def testUnknownFlagRaises(self):
        self.assertRaises(error.PySmiError, self.makeDebug, "nosuchcategory")

    def testFlagMapStillCoversEveryCategory(self):
        self.assertEqual(set(debug.flagMap), set(debug.DEBUG_CATEGORIES))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
