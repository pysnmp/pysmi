#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Pin the workarounds the code generators carry for known-broken MIBs.

Each generator keeps a ``constImports`` set: symbols imported into every module
it emits, whether or not the source asked for them. Five of those entries exist
for one reason -- real MIBs use the symbol without naming it in IMPORTS, which
RFC 2578 Section 3.2 does not allow. Each carries a comment naming the module
that motivated it, and a comment is all that held it in place.

``tests/data/broken/`` holds the smallest module that reproduces each one.
Dropping the matching ``constImports`` entry fails these tests. See
pysnmp/pysmi#69.
"""

import pathlib
import unittest

from tests.harness import render_json, render_source

BROKEN = pathlib.Path(__file__).parent / "data" / "broken"

#: Base types a MIB may use without importing, and the module that made it so.
UNIMPORTED_TYPES = {
    "TimeTicks": "DSA-MIB",
    "Counter32": "DSA-MIB",
    "Gauge32": "DSA-MIB",
    "Counter64": "A3COM-HUAWEI-LswINF-MIB",
}


def load(name):
    """Read a reproducer module off disk."""
    return (BROKEN / name).read_text()


def imports_of(source):
    """The IMPORTS clause of *source*, with the comments taken out.

    The reproducers explain themselves in a header comment that names the very
    symbol they leave unimported, so the clause has to be read from the module
    proper rather than from the file.
    """
    code = "\n".join(line.split("--", 1)[0] for line in source.splitlines())
    return code.split("IMPORTS", 1)[1].split(";", 1)[0]


class UnimportedTypeTestCase(unittest.TestCase):
    """A base type used without an IMPORTS entry still resolves."""

    def testThePySnmpBackendResolvesTheSyntax(self):
        for name in UNIMPORTED_TYPES:
            with self.subTest(syntax=name):
                source = render_source(load(f"UNIMPORTED-{name.upper()}-MIB"))
                self.assertIn(f"brokenObject = MibScalar((1, 3, 1), {name}())", source)
                # The type has to be imported into the generated module even
                # though the MIB never asked for it, or the line above raises
                # NameError on load.
                imported = next(line for line in source.splitlines() if '"SNMPv2-SMI"' in line)
                self.assertIn(f'"{name}"', imported)

    def testTheJsonBackendResolvesTheSyntax(self):
        for name in UNIMPORTED_TYPES:
            with self.subTest(syntax=name):
                doc = render_json(load(f"UNIMPORTED-{name.upper()}-MIB"))
                self.assertEqual(doc["brokenObject"]["syntax"]["type"], name)

    def testEveryReproducerNamesTheModuleThatMotivatedIt(self):
        for name, module in UNIMPORTED_TYPES.items():
            with self.subTest(syntax=name):
                self.assertIn(module, load(f"UNIMPORTED-{name.upper()}-MIB"))

    def testNoReproducerImportsTheTypeItReliesOn(self):
        for name in UNIMPORTED_TYPES:
            with self.subTest(syntax=name):
                self.assertNotIn(name, imports_of(load(f"UNIMPORTED-{name.upper()}-MIB")))


class UnimportedNotificationTypeTestCase(unittest.TestCase):
    """The NOTIFICATION-TYPE macro invoked without an IMPORTS entry."""

    def setUp(self):
        self.source = load("UNIMPORTED-NOTIFICATION-TYPE-MIB")

    def testThePySnmpBackendBuildsTheNotification(self):
        self.assertIn("brokenNotification = NotificationType((1, 3, 2))", render_source(self.source))

    def testTheJsonBackendBuildsTheNotification(self):
        doc = render_json(self.source)
        self.assertEqual(doc["brokenNotification"]["class"], "notificationtype")

    def testTheMacroIsNeverImported(self):
        self.assertNotIn("NOTIFICATION-TYPE", imports_of(self.source))


if __name__ == "__main__":
    unittest.main(verbosity=2)
