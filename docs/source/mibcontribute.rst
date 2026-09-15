.. _mibcontribute:

The *mibcontribute* tool
========================

.. toctree::
   :maxdepth: 2

A MIB distribution is only as complete as what people send it, and the people
holding the modules it is missing are rarely the people who open pull
requests. They have a directory: what a device shipped, what a vendor's
support portal gave them, what a collection they cloned holds. Somewhere in it
are modules the distribution publishes an older copy of, and modules it has
never carried, and nothing tells anybody which.

The *mibcontribute* tool answers that by asking. Point it at the directory:

.. code-block:: bash

   $ mibcontribute ./my-mibs
   2 module(s) worth offering: 1 the distribution carries an older copy of,
   1 it does not carry.

       ACME-CHASSIS-MIB      2024-03-11  against 2015-05-01
       ACME-POWER-MIB        2024-03-11  against not carried

   Wrote mib-contribution/issue.md

Nothing is sent by that run. It reads every module in the directory, asks the
distribution what it publishes for each, and writes the result as a GitHub
issue you can read before anybody else does.

What it compares
----------------

Which of two copies of a module wins is not a judgement this tool makes. It is
:py:func:`pysmi.compiler.rank_by_revision`, the rule a corpus is built with:
the newest MODULE-IDENTITY revision wins, and configured order breaks a tie.
Asking the same function the same question is what makes a module reported here
a module a build would actually prefer.

Four outcomes, of which two are worth sending:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - what the comparison found
     - reported
   * - the published copy is newer
     - no. The distribution is current for that module
   * - the published copy is the same text
     - no. There is nothing to offer
   * - your copy is newer
     - **yes**, as a better copy
   * - no source has a copy
     - **yes**, as a module it does not carry

A copy that wins on source order rather than on revision is not reported as
better unless ``--include-differing`` asks for it: two copies of one name are
as often two different modules that reuse a name as two revisions of one, and
no rule can tell them apart.

A module is offered under the name it declares, not the name of the file it
was found in, since that is the name the distribution would publish it as. A
file that declares no module at all -- a README, a licence, a tarball somebody
left in the directory -- is passed over and named in the log.

What it compares against
------------------------

Left alone, three sources in order:

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - source
     - why it is there
   * - the modules PySMI bundles
     - the standard MIBs the distribution publishes, each pinned to the RFC or
       IANA registry that publishes it. Local, so no request and no network
   * - ``data.mibsdepot.com``
     - the published corpus, one request per module
   * - ``pysnmp.github.io/mibs``
     - the same corpus again, as an availability fallback

The first source holding a module answers for it, which is the rule a compile
follows. A module none of them has is a module the distribution does not carry.

``--corpus`` names a different distribution: a directory, a ``.zip``, or a URL
with ``@mib@`` where the module name goes.

.. code-block:: bash

   $ mibcontribute --corpus=./asn1 ./my-mibs
   $ mibcontribute --corpus=./mibs-asn1.zip ./my-mibs

A scan of a large collection should use a local copy. A release archive
unpacked, or an OCI image mounted, is a directory like any other.

What ``--corpus`` may not be is anything that is not a distribution, and that
is checked before a single module is read. A path that is not there, a
directory holding no files, a file that is not an archive, and a URL with no
``@mib@`` in it are each refused by name. The failure this prevents is quiet:
every lookup against such a source misses, every module reads as one the
distribution does not carry, and the result is an offer of somebody's whole
collection arrived at without a single error.

Filing it
---------

.. list-table::
   :header-rows: 1
   :widths: 20 50 30

   * - ``--submit``
     - what happens
     - what it needs
   * - ``none``
     - the files are written and nothing is sent. The default
     - nothing
   * - ``url``
     - a GitHub issue URL with the report already in it is printed, for you to
       read and post
     - a GitHub account in your browser
   * - ``gh``
     - the issue is created by the GitHub CLI
     - ``gh``, already authenticated

GitHub accepts no issue anonymously, and this tool cannot file one on your
behalf. ``--submit=url`` is the closest thing to it, and the difference is
worth stating exactly: no credential is read, stored or sent by the tool, the
report travels as a link you inspect first, and the issue is posted by your
browser under whatever account that browser is signed in as.

.. code-block:: bash

   $ mibcontribute ./my-mibs --submit=url
   $ mibcontribute ./my-mibs --submit=gh --label=mib-contribution

An issue body holds 65,536 characters, which is smaller than some single MIBs.
The body carries as many modules in full as it holds, smallest first, and names
the rest as being in ``mib-contribution/contribution.zip``, which the GitHub web
form takes as a drag and drop. ``--submit=gh --gist`` uploads them as a secret
gist and links that instead.

``--per-module`` writes one issue per module rather than one for all of them,
which is the shape to use when the modules are unrelated: one module per issue
is one module per pull request.

What is already reported
------------------------

Before submitting anything, the tracker is searched for the modules about to be
offered, and the ones an issue or pull request is already open for are left
out. A closed issue does not stop a report, because it was closed for a reason
nothing here can read; the module is offered again with the old issue named
beside it.

One search finds every issue this tool has filed, matched on the marker each of
them carries. An offer of eight modules or fewer spends a search per module as
well, which is what finds the issue somebody opened by hand. The search runs
through ``gh`` where that is installed and over the public API otherwise, which
is rate limited; ``GITHUB_TOKEN`` is used when it is set.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - flag
     - effect
   * - ``--allow-duplicates``
     - offer a module even where an issue for it is open
   * - ``--require-duplicate-check``
     - submit nothing if the tracker cannot be searched

A search that cannot run does not stop a person from filing: the tool says so
and goes on. An unattended run should invert that with
``--require-duplicate-check``, because filing duplicates every time is worse
than filing nothing until the search works again.

What reaches the issue
----------------------

The MIB text, the two revisions, the two digests, and the module names. Not the
paths they were read from: those name the machine that ran the scan, and an
issue is public, so every file is named relative to the directory that was
scanned.

Every issue carries a ``json`` block holding the same findings as data, so that
whoever picks it up -- a maintainer or an agent -- has the module name, both
revisions and the digest of the text to carry, without parsing it back out of
prose.
