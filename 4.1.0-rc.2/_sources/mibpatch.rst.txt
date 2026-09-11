
.. _mibpatch:

The *mibpatch* tool
===================

.. toctree::
   :maxdepth: 2

Plenty of published MIBs use an SMIv2 base symbol without naming it in
IMPORTS, which :rfc:`2578` Section 3.2 does not allow. PySMI compiles them
anyway: where the omitted symbol is one a base module exports, the import that
was meant is not in doubt, so the compiler supplies it and names what it
supplied on the "Repaired MIBs" line of the report. See
:ref:`repairing-imports` for that behaviour and the ``--strict-imports`` flag
that turns it off.

That repair lives in memory for the length of the run that made it. It suits a
consumer compiling somebody else's MIBs, and it suits nobody who *owns* a tree
of them: the same defect is rediscovered on every run, the correction is never
reviewed, and the only record it happened is a line in a report that scrolls
past.

The *mibpatch* tool makes the repair a file instead. It scans a source tree,
works out the same corrections the compiler would have made, and writes each
one out as a unified diff. Those diffs go into version control, where they can
be read before anything runs; ``--apply`` writes them into the MIBs themselves,
after which the tree compiles under ``mibdump --strict-imports`` and nothing is
repaired at runtime at all.

.. code-block:: bash

    $ mibpatch --help
    Synopsis:
    Write the repairs a tree of MIBs needs out as reviewable patches
    Documentation:
    https://github.com/pysnmp/pysmi

    Usage: mibpatch [--help]
        [--version]
        [--quiet]
        [--debug=<all|borrower|codegen|compiler|grammar|lexer|parser|reader|searcher|writer>]
        [--source=<DIRECTORY>]
        [--output-directory=<DIRECTORY>]
        [--check]
        [--apply]

Writing the repairs down
------------------------

Point the tool at a directory of ASN.1 modules. It reads every file in it,
parses each one, and writes ``<MODULE>.patch`` for every module it can repair:

.. code-block:: bash

    $ mibpatch --source ./mibs --output-directory ./mib-patches
    Read 214 modules, 209 needing nothing
    Repairs derived for 4 modules:
     ACME-CHASSIS-MIB (TruthValue from SNMPv2-TC)
     ACME-POWER-MIB (enterprises from SNMPv2-SMI)
     ...
    No repair could be derived for 1 modules, so a patch for each has to be written by hand:
     ACME-LEGACY-MIB (Bad grammar near token type STRING, value "x", line 84)

A patch is named after the module rather than the file it was found in, because
that is what it is keyed by everywhere else. The sources are not touched.

What can and cannot be derived
------------------------------

A repair can be generated only when the correction can be *decided*. A missing
base-SMI import can be: the symbol is undefined, unimported, and exactly one
base module exports it, so there is nothing to guess at.

A module that does not parse cannot be. There is no symbol table to reason
from, so the tool reports it and moves on -- that module needs a patch written
by hand. This is not a corner case: most of the twelve repairs PySMI carries
for its own bundle are that kind, fixing a module that fails to parse at all
(see :ref:`bundled-mib-patches`). The tool tells you which modules need a human
rather than guessing on their behalf.

Applying them
-------------

``--apply`` writes each repaired module back over its source, as well as
writing the diff:

.. code-block:: bash

    $ mibpatch --source ./mibs --output-directory ./mib-patches --apply
    $ mibdump --mib-source ./mibs --strict-imports ACME-CHASSIS-MIB
    Created/updated MIBs: ACME-CHASSIS-MIB
    ...
    Repaired MIBs:

The MIBs are now correct on disk, ``--strict-imports`` passes, and the
"Repaired MIBs" line is empty because there was nothing left to repair. That is
the state the tool exists to reach.

Applying is idempotent. A patch offered to text that already carries it is
recognised as such rather than applied twice, so running ``--apply`` over an
already-patched tree changes nothing. A module's line endings survive it: a
CRLF file goes back as CRLF, since repairing a module should not also reformat
the file it came from.

Keeping them honest
-------------------

``--check`` writes nothing and exits ``79`` when the patches on disk are not
the ones the tree needs:

.. code-block:: bash

    $ mibpatch --source ./mibs --output-directory ./mib-patches --check
    Patches on disk disagree with the sources in 2 ways:
     ACME-FAN-MIB: needs a patch, and none is written
     ACME-PSU-MIB: needs no patch, but one is written

That is a CI gate over a MIB tree. It catches a module that grew a new defect,
a patch that no longer describes the repair its module needs, and a patch left
behind by a module whose publisher fixed it.

It is right in both of the trees it might be run in. A tree holding published
text with patches beside it is stale when a patch is missing or wrong. A tree
that ``--apply`` has been run over holds the *repaired* text, so no repair is
derived for it any more -- but its patches are not surplus, they are already
applied, and ``--check`` tells those two apart rather than failing on the
second.

Scanning more than one tree
---------------------------

``--source`` is repeatable, and each directory is walked recursively:

.. code-block:: bash

    $ mibpatch --source ./vendor-mibs --source ./standard-mibs \
               --output-directory ./mib-patches --check

A patch for a module that no scanned source holds is left alone rather than
reported, since the tree being scanned is not necessarily the only one the
patch set covers.

Using a patch set from Python
-----------------------------

The diffs the tool writes are read back by
:py:meth:`pysmi.patches.PatchSet.from_directory`, which is how a caller applies
them without shelling out:

.. code-block:: python

   from pysmi.patches import APPLIED, PatchSet

   patches = PatchSet.from_directory("./mib-patches")

   text, status = patches.apply("ACME-CHASSIS-MIB", source_text)

   if status == APPLIED:
       ...

See :ref:`patches` for the rest of that interface.

How PySMI uses the same machinery
---------------------------------

PySMI repairs twelve of its own bundled modules exactly this way, except that
its diffs are applied when a distribution is built rather than to a checkout:
the repository holds each module as its publisher printed it, and the wheel
holds the repaired text. :ref:`bundled-mib-patches` describes that split and
why it is drawn where it is.
