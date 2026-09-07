#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Suppressing texts removes prose and nothing else.

``--generate-mib-texts`` is meant to be presentational: the same model, minus
human-readable text. It was not. A document generated without texts differed
structurally from one generated with them, in three ways:

* ``lastupdated`` was suppressed with the prose, though it is a timestamp and
  is what date-based source precedence compares (pysnmp/pysmi#191)
* ``revisions[].description`` was emitted regardless, alone among every
  description in the document (pysnmp/pysmi#192)
* a MODULE-COMPLIANCE GROUP clause was dropped entirely rather than emitted
  without its description, so the compliance statement referenced fewer groups
  than the MIB declares (pysnmp/pysmi#190)

The first and third are structure, not prose. Together they meant a no-texts
document was lossy, and that the structural content hash could not be equal
across the two modes -- which is what pysnmp/pysmi#180 needs it to be.

The test that matters most is the last one here: strip the prose fields from a
with-texts document and it must equal a without-texts document exactly.
"""

import json
import sys
import unittest

from pysmi.codegen import JsonCodeGen
from pysmi.codegen.normalized import TEXT_FIELDS, structure_hash
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter
from tests.harness import render_json

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    MODULE-COMPLIANCE, OBJECT-GROUP
        FROM SNMPv2-CONF;

testMib MODULE-IDENTITY
    LAST-UPDATED "200001010000Z"
    ORGANIZATION "Test Organization"
    CONTACT-INFO "test@example.com"
    DESCRIPTION  "The module."
    REVISION     "200001010000Z"
    DESCRIPTION  "The first revision."
    ::= { 1 3 1 }

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object."
    ::= { testMib 1 }

testGroup OBJECT-GROUP
    OBJECTS     { testObject }
    STATUS      current
    DESCRIPTION "A group."
    ::= { testMib 2 }

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "A compliance statement."
    MODULE
        MANDATORY-GROUPS { testGroup }
        GROUP       testGroup
        DESCRIPTION "This group is conditional."
        OBJECT      testObject
        MIN-ACCESS  read-only
        DESCRIPTION "Write access is not required."
    ::= { testMib 3 }

END
"""

#: Compiled from the bundle, so the assertions run against real MIBs and not
#: only the fixture above. Chosen for compliance refinements and revisions.
CORPUS = ("SNMPv2-MIB", "HOST-RESOURCES-MIB", "IF-MIB", "SNMP-VIEW-BASED-ACM-MIB")


def build(*modules, genTexts):
    """Compile *modules* from the bundled ASN.1 into decoded documents."""
    documents = {}

    compiler = MibCompiler(
        SmiV1CompatParser(),
        JsonCodeGen(),
        CallbackWriter(
            lambda mibname, data, cbCtx: documents.__setitem__(
                mibname, json.loads(data)
            )
        ),
        useBundledMibs=False,
    )
    compiler.add_sources(PackageReader("pysmi.mibs.asn1"))
    compiler.compile(*modules, noDeps=False, genTexts=genTexts, rebuild=True)

    return documents


def strip_texts(value):
    """Remove every prose field, at any depth."""
    if isinstance(value, dict):
        return {
            key: strip_texts(item)
            for key, item in value.items()
            if key not in TEXT_FIELDS
        }
    if isinstance(value, list):
        return [strip_texts(item) for item in value]
    return value


class LastUpdatedTestCase(unittest.TestCase):
    """LAST-UPDATED is a timestamp, so it survives text suppression."""

    def testLastUpdatedIsEmittedWithoutTexts(self):
        identity = render_json(MIB, genTexts=False)["testMib"]

        self.assertEqual("2000-01-01 00:00", identity["lastupdated"])

    def testLastUpdatedIsUnchangedWithTexts(self):
        identity = render_json(MIB, genTexts=True)["testMib"]

        self.assertEqual("2000-01-01 00:00", identity["lastupdated"])

    def testOrganizationAndContactInfoStayGated(self):
        """Those two are prose, and stay suppressed.

        Provenance a corpus might want, but prose all the same. Recorded here
        so the decision is explicit rather than incidental.
        """
        identity = render_json(MIB, genTexts=False)["testMib"]

        self.assertNotIn("organization", identity)
        self.assertNotIn("contactinfo", identity)

        withTexts = render_json(MIB, genTexts=True)["testMib"]

        self.assertEqual("Test Organization", withTexts["organization"])
        self.assertEqual("test@example.com", withTexts["contactinfo"])


class RevisionDescriptionTestCase(unittest.TestCase):
    """Revision descriptions are descriptions, and are gated like the rest."""

    def testRevisionTimestampsSurvive(self):
        revisions = render_json(MIB, genTexts=False)["testMib"]["revisions"]

        self.assertEqual([{"revision": "2000-01-01 00:00"}], revisions)

    def testRevisionDescriptionsAreCarriedWithTexts(self):
        revisions = render_json(MIB, genTexts=True)["testMib"]["revisions"]

        self.assertEqual(
            [
                {
                    "revision": "2000-01-01 00:00",
                    "description": "The first revision.",
                }
            ],
            revisions,
        )


class ComplianceRefinementTestCase(unittest.TestCase):
    """A GROUP clause is a reference, not only a description."""

    def testGroupRefinementSurvivesWithoutItsDescription(self):
        compliance = render_json(MIB, genTexts=False)["testCompliance"]
        groups = [r for r in compliance["refinements"] if r["kind"] == "group"]

        self.assertEqual(
            [{"module": "TEST-MIB", "object": "testGroup", "kind": "group"}], groups
        )

    def testObjectRefinementKeepsItsMinAccessWithoutTexts(self):
        compliance = render_json(MIB, genTexts=False)["testCompliance"]
        objects = [r for r in compliance["refinements"] if r["kind"] == "object"]

        self.assertEqual(
            [
                {
                    "module": "TEST-MIB",
                    "object": "testObject",
                    "kind": "object",
                    "minaccess": "read-only",
                }
            ],
            objects,
        )

    def testRefinementCountsMatchAcrossTextModes(self):
        """Over real MIBs, not only the fixture.

        ``SNMPv2-MIB``'s ``snmpBasicCompliance`` used to lose
        ``snmpCommunityGroup`` entirely without texts.
        """
        withTexts = build(*CORPUS, genTexts=True)
        withoutTexts = build(*CORPUS, genTexts=False)

        for name in sorted(withTexts):
            for symbol, node in sorted(withTexts[name].items()):
                if not isinstance(node, dict) or "refinements" not in node:
                    continue
                with self.subTest(module=name, symbol=symbol):
                    self.assertEqual(
                        len(node["refinements"]),
                        len(withoutTexts[name][symbol].get("refinements", [])),
                    )


class NoTextsIsProseFreeTestCase(unittest.TestCase):
    """The property all three fixes exist to restore."""

    def testNoDescriptionSurvivesAnywhere(self):
        document = build("SNMPv2-MIB", genTexts=False)["SNMPv2-MIB"]
        serialized = json.dumps(document)

        for field in sorted(TEXT_FIELDS):
            with self.subTest(field=field):
                self.assertNotIn(f'"{field}":', serialized)

    def testStrippingProseFromATextedDocumentYieldsTheUntextedOne(self):
        """Suppressing texts differs from a texted document only by prose.

        This is the whole claim, asserted directly rather than through the
        hash: anything else that differs is structure a no-texts consumer is
        silently losing.
        """
        withTexts = build(*CORPUS, genTexts=True)
        withoutTexts = build(*CORPUS, genTexts=False)

        for name in sorted(withTexts):
            with self.subTest(module=name):
                expected = strip_texts(
                    {k: v for k, v in withTexts[name].items() if k != "meta"}
                )
                actual = {k: v for k, v in withoutTexts[name].items() if k != "meta"}

                self.assertEqual(expected, actual)

    def testStructuralHashAgreesAcrossTextModes(self):
        """pysnmp/pysmi#180's structural hash becomes mode-independent.

        It is *defined* as the model minus prose, so it must not depend on
        whether prose was generated. Until these three fixes it did, and
        ``tests/test_normalized_hash.py`` asserted the inequality deliberately.
        """
        withTexts = build(*CORPUS, genTexts=True)
        withoutTexts = build(*CORPUS, genTexts=False)

        for name in sorted(withTexts):
            with self.subTest(module=name):
                self.assertEqual(
                    structure_hash(withTexts[name]),
                    structure_hash(withoutTexts[name]),
                )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
