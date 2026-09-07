.. _mibs-as-data:

MIBs as data: layering review
=============================

.. note::

   Status: **proposal**. This reviews the plan recorded in pysnmp/pysnmp#148
   and its child issues, and proposes a different placement for one thing in
   it -- the schema. Nothing here is implemented. It is written down in pysmi
   because pysmi is the repository the proposal gives the schema to, and
   because a contract four repositories build against should be published by
   the one that produces it.

The effort under review replaces compiled-``.py`` MIB distribution with a
queryable corpus, so that OID-to-name translation stops requiring every module
to be preloaded. That goal is not in question here, and neither is most of the
plan. What is in question is a single ownership decision, and the argument
that produced it.

.. contents::
   :local:
   :depth: 1


The decision under review
-------------------------

pysnmp/pysnmp#147 places the corpus schema, the corpus writer, the corpus
reader and ``.py`` code generation in pysnmp, and gives the reason:

    Whoever owns the schema must own both sides of it.

and, in the same issue:

    ``pysmi/codegen/pysnmp.py`` means pysmi knows pysnmp's runtime shape,
    which is the actual inversion. pysmi should emit neutral IR; pysnmp
    should turn IR into pysnmp-shaped artifacts.

The second observation is correct. The first does not follow from it. The
inversion in pysmi is that pysmi knows what a ``mibBuilder`` is; the remedy
for that is to remove pysnmp's shape from pysmi, not to move pysmi's shape
into pysnmp. The plan does both, and the second move is the one that costs.


Three schemas, not one
----------------------

The word *schema* is doing three jobs in the current plan, and the ownership
argument is only valid for one of them.

.. list-table::
   :header-rows: 1
   :widths: 14 44 20

   * - Layer
     - What it fixes
     - Derived from
   * - **SMI model**
     - What a MIB module *means*: node classes, node types, syntax, subtype
       constraints, INDEX/AUGMENTS/IMPLIED, TEXTUAL-CONVENTIONs, DISPLAY-HINT,
       MAX-ACCESS, STATUS, UNITS, DEFVAL, revisions, per-symbol IMPORTS
       attribution.
     - RFC 2578-2580
   * - **Corpus serialization**
     - How that model is laid out for lookup: table layout, the sortable OID
       key, indexes, the core/text split, the manifest, publish state.
     - the model above, plus
       SQLite
   * - **Runtime object shape**
     - ``MibScalar`` / ``MibTableColumn`` / ``MibTableRow`` / ``MibTable``,
       class identity per ``(module, typename)``, ``prettyPrint`` / ``prettyIn``
       behaviour, the override table, ``loadTexts``.
     - pysnmp

"Whoever owns the schema must own both sides of it" is true of layer 3 and
only layer 3. Layer 1 is standards-derived and has consumers that will never
import pysnmp. Layer 2 is a file format; its two sides are a writer and
``sqlite3``, which is in the standard library.

Putting layer 1 in pysnmp means that anything wanting to know what a MIB row
means -- ``mibdump --destination-format=json`` users, splunk-connect-for-snmp,
libsmi-adjacent tooling, any future non-pysnmp reader -- depends on an SNMP
protocol engine to find out. That is a larger inversion than the one being
fixed, and it is pointed the same way.


pysmi already defines layer 1
-----------------------------

This is not a proposal to give pysmi a new responsibility. It is a proposal to
name one it already has and stopped noticing.

**The jsondoc schema is versioned and negotiable.** ``JsonCodeGen`` carries
``SCHEMA_VERSIONS`` and ``SCHEMA_VERSION``, accepts ``schemaVersion=`` on both
``gen_code()`` and ``gen_index()``, refuses a version it cannot emit, and
stamps what it emitted into ``meta.schema`` of every document and index. The
docstring already states the intent: *"A consumer that has to keep working
across pysmi releases asks for the one it understands and is told, rather than
left to infer the shape from the document."* That is a published contract with
a compatibility gate, which is exactly what pysnmp/pysnmp#141 sets out to
create.

**The model is complete.** Compiling ``IF-MIB``, ``ENTITY-MIB``,
``SNMPv2-MIB`` and ``DISMAN-EVENT-MIB`` to both back ends at pysmi 2.3.0 gives
symbol parity -- 94, 73, 70 and 122 nodes respectively in the JSON, matching
each module's ``exportSymbols`` call. Across that sample the JSON carries every
field pysnmp/pysnmp#142 was filed to go looking for:

* ``class`` -- ``objecttype``, ``objectidentity``, ``moduleidentity``,
  ``notificationtype``, ``textualconvention``, ``type``, ``objectgroup``,
  ``notificationgroup``, ``modulecompliance``, ``imports``
* ``nodetype`` -- ``scalar``, ``column``, ``row``, ``table``
* ``syntax`` with ``constraints`` -- ``range``, ``size``, ``enumeration`` --
  and ``bits``
* ``displayhint``, ``units``, ``default`` (DEFVAL), ``maxaccess``, ``status``,
  ``reference``, ``refinements``
* ``indices`` as ``{module, object, implied}``, and ``augmentation``
* ``objects`` as ``{module, object}`` for NOTIFICATION-TYPE
* ``revisions``, ``lastupdated``, ``organization``, ``contactinfo``
* ``imports`` as module-to-symbol-list, so every imported symbol is
  attributable to its source module

The ``class`` / ``nodetype`` split that the pysnmp/pysnmp#141 measurement
comment identifies as necessary -- *"The schema needs both -- they are not the
same axis"* -- is a jsondoc distinction being rediscovered downstream.

**Provenance is already emitted.** ``meta.comments`` carries a
``sha256`` digest of the ASN.1 source and the producing pysmi version. The
builder in pysnmp/pysnmp#147 proposes to invent both.

**The reverse index already exists.** ``JsonCodeGen.gen_index()`` produces the
OID-to-module index that pysnmp/pysnmp#148 describes as missing, with
deterministic ordering, prefix compression, mergeable output and its own
``meta.schema`` stamp. pysnmp/pysnmp#149 proposes to rebuild it in pysnmp
because the *mibs* repository's ``index.py`` is nondeterministic -- but
``index.py`` is a separate reimplementation, not the pysmi one.

**pysmi already ships the standard corpus.** As of 2.3.0 pysmi bundles **299**
RFC, IANA and IEEE modules in ``pysmi/mibs/asn1/``, with
``bundled_mibs.json`` recording each module's publisher and, for superseded
ones, which module took over each subtree. ``pysmi.mibs.successor_for()``
answers "which module defines this OID now" -- a runtime question, answered
from pysmi, today. Two premises in the older issues did not survive this:
pysnmp/pysmi#161's "bundling them makes pysmi a MIB distributor rather than a
base-layer provider", and the assumption in pysnmp/mibs#322 that
``src/standard`` is the only home for the standard tree.

What pysmi does **not** yet define, and would need to:

* a **canonical normalized form and content hash**. The current digest is over
  raw ASN.1 bytes, so whitespace and comment churn read as content changes.
  The plan is right to want a hash over normalized rows; it is a real gap.
* the **corpus serialization** (layer 2) -- no DDL exists anywhere yet.


What the current plan gets right
--------------------------------

Kept whole, and not re-argued below:

* **pyasn1 owns nothing here.** No SMI, MIB or OID knowledge belongs there.
* **``pysmi/codegen/pysnmp.py`` is an inversion.** Confirmed by the sample
  above: the only things the generated ``.py`` carries that the JSON does not
  are ``PYSNMP_MODULE_ID``, ``mibBuilder.importSymbols`` /
  ``exportSymbols`` calls, ``if mibBuilder.loadTexts:`` guards and
  ``getattr(mibBuilder, 'version', ...)`` compatibility branches. All four are
  pysnmp runtime shape, none is MIB semantics. Soft deprecation by disuse, with
  nothing removed, is the right disposition.
* **The runtime design.** ``MibStore`` / ``CompositeStore``, longest-prefix
  OID resolution across all stores with precedence only as tie-break,
  one-module-one-store, the class cache keyed ``(module, typename)``, the
  override table consulted before synthesis, per-module provenance, engine MIBs
  explicitly out of scope. This is the substance of pysnmp/pysnmp#144,
  pysnmp/pysnmp#145 and pysnmp/pysnmp#146 and none of it moves.
* **SQLite over DuckDB**, on the measured reasoning given.
* **The determinism defects** in pysnmp/pysnmp#149 -- the shared-directory race,
  the bootstrap off published output, ``--ignore-errors`` on only one pass,
  ``listdir``-ordered index collisions. All real, all still to be fixed.
* **Opt-in throughout**, with byte-identical default behaviour.
* **pysnmp/pysnmp#140** is independent of all of this and should ship now.


Where it goes wrong
-------------------

**1. It creates a second SMI model.** With the schema in pysnmp there are two
descriptions of what a MIB module means -- jsondoc v1 and corpus v1 -- and a
normalization step between them that neither repository owns. The whole of
pysnmp/pysnmp#142 exists to check whether they agree. With one model there is
nothing to check: the serialization is a rendering of the model, and drift is
not expressible.

**2. It deepens the dependency it wants to remove.** pysnmp/pysnmp#148's
ownership table says *"pysnmp needs neither at runtime"*, but today
``pysnmp-pysmi`` is a hard runtime dependency of pysnmp, not an extra. A
builder in pysnmp that parses raw ``.mib`` (pysnmp/pysnmp#149) makes pysnmp
depend on pysmi's parser more heavily, not less, while pysmi is stripped of
the ability to emit its own canonical form. Leaving the builder in pysmi lets
that dependency actually be dropped: SQLite is in the standard library, so a
reader needs the *format*, not the producer.

**3. It puts corpus rebuilds on a protocol library's release cadence.**
pysnmp/mibs#323 argues -- correctly -- that conflating schema version with
corpus version *"forces a pysnmp release on every corpus rebuild"*. But
pysnmp/pysnmp#147 ships the builder as a ``pysnmp[compile]`` console script, so
a builder fix ships as a pysnmp release regardless. A corpus rebuilds weekly; an
SNMP engine should not.

**4. It blocks everything behind one spike that cannot close.**
pysnmp/pysnmp#141 blocks seven issues across two repositories, and its own
"Prerequisite" section says the schema should not freeze until a post-dedup node
count exists. Nothing downstream can start, and the thing that would unblock it
is a measurement over a corpus whose build is itself being redesigned.

**5. It re-implements what exists.** The OID index (``gen_index``), the schema
version negotiation (``SCHEMA_VERSIONS``), the provenance stamp
(``meta.comments``) and module supersession (``bundled_mibs.json``) are all
already in pysmi and all appear as new work in the pysnmp issues.

**6. ``mibdump --destination-format=pysnmp`` and the schema are separable.**
The plan treats "remove the pysnmp format from mibdump" and "move the schema to
pysnmp" as the same move. They are opposite moves. The first narrows pysmi to
neutral output; the second widens pysnmp to own neutral output.


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
     - The SMI model and its version negotiation. The canonical normalized
       form and content hash. The corpus DDL, as a rendering of the model.
       The corpus writer. The OID-to-module index. Bundled base sources and
       their manifest.
     - Anything named after
       a consumer
   * - **pysnmp**
     - The corpus *reader*. ``MibStore`` / ``CompositeStore``, class synthesis,
       the override table, class identity, provenance API, ``loadTexts``,
       engine MIBs. Its own ``.py`` emitter, consuming the model.
     - The model, the DDL,
       the builder
   * - **mibs**
     - Raw ``.mib`` sources, selection configs, CI. No Python.
     - Build code
   * - **pyasn1**
     - Nothing in this effort.
     -

Dependency direction becomes ``mibs`` → ``pysmi``, and ``pysnmp`` → nothing.
pysnmp reads a documented file format with a stdlib driver.

Three concrete consequences:

*The contract is data, not code.* pysmi ships the DDL and a JSON Schema for
the document form as package data, versioned by the mechanism jsondoc already
has. pysnmp's reader gates on the ``schema_version`` in the corpus manifest
table exactly as a jsondoc consumer gates on ``meta.schema``. Neither repository
imports the other to honour it.

*Drift is held by a conformance fixture, not by co-location.* pysmi publishes a
small corpus built from a fixed module set, with the expected rows. pysnmp's
reader runs it in pysnmp's own CI. That is how a cross-repository contract is
normally held, and it does not require merging the repositories to get it.

*The corpus back end is neutral.* ``--destination-format=sqlite`` emits OIDs,
names, node types, syntax, constraints, indices and texts. There is nothing in
that list a libsmi user would call pysnmp-specific. If it ever needs to know
what a ``MibTableColumn`` is, the layering has been violated and the review
above applies to the new code.


Revised work plan
-----------------

**pysmi -- new work.** These are the items the replan adds here; each is
matched by an item it removes from pysnmp.

* Publish the SMI model as a specification: written spec plus a JSON Schema
  file shipped in the package, describing schema v1 as jsondoc emits it today.
  Documentation of existing behaviour, not a change to it.
* Define the canonical normalized form and the content hash over it. Must be
  stable across pysmi versions and identical between a full corpus and a subset
  filtered from it. Supersedes the raw-source digest for identity purposes;
  the source digest stays, as a different fact.
* Corpus DDL v1 -- the SQLite rendering. Sortable OID key, core/text split,
  manifest table with schema version and corpus version kept separate, publish
  state that permits ``immutable=1``.
* Corpus writer as a code generation back end.
* Batch compilation with a warm dependency cache -- the outstanding half of
  pysnmp/pysmi#133. Under this plan it stops being a cross-repository ask and
  becomes how pysmi's own corpus build works.
* A corpus driver over many source namespaces, deterministic by construction:
  fixed immutable input set, no writes into a directory that is concurrently a
  source, no network source. The defects catalogued in pysnmp/pysnmp#149 are
  fixed here rather than reproduced there.
* Conformance fixture for downstream readers.

**pysmi -- unchanged.** ``codegen/pysnmp.py`` and
``mibdump --destination-format=pysnmp`` stay, soft-deprecated by disuse, per
pysnmp/pysmi#132. Nothing is removed; that part of the original plan was right
and removal is not pysnmp's call to force.

**pysnmp -- unchanged from the current plan.** pysnmp/pysnmp#144,
pysnmp/pysnmp#145 and pysnmp/pysnmp#146 stand as written. pysnmp/pysnmp#140
ships independently. pysnmp gains its own ``.py`` emitter over the model, which
is what actually resolves the ``codegen/pysnmp.py`` inversion.

**pysnmp -- changed.** pysnmp/pysnmp#141 narrows to the runtime half: the
version-mismatch policy a reader applies, and the override table format, which
is genuinely pysnmp's because it names pysnmp modules. The DDL itself moves to
pysmi. pysnmp/pysnmp#147 loses the builder and keeps the reader;
``pysnmp[compile]`` is not needed, since a reader needs no compiler.
pysnmp/pysnmp#149 moves to pysmi with its defect list intact.

**pysnmp/pysnmp#142 closes.** Its question -- does jsondoc carry what the corpus
needs -- is only meaningful when the two are separate schemas. Under one model
the answer is definitional. The sample audit above stands as the record that
the fields are in fact present; the remaining gap it would have found, the
normalized hash, is listed above as pysmi work.

**mibs -- as planned, with one substitution.** pysnmp/mibs#322,
pysnmp/mibs#323, pysnmp/mibs#324 and pysnmp/mibs#325 stand. The repository's CI
calls pysmi rather than ``pysnmp-mib-build``; nothing else about them changes.
pysnmp/mibs#326 is independent and should proceed. pysnmp/mibs#335, freshness,
is unaffected either way.


Sequencing
----------

The point of the replan is that the critical path stops being one spike.

1. **Now, in parallel, nothing blocking:** pysnmp/pysnmp#140. pysnmp/mibs#326.
   The pysnmp/pysnmp#144 and pysnmp/pysnmp#145 stories that run against an
   in-memory fixture. Writing down the SMI model spec, which is documentation
   of shipped behaviour.
2. **Then:** the normalized form and content hash. This is the real gate -- it
   is what duplicate detection, shadow warnings and subset stability rest on --
   and it is a much smaller thing to freeze than a whole DDL, because the model
   underneath it already exists and already has consumers.
3. **Then:** corpus DDL v1 and the writer, reviewed by pysnmp and mibs before
   dependent work starts. The post-dedup node count is measured here, from the
   deterministic corpus driver, rather than being a prerequisite for starting.
4. **Then:** pysnmp's SQLite reader against the conformance fixture, and the
   mibs pipeline cutover behind legacy-compatible output.
5. **Last, unchanged:** pysnmp/mibs#325.


Open questions
--------------

Unchanged by this proposal and still open:

* Post-dedup node count. Every size figure and some column widths depend on it.
* External consumers of the published OID index and the ``asn1`` HTTP
  endpoints. Gates the retirement window in pysnmp/mibs#325 and the
  ``gh-pages`` history decision in pysnmp/mibs#326.
* Schema-version mismatch policy -- refuse a newer corpus outright, or read the
  subset understood. Now a pysnmp question about its reader rather than a
  schema question, but no more decided than before.
* Override table format. pysnmp's, and still unspecified.

Raised by this proposal:

* Whether the corpus back end is a ``mibdump`` destination format or its own
  console script. A corpus build takes a source set and a selection config
  rather than a module list, so the argument shapes differ enough that
  ``mibdump`` may be the wrong front door.
* Whether pysmi bundling 299 modules changes what ``src/standard`` in the mibs
  repository is for. Not a blocker, but the two now overlap and only one can be
  authoritative for a given module.
