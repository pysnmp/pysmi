.. _mibcorpus:

The *mibcorpus* tool
====================

.. toctree::
   :maxdepth: 2

``mibdump`` compiles the modules it is given. Building a *corpus* is a
different shape of job: it takes a declared set of source namespaces -- a
vendor's directory of ASN.1 files, the standard modules pysmi bundles -- and
produces every artifact the corpus publishes, with the property that two runs
over the same inputs produce the same bytes.

``mibcorpus`` is that job, and :py:mod:`pysmi.corpus` is the library beneath
it.

.. code-block:: text

   $ mibcorpus --help
   Synopsis:
     Build a MIB corpus from a declared set of source namespaces
   Documentation:
     https://github.com/pysnmp/pysmi
   Usage: mibcorpus [--help]
         [--version]
         [--quiet]
         [--debug=<all|borrower|codegen|compiler|grammar|lexer|parser|reader|searcher|writer>]
         [--manifest=<FILE>]
         [--namespace=<TIER>:<NAME>:<SOURCE>]
         [--output-directory=<DIRECTORY>]
         [--frozen-index=<FILE>]
         [--emit=<ARTIFACT>[:<PATH>]]
         [--corpus-version=<VERSION>]
         [--corpus-id=<NAME>]
         [--no-bundled-mibs]
         [--fail-on-errors]


The input set
-------------

A corpus is built from *source namespaces*, declared in a manifest:

.. code-block:: json

   {
     "version": 1,
     "namespaces": [
       {"name": "standard", "source": "package:pysmi.mibs.asn1",
        "tier": "standard"},
       {"include": "src/vendor/*", "tier": "vendor"}
     ]
   }

Each namespace has a name, a source and a tier. The source is a directory, or
``package:`` and a dotted package name for the modules a Python package ships.
An ``include`` entry stands for every directory matching a glob, expanded in
sorted order, so a corpus of three hundred vendor directories does not have to
list them by hand and still gets them in one order. Paths are relative to the
manifest's own directory.

The tier is one of ``standard``, ``draft`` and ``vendor``, and it is what tells
the OID index that a standard module owns an arc a vendor module also defines.
It is **declared** rather than inferred from where a file sits, because a tier
is a statement about a source, and the source is what the manifest names.

A namespace may also declare ``"publish": false``. It is then a *resolution
source*: it supplies what the published modules import and contributes nothing
to the output. Nothing of its is staged, compiled or indexed, and it is stubbed
in every output format so that it cannot arrive as a dependency either. On the
command line that is ``--resolve-namespace`` rather than ``--namespace``.

The order matters. Two namespaces can hold a module of the same name and
exactly one copy of it can be published; the newest MODULE-IDENTITY revision
wins and source order breaks the tie, which is the rule
:py:meth:`~pysmi.compiler.MibCompiler.compile` documents and applies.


What it produces
----------------

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Artifact
     - What it is
   * - ``asn1/``
     - One file per module name, flat, named for the module. Staged from
       what the compile resolved, so the ASN.1 beside a compiled module is
       the text it was compiled from. Its naming is a contract -- see
       :ref:`asn1-naming`.
   * - ``notexts/``
     - pysnmp modules without DESCRIPTION and the other texts.
   * - ``texts/``
     - pysnmp modules with them, in their original layout.
   * - ``json/``
     - jsondoc documents.
   * - ``index-v2.csv``
     - The ranked OID index: for every OID, the one module that owns it.
   * - ``index.csv``
     - The legacy OID index, which replays ``--frozen-index`` so that
       consumers keying on the module an OID resolves to keep the answers
       they already have.
   * - ``standard.txt``
     - The modules from every ``standard`` namespace, less the ``RFC*`` and
       ``SNMPv2*`` prefixes the published file has never carried.
   * - ``report.json``
     - What the build did: the failure inventory, the modules more than one
       namespace holds, the node counts, and how long each phase took.

One artifact is **not** in that layout and has to be asked for by name:

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Artifact
     - What it is
   * - ``core.db``
     - The corpus database: every node the corpus defines, keyed for lookup
       by OID and by name, and ordered for GETNEXT. See
       :doc:`/corpus-schema`. Building it costs a pass nothing else needs,
       which is why it is opt-in rather than part of the default layout.

``--emit`` narrows this to the artifacts named, so a build can ask for just the
index or just the JSON.

``core.db`` and the two indexes are projections of the jsondoc tree, which is a
dependency of pysmi's own rather than of the caller's: a build asking for one
of them without asking for ``json`` gets a tree staged in a temporary directory
and removed when the build ends, raise or return. The corpus carries what was
named and nothing else.

.. code-block:: sh

   mibcorpus --manifest=corpus.json --output-directory=output \
       --emit=asn1 --emit=index-v2 --emit=core-db

Emit ``json`` to keep the tree, and give it a path of its own to say where it
goes.

Every artifact but ``report.json`` is byte-reproducible. The report is the
build's log and records elapsed time.


.. _asn1-naming:

How the ASN.1 tree is named
---------------------------

The names in ``asn1/`` are a contract rather than an implementation detail.
pysnmp resolves a dependency by substituting a module name into a source
template, and splunk-connect-for-snmp runs that path in production:
``addMibCompiler()`` against ``https://.../asn1/@mib@``, compiling ASN.1 per
MIB on demand. There is no directory listing and no second guess -- the name
is the whole of the request.

So:

* **A file is named for the module it defines**, taken from the
  ``DEFINITIONS ::= BEGIN`` header, not from the file it was read from. A
  vendor shipping ``TEST-TC-MIB`` in ``tc.mib`` publishes it as
  ``asn1/TEST-TC-MIB``.
* **The name is the module's own spelling**, not a case variant of it or of
  the source file's.
* **There is no extension.** ``@mib@`` is replaced with a bare module name,
  so anything appended makes the file unreachable.
* **One name per module.** A source file defining two modules is published
  under both names, since either one may be what a consumer asks for.
* **A module the corpus only resolves against is not there at all.** A
  namespace declared ``"publish": false`` reaches no output tree.

A module that fails to compile is still staged: the tree is what the corpus
publishes its sources as, and a consumer asking for it should get the text
rather than a 404. It is absent from the indexes and from ``core.db``, which
are projections of what compiled. For a corpus that compiles clean the module
sets of all three agree.

``tests/test_corpus_asn1_contract.py`` pins this, and the consumer layer
compiles a module out of an emitted tree over the ``@mib@`` template itself.


Why it is deterministic
-----------------------

The shell pipeline this replaces -- ``scripts/vendor.sh`` in pysnmp/mibs --
ran ``mibdump`` once per vendor directory under GNU ``parallel``, each
invocation reading ``output/asn1`` as a dependency source while every other
invocation copied its own sources into that same directory on the way out.
Four properties made its output depend on something other than its input, and
this tool answers each of them (pysnmp/pysmi#182):

**Nothing is written into a directory that is read.** Every namespace is a
source for the whole build, so a module resolves the same way whatever order
the namespaces are processed in, and the driver refuses to start if an output
directory is, contains or is contained by a source. Cross-namespace resolution
was the sharp end of this: fifteen of the modules the old build could only
resolve through ``output/asn1`` live in a *different* vendor directory from
the one importing them, so whether they resolved at all depended on which
parallel job finished first.

**Nothing is fetched.** Sources are local directories and packages, and no
borrowers are configured. The old build passed
``--mib-source=https://pysnmp.github.io/mibs/asn1/@mib@``, resolving missing
dependencies from its own last publish -- so the corpus was not reproducible
from the repository alone, and a bad publish perpetuated itself. Measured
against the published corpus, dropping that source costs nothing: everything
it serves that the build uses is already in the tree.

**One error policy.** Every output format compiles the same module set and
keeps going past a defective module, and the run reports what failed. The old
build set ``--ignore-errors`` on the jsondoc pass alone, and
``MibCompiler.compile()`` was all-or-nothing at the time, so a single
defective module removed its entire namespace from ``notexts/`` and ``texts/``
while ``json/`` kept it: 41% of the vendor corpus was published with JSON
output and no Python. A corpus of MIBs nobody controls will always carry some
that do not compile; what it owes is an inventory of them, which
``report.json`` is.

**The index is decided by rule.** :py:mod:`pysmi.corpus.index` ranks the
modules defining an OID and takes the best one, term by term:

1. a module that still defines something current, over one whose objects are
   all obsolete;
2. tier -- standard, then Internet-Draft, then vendor;
3. the module that *registers* an arc with its MODULE-IDENTITY, over one that
   merely names it with an OBJECT-IDENTITY;
4. the newest MODULE-IDENTITY revision, read as a date by
   ``normalise_revision`` -- so a stamp that is not one,
   like ``HPR-MIB``'s ``970514000000Z``, is refused rather than sorting above
   every date there will ever be;
5. the later RFC, then the module name, which settles the SMI root arcs and
   makes the rule total.

:py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_index` is unchanged and
still records the complete fact -- every module defining a given OID. This is
the projection of it a consumer that has to load exactly one module needs.


Two corpora from one source set
-------------------------------

``"publish": false`` is what lets one set of sources produce two corpora that
differ in what they carry rather than in how they were built.

**The full corpus** carries the standard modules, because its consumers fetch
them from it: splunk-connect-for-snmp resolves ``asn1/@mib@`` against the
published tree for every module it meets, standard ones included. This is what
pysnmp/mibs serves today and what must keep working unchanged.

.. code-block:: json

   {"version": 1, "namespaces": [
     {"name": "standard", "source": "package:pysmi.mibs.asn1", "tier": "standard"},
     {"include": "src/vendor/*", "tier": "vendor"}]}

**The compact corpus** is the same source set with the standard namespace
declared unpublished. It carries only what a runtime that already has the
standard modules does not have -- pysmi bundles 210 of them and its wheel ships
their compiled form, so restating them costs size and says nothing new:

.. code-block:: json

   {"version": 1, "namespaces": [
     {"name": "standard", "source": "package:pysmi.mibs.asn1", "tier": "standard",
      "publish": false},
     {"include": "src/vendor/*", "tier": "vendor"}]}

Leaving the standard namespace out altogether is **not** the same thing: every
vendor module that imports ``SNMPv2-SMI`` would fail to compile. The difference
between the two manifests is what is carried, not what is resolved, which is
why the compact corpus is a subset of the full one and not a second rendering
of it -- each module it carries is byte-identical to the same module in the
full corpus, and its index covers exactly the modules it carries, so a runtime
can merge it with whatever it already knows about the standard tree.

A build for the compact corpus normally asks for a subset of the artifacts too,
since ``standard.txt`` and the frozen legacy index are compatibility surfaces
of the published one:

.. code-block:: console

   $ mibcorpus --manifest=corpus-compact.json --output-directory=compact \
       --emit=asn1 --emit=notexts --emit=texts --emit=json \
       --emit=index-v2 --emit=report

Packaging is the caller's: the driver writes a directory, and what a release
does with it -- an archive, a container image built from ``scratch`` for a
runtime to mount -- belongs to the repository publishing it, not to the
compiler driver. What the driver owes such a consumer is that the directory is
the same bytes every time, which is the property the tests above pin.


One driver, both corpora
------------------------

pysmi's own wheel is built with this driver. ``hatch_build.py`` compiles the
210 bundled ASN.1 modules into ``pysmi/mibs/pysnmp/`` while the wheel is
built, and it does that by running :py:class:`~pysmi.corpus.driver.CorpusDriver`
over a corpus of one namespace -- the bundle -- rather than by keeping a
compile loop of its own. A difference between how pysmi builds the base layer
and how pysnmp/mibs builds on top of it would be a difference nobody chose.

The one thing the wheel configures differently is the stub list. A corpus
published beside pysnmp does not restate what pysnmp already implements, so
the default is ``mibdump``'s: the base MIBs. The wheel *is* that base layer,
and only three of those modules genuinely cannot be generated -- the ones the
generator emits an unconditional import *from*, which would become an import
from itself. The other 11 generate perfectly well and consumers want them
(pysnmp/pysmi#196), so the wheel passes the narrower list through the
``stubs`` argument.


Compatibility
-------------

``--frozen-index`` is what keeps a published index answering what it has
always answered. The legacy index is not regenerated: it replays the snapshot,
drops rows naming a module the corpus no longer carries, and adds OIDs the
snapshot never had. Corrections land in ``index-v2.csv``.
