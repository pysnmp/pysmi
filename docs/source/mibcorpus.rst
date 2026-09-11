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


What the corpus is
------------------

A manifest also says **which artifacts** the corpus carries and **what must be
true** of the result. Without those two keys the definition of a distribution
is split between a JSON file pysmi reads and a build script pysmi has never
seen, and a second publisher reproducing the corpus starts by copying the
build script -- which means copying decisions that were never theirs.

.. code-block:: json

   {
     "version": 1,
     "emit": ["asn1", "index-v2", "report"],
     "expect": {
       "modules": {"min": 8000},
       "failures": {"max": 12},
       "namespaces-present": ["iana", "ietf"]
     },
     "namespaces": [
       {"include": "src/vendor/*", "tier": "vendor"}
     ]
   }

``emit`` takes the same artifact names ``--emit`` does, a path of its own
included -- ``"json:build/jsondoc"``. ``--emit`` on the command line overrides
it, as a flag overrides a file. With it declared,
``mibcorpus --manifest=M --output-directory=D`` is the whole build, and the
reason a corpus carries what it carries sits next to the set itself.

``expect`` is checked after the build, against the same numbers
``report.json`` records:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Expectation
     - What it bounds
   * - ``modules``
     - How many modules the corpus publishes, counted once however many
       namespaces hold one. Independent of the emit set.
   * - ``failures``
     - How many of those failed to compile, counted once however many
       output formats they failed in.
   * - ``namespaces-present``
     - Namespaces that must be in the build and published.

``modules`` and ``failures`` take ``min``, ``max`` or both.
An expectation missed prints the field, the bound and the actual value, and
exits 65. An expectation the build does not report -- a misspelling among them
-- is refused when the manifest is read, since one silently ignored leaves the
publisher believing a check is being made that never is.


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
     - jsondoc documents. Without DESCRIPTION and the other texts unless
       the build asks -- see :ref:`json-texts`.
   * - ``index-v2.csv``
     - The ranked OID index: for every OID, the one module that owns it.
   * - ``index.csv``
     - The legacy OID index, which replays ``--frozen-index`` so that
       consumers keying on the module an OID resolves to keep the answers
       they already have.
   * - ``standard.txt``
     - The modules from every ``standard`` namespace, less the ``RFC*`` and
       ``SNMPv2*`` prefixes the published file has never carried.
   * - ``closure.json``
     - Per module, the files a consumer needs in order to load it, and
       anything it needs that the corpus does not hold. See
       :ref:`import-closure`.
   * - ``entity.json``
     - Which enterprise arcs the corpus registers under, who the registry
       says holds each, and who to report a problem to. Asked for by name,
       and wants ``--oid-registry``. See :ref:`entity-index`.
   * - ``arcs.json``
     - What every arc the corpus reaches is called, and which authority says
       so. Asked for by name. See :ref:`arc-names`.
   * - ``report.json``
     - What the build did: the failure inventory, the modules more than one
       namespace holds, the node counts, which JSON implementation wrote the
       artifacts, and how long each phase took.

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

.. _corpus-json-encoding:

How the JSON is written
-----------------------

``json/`` and the JSON index are written compactly -- one line per document,
no space after a separator, UTF-8 written as itself rather than escaped. They
are generated trees that nobody reads by eye, and indenting them costs about
30% of the tree on disk: roughly 50 MB over a corpus the size of the one
pysnmp/mibs publishes. Gzipped the difference is about 8%, because gzip
already eats indentation, so this is a saving on a checkout, an image and a
Pages site rather than on bandwidth.

``report.json`` is not written that way and stays indented. It is the build's
log, read by a person looking at a failed build.

A faster JSON implementation is used when one is installed:

.. code-block:: sh

   pip install 'pysnmp-pysmi[fast]'

That pulls in orjson; msgspec is taken instead if a caller already has it.
Either is worth about 4% of a build, because SMI parsing dominates everything
else, which is why it is an extra rather than a dependency -- 4% does not buy
a wheel with a compiled extension in it for everyone.

**What is installed does not change a published byte.** The standard library
is the reference, the faster encoders are used only where they agree with it,
and ``tests/test_jsonio.py`` asserts that agreement over every document the
bundled corpus produces rather than trusting that it holds. A build with the
extra and one without are the same corpus. ``report.json`` records which
implementation ran, as ``json``, so two builds being compared can each say
what they resolved.


.. _import-closure:

The files a module needs
------------------------

``core.db``'s ``import`` table holds the direct edges -- this module imports
that symbol from that module. The question consumers actually arrive with is
the closure: *which files do I need in order to load this module?*
``closure.json`` answers it per module:

.. code-block:: json

   {
     "meta": {"schema": 1, "modules": 5347, "incomplete": 0},
     "closure": {
       "IF-MIB": {
         "files": ["IANAifType-MIB", "IF-MIB", "SNMPv2-CONF",
                   "SNMPv2-MIB", "SNMPv2-SMI", "SNMPv2-TC"],
         "missing": []
       }
     }
   }

(Re-indented to be read; the file is written on one line.)

The build resolves every one of those edges in order to compile, so having
each consumer re-walk a table to recover a fact the compiler established is
the pattern this exists to avoid. Three arrive with the question: a page
answering "the files you need", anyone packaging a subset -- an air-gapped
install, an image carrying only what one product needs -- and pysnmp,
deciding what to preload.

Two things the artifact settles rather than leaving to the caller:

* **A module is in its own closure.** ``IF-MIB`` needs six files and one of
  them is ``IF-MIB``. That makes the list directly usable as a file list,
  which is what most callers want.
* **A dependency the corpus does not hold is recorded, not dropped.** It goes
  in ``missing`` rather than quietly out of ``files``, so a caller can tell
  "this module needs nothing else" from "something it needs is not here". A
  module is listed however deep it was reached from: a hole anywhere below a
  module is a hole for that module, which still cannot be loaded. The build
  report counts them, as ``closure.incomplete``.

The names are module names, which are the names of the files in ``asn1/`` --
see :ref:`asn1-naming` -- so a caller holding a closure holds the file list
and can build the URLs itself.

.. _json-texts:

Prose in the JSON
-----------------

A published jsondoc carries names, OIDs, syntax, access and status, and no
prose. `IF-MIB.json <https://pysnmp.github.io/mibs/json/IF-MIB.json>`_ has no
description on ``ifOperStatus``, though the module's text describes all seven
of its enumerated states. Measured over a 300-file sample,
``DESCRIPTION``, ``REFERENCE`` and ``CONTACT-INFO`` are **38% of the text of a
MIB** -- a large part of the module the JSON rendering omits, and a consumer
that wants it has to fetch and parse the ASN.1, which means a second SMI parser
for prose the compiler already read.

``json-texts`` is a jsondoc tree with the texts in it:

.. code-block:: sh

   mibcorpus --manifest=corpus.json --output-directory=output --emit=json-texts

That writes ``json/`` -- one tree, carrying the prose, at one compile pass.

It is a destination of its own rather than a flag on ``json``, so a build may
also have both:

.. code-block:: sh

   mibcorpus --manifest=corpus.json --output-directory=output \
       --emit=json --emit=json-texts:build/full

which publishes the lean tree and keeps a complete one for something that needs
the prose -- a site generator rendering descriptions into its pages, say --
without the published artifact growing. That is two passes, because it is two
trees. Naming both at one path is refused: the second pass would overwrite the
first, and which of them survived would depend on the order the emit list was
read in.

The texts cost roughly 70% more on disk: over pysnmp/mibs' corpus ``json/``
goes from about 170 MB to about 290 MB. That is a decision for the build, which
is the argument for asking rather than assuming, and ``json-texts`` is not in
the default layout.

What ``genTexts`` gates is more than descriptions:
``JsonCodeGen.gen_module_identity`` puts ``organization`` and ``contactinfo``
behind the same switch. ``CISCO-ENTITY-ALARM-MIB`` carries a full
``CONTACT-INFO`` block in its ASN.1 -- Cisco Systems, Customer Service, a
postal address, a phone number and ``cs-snmp@cisco.com`` -- and none of it
reaches the published JSON. Over a 500-module sample, 90% of modules carry
``ORGANIZATION`` and ``CONTACT-INFO``, and 66% of those carry an email. That is
the publisher's own statement of where to report a problem, and it is what
:doc:`/mibcorpus` cannot show a reader until this is turned on.

``keepTextsLayout`` is not turned on with it. The two are separate for the
pysnmp destinations and stay separate here: a JSON consumer generally wants the
text normalised rather than the publisher's line breaks preserved.

.. _entity-index:

Who registered an arc
---------------------

A corpus knows that ``CISCO-ENTITY-ALARM-MIB`` registers under
``1.3.6.1.4.1.9``. It does not know that ``1.3.6.1.4.1.9`` is Cisco: nothing in
the MIB text says so in a form anything can rely on, and the directory a file
sits in is a filing convention rather than a registration. Over pysnmp/mibs the
two disagree in practice -- the ``aironet`` directory holds Cisco modules, and
``src/vendor/cisco/ALTIGA-*`` registers under Altiga's arc.

The registration is a published fact. ``--oid-registry`` supplies it and
``--emit=entity`` writes the projection:

.. code-block:: sh

   mibcorpus --manifest=corpus.json --output-directory=output \
       --emit=entity --oid-registry=pen-snapshot.csv

.. code-block:: json

   {
     "meta": {"schema": 1, "arcs": 351, "named": 350, "unregistered": 1},
     "entity": {
       "1.3.6.1.4.1.9": {
         "number": 9,
         "organization": "Cisco Systems, Inc.",
         "modules": ["CISCO-AAA-CLIENT-MIB", "..."],
         "contacts": [
           {"source": "module", "organization": "Cisco Systems, Inc.",
            "contact": "Cisco Systems\n Customer Service\n ...",
            "email": "", "module": "CISCO-ENTITY-ALARM-MIB", "authority": ""},
           {"source": "registry", "organization": "Cisco Systems, Inc.",
            "contact": "Dave J", "email": "davej&cisco.com", "module": "",
            "authority": "https://www.iana.org/assignments/enterprise-numbers#9"}
         ]
       }
     }
   }

Measured over pysnmp/mibs: 351 distinct enterprise arcs, 350 of them named by
the registry, against 290 vendor directories. Those two numbers are the
argument for driving navigation from the registry rather than from the tree.

**An arc the registry does not name is reported as unregistered, never guessed
at.** pysnmp/mibs has exactly one, ``1.3.6.1.4.1.1004849``, above anything IANA
has allocated. The build report counts them, as ``entity.unregistered``.

The index groups by **arc**, not by company. The registry maps arcs to
registrants and a company can hold several: Cisco modules sit under
``1.3.6.1.4.1.9`` and, from the Altiga acquisition, under
``1.3.6.1.4.1.3076``, which IANA still lists as "Altiga Networks, Inc.".
Nothing in the registry models an acquisition and PySMI does not infer one.

``entity.json`` is not in the default layout: it is only worth having with a
registry to name its arcs, and that is an input the caller supplies.

Owner contact
~~~~~~~~~~~~~

Each arc carries who to report a problem to, best source first, each naming its
source so a reader can weigh a vendor's current support address against an
undated registration:

1. **The module's own ``CONTACT-INFO``** -- a corporate block with a role
   mailbox, and the publisher's current statement of where to report a
   problem. It reaches the corpus only when the build carries texts, since
   ``JsonCodeGen`` gates ``organization`` and ``contactinfo`` behind the same
   switch as ``description`` -- see pysnmp/pysmi#277. Where an arc has
   many modules, the one with the newest ``LAST-UPDATED`` speaks for it, with
   the module name breaking a tie so that two builds agree.

2. **The IANA registration** -- registrant, contact name, contact email.
   Second because it is undated and often stale, and carrying the authority
   link, because a correction to a registration belongs at IANA.

Each is rendered as its source publishes it. An email from the registry is
``davej&cisco.com`` because that is what the registry says; a module's block is
reproduced whole rather than picked apart for an address, since a block holds a
company, a postal address, a phone number and a mailbox and choosing between
them is not the build's decision.

Remediation is precedence rather than a suppression list. A registrant who does
not want an undated personal registration standing as the contact for their arc
publishes a module carrying current ``ORGANIZATION`` and ``CONTACT-INFO``, and
source 1 displaces source 2 on the next build.

The registry file
~~~~~~~~~~~~~~~~~

**Taken as an input. Never bundled, never fetched.** A corpus build resolves
nothing over the network -- a build with the network unplugged produces the
same corpus as one without -- and a registry that changes daily, fetched at
build time, would end that. 5.1 MB that changes daily is also not a thing to
vendor into a compiler.

``--oid-registry`` is repeatable and reads two registries: the Private
Enterprise Numbers registry, in either the published four-line-record format or
a reduced CSV, and IANA's ``smi-numbers`` XML (see :ref:`arc-names`). Which one
a file is comes from its content rather than from its name, since a snapshot a
repository commits is called whatever that repository calls it. A repository that keeps a snapshot reduces a download once:

.. code-block:: sh

   python -m pysmi.registry enterprise-numbers.txt > pen-snapshot.csv

The reduced form keeps the whole record by default, and ``--fields`` narrows
it. Which fields leave IANA's copy is the committing repository's decision
rather than PySMI's, so it is an argument rather than a hard-coded projection.
Nothing is normalised: the output is a rendering of IANA's record rather than a
corrected version of it.

.. _arc-names:

What an arc is called
---------------------

The OID index ranks modules to decide which one owns an arc. The rule is total
and works for arcs a module actually registers; for the arcs *above* those it
has nothing good to choose from, so it picks whichever module happened to
mention the arc on its way somewhere else. Measured against pysnmp/mibs:

===================  ===========================  =========================
arc                  is                           attributed to
===================  ===========================  =========================
``1.3``              ``identified-organization``  ``OCCAM-ETHERLIKE-MIB``
``1.3.6``            ``dod``                      ``OCCAM-ETHERLIKE-MIB``
``1.3.6.1.6``        ``snmpv2``                   ``RAPID-CITY``
``1.3.6.1.6.3``      ``snmpModules``              ``RAPID-CITY``
``1.2``              ISO member-body              ``IEEE802dot11-MIB``
``0.0``              ITU-T recommendation         ``DLSW-MIB``
===================  ===========================  =========================

A tree that says ``snmpModules`` belongs to a Nortel enterprise MIB is wrong in
a way that matters, and no ranking over MIB text can fix it, because the fact
is not in the MIB text. Twenty-five arcs are claimed by nothing at all, and a
tree still has to render a path through them -- ``1.3.6.1.4.1.9`` among them,
since no module registers Cisco's bare arc, only what hangs beneath it.

``--emit=arcs`` writes the answer, from the registries the build was given:

.. code-block:: sh

   mibcorpus --manifest=corpus.json --output-directory=output --emit=arcs \
       --oid-registry=smi-numbers.xml --oid-registry=pen-snapshot.csv

.. code-block:: json

   {
     "meta": {"schema": 1, "arcs": 6694,
              "by-source": {"module": 5900, "registry": 700,
                            "standard": 15, "unnamed": 79}},
     "arc": {
       "1.3.6.1.6.3": {"name": "snmpModules", "source": "registry",
                       "reference": "https://www.iana.org/assignments/smi-numbers"},
       "1.0.8802": {"name": "iso8802", "source": "standard",
                    "reference": "ISO-IEC 8802"}
     }
   }

Every name says which kind of fact it is
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``source`` is rendered, because an IANA registration, a cited standard and a
name read off whichever MIB mentioned an arc are three different things and a
reader has to be able to tell them apart. Strongest first:

``registry``
    IANA. ``smi-numbers`` names the ``1.3.6.1`` subtree -- and, through the
    dotted names in its own registry descriptions, ``1 iso`` down to
    ``1.3.6.1 internet``, which nothing else in the file names. The Private
    Enterprise Numbers registry names a bare enterprise arc.

``standard``
    A standard, cited. ITU-T's OID registry does not answer, and IEEE
    publishes landing pages and PDFs, so there is no feed for ``0``, ``1.0``,
    ``1.2``, ``1.3.111`` or ``1.0.8802`` -- the chains IEEE registers its 802
    MIBs under, and ``LLDP-MIB`` sits at ``1.0.8802.1.1.2``. Those are defined
    in ITU-T X.660 and ISO/IEC 9834-1 and have not changed in decades, so
    PySMI carries a small table with a reference per entry. A cited name is
    not a registration and is labelled as what it is.

``module``
    A module's own descriptor, which is what the index has always used. Still
    here, still useful, and now labelled rather than presented as though it
    were an authority's answer.

**An arc nothing names says so**, with an empty name rather than a borrowed
one. The build report counts them.

When a committed PEN snapshot has gone stale
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A repository that commits the whole Private Enterprise Numbers registry
commits 66,807 registrants and re-diffs all of them every time IANA moves,
which is daily. Committing only the registrants its own arcs use is a far
smaller file and a far smaller monthly diff, at the cost of going stale: the
first module the corpus gains under a newer enterprise arc has no registrant
in the snapshot, and that registrant's page renders nameless.

Nothing about the build would otherwise say so -- the arc is still in the
index, still reachable, still rendered, just blank. So the build says it:

.. code-block:: text

   WARNING  3 enterprise arc(s) no PEN registrant names: 62373, 99999, 100001

and ``report.json`` carries the count as ``arcs.unregistered-enterprises``, so
a build nobody watched can still be asked. ``arcs.json`` carries every one of
them, since a log line is not the artifact.

It is a **warning and never a failure**. An arc can be registered to nobody,
and IANA's registry has gaps of its own. An arc a module names is still
counted: the module's own descriptor says what the vendor calls its subtree,
not who registered it, and it is the registrant a refresh would supply.

:py:func:`pysmi.corpus.arcs.unregistered` is the same answer as data, for a
build that wants to act on it.

What is in the inventory
~~~~~~~~~~~~~~~~~~~~~~~~

The arc set comes from the OID index and every prefix of it -- the
registration tree -- rather than from every OID a module defines. Over
pysnmp/mibs that is about 6,700 arcs instead of 95,000; the difference is
objects, and an object's arc is a thing inside a module rather than a node
anybody navigates to.

It is not filtered to one subtree. 97.0% of pysnmp/mibs' index rows sit under
``1.3.6.1.4.1`` and 2.3% under ``1.3.6.1.2.1``, but IEEE publishes its 802.1
MIBs under ``1.3.111.2.802.1`` and ``LLDP-MIB`` registers under
``1.0.8802.1.1.2``. A ``1.3.6.1`` filter drops both, and LLDP is among the most
widely polled MIBs there is. Arc depth runs from 2 to 20.

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
* **Only what compiled is there.** A module the build could not compile is
  left out, and so is anything that imports it. Serving its ASN.1 buys a
  consumer nothing -- it fetches the text, compiles it with the same pysmi
  and fails where this build failed, one round trip later. ``asn1/``,
  ``standard.txt``, both indexes and ``core.db`` therefore carry one module
  set rather than several. What was dropped is named in ``report.json``,
  with the error that dropped it.

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
