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
            ["compliance", "enterprise", "identity", "meta", "oids"],
        )

    def testIdentityMapsOidToModule(self):
        out = self.index({"A-MIB": status(identity="1.3.6.1.4.1.9")})
        self.assertEqual(out["identity"], {"1.3.6.1.4.1.9": ["A-MIB"]})

    def testEnterpriseMapsOidToModule(self):
        out = self.index({"A-MIB": status(enterprise="1.3.6.1.4.1.9")})
        self.assertEqual(out["enterprise"], {"1.3.6.1.4.1.9": ["A-MIB"]})

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
        self.assertEqual(list(out), ["compliance", "enterprise", "identity", "meta", "oids"])

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


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
