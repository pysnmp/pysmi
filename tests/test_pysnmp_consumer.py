#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""A generated module loads under pysnmp and its public API accepts it.

This is the only file that reads a pysmi artifact back off a pysnmp object, and
it is deliberately thin. It answers one question -- does the module we emit
still load and work in the consumer it is emitted for -- and it answers no
question about correctness. Whether the emitted output matches the SMI
specifications is settled in the ``test_spec_*`` files, against RFC 2578, RFC
2579, RFC 2580 and RFC 3584, by reading the output itself.

Nothing here may become the oracle for a clause. If a pysnmp release changes an
accessor, this file goes red and pysmi is not at fault, which is why it is
marked ``pysnmp_consumer`` and does not gate CI. See pysnmp/pysmi#127.
"""

import pathlib
import shutil
import sys
import unittest

import pytest

from hatch_build import build as build_precompiled
from pysmi.codegen import PySnmpCodeGen
from tests.harness import render_pysnmp
from tests.test_spec_index import MULTI_MIB
from tests.test_spec_objecttype import ACCESS_MIB
from tests.test_standard_corpus import LOAD_ORDER, compiled, documents

pytestmark = pytest.mark.pysnmp_consumer

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-IDENTITY, NOTIFICATION-TYPE, OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    OBJECT-GROUP, NOTIFICATION-GROUP, MODULE-COMPLIANCE, AGENT-CAPABILITIES
        FROM SNMPv2-CONF
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

testModule MODULE-IDENTITY
    LAST-UPDATED "200001100000Z"
    ORGANIZATION "AgentX Working Group"
    CONTACT-INFO "WG-email: agentx@example.com"
    DESCRIPTION  "Module."
    REVISION     "200001100000Z"
    DESCRIPTION  "Initial version."
    ::= { 1 3 }

TestConvention ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "1x:"
    STATUS       current
    DESCRIPTION  "A convention."
    SYNTAX       OCTET STRING

testIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "Identity."
    REFERENCE   "ABC"
    ::= { testModule 1 }

testScalar OBJECT-TYPE
    SYNTAX      Integer32 (0..7)
    UNITS       "seconds"
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Scalar."
    DEFVAL      { 3 }
    ::= { testModule 2 }

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Table."
    ::= { testModule 3 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Row."
    INDEX       { testIndex, IMPLIED testName }
    ::= { testTable 1 }

TestEntry ::= SEQUENCE { testIndex Integer32, testName OCTET STRING }

testIndex OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "Index column."
    ::= { testEntry 1 }

testName OBJECT-TYPE
    SYNTAX      OCTET STRING
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "Name column."
    ::= { testEntry 2 }

testNotification NOTIFICATION-TYPE
    OBJECTS     { testScalar }
    STATUS      current
    DESCRIPTION "Notification."
    ::= { testModule 4 }

testObjectGroup OBJECT-GROUP
    OBJECTS     { testScalar }
    STATUS      current
    DESCRIPTION "Object group."
    ::= { testModule 5 }

testNotificationGroup NOTIFICATION-GROUP
    NOTIFICATIONS { testNotification }
    STATUS        current
    DESCRIPTION   "Notification group."
    ::= { testModule 6 }

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "Compliance."
    MODULE
        MANDATORY-GROUPS { testObjectGroup }
    ::= { testModule 7 }

testCapability AGENT-CAPABILITIES
    PRODUCT-RELEASE "Release."
    STATUS          current
    DESCRIPTION     "Capabilities."
    SUPPORTS        TEST-MIB
    INCLUDES        { testObjectGroup }
    ::= { testModule 8 }

END
"""

#: Every construct the pysnmp backend emits, and the class pysnmp builds for it.
CONSTRUCTS = (
    ("testModule", "ModuleIdentity"),
    ("testIdentity", "ObjectIdentity"),
    ("testScalar", "MibScalar"),
    ("testTable", "MibTable"),
    ("testEntry", "MibTableRow"),
    ("testIndex", "MibTableColumn"),
    ("testNotification", "NotificationType"),
    ("testObjectGroup", "ObjectGroup"),
    ("testNotificationGroup", "NotificationGroup"),
    ("testCompliance", "ModuleCompliance"),
    ("testCapability", "AgentCapabilities"),
)


class LoadTestCase(unittest.TestCase):
    """The generated module executes against a MibBuilder."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = render_pysnmp(MIB)

    def testEveryConstructBuildsItsObject(self):
        for symbol, klass in CONSTRUCTS:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, self.ctx)
                self.assertEqual(self.ctx[symbol].__class__.__name__, klass)

    def testATextualConventionBuildsItsClass(self):
        self.assertEqual(self.ctx["TestConvention"]().getDisplayHint(), "1x:")

    def testTheModuleAlsoLoadsWithoutTexts(self):
        # The narrative setters are emitted behind a guard, so a module built
        # without them has to remain loadable.
        ctx = render_pysnmp(MIB, genTexts=False)
        for symbol, _ in CONSTRUCTS:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, ctx)


class PublicApiTestCase(unittest.TestCase):
    """pysnmp's accessors return what the module was built with."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = render_pysnmp(MIB)

    def testAnObjectKnowsItsName(self):
        self.assertEqual(self.ctx["testScalar"].getName(), (1, 3, 2))

    def testAScalarCarriesItsSyntaxAndDefault(self):
        self.assertEqual(self.ctx["testScalar"].getSyntax(), 3)
        self.assertEqual(self.ctx["testScalar"].getUnits(), "seconds")

    def testARowKnowsItsIndexColumns(self):
        self.assertEqual(
            self.ctx["testEntry"].getIndexNames(),
            ((0, "TEST-MIB", "testIndex"), (1, "TEST-MIB", "testName")),
        )

    def testTheRowEncodesAnInstanceIdentifier(self):
        # The encoding itself belongs to pysnmp; that it agrees with the
        # section 7.7 model in test_spec_index is what this checks.
        self.assertEqual(
            self.ctx["testEntry"].getInstIdFromIndices(7, b"ab"), (7, 97, 98)
        )

    def testANotificationKnowsItsObjects(self):
        self.assertEqual(
            self.ctx["testNotification"].getObjects(), (("TEST-MIB", "testScalar"),)
        )

    def testTheModuleIdentityCarriesItsRevisions(self):
        self.assertEqual(self.ctx["testModule"].getRevisions(), ("2000-01-10 00:00",))


class MaxAccessTestCase(unittest.TestCase):
    """The access a module declares survives being loaded.

    This reads back an accessor whose value pysmi wrote, so it only says pysnmp
    kept what it was handed. What the emitted call has to be is settled against
    RFC 2578 section 7.3 in test_spec_objecttype. It is worth reading back all
    the same: pysnmp defaults MibScalar and MibTableColumn to "readonly" and
    MibTable and MibTableRow to "not-accessible", and none of those is spelled
    "notaccessible", so dropping the call again shows up here too rather than
    reading back as its own default. See pysnmp/pysmi#128.
    """

    @classmethod
    def setUpClass(cls):
        cls.scalars = render_pysnmp(ACCESS_MIB)
        cls.table = render_pysnmp(MULTI_MIB % "")

    def testAScalarKeepsEveryValueOfSection73(self):
        for symbol, access in (
            ("testNotAccessible", "notaccessible"),
            ("testForNotify", "accessiblefornotify"),
            ("testReadOnly", "readonly"),
            ("testReadWrite", "readwrite"),
            ("testReadCreate", "readcreate"),
        ):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.scalars[symbol].getMaxAccess(), access)

    def testEveryClassBehindATableKeepsNotAccessible(self):
        for symbol in ("testTable", "testEntry", "testInt", "testStr"):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.table[symbol].getMaxAccess(), "notaccessible")


class CorpusLoadTestCase(unittest.TestCase):
    """The real-MIB corpus loads into one builder.

    A missing guard, or a call pysnmp does not implement, leaves source that
    compiles and then fails at load. Only running it finds that. The corpus
    fixtures live in tests/test_standard_corpus.py, which asserts on the
    documents and the sources themselves.
    """

    def testEveryGeneratedModuleLoadsIntoOneBuilder(self):
        from pysnmp.smi.builder import MibBuilder

        _, written = compiled(PySnmpCodeGen)

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True
        ctx = {"mibBuilder": mibBuilder}

        for name in LOAD_ORDER:
            with self.subTest(module=name):
                exec(compile(written[name], name, "exec"), ctx, ctx)

    def testTheLoadedSymbolsCarryTheOidsTheJsonDocumentReports(self):
        from pysnmp.smi.builder import MibBuilder

        _, written = compiled(PySnmpCodeGen)
        docs = documents()

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True
        ctx = {"mibBuilder": mibBuilder}
        for name in LOAD_ORDER:
            exec(compile(written[name], name, "exec"), ctx, ctx)

        compared = 0
        for name in LOAD_ORDER:
            for symbol, node in docs[name].items():
                if not isinstance(node, dict) or "oid" not in node:
                    continue
                built = ctx.get(symbol)
                if built is None or not hasattr(built, "getName"):
                    continue
                with self.subTest(module=name, symbol=symbol):
                    self.assertEqual(
                        ".".join(str(x) for x in built.getName()), node["oid"]
                    )
                compared += 1

        self.assertGreater(compared, 200)


class PrecompiledBundleTestCase(unittest.TestCase):
    """The modules a wheel carries in ``pysmi/mibs/pysnmp`` load as they are.

    That is the whole point of generating them: a consumer adds the package as
    a MIB source and loads a standard module without running the compiler.
    A wheel is not built here, so the hook's generator is called directly and
    its output read as a directory rather than as ``pysmi.mibs.pysnmp``.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = build_precompiled(pathlib.Path(__file__).parent.parent)

        from pysnmp.smi import builder

        cls.mibBuilder = builder.MibBuilder()
        cls.mibBuilder.addMibSources(builder.DirMibSource(str(cls.out)))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def testAStandardModuleLoadsWithoutBeingCompiledFirst(self):
        self.mibBuilder.loadModules("IF-MIB")

        (ifDescr,) = self.mibBuilder.importSymbols("IF-MIB", "ifDescr")

        self.assertEqual((1, 3, 6, 1, 2, 1, 2, 2, 1, 2), tuple(ifDescr.name))

    def testAModuleLoadsTheDependenciesItImports(self):
        self.mibBuilder.loadModules("ENTITY-MIB")

        (entPhysicalDescr,) = self.mibBuilder.importSymbols(
            "ENTITY-MIB", "entPhysicalDescr"
        )

        self.assertEqual(
            (1, 3, 6, 1, 2, 1, 47, 1, 1, 1, 1, 2), tuple(entPhysicalDescr.name)
        )


class PrecompiledBundleLoadsTestCase(unittest.TestCase):
    """Every module the wheel carries loads, with ours registered first.

    ``PrecompiledBundleTestCase`` loads two modules through ``addMibSources``,
    which *appends*: pysnmp's own copies are searched first, so a broken module
    of ours is shadowed rather than exercised. Both limits matter. Registering
    the package ahead of pysnmp's is the configuration pysnmp/pysnmp#198 needs,
    and it is what surfaced pysnmp/pysmi#196 in the first place -- with the
    package first, 19 of 19 modules failed, because everything depends
    transitively on ``SNMPv2-CONF``.

    pysnmp's own copies stay registered behind ours, as the fallback for the
    three modules we deliberately do not emit.

    ``loadModules`` is not on its own a loadability check: it catches
    ``MibNotFoundError`` and, with no compiler attached, swallows it, so a
    module that was never found reports success. Exported symbols are checked
    too.
    """

    #: Empty by construction. An SMIv1 dialect shim with no definitions of its
    #: own (pysnmp/pysmi#186), so exporting nothing is correct for it.
    EMPTY_BY_DESIGN = frozenset(("SNMPv2-CONF-v1",))

    #: Modules that do not load, with the reason. Neither cause is this
    #: generator's, and neither is fixable here, so they are recorded rather
    #: than hidden -- a fix flips a test.
    #:
    #: ``RFC-1212`` and ``RFC-1215`` raise ``No symbol SNMPv2-SMI::ObjectName``.
    #: ``SNMPv2-SMI``'s ASN.1 defines ``ObjectName``, but the copy pysnmp ships
    #: does not export it, and ``SNMPv2-SMI`` is one of the three we cannot
    #: generate, so nothing else can supply it. Blocked on pysnmp/pysnmp#198 --
    #: the same shape as the ``RFC1158-MIB::DisplayString`` gap recorded in
    #: pysnmp/mibs#370.
    #:
    #: ``DSA-MIB`` and ``RDBMS-MIB`` import ``applIndex`` and
    #: ``DistinguishedName`` from ``APPLICATION-MIB``. They mean RFC 2248's
    #: module of that name, which RFC 2788 renamed to ``NETWORK-SERVICES-MIB``
    #: -- where those symbols are, in the bundle. The ``APPLICATION-MIB`` the
    #: bundle carries is RFC 2287's unrelated module that reused the name. A
    #: corpus problem, tracked in pysnmp/pysmi#199.
    KNOWN_FAILURES = {
        "RFC-1212": "SNMPv2-SMI::ObjectName",
        "RFC-1215": "SNMPv2-SMI::ObjectName",
        "DSA-MIB": "APPLICATION-MIB::DistinguishedName",
        "RDBMS-MIB": "APPLICATION-MIB::applGroup",
    }

    @classmethod
    def setUpClass(cls):
        from pysnmp.smi import builder

        cls.out = build_precompiled(pathlib.Path(__file__).parent.parent)
        cls.modules = sorted(
            path.stem for path in cls.out.glob("*.py") if not path.name.startswith("__")
        )

        cls.mibBuilder = builder.MibBuilder()
        cls.mibBuilder.setMibSources(
            builder.DirMibSource(str(cls.out)), *cls.mibBuilder.getMibSources()
        )

        cls.errors = {}
        for name in cls.modules:
            try:
                cls.mibBuilder.loadModules(name)
            except Exception as exc:  # noqa: BLE001 -- the failure is the finding
                cls.errors[name] = str(exc)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def testTheBundleIsNotEmpty(self):
        """A build that emitted nothing would pass every other check here."""
        self.assertGreater(len(self.modules), 250)

    def testEveryModuleLoadsExceptTheKnownFailures(self):
        self.assertEqual(sorted(self.KNOWN_FAILURES), sorted(self.errors))

    def testTheKnownFailuresStillFailForTheSameReason(self):
        """A changed reason means the diagnosis above is stale.

        And a module that starts loading fails here too, which is the point:
        pysnmp/pysnmp#198 and pysnmp/pysmi#199 each flip one of these.
        """
        for name, marker in sorted(self.KNOWN_FAILURES.items()):
            with self.subTest(module=name):
                self.assertIn(marker, self.errors[name])

    def testEveryLoadedModuleExportedSymbols(self):
        """Because loadModules reports success for a module it never found."""
        silent = sorted(
            name
            for name in self.modules
            if name not in self.errors
            and name not in self.EMPTY_BY_DESIGN
            and not self.mibBuilder.mibSymbols.get(name)
        )

        self.assertEqual([], silent)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
