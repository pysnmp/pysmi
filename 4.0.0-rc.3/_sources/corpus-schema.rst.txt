.. _corpus-schema:

Corpus database schema
======================

:py:mod:`pysmi.corpus.db` renders a corpus as a SQLite database, ``core.db``.
This page specifies it.

The specification exists because the database is a contract, and an unusual
one: its consumer reads it with stdlib ``sqlite3`` and **does not import
pysmi**. pysnmp gates on the schema version and opens the file directly
(pysnmp/pysnmp#199), which is what lets pysnmp drop its required dependency on
this package. A reader should be writable from this page alone.

.. contents::
   :local:
   :depth: 2


What it is for
--------------

The published corpus already answers *which module owns this OID* --
``index-v2.csv`` is exactly that projection. Two questions it cannot answer are
why this file exists:

**What is the node at this OID?** The CSV is ``MODULE,OID`` and carries a
module's *anchors* only, so a leaf like ``ifDescr`` is not in it. Answering
from the ``json/`` tree means parsing a whole module -- 11 ms and 9,773 symbols
of ``CISCO-ENTITY-VENDORTYPE-OID-MIB`` to reach one of them. Here it is one
row, in microseconds.

**What comes after this OID?** Nothing published answers it at all. An anchor
index has no per-node ordering, so a GETNEXT walk cannot be served from one.

What it deliberately does **not** carry is prose. DESCRIPTION and REFERENCE are
roughly a third of a module's bytes, the runtime discards them under the
default ``loadTexts=False``, and the ``json/`` tree already serves the consumer
that wants them. See :doc:`/mibs-as-data`.


Versioning
----------

Two versions, kept apart on purpose.

``schema_version``
    The layout this page specifies. Stamped in the ``meta`` table and in the
    file's own ``user_version`` header field, so a reader can gate before it
    runs a query. Changes rarely.

``corpus_version``
    Which build of which MIB set this is. Supplied by whoever ran the build;
    nothing here invents one. Changes weekly.

Conflating them would force a pysnmp release on every corpus rebuild, which is
the mistake pysnmp/pysnmp#196 records.

The file also carries ``application_id`` ``0x50534D49`` (``PSMI``), so a reader
-- or ``file`` -- can tell a corpus from an unrelated database before trusting
its tables.

Within a schema version a column will not be removed, change type, or change
meaning. New *optional* columns and new tables may be added, so a reader must
select the columns it wants by name rather than by position, and must ignore
tables it does not recognize. Anything else requires a new schema version.


Opening it
----------

.. code-block:: python

   import sqlite3

   db = sqlite3.connect(f"file:{path}?immutable=1", uri=True)

``immutable=1`` tells SQLite the file cannot change, so it takes no locks and
needs no writable directory -- which is what lets a corpus be mounted read-only
from an image volume with nothing writable anywhere near it.

A published corpus is one file. It is written with ``journal_mode=DELETE`` and
VACUUMed, so there is no ``-wal`` sidecar for a reader to replay and none for
``immutable=1`` to refuse.


.. _corpus-oid-key:

The OID key
-----------

Every OID appears twice: as ``oid``, dotted decimal, for a consumer that wants
to print it, and as ``oid_key``, a BLOB, for every comparison.

SQLite compares BLOBs bytewise, so the encoding has to make bytewise order
equal numeric OID order. Dotted decimal does not -- ``"1.3.10"`` sorts below
``"1.3.9"`` -- and fixed-width arcs cost four bytes each for a value that is
almost always one.

**Each arc is a length byte followed by that many big-endian bytes.**

.. code-block:: text

   1.3.6      ->  01 01  01 03  01 06
   1.3.256    ->  01 01  01 03  02 01 00

Comparing two encodings compares the length bytes first, and a longer arc is a
larger arc, so the order comes out right with no padding. Two properties follow
and both are load-bearing:

* An OID that is a prefix of another encodes to a **byte prefix** of its
  encoding, so a subtree is a range rather than a scan.
* A prefix sorts **before** everything under it, so ``oid_key > ?`` ordered
  ascending is GETNEXT.

Reference implementations are :py:func:`~pysmi.corpus.db.oid_key`,
:py:func:`~pysmi.corpus.db.oid_from_key` and
:py:func:`~pysmi.corpus.db.subtree_bound`. A reader reimplements them; they are
twenty lines and importing pysmi for them would defeat the point.


Tables
------

meta
~~~~

``key`` / ``value``, both TEXT. Every value is a string, including the numbers.

==================  ============================================================
Key                 Meaning
==================  ============================================================
``schema_version``  The version this page specifies. Always present.
``producer``        ``pysmi``. Always present.
``modules``         Rows in ``module``.
``nodes``           Rows in ``node``.
``types``           Rows in ``type``.
``texts``           ``0``. Reserved: no build emits prose today.
``corpus_version``  Present only when the build was given one.
``corpus_id``       Present only when the build was given one.
==================  ============================================================

module
~~~~~~

One row per module the corpus carries.

================  =======  ===================================================
Column            Type     Notes
================  =======  ===================================================
``name``          TEXT     Primary key. The module's descriptor.
``tier``          TEXT     ``standard``, ``draft`` or ``vendor``, as the
                           build's manifest declared the namespace.
``oid``           TEXT     The MODULE-IDENTITY OID. NULL when the module
                           declares none, which SMIv1 modules do not.
``lastupdated``   TEXT     LAST-UPDATED, as the jsondoc normalized it.
``revision``      TEXT     Newest readable revision, ``YYYYMMDDHHMMZ``. NULL
                           when the module carries none that is a date.
``content_hash``  TEXT     ``pysmi.codegen.normalized.content_hash()`` of
                           the module. Two corpora agree on a module iff they
                           agree here.
``nodes``         INTEGER  How many rows this module has in ``node``.
================  =======  ===================================================

type
~~~~

One row per distinct type specification in the corpus, stored once.

============  =======  =======================================================
Column        Type     Notes
============  =======  =======================================================
``id``        INTEGER  Primary key. Referenced by ``node.syntax`` and
                       ``symbol.type``.
``spec``      TEXT     A :ref:`type specification <jsondoc-typespec>` as
                       compact JSON with sorted keys. Unique.
============  =======  =======================================================

A corpus repeats a handful of specifications tens of thousands of times, so
this takes real bytes out of the hottest table. The other reason matters more:
it hands a reader a **stable identity** for "this is the same type", which is
what keeps runtime class synthesis from producing two classes that one
``isinstance`` check has to tell apart (pysnmp/pysnmp#145).

node
~~~~

One row per symbol that has a place in the OID tree.

=============  =======  ======================================================
Column         Type     Notes
=============  =======  ======================================================
``oid_key``    BLOB     With ``module``, the primary key. See
                        :ref:`corpus-oid-key`.
``module``     TEXT     The module that defines it.
``name``       TEXT     The symbol's descriptor.
``oid``        TEXT     Dotted decimal.
``class``      TEXT     ``objecttype``, ``objectidentity``,
                        ``moduleidentity``, ``notificationtype``,
                        ``objectgroup``, ``notificationgroup``,
                        ``modulecompliance`` or ``agentcapabilities``.
``nodetype``   TEXT     ``scalar``, ``table``, ``row``, ``column``.
                        ``objecttype`` only; NULL elsewhere.
``status``     TEXT     As :ref:`jsondoc-status` defines it.
``maxaccess``  TEXT     As :ref:`jsondoc-maxaccess` defines it.
``units``      TEXT     UNITS.
``syntax``     INTEGER  ``type.id``, or NULL.
``defval``     TEXT     DEFVAL as :ref:`jsondoc-defval` JSON, or NULL.
``indices``    TEXT     INDEX as JSON, in declaration order. ``row`` only.
``augments``   TEXT     AUGMENTS as JSON. ``row`` only.
=============  =======  ======================================================

**The key is (oid_key, module), not oid_key alone.** Two modules may define one
OID and the corpus records both; deciding which one answers is ``oid_index``'s
job, not this table's.

Two indexes come with it: ``node_by_module`` on ``(module, oid_key)``, for
walking one module in OID order, and ``node_by_name`` on ``(module, name)``,
for the ``importSymbols(module, name)`` lookup that is pysnmp's usual way in.

Symbols whose OID is a ``pysmiFakeCol`` template are **not** here. The template
carries ``%s`` and is resolved against a row OID that a corpus never sees.

symbol
~~~~~~

One row per symbol that declares a type rather than a node.

===============  =======  ====================================================
Column           Type     Notes
===============  =======  ====================================================
``module``       TEXT     With ``name``, the primary key.
``name``         TEXT     The descriptor.
``class``        TEXT     ``textualconvention`` or ``type``.
``status``       TEXT     ``textualconvention`` only.
``displayhint``  TEXT     DISPLAY-HINT. ``textualconvention`` only.
``type``         INTEGER  ``type.id``, or NULL.
===============  =======  ====================================================

import
~~~~~~

The IMPORTS clauses, one row per imported symbol rather than per clause,
because the lookup is by symbol: a reader resolving the type a ``syntax`` names
asks which module defines it.

============  ====  ======================================================
Column        Type  Notes
============  ====  ======================================================
``module``    TEXT  With ``name``, the primary key. The importing module.
``name``      TEXT  The symbol imported.
``source``    TEXT  The module it is imported from.
============  ====  ======================================================

oid_index
~~~~~~~~~

The ranked OID projection -- the same content as ``index-v2.csv``, carried here
so a consumer needs one file rather than two.

============  ====  ======================================================
Column        Type  Notes
============  ====  ======================================================
``oid_key``   BLOB  Primary key.
``oid``       TEXT  Dotted decimal.
``module``    TEXT  The module that owns the arc, by the rule
                    :py:mod:`pysmi.corpus.index` states.
============  ====  ======================================================

This indexes **anchors**, not every node: a module registers arcs with its
MODULE-IDENTITY and OBJECT-IDENTITY declarations, and that is what an index
consumer resolves against. ``find_module(oid)`` is therefore a longest-prefix
search -- chop one arc at a time and look each candidate up -- not a single
exact match.


Resolving an OID
----------------

The whole access pattern, in the order a trap receiver runs it:

.. code-block:: python

   def find_module(db, oid):
       """Longest prefix of oid that the index resolves, and its module."""
       arcs = oid.split(".")

       while arcs:
           row = db.execute(
               "SELECT module FROM oid_index WHERE oid_key = ?",
               (oid_key(".".join(arcs)),),
           ).fetchone()

           if row:
               return row[0]

           arcs.pop()

       return None

   def node(db, oid):
       """The node at an exact OID, from the module that owns the arc."""
       # Not ORDER BY module LIMIT 1. Two modules may define one OID, and
       # which of them answers is oid_index's decision -- resolving it by
       # module name instead means a real collision is settled alphabetically.
       module = find_module(db, oid)

       return db.execute(
           "SELECT module, name, class, nodetype, maxaccess, syntax "
           "FROM node WHERE oid_key = ? AND module = ?",
           (oid_key(oid), module),
       ).fetchone()

   def next_node(db, oid):
       """GETNEXT: the first node ordered after oid."""
       return db.execute(
           "SELECT oid, module, name FROM node WHERE oid_key > ? "
           "ORDER BY oid_key LIMIT 1",
           (oid_key(oid),),
       ).fetchone()

   def subtree(db, oid):
       """Every node at or below oid, in OID order."""
       low = oid_key(oid)

       return db.execute(
           "SELECT oid, module, name FROM node "
           "WHERE oid_key >= ? AND oid_key < ? ORDER BY oid_key",
           (low, subtree_bound(low)),
       ).fetchall()

``find_module`` is at most one point query per arc -- twenty for the deepest
OIDs in practice. Measured at roughly 3 µs each on a corpus of the published
size, so the whole chop is well inside any trap budget; the range scan
alternative measures about the same, and neither is a reason to prefer one
shape over the other.


Determinism
-----------

Two builds of one source tree produce **byte-identical** files, which is what
lets a corpus be content-addressed and a rebuild that changed nothing publish
nothing.

Getting there rules out the obvious things -- no build timestamp, no host name,
no producer version anywhere in the file -- and some less obvious ones:

* Rows are inserted in a fixed order -- modules by name, nodes by
  ``(oid_key, name)``, types by ``spec`` -- so the b-tree is laid out the same
  way whatever order the caller iterated in.
* ``type.id`` is assigned in sorted ``spec`` order, so an id means the same
  thing in two builds of one tree.
* Structured columns are rendered as JSON with sorted keys and no incidental
  whitespace.
* The file is ``ANALYZE``\ d and then ``VACUUM``\ ed, so no free page survives
  to record how it was filled.

A caller that wants its build stamped passes ``corpus_version``, which is data
it chose rather than data the build observed. From the command line that is
``mibcorpus --corpus-version``, with ``--corpus-id`` naming the corpus it is a
build of; both are recorded verbatim and both are absent from the metadata
when the build was given neither. Nothing is invented in their place, because
a version taken from a clock or from a checkout would make two builds of one
source tree differ -- which is the property everything above is written to
preserve.


Checking a build before publishing it
-------------------------------------

:py:func:`pysmi.corpus.db.open_db` decides whether a file is a corpus at all:
the ``application_id``, a readable header, a schema version the reader
implements. :py:func:`pysmi.corpus.db.validate` asks the question that one
cannot -- the file is a corpus, but is it a *sound* one:

.. code-block:: python

   from pysmi.corpus.db import validate

   problems = validate("core.db")

   if problems:
       for problem in problems:
           print(problem)

       raise SystemExit(1)

Every check is a universal over a whole build rather than a property of one
row, which is why they belong here rather than in a publisher's own tests. A
unit test asserts that one module round-trips; none can say that no module
among thousands lost its content hash, that no node references a type row that
is not there, that every scalar carries a syntax, that every tier is in the
vocabulary, that each ``module.nodes`` agrees with the rows that module
actually contributed, or that ``oid_key`` orders the whole corpus the way the
arcs do.

It returns a list rather than raising, because a build wants to see every
problem it has rather than one per round trip. An empty list is a sound
corpus. Over pysnmp/mibs' 5,510 modules and 767,450 nodes it is one indexed
pass, measured at 17 seconds.


Proving a reader conforms
-------------------------

:py:mod:`pysmi.corpus.conformance` publishes a small fixed corpus and the
answers a reader of it must give. It exists because the contract between the
two repositories is data: pysnmp's reader is correct or not in a repository
this one cannot test, and this writer's output is consumed in a repository
that does not run these tests.

.. code-block:: python

   from pysmi.corpus.conformance import VECTORS, build_fixture

   build_fixture("conformance.db")

   for vector in VECTORS:
       ...  # dispatch on vector["op"], compare against vector["expect"]

The fixture is **built rather than shipped**, so it is always this tree's
writer over this tree's documents rather than a committed copy free to drift
from it. It is deterministic, so a harness may cache it.

The vectors cover the cases that break readers rather than the common path:
an OID two modules define, a leaf that is not in the index and has to chop
back to an anchor, an instance OID no MIB declares at all, the ``9``/``10``/
``256`` neighbours that catch string comparison and single-byte arcs, a walk
that must visit a shadowed OID once rather than once per module, and running
off the end of the corpus, which is ``endOfMibView`` and not an error.

They also cover the key encoding itself, and those vectors take no corpus:
they encode, decode, order, bracket and refuse, with the expected bytes
pinned rather than described. A reader that reimplements the codec -- which
is the supported thing to do, since reading a corpus is meant to need no
pysmi -- otherwise has only its own transcription of :ref:`corpus-oid-key` to
check itself against, and a transcription agrees with the specification right
up until the specification changes. Two implementations can satisfy every
ordering property here and still disagree on one length prefix, at which
point neither can read the other's files, so the bytes are the contract.

``vectors_as_json()`` renders them for a harness that is not written in
Python.


Proving the precedence rule agrees
----------------------------------

"Newest MODULE-IDENTITY revision wins, configured order breaks ties only" is
implemented three times, in two repositories that cannot import each other.
pysmi ranks a module found in several sources
(:py:func:`pysmi.compiler.rank_by_revision`) and ranks modules anchored at the
same OID (:py:func:`pysmi.corpus.index.rank_index`). pysnmp ranks the same
module found in several MIB directories, and again when several corpora carry
it. pysmi is an optional dependency of pysnmp, so pysnmp cannot import the
rule at runtime; pysmi cannot import pysnmp at all.

:py:mod:`pysmi.corpus.precedence` publishes the decisions as data, the same
way the fixture above publishes the reader contract:

.. code-block:: python

   from pysmi.corpus.precedence import VECTORS, run_vectors

   run_vectors()  # [] -- this side answers what it publishes

   for vector in VECTORS:
       ...  # dispatch on vector["op"], compare against vector["expect"]

Three operations. ``normalise_revision`` pins the widening of RFC 2578's
two-digit-year form and the refusal of a stamp that is not a date, because
the ranking is a string comparison over its output and two implementations
that agree on the ranking and disagree on the normalisation still resolve
differently. ``module_precedence`` is the module-name rule: candidates in
configured order, to the order they rank in and which ``PRECEDENCE_*`` rule
put the winner first. ``oid_precedence`` is the corpus rule, which carries
terms the module-name rule has nowhere to put -- obsolete over live, tier,
how strongly a module claims the arc, publishing RFC, and the module name
last so the rule is total and a rebuild cannot change its mind.

The two rules part company on an undated candidate. In the module-name rule a
single undated copy disables the comparison and the caller's source order
decides, because an undated module may well be the newer one. A corpus has no
source order to fall back to, so there an unplaceable revision sorts after
every placeable one instead.

Both projects run the vectors in their own CI, so a change on either side that
would break the other fails in whichever project moved, rather than surfacing
much later as a trap decoded against the wrong definition. See
pysnmp/pysmi#248.


Building one
------------

.. code-block:: sh

   mibcorpus --manifest=corpus.json \
     --output-directory=output \
     --emit=core-db --emit=json:build/scratch-jsondoc

``core-db`` is not in the default artifact layout: building it costs a pass
nothing else needs, so it is asked for by name. It is a projection of the
jsondoc tree, exactly as the two indexes are, so a build asking for it has to
emit ``json`` as well -- to a scratch path outside the corpus when the corpus
is not meant to carry the JSON.
