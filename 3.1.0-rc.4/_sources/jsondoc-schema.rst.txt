.. _jsondoc-schema:

JSON document schema
====================

:py:class:`~pysmi.codegen.jsondoc.JsonCodeGen` renders a MIB module as a JSON
document describing the SMI model: what the module declares, and what each
declaration means. This page specifies that document.

The specification exists because the document is a contract. Consumers outside
pysmi build against it -- ``mibdump --destination-format=json`` users, and the
corpus work described in :doc:`/mibs-as-data` -- and a consumer should be able
to write a reader from this page without reading ``jsondoc.py``.

Machine-readable schemas ship beside it as package data, so a consumer can
validate a document rather than trust it:

.. code-block:: python

   from pysmi.codegen.schemas import schema

   document_schema = schema("document")
   index_schema = schema("index")

Where the prose and the schema disagree, the prose states intent and the schema
states what is emitted. Such a disagreement is a defect in one of them.

.. contents::
   :local:
   :depth: 2


Versioning
----------

Every document records the schema version it was emitted against:

.. code-block:: json

   {"meta": {"schema": 1}}

A consumer reads ``meta.schema`` and selects its handling from that. It does not
infer the shape from the document in front of it.

A caller may ask for a specific version:

.. code-block:: python

   info, document = JsonCodeGen().gen_code(ast, symbolTable, schemaVersion=1)

:py:attr:`~pysmi.codegen.jsondoc.JsonCodeGen.SCHEMA_VERSIONS` lists what the
installed pysmi can emit and :py:attr:`~pysmi.codegen.jsondoc.JsonCodeGen.SCHEMA_VERSION`
is the newest, which is the default. Asking for a version outside that set
raises :py:class:`~pysmi.error.PySmiCodegenError` rather than silently emitting
something else.

Compatibility policy
~~~~~~~~~~~~~~~~~~~~

Within a schema version:

* a field that is documented as present will not be removed
* a field's type will not change
* the members of a closed enumeration -- ``class``, ``nodetype``, ``status``,
  ``maxaccess``, ``kind``, DEFVAL ``format`` -- will not change meaning

New *optional* fields may be added within a version. A consumer must therefore
ignore fields it does not recognize rather than reject a document for carrying
them. This is the one direction in which a version can move, and it is why
``additionalProperties`` is open on symbol objects in the shipped schema.

Anything else -- removing a field, changing a type, narrowing an enumeration,
changing what a field means -- requires a new schema version, and both versions
are then emittable for as long as ``SCHEMA_VERSIONS`` lists them.


Document structure
------------------

A document is a JSON object. Its keys are:

``meta``
    Document metadata. Always present. Never a MIB symbol, because ``meta`` is
    not a legal SMI descriptor.

``imports``
    The module's IMPORTS clause. Absent for a module that imports nothing.

everything else
    One key per MIB symbol, keyed by descriptor. Symbols appear in the order the
    module's symbol table rendered them, which follows declaration order.

.. code-block:: json

   {
     "imports": {"class": "imports", "SNMPv2-SMI": ["OBJECT-TYPE", "mib-2"]},
     "ifNumber": {
       "name": "ifNumber",
       "oid": "1.3.6.1.2.1.2.1",
       "nodetype": "scalar",
       "class": "objecttype",
       "syntax": {"type": "Integer32", "class": "type"},
       "maxaccess": "read-only",
       "status": "current"
     },
     "meta": {"schema": 1}
   }

meta
~~~~

===============  ========  =============================================
Field            Type      Notes
===============  ========  =============================================
``schema``       integer   Required. The version this document follows.
``comments``     array     Present when the caller passed ``comments``.
``module``       string    Emitted alongside ``comments``, not alone.
===============  ========  =============================================

pysmi's own callers pass three comment lines: the ASN.1 source name, a
``Source digest sha256:<hex>`` line over the source bytes, and a
``Produced by pysmi-<version>`` line.

The digest covers the **raw ASN.1 bytes**. It answers "is this the same file?",
which is not the same question as "is this the same module content?" --
reindenting a MIB changes it. A hash over normalized model rows is separate work
(pysnmp/pysmi#180).

imports
~~~~~~~

An object with the fixed key ``class`` set to ``"imports"``, plus one key per
source module whose value is the list of symbols taken from it.

.. code-block:: json

   {
     "class": "imports",
     "SNMPv2-SMI": ["Counter32", "MODULE-IDENTITY", "OBJECT-TYPE", "mib-2"],
     "SNMPv2-TC": ["DisplayString", "TEXTUAL-CONVENTION"]
   }

Symbols pysmi repaired are included as though the MIB had imported them. A
module whose IMPORTS omits a symbol it uses -- common in older MIBs -- yields a
document in which the import is present, because that is what the module means
rather than what it says. The compilation summary reports such a module as
repaired.

This section is what makes ``syntax.type`` resolvable: a type name that is not a
base type is defined either in this module or in exactly one module named here.


Symbols
-------

Every symbol object carries ``name`` and ``class``. ``class`` selects the rest
of the shape.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - ``class``
     - Declares
   * - ``objecttype``
     - OBJECT-TYPE: a scalar, a table, a conceptual row, or a column
   * - ``objectidentity``
     - OBJECT-IDENTITY, and plain OID value assignments
   * - ``moduleidentity``
     - MODULE-IDENTITY
   * - ``notificationtype``
     - NOTIFICATION-TYPE, and SMIv1 TRAP-TYPE
   * - ``textualconvention``
     - TEXTUAL-CONVENTION
   * - ``type``
     - A type assignment that is not a TEXTUAL-CONVENTION
   * - ``objectgroup``
     - OBJECT-GROUP
   * - ``notificationgroup``
     - NOTIFICATION-GROUP
   * - ``modulecompliance``
     - MODULE-COMPLIANCE
   * - ``agentcapabilities``
     - AGENT-CAPABILITIES

``class`` and ``nodetype`` are independent axes and a consumer needs both.
``class`` says which SMI macro declared the symbol; ``nodetype``, which only
``objecttype`` carries, says its role in the conceptual-table structure:
``scalar``, ``table``, ``row`` or ``column``.

objecttype
~~~~~~~~~~

===================  ========  ======================================================
Field                Type      Notes
===================  ========  ======================================================
``name``             string    Required.
``oid``              string    Required. See :ref:`jsondoc-oid`.
``nodetype``         string    Required. ``scalar``, ``table``, ``row``, ``column``.
``class``            string    Required. ``"objecttype"``.
``maxaccess``        string    Required. See :ref:`jsondoc-maxaccess`.
``status``           string    Required. See :ref:`jsondoc-status`.
``syntax``           object    A :ref:`jsondoc-typespec`. Absent on ``table`` and
                               ``row``, which have no SYNTAX of their own.
``units``            string    UNITS.
``default``          object    DEFVAL. See :ref:`jsondoc-defval`.
``indices``          array     INDEX, in declaration order. ``row`` only.
``augmentation``     object    AUGMENTS. ``row`` only, exclusive with ``indices``.
``description``      string    Text-gated. See :ref:`jsondoc-texts`.
``reference``        string    Text-gated.
===================  ========  ======================================================

moduleidentity
~~~~~~~~~~~~~~

===================  ========  ======================================================
Field                Type      Notes
===================  ========  ======================================================
``name``             string    Required.
``oid``              string    Required.
``class``            string    Required. ``"moduleidentity"``.
``lastupdated``      string    LAST-UPDATED. A timestamp, so it is emitted in
                               both modes -- see :ref:`jsondoc-texts`.
``organization``     string    Text-gated.
``contactinfo``      string    Text-gated.
``revisions``        array     REVISION clauses, newest first. Each entry has
                               ``revision``, and ``description`` when texts are
                               generated.
``description``      string    Text-gated.
===================  ========  ======================================================

Revision *timestamps* are emitted whether or not texts are generated. Revision
*descriptions* are text-gated like every other description in the document
(pysnmp/pysmi#192).

textualconvention and type
~~~~~~~~~~~~~~~~~~~~~~~~~~

===================  ========  ======================================================
Field                Type      Notes
===================  ========  ======================================================
``name``             string    Required.
``class``            string    Required.
``type``             object    Required. A :ref:`jsondoc-typespec`.
``status``           string    ``textualconvention`` only, required.
``displayhint``      string    DISPLAY-HINT. ``textualconvention`` only.
``description``      string    Text-gated. ``textualconvention`` only.
``reference``        string    Text-gated. ``textualconvention`` only.
===================  ========  ======================================================

Neither carries an ``oid``: a type declaration names no node in the OID tree.

objectidentity
~~~~~~~~~~~~~~

``name``, ``oid`` and ``class`` are required. ``status``, ``description`` and
``reference`` appear when the module declared them -- a bare OID value
assignment such as ``mib-2 OBJECT IDENTIFIER ::= { mgmt 1 }`` carries none of
the three, which is why they are optional here and required on OBJECT-TYPE.

notificationtype, objectgroup, notificationgroup
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All three carry ``name``, ``oid``, ``class``, ``status``, and an ``objects``
array of :ref:`jsondoc-symbolref`. ``objects`` is required on the two group
classes and optional on ``notificationtype``, where a notification may carry no
OBJECTS clause.

modulecompliance
~~~~~~~~~~~~~~~~

====================  ========  =====================================================
Field                 Type      Notes
====================  ========  =====================================================
``name``              string    Required.
``oid``               string    Required.
``class``             string    Required.
``status``            string    Required.
``modulecompliance``  array     Required. MANDATORY-GROUPS across every MODULE
                                clause, flattened to a list of
                                :ref:`jsondoc-symbolref`.
``refinements``       array     GROUP and OBJECT clauses.
====================  ========  =====================================================

A refinement entry carries ``module``, ``object`` and ``kind`` (``"group"`` or
``"object"``), plus any of ``minaccess`` (MIN-ACCESS), ``syntax`` (SYNTAX),
``writesyntax`` (WRITE-SYNTAX) and ``description``.

Flattening the MODULE clauses loses which module a MANDATORY-GROUPS entry was
declared under. Each entry is still attributed to the module defining the group,
so the information is recoverable; the grouping is not.

agentcapabilities
~~~~~~~~~~~~~~~~~

===================  ========  ======================================================
Field                Type      Notes
===================  ========  ======================================================
``name``             string    Required.
``oid``              string    Required.
``class``            string    Required.
``status``           string    Required. The grammar makes STATUS mandatory.
``productrelease``   string    PRODUCT-RELEASE. Mandatory in the grammar, but
                               omitted here when the MIB declares it empty.
``capabilities``     array     One entry per SUPPORTS clause, in the order the
                               clauses appear. Absent when there are none.
``description``      string    Text-gated.
``reference``        string    Text-gated.
===================  ========  ======================================================

Each ``capabilities`` entry carries ``module`` -- the module the SUPPORTS clause
names, which is not necessarily one this document defines and not necessarily one
that was read -- plus ``includes``, the INCLUDES groups by name, and
``variations``.

A ``variations`` entry describes one VARIATION sub-clause:

====================  ========  =====================================================
Field                 Type      Notes
====================  ========  =====================================================
``object``            string    Required, and the only required field.
``syntax``            object    SYNTAX, as a :ref:`jsondoc-typespec`.
``writesyntax``       object    WRITE-SYNTAX, likewise.
``access``            string    ACCESS. Wider than ``maxaccess``: RFC 2580 section
                                6.5.2 adds ``not-implemented``, which no
                                OBJECT-TYPE can declare.
``creationrequires``  array     CREATION-REQUIRES, by object name.
``default``           object    DEFVAL, as a :ref:`jsondoc-defval`.
``description``       string    Text-gated.
====================  ========  =====================================================

``object`` alone being required is not an accident of the encoding. RFC 2580
section 6.5.2 makes DESCRIPTION mandatory on a VARIATION, so a variation that
records implementation without refining syntax or access carries nothing else --
and once texts are suppressed, nothing at all beyond the object. The entry is
still emitted, because which objects a SUPPORTS clause varies is structure. See
:ref:`jsondoc-texts`.


Shared structures
-----------------

.. _jsondoc-oid:

OIDs
~~~~

Dotted decimal, as a string: ``"1.3.6.1.2.1.2.2.1.1"``.

One exception. When pysmi synthesizes a stand-in column for an SMIv1 table whose
INDEX names a type rather than a column, that column's ``oid`` is a template
containing ``%s``, resolved against the row OID once it is known. Such symbols
are named ``pysmiFakeCol<n>`` starting at 1000.

.. _jsondoc-status:

status
~~~~~~

``current``, ``deprecated``, ``obsolete`` for SMIv2; ``mandatory``, ``optional``,
``obsolete``, ``deprecated`` for SMIv1. pysmi does not translate between the two
vocabularies, so a consumer sees the module's own.

.. _jsondoc-maxaccess:

maxaccess
~~~~~~~~~

``not-accessible``, ``accessible-for-notify``, ``read-only``, ``read-write``,
``read-create``, and ``write-only``, which is SMIv1 only.

.. _jsondoc-typespec:

Type specifications
~~~~~~~~~~~~~~~~~~~

The value of ``syntax`` on an OBJECT-TYPE and of ``type`` on a
TEXTUAL-CONVENTION or type assignment.

.. code-block:: json

   {
     "type": "INTEGER",
     "class": "type",
     "constraints": {"enumeration": {"up": 1, "down": 2, "testing": 3}}
   }

``type`` is the SMI type name **exactly as the MIB declares it**: a base type, or
the name of a TEXTUAL-CONVENTION or type assignment resolvable through the
module's own declarations or its ``imports``. It is never resolved to an
implementation class. That binding belongs to whatever consumes this model, and
keeping it out is what makes the document neutral.

``constraints`` carries any of:

``range``
    Array of ``{"min": <int>, "max": <int>}``, for numeric subtyping. A
    single-value constraint has ``min`` equal to ``max``.

``size``
    Array of the same shape, for OCTET STRING length.

``enumeration``
    Object mapping label to integer, for INTEGER named values.

``bits``, when present, sits beside ``constraints`` rather than inside it, and
maps bit label to bit position.

.. _jsondoc-defval:

DEFVAL
~~~~~~

``{"format": ..., "value": ...}``, where ``format`` says how to read ``value``:

==============  ===================================================
``format``      ``value``
==============  ===================================================
``decimal``     integer
``hex``         string of hex digits, no ``0x`` prefix
``string``      string
``oid``         dotted-decimal string
``enum``        string, a label from the type's enumeration
``bits``        a type specification carrying ``bits``
==============  ===================================================

.. _jsondoc-symbolref:

Symbol references
~~~~~~~~~~~~~~~~~

``{"module": ..., "object": ...}``. Used by ``objects``, ``modulecompliance``,
``refinements``, ``indices`` and ``augmentation``. Every reference is attributed
to the module that *defines* the symbol, not the one referring to it, so a
consumer resolves cross-module references without re-deriving them from
``imports``.

``indices`` entries add ``implied``, an integer 0 or 1 rather than a boolean,
recording whether the element was declared IMPLIED. ``augmentation`` adds
``name``, the augmenting row's own descriptor.


.. _jsondoc-texts:

Text generation
---------------

Human-readable text is emitted only when the caller asks for it -- ``genTexts``
on the API, ``--generate-mib-texts`` on ``mibdump``. Without it these fields are
absent:

* ``description`` and ``reference``, on every class that can carry them
* ``organization`` and ``contactinfo`` on ``moduleidentity``
* ``description`` on a ``revisions`` entry
* ``description`` on a ``refinements`` entry
* ``description`` on a ``variations`` entry

Descriptions are roughly a third of a generated module's bytes and many
consumers discard them, so suppressing them is worth having.

**Suppression removes prose and nothing else.** Everything that is not prose
survives, including the two fields that look textual and are not:

``lastupdated``
    A normalized timestamp, and the field date-based source precedence
    compares. Emitted whether or not texts are.

``revisions[].revision``
    Likewise. A revision entry without texts carries its timestamp and no
    description.

A MODULE-COMPLIANCE ``refinements`` entry is emitted whether or not it has a
description, including a GROUP clause whose only other content is the group it
names. Which groups a compliance statement refines is structure.

An AGENT-CAPABILITIES ``variations`` entry likewise. RFC 2580 section 6.5.2
makes DESCRIPTION mandatory on a VARIATION, so a variation that records
implementation without refining syntax or access carries nothing else -- and
which objects a SUPPORTS clause varies is structure, so the entry stays
(pysnmp/pysmi#198).

The property is asserted directly rather than described: stripping the prose
fields from a document generated with texts yields, exactly, the document
generated without them. ``tests/test_jsondoc_text_gating.py`` checks that over
a sample of real modules, and it is what makes the structural hash under
`Module identity`_ independent of the mode a document was generated in.

.. note::

   Three defects made this untrue in earlier releases. A no-texts document
   suppressed ``lastupdated`` with the prose (pysnmp/pysmi#191), emitted
   ``revisions[].description`` when every other description was suppressed
   (pysnmp/pysmi#192), and dropped MODULE-COMPLIANCE GROUP entries entirely
   rather than emitting them without their description (pysnmp/pysmi#190) --
   so ``SNMPv2-MIB``'s ``snmpBasicCompliance`` lost ``snmpCommunityGroup``
   altogether.

   A consumer comparing no-texts documents across that boundary sees the
   structural content change once, in the release carrying those fixes.


Module identity
---------------

A module needs an identity answering "is this the same module content?" The
digest in ``meta.comments`` answers "is this the same file?", which is a
different question: it covers raw ASN.1 bytes, so reindenting a MIB or fixing a
typo in a comment changes it while changing nothing a consumer of the model can
observe.

Both are kept. The source digest establishes provenance of a file; the hashes
below establish identity of a model.

.. code-block:: python

   from pysmi.codegen.normalized import module_hashes

   module_hashes(document)
   # {'normalization': 1,
   #  'content':   '614f6b29...',
   #  'structure': 'f74515e6...'}

``content``
    The model including prose. Two documents share it exactly when their models
    are equal. This is a module's identity.

``structure``
    The model with prose removed. Two modules differing only in DESCRIPTION text
    share it. The corpus ships descriptions as a separate artifact, so a build
    that carries structure alone has an identity for what it carried.

``normalization``
    The version of the algorithm below. It travels with the hashes because a
    hash without the algorithm that produced it compares to nothing.

Canonical form
~~~~~~~~~~~~~~

The hash is SHA-256 over a canonical byte sequence. A non-pysmi implementation
has to agree on all of this:

1. ``meta`` is excluded. Every other top-level key -- ``imports`` and each
   symbol -- is kept. Excluding ``meta`` is what keeps the hash stable across
   pysmi releases, since it carries the producing version.
2. For the structural form only, these fields are removed wherever they occur,
   at any depth: ``description``, ``reference``, ``organization``,
   ``contactinfo``. ``units`` and ``displayhint`` are **not** removed -- both
   are machine-readable and both change how a value is interpreted.
3. Object keys are sorted by Unicode code point.
4. Arrays keep their order. Order is semantic throughout the model: INDEX
   elements, revisions, ranges and object lists all mean something different
   reordered.
5. Separators are ``","`` and ``":"``, with no spaces.
6. Non-ASCII characters are emitted as themselves, not escaped.
7. The result is encoded UTF-8 and prefixed with
   ``pysmi-normalized-v<N>\n``, where ``<N>`` is the normalization version.
   The prefix is domain separation and pins the algorithm version into the
   digest.

Bumping the normalization version changes every hash even when no module
changed. That is deliberate -- a consumer comparing across the change must be
told rather than silently see everything move -- and it is a breaking change for
anyone who pinned a hash.

Properties
~~~~~~~~~~

Asserted in ``tests/test_normalized_hash.py``:

* reindenting a MIB, adding a comment, or converting line endings does not
  change either hash
* changing a constraint, MAX-ACCESS, STATUS, UNITS, an OID, or a SYNTAX does
* changing a DESCRIPTION changes ``content`` and not ``structure``
* a module compiled alone and the same module compiled in a batch hash
  identically, which is what makes a slim corpus a filter over a full one
  rather than a rebuild
* the producing pysmi version does not reach either hash

``structure`` is equal between a document generated with texts and one
generated without: prose is the only thing that differs between them. See
:ref:`jsondoc-texts`, which is where that property is established and where the
three defects that used to break it are recorded.


The OID index
-------------

:py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_index` emits a separate
document: the OID-to-module reverse index over a set of compiled modules.

.. code-block:: json

   {
     "meta": {"schema": 1},
     "identity": {"1.3.6.1.2.1.31": ["IF-MIB"]},
     "enterprise": {},
     "compliance": {"1.3.6.1.2.1.31.2.2.1": ["IF-MIB"]},
     "notification": {"1.3.6.1.6.3.1.1.5.3": ["IF-MIB"]},
     "oids": {"1.3.6.1.2.1.2": ["IF-MIB"]}
   }

All five sections map a dotted-decimal OID to a **list** of module names, because
more than one module can claim an OID. The index records that rather than
choosing, and leaves the precedence decision to the consumer.

``oids`` is prefix-compressed: an OID is omitted when a shorter prefix already
present maps to a module set that is a superset of its own. This keeps the index
proportional to the number of subtrees rather than the number of nodes.

Ordering is deterministic. Keys sort numerically when they are all OIDs and
lexicographically otherwise, and lists are sorted and deduplicated, so two runs
over the same input produce identical bytes.

An existing index can be merged into rather than replaced, via
``old_index_data``. ``meta.schema`` is rewritten on merge, so a merged index
carries the version of the run that last wrote it.


Validating a document
---------------------

.. code-block:: python

   import json

   import jsonschema

   from pysmi.codegen.schemas import schema

   document = json.loads(raw)
   jsonschema.validate(document, schema("document", document["meta"]["schema"]))

``tests/test_jsondoc_schema_contract.py`` does this over a module sample chosen
to reach every class and every awkward construct -- AUGMENTS, IMPLIED indices,
BITS, each constraint kind, each DEFVAL format, compliance refinements, and
SMIv1 alongside SMIv2 -- in both text modes. That test is what keeps this page
and the emitter from drifting apart.
