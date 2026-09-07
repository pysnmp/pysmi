#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Documents pysmi emits must validate against the schema pysmi publishes.

The JSON schema in ``pysmi/codegen/schemas/`` is a contract other repositories
build against -- the corpus builder and the pysnmp reader both consume this
model. A published contract that has drifted from the emitter is worse than
none, because it is trusted.

So the schema is not checked by hand against the prose. It is checked against
output, over a sample wide enough to reach every construct it describes: tables
with INDEX and with AUGMENTS, IMPLIED indices, BITS, every constraint kind,
every DEFVAL format, TEXTUAL-CONVENTIONs with and without DISPLAY-HINT,
MODULE-COMPLIANCE refinements, and SMIv1 modules alongside SMIv2. Two of those
assertions are about the sample rather than the schema: a branch no document
reaches is a branch nothing tests.

See pysnmp/pysmi#179.
"""

import json
import sys
import unittest

from pysmi.codegen import JsonCodeGen
from pysmi.codegen.schemas import schema
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter

try:
    import jsonschema

except ImportError:
    jsonschema = None

#: Chosen for construct coverage rather than importance. Each earns its place:
#:
#: ``HOST-RESOURCES-MIB``       AUGMENTS, DEFVAL, compliance refinements
#: ``IF-MIB``                   multi-column INDEX, TCs with DISPLAY-HINT
#: ``ENTITY-MIB``               cross-module INDEX references
#: ``SNMPv2-MIB``               notifications, object and notification groups
#: ``SNMPv2-TC``                TEXTUAL-CONVENTIONs, no OBJECT-TYPEs
#: ``SNMPv2-SMI``               base type declarations, class "type" symbols
#: ``RFC1213-MIB``              SMIv1, no MODULE-IDENTITY
#: ``RFC1155-SMI``              SMIv1 base module
#: ``T11-FC-ZONE-SERVER-MIB``   BITS syntax and BITS DEFVAL
#: ``DISMAN-EVENT-MIB``         IMPLIED index, size and range constraints
#: ``MPLS-TE-STD-MIB``          BITS, dense enumerations
#: ``IANAifType-MIB``           a very large enumeration
MODULES = (
    "HOST-RESOURCES-MIB",
    "IF-MIB",
    "ENTITY-MIB",
    "SNMPv2-MIB",
    "SNMPv2-TC",
    "SNMPv2-SMI",
    "RFC1213-MIB",
    "RFC1155-SMI",
    "T11-FC-ZONE-SERVER-MIB",
    "DISMAN-EVENT-MIB",
    "MPLS-TE-STD-MIB",
    "IANAifType-MIB",
)


def compile_modules(genTexts):
    """Compile :py:data:`MODULES` from the bundled ASN.1 into decoded documents."""
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
    compiler.compile(*MODULES, noDeps=False, genTexts=genTexts, rebuild=True)

    return documents


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class DocumentValidationTestCase(unittest.TestCase):
    """Every emitted document satisfies the published document schema."""

    @classmethod
    def setUpClass(cls):
        cls.withTexts = compile_modules(genTexts=True)
        cls.withoutTexts = compile_modules(genTexts=False)
        cls.validator = jsonschema.Draft202012Validator(schema("document"))

    def assertValidates(self, documents):
        """Every document in *documents* validates, named on failure."""
        for name, document in sorted(documents.items()):
            with self.subTest(module=name):
                errors = sorted(self.validator.iter_errors(document), key=str)
                self.assertEqual(
                    errors,
                    [],
                    f"{name}: {errors[0].json_path} -- {errors[0].message}"
                    if errors
                    else "",
                )

    def testDocumentsWithTextsValidate(self):
        self.assertValidates(self.withTexts)

    def testDocumentsWithoutTextsValidate(self):
        """The same schema covers both text modes.

        Text-bearing fields are optional in the schema precisely so that one
        schema covers both; this is what proves the optionality is real rather
        than assumed.
        """
        self.assertValidates(self.withoutTexts)

    def testTheSampleReachesEverySymbolClass(self):
        """A schema branch no document reaches is a branch nothing tests."""
        reached = {
            symbol["class"]
            for document in self.withTexts.values()
            for key, symbol in document.items()
            if key != "meta" and isinstance(symbol, dict)
        }
        declared = set(
            schema("document")["$defs"]["symbol"]["properties"]["class"]["enum"]
        )

        self.assertEqual(declared - reached, set())

    def testTheSampleReachesTheAwkwardConstructs(self):
        """The sample covers more than the common shapes."""
        reached = set()

        for document in self.withTexts.values():
            for key, symbol in document.items():
                if key == "meta" or not isinstance(symbol, dict):
                    continue

                if "indices" in symbol:
                    reached.add("indices")
                    if any(entry["implied"] for entry in symbol["indices"]):
                        reached.add("implied")
                if "augmentation" in symbol:
                    reached.add("augmentation")
                if "default" in symbol:
                    reached.add(f"defval:{symbol['default']['format']}")
                if "units" in symbol:
                    reached.add("units")
                if "displayhint" in symbol:
                    reached.add("displayhint")
                if "refinements" in symbol:
                    reached.add("refinements")

                spec = symbol.get("syntax") or symbol.get("type")
                if isinstance(spec, dict):
                    if "bits" in spec:
                        reached.add("bits")
                    for kind in spec.get("constraints", {}):
                        reached.add(f"constraint:{kind}")

        required = {
            "indices",
            "implied",
            "augmentation",
            "units",
            "displayhint",
            "refinements",
            "bits",
            "constraint:range",
            "constraint:size",
            "constraint:enumeration",
            "defval:decimal",
            "defval:enum",
        }

        self.assertEqual(required - reached, set())


@unittest.skipIf(jsonschema is None, "jsonschema is not installed")
class IndexValidationTestCase(unittest.TestCase):
    """The OID index satisfies the published index schema."""

    def testTheIndexValidates(self):
        codegen = JsonCodeGen()
        compiler = MibCompiler(
            SmiV1CompatParser(),
            codegen,
            CallbackWriter(lambda mibname, data, cbCtx: None),
            useBundledMibs=False,
        )
        compiler.add_sources(PackageReader("pysmi.mibs.asn1"))
        processed = compiler.compile(*MODULES, noDeps=False, rebuild=True)

        index = json.loads(codegen.gen_index(processed))
        validator = jsonschema.Draft202012Validator(schema("index"))
        errors = sorted(validator.iter_errors(index), key=str)

        self.assertEqual(
            errors,
            [],
            f"{errors[0].json_path} -- {errors[0].message}" if errors else "",
        )


class SchemaAccessTestCase(unittest.TestCase):
    """The schemas are reachable as package data, and say what they cover."""

    def testBothSchemasShip(self):
        self.assertTrue(schema("document")["$id"].endswith("jsondoc-v1.schema.json"))
        self.assertTrue(schema("index")["$id"].endswith("jsonindex-v1.schema.json"))

    def testEveryEmittableVersionHasASchema(self):
        """A version the generator can emit is a version a consumer can check."""
        for version in JsonCodeGen.SCHEMA_VERSIONS:
            with self.subTest(version=version):
                for kind in ("document", "index"):
                    declared = schema(kind, version)["$defs"]["meta"]["properties"][
                        "schema"
                    ]["const"]
                    self.assertEqual(declared, version)

    def testAnUnknownKindIsRefused(self):
        with self.assertRaisesRegex(ValueError, "unknown schema kind"):
            schema("mibdump")

    def testAnUnknownVersionIsRefused(self):
        with self.assertRaisesRegex(ValueError, "no document schema ships"):
            schema("document", 99)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
