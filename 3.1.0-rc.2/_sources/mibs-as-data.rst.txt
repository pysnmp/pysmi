.. _mibs-as-data:

MIBs as data: layering review
=============================

.. note::

   Status: **proposal**, with one part since carried out. This page reviews the
   plan recorded in pysnmp/pysnmp#148 and its child issues and proposes a
   different placement for one element of it, the schema. It is recorded in
   pysmi because pysmi is the repository the proposal assigns the schema to.

   The schema placement this page argues for is still a proposal. What has been
   done is the loader contract: pysnmp publishes it and exposes
   ``MibBuilder.loaderContract``, and pysmi's back end targets it rather than
   inferring the loader's shape at runtime (pysnmp/pysnmp#197,
   pysnmp/pysmi#194). :ref:`the-base-mib-shape` says so where it comes up, in
   the past tense.

The effort under review replaces compiled-``.py`` MIB distribution with a
queryable corpus, so that OID-to-name translation no longer requires every
module to be preloaded. That objective is not in question, and neither is the
majority of the plan. One ownership decision is.

.. contents::
   :local:
   :depth: 1


The decision under review
-------------------------

pysnmp/pysnmp#147 places the corpus schema, the corpus writer, the corpus
reader and ``.py`` code generation in pysnmp. Its stated reason:

    Whoever owns the schema must own both sides of it.

and, in the same issue:

    ``pysmi/codegen/pysnmp.py`` means pysmi knows pysnmp's runtime shape,
    which is the actual inversion. pysmi should emit neutral IR; pysnmp
    should turn IR into pysnmp-shaped artifacts.

The second statement is accurate. The conclusion drawn from it does not follow.
The coupling identified in pysmi is that pysmi encodes pysnmp's loader
interface. Removing that coupling requires pysnmp to define its loader
interface. It does not require pysmi's data model to move to pysnmp, which is a
separate transfer in the opposite direction.


Three schemas, not one
----------------------

The term *schema* denotes three distinct artifacts in the current plan. The
ownership argument applies to one of them.

.. list-table::
   :header-rows: 1
   :widths: 14 44 20

   * - Layer
     - Definition
     - Derived from
   * - **SMI model**
     - The meaning of a MIB module: node classes, node types, syntax, subtype
       constraints, INDEX/AUGMENTS/IMPLIED, TEXTUAL-CONVENTIONs, DISPLAY-HINT,
       MAX-ACCESS, STATUS, UNITS, DEFVAL, revision history, per-symbol IMPORTS
       attribution.
     - RFC 2578-2580
   * - **Corpus serialization**
     - The layout of that model for lookup: table structure, sortable OID key,
       indexes, core/text split, manifest, publish state.
     - the model above, plus
       SQLite
   * - **Runtime object shape**
     - ``MibScalar`` / ``MibTableColumn`` / ``MibTableRow`` / ``MibTable``,
       class identity per ``(module, typename)``, ``prettyPrint`` / ``prettyIn``
       behaviour, the override table, ``loadTexts``.
     - pysnmp

The premise "whoever owns the schema must own both sides of it" holds for layer
3. Layer 1 is derived from the SMI standards and has consumers that do not
depend on pysnmp.

Layer 2 has two sides, and they are not the writer and SQLite. They are pysmi's
**writer** and pysnmp's **reader**, which must agree on application-level
semantics: the manifest, the schema version, the OID key encoding and the
publish state. Compatibility and validation belong to that boundary, and this
proposal assigns them there.

Co-location of the two sides in one repository is a separate question.
``sqlite3`` is in the standard library, so the reader requires the format
rather than the producer. The agreement is therefore expressible as a published
specification plus a conformance fixture executed by the reader's own CI.

Placing layer 1 in pysnmp requires any component that interprets a MIB row to
depend on an SNMP protocol engine. Current consumers in that category include
``mibdump --destination-format=json`` users and splunk-connect-for-snmp.


pysmi already defines layer 1
-----------------------------

The proposal does not assign pysmi a new responsibility. It names one that
already exists and is undocumented as a contract.

**The jsondoc schema is versioned and negotiable.** ``JsonCodeGen`` defines
``SCHEMA_VERSIONS`` and ``SCHEMA_VERSION``, accepts ``schemaVersion=`` on
``gen_code()`` and ``gen_index()``, raises ``PySmiCodegenError`` for an
unsupported version, and records the emitted version in ``meta.schema`` of every
document and index. ``tests/test_jsondoc_schema_version.py`` covers this
behaviour. The class docstring states the intent:

    A consumer that has to keep working across pysmi releases asks for the one
    it understands and is told, rather than left to infer the shape from the
    document.

This is a versioned contract with a compatibility gate, which is what
pysnmp/pysnmp#141 proposes to create.

**The model is complete.** ``IF-MIB``, ``ENTITY-MIB``, ``SNMPv2-MIB`` and
``DISMAN-EVENT-MIB`` compiled with both back ends at pysmi 2.3.0 produce equal
node counts -- 94, 73, 70 and 122 respectively, matching each module's
``exportSymbols`` call. Across that sample the JSON carries every field
enumerated in pysnmp/pysnmp#142:

* ``class`` -- ``objecttype``, ``objectidentity``, ``moduleidentity``,
  ``notificationtype``, ``textualconvention``, ``type``, ``objectgroup``,
  ``notificationgroup``, ``modulecompliance``, ``imports``
* ``nodetype`` -- ``scalar``, ``column``, ``row``, ``table``
* ``syntax`` with ``constraints`` (``range``, ``size``, ``enumeration``) and
  ``bits``
* ``displayhint``, ``units``, ``default`` (DEFVAL), ``maxaccess``, ``status``,
  ``reference``, ``refinements``
* ``indices`` as ``{module, object, implied}``, and ``augmentation``
* ``objects`` as ``{module, object}`` for NOTIFICATION-TYPE
* ``revisions``, ``lastupdated``, ``organization``, ``contactinfo``
* ``imports`` as a module-to-symbol-list mapping, attributing each imported
  symbol to its source module

``class`` and ``nodetype`` are independent axes and both are required. The
pysnmp/pysnmp#141 measurement comment reaches the same conclusion
independently.

**Provenance is emitted.** ``meta.comments`` carries a ``sha256`` digest of the
ASN.1 source and the producing pysmi version. pysnmp/pysnmp#147 proposes to
introduce both in the builder.

**The reverse index exists.** ``JsonCodeGen.gen_index()`` produces the
OID-to-module index that pysnmp/pysnmp#148 describes as absent, with
deterministic ordering, prefix compression, mergeable output and a
``meta.schema`` stamp. pysnmp/pysnmp#149 proposes to reimplement it in pysnmp
because ``index.py`` in the *mibs* repository is nondeterministic; ``index.py``
is a separate implementation, not this one.

**pysmi distributes the standard corpus.** As of 3.0.0 pysmi bundles 210 RFC,
IANA, IEEE and Internet-Draft modules in ``pysmi/mibs/asn1/`` -- the ones the
corpus at pysnmp/mibs actually needs -- and holds a further 275 of the same
provenance in ``pysmi/mibs/future/``, which is not installed and not
freshness-checked; see :ref:`bundled-mib-future`. ``bundled_mibs.json`` records
each module's publisher and, for superseded modules, which module took over
each subtree. ``pysmi.mibs.successor_for()`` answers which module currently
defines a given OID, which is a runtime question. Two premises in earlier issues
are superseded by this: pysnmp/pysmi#161's statement that bundling would make
pysmi a MIB distributor rather than a base-layer provider, and the assumption in
pysnmp/mibs#322 that ``src/standard`` is the only location of the standard tree.

Two elements of layer 1 are not yet defined and are required:

* a **canonical normalized form and content hash**. The existing digest covers
  raw ASN.1 bytes, so whitespace and comment changes register as content
  changes. A hash over normalized rows is required, as the plan states.
* the **corpus serialization** (layer 2). No DDL exists in any repository.


What the current plan gets right
--------------------------------

The following are retained without modification and are not re-argued below.

* **pyasn1 has no role.** It contains no SMI, MIB or OID knowledge.
* **The generated ``.py`` contains no MIB semantics absent from the JSON.**
  What it adds is runtime shape: ``PYSNMP_MODULE_ID``,
  ``mibBuilder.importSymbols`` and ``exportSymbols`` calls,
  ``if mibBuilder.loadTexts:`` guards, and the binding of each SMI type name to
  a pysnmp implementation class. It also carried
  ``getattr(mibBuilder, 'version', ...)`` compatibility branches until the
  loader contract replaced them; see below. jsondoc retains the type name as declared,
  ``{"type": "INTEGER", "class": "type"}``; the pysnmp back end resolves it to
  the implementing class. ``tests/test_codegen_fake_index.py`` asserts this as
  the difference between the two back ends. That binding is layer-3 knowledge
  and is a case for the loader contract to state explicitly. The conclusion
  drawn from this observation in pysnmp/pysmi#132 does not hold; see
  :ref:`the-base-mib-shape`.
* **The runtime design.** ``MibStore`` / ``CompositeStore``, longest-prefix OID
  resolution across all stores with precedence as tie-break only,
  one-module-one-store, the class cache keyed ``(module, typename)``, the
  override table consulted before synthesis, per-module provenance, and engine
  MIBs excluded from scope. This is the content of pysnmp/pysnmp#144,
  pysnmp/pysnmp#145 and pysnmp/pysnmp#146 and none of it changes.
* **SQLite rather than DuckDB**, on the measured reasoning recorded in
  pysnmp/pysnmp#146.
* **The determinism defects** identified in pysnmp/pysnmp#149: the
  shared-directory race, the bootstrap from published output, ``--ignore-errors``
  applied to one pass only, and ``listdir``-ordered index collisions.
* **Opt-in behaviour throughout**, with byte-identical default resolution.
* **pysnmp/pysnmp#140** is independent of the corpus work and can ship
  separately.


Where it goes wrong
-------------------

**1. It defines a second SMI model.** With the schema in pysnmp there are two
descriptions of a MIB module's meaning, jsondoc v1 and corpus v1, and a
normalization step between them owned by neither repository. pysnmp/pysnmp#142
exists to determine whether the two agree. A single model makes the question
definitional and the spike unnecessary.

**2. It increases the dependency it aims to remove.** pysnmp/pysnmp#148's
ownership table states that pysnmp requires neither pysmi nor mibs at runtime.
``pysnmp-pysmi`` is currently a required runtime dependency of pysnmp, declared
in ``[tool.poetry.dependencies]`` rather than as an extra. A builder in pysnmp
that parses raw ``.mib`` (pysnmp/pysnmp#149) adds a build-time dependency on
pysmi's parser. Retaining the builder in pysmi permits the runtime dependency to
be removed, since the reader requires only the format.

**3. It couples corpus rebuilds to a protocol library's release cadence.**
pysnmp/mibs#323 states that conflating schema version with corpus version forces
a pysnmp release on every corpus rebuild. pysnmp/pysnmp#147 ships the builder as
a ``pysnmp[compile]`` console script, which produces the same coupling through
packaging. The corpus rebuilds on a weekly cadence.

**4. The dependency graph is blocked on a spike that cannot close.**
pysnmp/pysnmp#141 blocks seven issues across two repositories. Its prerequisite
section states that the schema should not freeze until a post-deduplication node
count exists, and that count is produced by a corpus build that is itself being
redesigned.

**5. It reimplements existing functionality.** The OID index (``gen_index``),
the schema version negotiation (``SCHEMA_VERSIONS``), the provenance stamp
(``meta.comments``) and module supersession (``bundled_mibs.json``) exist in
pysmi and appear as new work in the pysnmp issues.

**6. Two independent changes are treated as one.** Removing the pysnmp format
from ``mibdump`` narrows pysmi to neutral output. Moving the schema to pysnmp
widens pysnmp to own neutral output. These are opposite changes and the plan
couples them.

**7. Soft deprecation of the pysnmp back end is not achievable.**
pysnmp/pysmi#132 proposes that ``codegen/pysnmp.py`` fade by disuse. pysmi
executes that generator during its own wheel build, and it is the runtime
compilation path for splunk-connect-for-snmp.


.. _the-base-mib-shape:

The base-MIB shape has three copies
-----------------------------------

pysmi produces and distributes the pysnmp artifact shape. ``hatch_build.py``
runs ``PySnmpCodeGen`` over all 210 bundled ASN.1 modules during the wheel build
and force-includes the output as ``pysmi/mibs/pysnmp/``. Its docstring states
the rationale: a consumer that needs to load one of the 210 standard modules
rather than compile it should not have to run the compiler first. Generating
rather than committing the modules makes their correspondence to the ASN.1
verifiable by construction.

The pysnmp-shaped base layer therefore exists in three copies, from three
producers.

.. list-table::
   :header-rows: 1
   :widths: 26 12 30 20

   * - Copy
     - Modules
     - Producer
     - Consumer
   * - ``pysmi/mibs/pysnmp/``
     - 207
     - the current generator over the current ASN.1, during the wheel build
     - none
   * - ``pysnmp/smi/mibs/``
     - 26
     - pysmi 0.1.2 / 0.1.3, April 2017; not regenerated since
     - pysnmp's ``MibBuilder``
   * - sc4snmp runtime
     - on demand
     - pysmi in-process, from ASN.1 retrieved over HTTP per module
     - sc4snmp

``MibBuilder`` defaults to ``('pysnmp.smi.mibs.instances', 'pysnmp.smi.mibs')``
and contains no reference to ``pysmi.mibs``. The generated copy in the wheel
pysnmp depends on is therefore unused.

The copies have diverged. Compiling pysmi's bundled ASN.1 with the current
generator and comparing against the 2017 files:

.. list-table::
   :header-rows: 1
   :widths: 30 12 12 34

   * - Module
     - frozen
     - current
     - exported symbols
   * - ``SNMPv2-MIB``
     - 204 L
     - 158 L
     - 71 / 71, equal
   * - ``SNMP-COMMUNITY-MIB``
     - 91 L
     - 75 L
     - 27 / 27, equal
   * - ``SNMP-NOTIFICATION-MIB``
     - 98 L
     - 79 L
     - 30 / 30, equal
   * - ``SNMP-PROXY-MIB``
     - 68 L
     - 52 L
     - 19 / 19, equal
   * - ``SNMP-VIEW-BASED-ACM-MIB``
     - 129 L
     - 90 L
     - 40 / 39; frozen copy defines ``vacmContextStatus``
   * - ``RFC1213-MIB``
     - 417 L
     - 410 L
     - 135 / 203; disjoint in both directions

These are line counts and exported symbol sets. They do not establish
equivalence: they do not cover subtype constraints, DEFVALs, INDEX and AUGMENTS
wiring, resolved IMPORTS, the SMI-type-to-class binding, or behaviour in the
modules that contain code. Two modules disagree on symbols alone. Eight of the
26 contain hand-written behaviour: ``SNMPv2-SMI``, ``SNMPv2-TC``,
``SNMPv2-CONF``, ``SNMPv2-TM``, ``SNMP-FRAMEWORK-MIB``, ``SNMP-TARGET-MIB``,
``INET-ADDRESS-MIB`` and ``TRANSPORT-ADDRESS-MIB``.

The table therefore establishes that the copies have diverged. It does not
establish that any individual module can be substituted safely. Substitution
requires an equivalence check covering the properties listed above, applied per
module.

**Consequence for the inversion argument.** A code generator that targets a
runtime encodes that runtime's shape; this is the definition of a back end. The
specific defect was narrower and visible in the emitted output:
``getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0)`` guards indicated that
pysmi was inferring pysnmp's loader behaviour across versions, because pysnmp
had not specified which setters exist or what ``exportSymbols`` accepts.

That correction has been applied. pysnmp publishes the loader contract and
exposes ``MibBuilder.loaderContract``; pysmi targets v1 and emits the setters it
names without testing for them. The inference had already gone stale in both
directions by the time it was removed: the version branches named releases from
2017 and 2018, and a separate list of classes believed to lack
``setReference()`` was dropping REFERENCE text from three conformance macros
that had gained the setter (pysnmp/pysmi#194). One generated artifact now serves
pysmi's bundle, pysnmp's base layer and sc4snmp.


The revised layering
--------------------

Ownership follows the layer.

.. list-table::
   :header-rows: 1
   :widths: 16 46 22

   * - Repository
     - Owns
     - Does not own
   * - **pysmi**
     - The SMI model and its version negotiation. The canonical normalized form
       and content hash. The corpus DDL, as a rendering of the model. The corpus
       writer. The OID-to-module index. Bundled base sources and their manifest.
       Every artifact shape -- ``json``, ``.py``, ``.db`` -- each targeting a
       contract published by its consumer.
     - Any consumer's
       loader contract
   * - **pysnmp**
     - The corpus reader. ``MibStore`` / ``CompositeStore``, class synthesis,
       the override table, class identity, provenance API, ``loadTexts``, engine
       MIBs. The loader contract ``codegen/pysnmp.py`` targets, and the
       behavioural base modules.
     - The model, the DDL,
       the builder, its own
       generated modules
   * - **mibs**
     - Raw ``.mib`` sources, selection configs, CI.
     - Build code
   * - **pyasn1**
     - Nothing in this effort.
     -

The dependency direction becomes ``mibs`` to ``pysmi``, with pysnmp depending on
neither at runtime and reading a documented file format with a standard-library
driver.

Three consequences follow.

*The contract is data.* pysmi ships the DDL and a JSON Schema for the document
form as package data, versioned by the mechanism jsondoc already implements.
pysnmp's reader gates on the ``schema_version`` in the corpus manifest table as
a jsondoc consumer gates on ``meta.schema``. Neither repository imports the
other to satisfy it.

*Drift is held by a conformance fixture.* pysmi publishes a corpus built from a
fixed module set with the expected results. pysnmp's reader executes it in
pysnmp's CI. This is the standard mechanism for a cross-repository format and
does not require the repositories to merge.

*The corpus back end is neutral.* ``--destination-format=sqlite`` emits OIDs,
names, node types, syntax, constraints, indices and texts. None of these are
pysnmp-specific. A requirement for the writer to know what a ``MibTableColumn``
is would indicate a layering violation in the new code.


Revised work plan
-----------------

**pysmi -- new work.** Each item added here corresponds to an item removed from
pysnmp.

* Publish the SMI model as a specification: a written spec and a JSON Schema
  file shipped as package data, describing schema v1 as jsondoc emits it. This
  documents existing behaviour and changes none of it.
* Define the canonical normalized form and the content hash over it. The hash
  must be stable across pysmi versions and identical between a full corpus and a
  subset filtered from it. It supersedes the raw-source digest for identity
  purposes; the source digest remains as a separate fact.
* Corpus DDL v1, the SQLite rendering: sortable OID key, core/text split,
  manifest table with schema version and corpus version held separately, and
  publish state permitting ``immutable=1``. ``immutable=1`` disables locking and
  change detection, so a file modified beneath a reader produces incorrect
  results or ``SQLITE_CORRUPT`` rather than a contention error. The invariant is
  that a corpus is sealed before publication, published atomically, and never
  updated in place; a new corpus is a new file.
* Corpus writer as a code generation back end.
* Batch compilation with a warm dependency cache, the outstanding half of
  pysnmp/pysmi#133. Under this plan it becomes a requirement of pysmi's own
  corpus build rather than a cross-repository request.
* A corpus driver over multiple source namespaces, deterministic by
  construction: a fixed immutable input set, no writes into a directory that is
  concurrently a source, and no network source. The defects catalogued in
  pysnmp/pysnmp#149 are corrected here. **Done**: :ref:`mibcorpus` and
  :py:mod:`pysmi.corpus` (pysnmp/pysmi#182). The open question below about the
  entry point is settled with it -- a corpus build takes a manifest of source
  namespaces rather than a module list, so it is its own console script.
* Conformance fixture for downstream readers.

**pysmi -- retained.** ``codegen/pysnmp.py`` and
``mibdump --destination-format=pysnmp`` remain supported and maintained.

**pysnmp -- unchanged from the current plan.** pysnmp/pysnmp#144,
pysnmp/pysnmp#145 and pysnmp/pysnmp#146 stand as written. pysnmp/pysnmp#140
ships independently.

**pysnmp -- added by this review.** Publish and version the loader contract that
``codegen/pysnmp.py`` targets. Converge the base layer: retain the eight
behavioural modules and the override set as hand-written code and take the
remainder from ``pysmi/mibs/pysnmp/`` rather than the 2017 files, behind the
equivalence check the drift table requires. This resolves the coupling; a second
emitter in pysnmp does not.

**pysnmp -- changed.** pysnmp/pysnmp#141 narrows to the runtime half: the
version-mismatch policy applied by a reader, and the override table format,
which is pysnmp's because it names pysnmp modules. The DDL moves to pysmi.
pysnmp/pysnmp#147 retains the reader and loses the builder. pysnmp/pysnmp#149
moves to pysmi with its defect list intact.

``pysnmp[compile]`` and the ``pysnmp-mib-build`` console script were proposals
in pysnmp/pysnmp#147 and were never implemented. Neither appears in any release,
so no interface is removed or deprecated and no caller requires migration.
``mibdump`` is the supported tool for compiling MIBs and is unaffected by this
proposal.

**pysnmp/pysnmp#142 closes.** Its question, whether jsondoc carries what the
corpus requires, is meaningful only while the two are separate schemas. Under a
single model the answer is definitional. The sample audit recorded above stands
as evidence that the fields are present. The remaining gap it would have
identified, the normalized hash, is listed as pysmi work.

**mibs -- as planned, with one substitution.** pysnmp/mibs#322,
pysnmp/mibs#323, pysnmp/mibs#324 and pysnmp/mibs#325 stand. CI invokes pysmi
rather than ``pysnmp-mib-build``. pysnmp/mibs#326 is independent.
pysnmp/mibs#335 is unaffected.


sc4snmp: the downstream consumer
--------------------------------

`splunk-connect-for-snmp <https://github.com/splunk/splunk-connect-for-snmp>`_
is the largest downstream consumer and an instance of the problem statement.
``splunk_connect_for_snmp/snmp/manager.py`` binds three artifacts of the *mibs*
repository:

.. list-table::
   :header-rows: 1
   :widths: 20 34 40

   * - Variable
     - Default
     - Use
   * - ``MIB_SOURCES``
     - ``https://pysnmp.github.io/mibs/asn1/@mib@``
     - passed to ``compiler.addMibCompiler()``; pysmi compiles ASN.1 to pysnmp
       modules in process, per module, at runtime
   * - ``MIB_INDEX``
     - ``https://pysnmp.github.io/mibs/index.csv``
     - parsed into ``mib_map`` as OID-to-module
   * - ``MIB_STANDARD``
     - ``https://pysnmp.github.io/mibs/standard.txt``
     - the standard module list

``is_mib_known()`` truncates the OID one arc at a time, longest prefix first,
looks each candidate up in ``mib_map``, and calls ``builder.loadModules()`` on
the module found. This is ``find_module(oid)`` followed by a lazy load,
implemented against an index built by ``index.py``. The ``1.3.6.1.6.3.1``
collision catalogued in pysnmp/pysnmp#149 resolves to ``RAPID-CITY`` rather than
``SNMPv2-MIB``, and this is the code path that consumes that result.

Three consequences follow.

*The corpus addresses an existing requirement.* It replaces ``mib_map``,
``MIB_SOURCES`` and the runtime compilation with one mounted file and one
lookup.

*A compatibility break is acceptable given a stated reason and a migration
route.* The reason is that the current path performs a network fetch and a full
ASN.1 compilation on the trap path, keyed against an index with a known
incorrect entry. The route is additive and staged:

1. ``index.csv``, ``asn1/`` and ``standard.txt`` continue to be published, and
   the determinism corrections fix ``index.csv`` in place. sc4snmp receives the
   ``1.3.6.1.6.3.1`` correction without any change on its side.
2. sc4snmp mounts ``core.db`` and configures the corpus source. ``mib_map`` and
   ``is_mib_known()`` reduce to a store lookup; ``MIB_SOURCES`` and the runtime
   compiler leave the trap path; ``MIB_INDEX`` and ``MIB_STANDARD`` become
   unnecessary rather than unsupported.
3. The HTTP endpoints and the mibserver are withdrawn only after stage 2 has
   shipped and been adopted, per pysnmp/mibs#325, which states that the
   retirement window depends on remaining consumers. This document identifies
   sc4snmp as one such consumer, by default, on every deployment.

*The Helm chart is part of the contract.* ``charts/mibserver``,
``local_mibs.sh`` and the ``localMibs.pathToMibs`` / ``existingClaim`` behaviour
are deployed by sc4snmp users. pysnmp/mibs#208 and any other change affecting
them is a compatibility surface.


Sequencing
----------

Under this proposal the critical path is not a single spike.

1. **Unblocked, no dependencies:** pysnmp/pysnmp#140; pysnmp/mibs#326; the
   pysnmp/pysnmp#144 and pysnmp/pysnmp#145 stories that run against an in-memory
   fixture; the SMI model specification, which documents shipped behaviour.
2. **Next:** the normalized form and content hash. This is the gate for
   duplicate detection, shadow warnings and subset stability, and is a smaller
   artifact to freeze than a DDL, since the model beneath it exists and has
   consumers.
3. **Then:** corpus DDL v1 and the writer, reviewed by pysnmp and mibs before
   dependent work starts. The post-deduplication node count is measured here, by
   the deterministic corpus driver, rather than being a prerequisite for
   starting.
4. **Then:** pysnmp's SQLite reader against the conformance fixture, and the
   mibs pipeline cutover behind legacy-compatible output.
5. **Last:** pysnmp/mibs#325.


Open questions
--------------

Unchanged by this proposal:

* Post-deduplication node count. Size estimates and some column widths depend on
  it.
* External consumers of the published OID index and the ``asn1`` HTTP endpoints,
  beyond sc4snmp. This gates the retirement window in pysnmp/mibs#325 and the
  ``gh-pages`` history decision in pysnmp/mibs#326.
* Schema version mismatch policy: whether a runtime refuses a newer corpus or
  reads the subset it understands. This is a property of the reader rather than
  of the schema, but remains undecided.
* Override table format, which is pysnmp's and remains unspecified.

Raised by this proposal:

* Whether the corpus back end is a ``mibdump`` destination format or a separate
  console script. **Settled**: a separate console script. A corpus build takes
  a manifest of source namespaces rather than a module list, and it produces
  every artifact at once; the *formats* remain ``mibdump`` destinations. See
  :ref:`mibcorpus`.
* Whether pysmi bundling 210 modules changes the purpose of ``src/standard`` in
  the mibs repository. The two now overlap, and one of them must be
  authoritative for a given module. Narrowing the bundle to what the corpus
  needs sharpens rather than settles this: the 275 modules now held in
  ``pysmi/mibs/future/`` are not published by either project, and whether
  ``src/standard`` should carry the ones a user might still poll is open.
