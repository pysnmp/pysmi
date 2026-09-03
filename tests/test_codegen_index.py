#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The MIB index is a published artifact and must be asserted directly.

``mibdump --build-index`` renders the index through ``gen_index``, and
``pysnmp/mibs`` republishes the JSON form as its OID lookup table. No consumer
object model stands between pysmi and that file, so nothing but a source-level
assertion can check it. See pysnmp/pysmi#96 and #99.
"""

import json
import sys
import unittest

from pysmi import error
from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.null import NullCodeGen
from pysmi.compiler import MibStatus
from tests.harness import symbol_table


def status(**attrs):
    """Build a compiled MibStatus carrying the attributes the index reads."""
    st = MibStatus("compiled")
    for name, value in attrs.items():
        setattr(st, name, value)
    return st


class JsonIndexTestCase(unittest.TestCase):
    def index(self, processed, **kwargs):
        return json.loads(JsonCodeGen().gen_index(processed, **kwargs))

    def testEmptyIndexHasEverySection(self):
        self.assertEqual(
            sorted(self.index({})),
            ["compliance", "enterprise", "identity", "meta", "notification", "oids"],
        )

    def testIdentityMapsOidToModule(self):
        out = self.index({"A-MIB": status(identity="1.3.6.1.4.1.9")})
        self.assertEqual(out["identity"], {"1.3.6.1.4.1.9": ["A-MIB"]})

    def testEnterpriseMapsOidToModule(self):
        out = self.index({"A-MIB": status(enterprise="1.3.6.1.4.1.9")})
        self.assertEqual(out["enterprise"], {"1.3.6.1.4.1.9": ["A-MIB"]})

    def testNotificationMapsOidToModule(self):
        out = self.index({"A-MIB": status(notification=("1.3.6.1.4.1.9.0.1",))})
        self.assertEqual(out["notification"], {"1.3.6.1.4.1.9.0.1": ["A-MIB"]})

    def testNotificationGathersEveryModuleAtOneOid(self):
        out = self.index(
            {
                "A-MIB": status(notification=("1.3.6.1.4.1.9.0.1",)),
                "B-MIB": status(notification=("1.3.6.1.4.1.9.0.1",)),
            }
        )
        self.assertEqual(out["notification"], {"1.3.6.1.4.1.9.0.1": ["A-MIB", "B-MIB"]})

    def testNotificationIsNotCollapsedByPrefix(self):
        """Unlike ``oids``, every notification stays addressable on its own."""
        out = self.index({"A-MIB": status(notification=("1.3.6.1.4.1.9.0.1", "1.3.6.1.4.1.9.0.2"))})
        self.assertEqual(sorted(out["notification"]), ["1.3.6.1.4.1.9.0.1", "1.3.6.1.4.1.9.0.2"])

    def testComplianceMapsEveryOidToModule(self):
        out = self.index({"A-MIB": status(compliance=("1.3.6.1.4.1.9.1", "1.3.6.1.4.1.9.2"))})
        self.assertEqual(
            out["compliance"],
            {"1.3.6.1.4.1.9.1": ["A-MIB"], "1.3.6.1.4.1.9.2": ["A-MIB"]},
        )

    def testTwoModulesUnderOneIdentityBothAppear(self):
        out = self.index(
            {
                "A-MIB": status(identity="1.3.6.1.4.1.9"),
                "B-MIB": status(identity="1.3.6.1.4.1.9"),
            }
        )
        self.assertEqual(out["identity"], {"1.3.6.1.4.1.9": ["A-MIB", "B-MIB"]})

    def testAbsentAttributesAreSkipped(self):
        out = self.index({"A-MIB": status()})
        self.assertEqual(out["identity"], {})
        self.assertEqual(out["enterprise"], {})
        self.assertEqual(out["compliance"], {})
        self.assertEqual(out["oids"], {})

    def testCommentsLandInMeta(self):
        out = self.index({}, comments=["Produced by pysmi"])
        self.assertEqual(out["meta"]["comments"], ["Produced by pysmi"])

    def testMetaIsEmptyWithoutComments(self):
        self.assertEqual(self.index({})["meta"], {})


class JsonIndexOidsTestCase(unittest.TestCase):
    """The oids section collapses to the shortest prefix that answers a lookup."""

    def index(self, processed, **kwargs):
        return json.loads(JsonCodeGen().gen_index(processed, **kwargs))

    def testOidsMapEveryOidToModule(self):
        out = self.index({"A-MIB": status(oids=("1.3.6.1.4.1.9", "1.3.6.1.4.1.10"))})
        self.assertEqual(
            out["oids"],
            {"1.3.6.1.4.1.9": ["A-MIB"], "1.3.6.1.4.1.10": ["A-MIB"]},
        )

    def testChildOidsCollapseIntoTheirPrefix(self):
        out = self.index({"A-MIB": status(oids=("1.3.6.1.4.1.9", "1.3.6.1.4.1.9.1", "1.3.6.1.4.1.9.1.2"))})
        self.assertEqual(out["oids"], {"1.3.6.1.4.1.9": ["A-MIB"]})

    def testChildOidOfAnotherModuleIsKept(self):
        # The prefix does not answer for B-MIB, so collapsing would lose it.
        out = self.index(
            {
                "A-MIB": status(oids=("1.3.6.1.4.1.9",)),
                "B-MIB": status(oids=("1.3.6.1.4.1.9.1",)),
            }
        )
        self.assertEqual(
            out["oids"],
            {"1.3.6.1.4.1.9": ["A-MIB"], "1.3.6.1.4.1.9.1": ["B-MIB"]},
        )

    def testPrefixCoveringBothModulesCollapses(self):
        out = self.index(
            {
                "A-MIB": status(oids=("1.3.6.1.4.1.9", "1.3.6.1.4.1.9.1")),
                "B-MIB": status(oids=("1.3.6.1.4.1.9", "1.3.6.1.4.1.9.1")),
            }
        )
        self.assertEqual(out["oids"], {"1.3.6.1.4.1.9": ["A-MIB", "B-MIB"]})

    def testOidsFromSeparateSubtreesAreBothKept(self):
        out = self.index(
            {
                "A-MIB": status(oids=("1.3.6.1.2.1.1",)),
                "B-MIB": status(oids=("1.3.6.1.4.1.9",)),
            }
        )
        self.assertEqual(sorted(out["oids"]), ["1.3.6.1.2.1.1", "1.3.6.1.4.1.9"])


class JsonIndexOrderingTestCase(unittest.TestCase):
    """Ordering is what makes the published index reproducible across runs."""

    def testOidKeysSortNumericallyNotLexicographically(self):
        out = JsonCodeGen().gen_index(
            {
                "A-MIB": status(compliance=("1.3.6.1.4.1.10", "1.3.6.1.4.1.9", "1.3.6.1.4.1.100")),
            }
        )
        keys = list(json.loads(out)["compliance"])
        self.assertEqual(keys, ["1.3.6.1.4.1.9", "1.3.6.1.4.1.10", "1.3.6.1.4.1.100"])

    def testNonOidKeysSortLexicographically(self):
        old = json.dumps({"identity": {"zzz": ["Z-MIB"], "aaa": ["A-MIB"]}})
        out = json.loads(JsonCodeGen().gen_index({}, old_index_data=old))
        self.assertEqual(list(out["identity"]), ["aaa", "zzz"])

    def testModuleListsAreSortedAndDeduplicated(self):
        old = json.dumps({"identity": {"1.3.6": ["Z-MIB", "A-MIB", "Z-MIB"]}})
        out = json.loads(JsonCodeGen().gen_index({}, old_index_data=old))
        self.assertEqual(out["identity"]["1.3.6"], ["A-MIB", "Z-MIB"])

    def testTopLevelSectionsAreSorted(self):
        out = json.loads(JsonCodeGen().gen_index({}))
        self.assertEqual(list(out), ["compliance", "enterprise", "identity", "meta", "notification", "oids"])

    def testSameInputRendersByteIdentically(self):
        processed = {
            "B-MIB": status(identity="1.3.6.1.4.1.10", oids=("1.3.6.1.4.1.10.1",)),
            "A-MIB": status(identity="1.3.6.1.4.1.9", oids=("1.3.6.1.4.1.9.1",)),
        }
        first = JsonCodeGen().gen_index(processed)
        second = JsonCodeGen().gen_index(dict(reversed(list(processed.items()))))
        self.assertEqual(first, second)


class JsonIndexMergeTestCase(unittest.TestCase):
    """An existing index is merged into, not replaced -- mibs compiles in batches."""

    def testExistingSectionsSurvive(self):
        old = json.dumps({"identity": {"1.3.6.1.4.1.9": ["A-MIB"]}})
        out = json.loads(JsonCodeGen().gen_index({}, old_index_data=old))
        self.assertEqual(out["identity"], {"1.3.6.1.4.1.9": ["A-MIB"]})

    def testNewModuleJoinsAnExistingOid(self):
        old = json.dumps({"identity": {"1.3.6.1.4.1.9": ["A-MIB"]}})
        out = json.loads(JsonCodeGen().gen_index({"B-MIB": status(identity="1.3.6.1.4.1.9")}, old_index_data=old))
        self.assertEqual(out["identity"]["1.3.6.1.4.1.9"], ["A-MIB", "B-MIB"])

    def testUnknownSectionsInAnOldIndexAreCarried(self):
        old = json.dumps({"custom": {"1.3.6": ["A-MIB"]}})
        out = json.loads(JsonCodeGen().gen_index({}, old_index_data=old))
        self.assertEqual(out["custom"], {"1.3.6": ["A-MIB"]})

    def testEmptyOldIndexIsIgnored(self):
        self.assertEqual(
            JsonCodeGen().gen_index({}, old_index_data=""),
            JsonCodeGen().gen_index({}),
        )

    def testMalformedOldIndexRaises(self):
        with self.assertRaises(error.PySmiCodegenError):
            JsonCodeGen().gen_index({}, old_index_data="{not json")

    def testOldIndexOfWrongTypeRaises(self):
        with self.assertRaises(error.PySmiCodegenError):
            JsonCodeGen().gen_index({}, old_index_data=b"\xff\xfe")


class PySnmpIndexTestCase(unittest.TestCase):
    """The pysnmp index is Python source and must stay importable."""

    def testIndexMapsModuleIdentityOidToModule(self):
        out = PySnmpCodeGen().gen_index({"A-MIB": status(oid="1.3.6.1.4.1.9")})
        self.assertIn('ObjectName("1.3.6.1.4.1.9"): "A-MIB",', out)

    def testModulesWithoutAnOidAreSkipped(self):
        out = PySnmpCodeGen().gen_index({"A-MIB": status()})
        self.assertIn("oidToMibMap = {\n}", out)

    def testIndexIsValidPythonYieldingTheMap(self):
        out = PySnmpCodeGen().gen_index(
            {
                "A-MIB": status(oid="1.3.6.1.4.1.9"),
                "B-MIB": status(oid="1.3.6.1.4.1.10"),
            }
        )
        ctx = {}
        exec(compile(out, "index", "exec"), ctx, ctx)
        self.assertEqual(
            {str(k): v for k, v in ctx["oidToMibMap"].items()},
            {"1.3.6.1.4.1.9": "A-MIB", "1.3.6.1.4.1.10": "B-MIB"},
        )

    def testCommentsBecomeAHeaderNotCode(self):
        out = PySnmpCodeGen().gen_index({}, comments=["Produced by pysmi"])
        self.assertIn("# Produced by pysmi\n", out)
        self.assertTrue(out.startswith("#"))
        exec(compile(out, "index", "exec"), {}, {})

    def testNoCommentsMeansNoHeader(self):
        out = PySnmpCodeGen().gen_index({})
        self.assertFalse(out.startswith("#"))


class NullIndexTestCase(unittest.TestCase):
    def testNullCodeGenRendersAnEmptyIndex(self):
        self.assertEqual(NullCodeGen().gen_index({"A-MIB": status(oid="1.3.6")}), "")


NOTIFICATION_MIB = """
NOTIFY-MIB DEFINITIONS ::= BEGIN

IMPORTS
    OBJECT-TYPE, NOTIFICATION-TYPE, MODULE-IDENTITY, Integer32
        FROM SNMPv2-SMI;

notifyModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "A module that defines notifications."
    ::= { 1 3 6 1 4 1 99 }

notifyObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object carried by the notification."
    ::= { 1 3 6 1 4 1 99 1 }

notifyEvent NOTIFICATION-TYPE
    OBJECTS     { notifyObject }
    STATUS      current
    DESCRIPTION "A notification."
    ::= { 1 3 6 1 4 1 99 2 }
END
"""

TRAP_MIB = """
TRAP-MIB DEFINITIONS ::= BEGIN

IMPORTS
    TRAP-TYPE
        FROM RFC-1215

    OBJECT-TYPE
        FROM RFC1155-SMI;

trapEnterprise OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 98 }

trapObject OBJECT-TYPE
    SYNTAX      INTEGER
    ACCESS      read-only
    STATUS      mandatory
    DESCRIPTION "An object carried by the trap."
    ::= { 1 3 6 1 4 1 98 1 }

trapEvent TRAP-TYPE
    ENTERPRISE  trapEnterprise
    VARIABLES   { trapObject }
    DESCRIPTION "A trap."
    ::= 3
END
"""


class NotificationsReachTheIndexTestCase(unittest.TestCase):
    """A notification is recorded as one, not just swept into ``oids``.

    ``gen_index`` reads what the backend reported for each module, so the
    section is only useful if ``gen_code`` fills it in. See pysnmp/pysmi#64.
    """

    def info(self, mib):
        ast, _, table = symbol_table(mib)
        mibInfo, _ = JsonCodeGen().gen_code(ast, table, genTexts=True)
        return mibInfo

    def testNotificationTypeIsRecorded(self):
        self.assertEqual(self.info(NOTIFICATION_MIB).notification, ["1.3.6.1.4.1.99.2"])

    def testAConvertedTrapTypeIsRecorded(self):
        """RFC 3584 turns a TRAP-TYPE into a NOTIFICATION-TYPE, so it counts."""
        self.assertEqual(self.info(TRAP_MIB).notification, ["1.3.6.1.4.1.98.0.3"])

    def testPlainObjectsAreNotRecordedAsNotifications(self):
        self.assertNotIn("1.3.6.1.4.1.99.1", self.info(NOTIFICATION_MIB).notification)

    def testTheNotificationAlsoStaysInOids(self):
        """The section adds a way to look a trap up; it takes nothing away."""
        self.assertIn("1.3.6.1.4.1.99.2", self.info(NOTIFICATION_MIB).oids)

    def testTheIndexPlacesTheNotificationUnderItsSection(self):
        info = self.info(NOTIFICATION_MIB)
        out = json.loads(
            JsonCodeGen().gen_index({"NOTIFY-MIB": status(notification=info.notification, oids=info.oids)})
        )
        self.assertEqual(out["notification"], {"1.3.6.1.4.1.99.2": ["NOTIFY-MIB"]})


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
