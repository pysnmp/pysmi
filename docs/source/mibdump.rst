
The *mibdump* tool
==================

.. toctree::
   :maxdepth: 2

The *mibdump* tool is a command-line frontend to the PySMI library. This
tool can be used for automatic downloading and transforming SNMP MIB modules
into various formats.

.. code-block:: text

   $ mibdump --help
   Synopsis:
     SNMP SMI/MIB files conversion tool
   Documentation:
     https://github.com/pysnmp/pysmi
   Usage: mibdump [--help]
         [--version]
         [--quiet]
         [--debug=<all|borrower|codegen|compiler|grammar|lexer|parser|reader|searcher|writer>]
         [--mib-source=<URI>]
         [--mib-searcher=<PATH|PACKAGE>]
         [--mib-stub=<MIB-NAME>]
         [--mib-borrower=<PATH>]
         [--destination-format=<FORMAT>]
         [--destination-directory=<DIRECTORY>]
         [--emit=<FORMAT>[+texts][:<DIRECTORY>]]
         [--cache-directory=<DIRECTORY>]
         [--disable-fuzzy-source]
         [--no-dependencies]
         [--no-bundled-mibs]
         [--prefer-mib-source]
         [--no-base-mibs]
         [--no-python-compile]
         [--python-optimization-level]
         [--ignore-errors]
         [--build-index]
         [--rebuild]
         [--prune]
         [--dry-run]
         [--no-mib-writes]
         [--generate-mib-texts]
         [--keep-texts-layout]
         [--repair-imports]
         [--strict-sources]
         <MIB-NAME> [MIB-NAME [...]]]
   Where:
       URI      - file, zip, http, https schemes are supported.
                  Use @mib@ placeholder token in URI to refer directly to
                  the required MIB module when source does not support
                  directory listing (e.g. HTTP).
       FORMAT   - pysnmp, json, null
       --prune  - remove previously stored output whose source MIB no
                  longer exists in any configured source. Runs without
                  MIB-NAME arguments; deletes unless combined with
                  --dry-run.
       --no-bundled-mibs - do not use pysmi's own bundled copies of the
                  bundled base MIBs (SNMPv2-SMI and similar) at all. The
                  bundle is not a last-resort fallback: it is consulted
                  ahead of --mib-source, and where both have one of the
                  485 bundled modules the newer MODULE-IDENTITY
                  LAST-UPDATED supplies it -- so a --mib-source carrying a
                  newer revision still wins, and one carrying an older or
                  undated copy does not. Revisions are only compared across
                  sources read locally (file, zip); a remote --mib-source is
                  not fetched once a local source has the module, leaving
                  the bundled copy in place. Pass this to compile strictly
                  from --mib-source, so a base MIB that is missing there
                  fails loudly rather than resolving to the bundled copy.
       --prefer-mib-source - keep the bundled base MIBs, but let
                  --mib-source supply one wherever the revisions do not
                  decide: a module with no MODULE-IDENTITY to compare, or two
                  copies carrying the same one. The newest revision still
                  wins when every copy found has one. 51 of the 485 bundled
                  modules -- SNMPv2-SMI, SNMPv2-TC, SNMPv2-CONF and the other
                  SMI and RFC-numbered ones -- have no MODULE-IDENTITY at
                  all, so this is what decides them.
       --repair-imports - supply the import a MIB should have carried for
                  any SNMPv2-SMI, SNMPv2-TC or SNMPv2-CONF symbol it uses
                  without naming it in IMPORTS, which RFC 2578 Section 3.2
                  does not allow. Off by default, so a MIB broken this way
                  fails rather than being silently patched; what was
                  repaired is listed in the report.
       --strict-sources - fail a MIB that more than one source has a
                  different copy of. Without this, the precedence above picks
                  one and the copies passed over are named on the "MIBs found
                  in more than one source" line of the report.


When JSON destination format is requested, for each MIB module *mibdump*
will produce a JSON document containing all MIB objects. For example,
`IF-MIB <https://pysnmp.github.io/mibs/asn1IF-MIB>`_ module in JSON form
would look like:

.. code-block:: python

   {
      "ifMIB": {
          "name": "ifMIB",
          "oid": "1.3.6.1.2.1.31",
          "class": "moduleidentity",
          "revisions": [
            "2007-02-15 00:00",
            "1996-02-28 21:55",
            "1993-11-08 21:55"
          ]
        },

      ...
      "ifTestTable": {
        "name": "ifTestTable",
        "oid": "1.3.6.1.2.1.31.1.3",
        "class": "objecttype",
        "maxaccess": "not-accessible"
      },
      "ifTestEntry": {
        "name": "ifTestEntry",
        "oid": "1.3.6.1.2.1.31.1.3.1",
        "class": "objecttype",
        "maxaccess": "not-accessible",
        "augmentation": {
          "name": "ifTestEntry",
          "module": "IF-MIB",
          "object": "ifEntry"
        }
      },
      "ifTestId": {
        "name": "ifTestId",
        "oid": "1.3.6.1.2.1.31.1.3.1.1",
        "class": "objecttype",
        "syntax": {
          "type": "TestAndIncr",
          "class": "type"
        },
        "maxaccess": "read-write"
      },
      ...
   }

In general, JSON MIB captures all aspects of original (ASN.1) MIB contents
and layout. The snippet above is just an example, here is the complete
`IF-MIB.json <http://pysnmp.github.io/json/fulltext/IF-MIB.json>`_
file.

Specifying MIB source
---------------------

The --mib-source option can be given multiple times. Each instance of
--mib-source must specify a URL where ASN.1 MIB modules should be
looked up and downloaded from. At this moment three MIB sourcing
methods are supported -- a URL of any other scheme is rejected:

* Local files. This could be a top-level directory where MIB files are
  located. Subdirectories will be automatically traversed as well. 
  Example: file:///usr/share/snmp
* ZIP archives containing MIB files. Subdirectories and embedded ZIP
  archives will be automatically traversed.
  Example: zip://mymibs.zip
* HTTP/HTTPS. A fully specified URL where MIB module name is specified by
  a @mib@ placeholder. When specific MIB is looked up, PySMI will replace
  that placeholder with MIB module name it is looking for. 
  Example: `https://pysnmp.github.io/mibs/asn1/@mib@ <https://pysnmp.github.io/mibs/asn1>`_

When trying to fetch a MIB module, the *mibdump* tool will try each of
configured --mib-source transports in order of specification. For most
modules the first successful hit supplies the module; for the base MIBs
pysmi bundles a copy of, the newest revision does. `Which copy of a MIB gets
compiled`_ states the whole rule.

With no --mib-source given, *mibdump* searches:

* pysmi's own bundled base MIBs (unless --no-bundled-mibs is given)
* https://pysnmp.github.io/mibs/asn1/@mib@

Once a --mib-source option is given, that mirror is not searched and should be
given explicitly if it is still wanted. The bundled base MIBs are not a
--mib-source and are unaffected: they are searched whatever --mib-source says,
and only --no-bundled-mibs takes them out.

Naming a MIB to compile by path rather than by module name -- ``mibdump
/some/dir/MY-MIB`` -- also puts its directory ahead of every --mib-source, so
that the file named on the command line is the one that gets read.

Producing more than one format at once
--------------------------------------

``--emit=FORMAT[+texts][:DIRECTORY]`` writes one format to one directory and
may be given more than once, so a build that wants several formats reads its
sources once instead of once per format::

   mibdump --mib-source=file:///usr/share/snmp/mibs \
           --emit=pysnmp:./output/notexts \
           --emit=pysnmp+texts:./output/texts \
           --emit=json:./output/json \
           IF-MIB IP-MIB

Parsing is roughly three quarters of a compile pass, and every destination
parses the same ASN.1, so the run shares one parse cache across them. Measured
over a 269-module vendor directory, the three destinations above take 15.8s as
three invocations and 10.2s as one -- with byte-identical output, ``.pyc``
timestamps aside.

``+texts`` is the per-destination form of ``--generate-mib-texts``, which is
the whole-run spelling: one destination can carry DESCRIPTION and the others
not, which is exactly the pysnmp-with-and-without-texts pair a MIB site
publishes. The directory is optional, so ``--emit=json`` alone means what
``--destination-format=json`` alone means.

Refused rather than guessed at: ``--emit`` together with
``--destination-format`` or ``--destination-directory``, since those name the
same two things; and two destinations writing to one directory, where one
would overwrite the other.

Which copy of a MIB gets compiled
---------------------------------

pysmi ships its own copies of 485 base MIBs (SNMPv2-SMI and similar; see
:ref:`bundled-mibs`) and searches them alongside --mib-source, so more than one source can
have the same MIB module -- two --mib-source options, or a --mib-source and
the bundle. Which copy is used is decided by these rules, in order:

1. For a module pysmi bundles a copy of, the newest MODULE-IDENTITY
   LAST-UPDATED wins -- provided every copy found carries one.
2. Otherwise -- to break a tie between equal revisions, when any copy found
   carries no LAST-UPDATED, and for everything pysmi does not bundle --
   source order wins: pysmi's bundled copy first, then each --mib-source in
   the order it was given. --prefer-mib-source moves the bundled copy behind
   --mib-source for this rule, and for this rule only.

Rule 1 applies only to the modules pysmi bundles, each pinned to the RFC, IANA
registry, IEEE 802.1 file or archived Internet-Draft revision that publishes it
and re-checked against it. Two copies of one of those are
the same specification at two revisions, and the newer is simply better. Two
copies of a vendor MIB are not that -- they are a collision, or two firmware
revisions -- so pysmi never picks between them: whichever --mib-source came
first supplies it.

Rule 1 needs a LAST-UPDATED on *every* copy, not just on the bundled one: an
undated copy cannot be placed against a dated one, so a single undated copy
drops the whole module to rule 2 whatever the others carry.

That case is not a corner: **51 of the 485 bundled modules carry no
MODULE-IDENTITY at all** -- SNMPv2-SMI, SNMPv2-TC, SNMPv2-CONF, RFC1155-SMI,
RFC1213-MIB, RFC-1212, RFC-1215, IPV6-TC, TOKEN-RING-RMON-MIB, the PPP and
RFC1xxx-MIB modules, and the rest of the pre-SMIv2 set;
:ref:`bundled-mibs` lists them all with a blank revision. For those, rule 1
can never fire, so the bundled copy is what gets compiled unless
--prefer-mib-source or --no-bundled-mibs says otherwise. Every one of them is
text an RFC froze, which is what makes that safe: none can be revised upstream
without becoming a new module under a new name.

The bundle is therefore not a last-resort fallback that only fills gaps in
--mib-source: for those names it is a source in its own right,
and rule 2 puts it ahead of anything a --mib-source has when the revisions do
not settle it. This is a deliberate reversal of what pysmi did before 2.0. A
distribution's /usr/share/snmp/mibs routinely carries a base MIB frozen years
ago, and taking that over a copy pinned to its RFC is almost never what was
wanted. To use your own copy of a bundled module anyway, there are three
ways, in increasing order of bluntness: ship a newer MODULE-IDENTITY revision
of it, so rule 1 picks it; pass --prefer-mib-source, so --mib-source outranks
the bundle wherever rule 1 cannot decide -- which is the only way to override
the 37 undated modules short of the third; or pass --no-bundled-mibs to drop
the bundle entirely, after which nothing but --mib-source is searched and a
base MIB missing there fails the compile rather than resolving to a bundled
copy.

Rule 1 compares only the copies pysmi actually reads. Once some source has
the module, pysmi keeps reading further sources just to compare revisions
while they are local -- file, zip, or the bundle itself -- and stops at the
first one it would have to go over the network for. A remote --mib-source --
http or https -- is therefore never fetched merely to compare revisions, and
neither is anything listed after it: whatever revision that copy carries, it
is not considered. This is why the default
https://pysnmp.github.io/mibs/asn1/@mib@ mirror does not override a bundled
base MIB, and why a local --mib-source meant to override one should be given
ahead of any remote source.

Seeing what was decided
-----------------------

Whenever two sources had the same module and their content differed, *mibdump*
reports the choice as it makes it -- not only that one was passed over, but
which rule passed it over and what would change the outcome::

   WARNING: SNMPv2-MIB resolved to pysmi's bundled copy, not to --mib-source
       used        package://pysmi.mibs.asn1/SNMPv2-MIB
       passed over file:///usr/share/snmp/mibs/SNMPv2-MIB
       decided by  newest MODULE-IDENTITY revision
       to change   give your copy a newer MODULE-IDENTITY revision, or pass
                   --prefer-mib-source, or --no-bundled-mibs

A module that resolved to a copy other than the one you configured is why an
upgrade of pysmi can change compiled output that no --mib-source change
explains, so it is a warning rather than a footnote. Where the winner came
from a --mib-source rather than from the bundle the same block is printed as a
NOTE, since nothing pysmi ships was involved.

It is reported whether or not the module was recompiled: a run that finds
everything already up to date still says which copy each module resolves to,
which is the run where a quiet override would otherwise go unmentioned.

The same MIBs are listed again on the "MIBs found in more than one source"
line of the summary, with the deciding rule named there too. In the library,
``MibStatus.path``, ``MibStatus.shadowed`` and ``MibStatus.precedence`` carry
the same three facts for a caller that wants to record them. Pass
--strict-sources to fail such a MIB instead of choosing.

--quiet suppresses all of this, as it does the rest of the report.

What ends up in the destination directory
-----------------------------------------

*mibdump* compiles the MIB modules you name and, unless --no-dependencies says
otherwise, everything they import -- taking whatever a --mib-source does not
have from pysmi's own bundled copies. So a destination directory built from a
single vendor MIB also holds the IF-MIB, ENTITY-MIB or BRIDGE-MIB it leans on,
with no MIB repository of your own behind it.

The base MIBs are the exception, and which way they go depends on the format:

* --destination-format=pysnmp does not write them. SNMPv2-SMI, SNMPv2-TC and
  the rest are not generated code in pysnmp -- it implements them, in
  ``pysnmp/smi/mibs/`` -- and a generated copy in the destination directory
  would shadow the implementation. The report lists them under *Up to date
  MIBs*.
* --destination-format=json writes them out with everything else, because
  nothing supplies a JSON SNMPv2-TC the way pysnmp supplies a Python one. A
  JSON tree without one refers to a DisplayString that is not in it, so the
  tree cannot be read on its own.

Only the base MIBs actually imported are written, and only from pysmi's
bundled copies, so --no-bundled-mibs turns this off along with the bundle.
Pass --no-base-mibs to keep the bundle but leave the base MIBs stubbed out, as
releases before 2.2 did. The summary's "Base MIBs eligible to be written out
from the bundle" line names the whole set a run may write; which of them it
did write is on the created/updated line.

What holds a base MIB back on the pysnmp target is the default --mib-stub
list, not the target itself. Give --mib-stub explicitly and it replaces that
list entirely -- so a base MIB the replacement omits is compiled and written
like any other module, and it is then yours to make sure the result does not
shadow the implementation pysnmp loads. --no-base-mibs is not consulted at all
once --mib-stub is given, since it only chooses what the default list holds
back.

--no-bundled-mibs is a different lever and keeps working either way: it decides
whether the bundle is a source, not whether a module is stubbed. Combine it
with a --mib-stub list that leaves a base MIB unstubbed and that MIB has to
come from a --mib-source, or the compile fails on it as missing.

Fuzzying MIB module names
-------------------------

There is no single convention on how MIB module files should be named. By
default *mibdump* will try a handful of guesses when trying to find a file
containing specific MIB module. It will try upper and lower cases, a file 
named after MIB module, try adding different extensions to a file (.mib,
.my etc), try adding/cutting the '-MIB' part of the file name.
If nothing matches, *mibdump* will consider that probed --mib-source
does not contain MIB module it is looking for.

There is a small chance, though, that fuzzy natching may result in getting
a wrong MIB. If that happens, you can disable the above fuzzyness by
giving *mibdump* the --disable-fuzzy-source flag.

Avoiding excessive transformation
---------------------------------

It well may happen that many MIB modules refer to a common single MIB
module. In that case *mibdump* may transform it many times unless you
tell *mibdump* where to search for already transformed MIBs. That place
could of course be a directory where *mibdump* writes its transforms into
and/or some other local locations.

The --mib-searcher option specifies either local directory or importable
Python package (applicable to pysnmp transformation) containing transformed
MIB modules. Multiple --mib-searcher options could be given, *mibdump*
will use each of them in order of specification till first hit.

If no transformed MIB module is found, *mibdump* will go on running its full
transformation cycle.

By default *mibdump* will use:

* --mib-searcher=$HOME/.pysnmp/mibs
* --mib-searcher=pysnmp_mibs

Once another --mib-searcher option is given, those defaults will not be used
and should be manually given to *mibdump* if needed.

Blacklisting MIBs
-----------------

Some MIBs may not be automatically transformed into another form and 
therefore must be explicitly excluded from processing. Such MIBs are
normally manually implemented for each target MIB format. Examples
include MIBs containing base SMI types or ASN.1 MACRO definitions
(SNMPv2-SMI, SNMPV2-TC), initially compiled but later manually modified 
MIBs and others.

Default list of blacklisted MIBs for pysnmp transformation target 
is: RFC-1212, RFC-1215, RFC1065-SMI, RFC1155-SMI, RFC1158-MIB, 
RFC1213-MIB, SNMP-FRAMEWORK-MIB, SNMP-TARGET-MIB, SNMPv2-CONF, SNMPv2-SMI,
SNMPv2-TC, SNMPv2-TM, TRANSPORT-ADDRESS-MIB.

If you need to modify this list use the --mib-stub option.

The JSON transformation target blacklists only what it cannot compile: the
base MIBs pysmi bundles are compiled and written out with the modules that
import them, so that a JSON destination directory resolves its own imports.
See `What ends up in the destination directory`_.

Dealing with broken MIBs
------------------------

Curiously enough, some MIBs coming from quite prominent vendors 
appear syntactically incorrect. That leads to MIB compilers fail on
such MIBs. While many MIB compiler implementations (PySMI included)
introduce workarounds and grammar relaxations allowing slightly
broken MIBs to compile, however severely broken MIBs can't be
reliably compiled. 

As another workaround PySMI offers the *borrow* feature. It allows
PySMI to fetch already transformed MIBs even if corresponding
ASN.1 MIB can't be found or parsed.

Default source of pre-compiled MIBs for pysnmp target is:

* http://pysnmp.github.com/mibs/fulltexts/@mib@
* http://pysnmp.github.com/mibs/notexts/@mib@

If you wish to modify this default list use one or more
--mib-borrower options.

Repairing missing IMPORTS
-------------------------

RFC 2578, Section 3.2 requires a MIB module to name in IMPORTS every
symbol it refers to and does not define itself. A great many vendor MIBs
do not, and refer to a base type, textual convention or registration node
they never imported.

Where the omitted symbol is one that SNMPv2-SMI, SNMPv2-TC or SNMPv2-CONF
exports, the import that was meant is not in doubt -- there is exactly
one module it could have come from. The --repair-imports option supplies
it.

This is off by default, so that the strict reading of RFC 2578 stays the
one you get unless you ask otherwise, and a MIB broken this way fails
rather than being quietly patched. What was repaired, for which module,
is listed on the "Repaired MIBs" line of the report.

Symbols out of any other module are never repaired: supplying an import
for, say, *sysUpTime* would add a compilation dependency on SNMPv2-MIB
that the module never declared.

Choosing target transformation
------------------------------

PySMI design allows many transformation formats to be
supported in form of specialized code generation components.
At the moment PySMI can produce MIBs in form of pysnmp classes
and JSON documents.

JSON document schema is chosen to preserve as much of MIB
information as possible. There's no established JSON schema
known to the authors.

Setting destination directory
-----------------------------

By default *mibdump* writes pysnmp MIBs into:

* $HOME/.pysnmp/mibs  (on UNIX)
* @HOME@\PySNMP Configuration\MIBs\  (on Windows)

and JSON files in current working directory.

Use --destination-directory option to change default output
directory.

Performing unconditional transformation
---------------------------------------

By default PySMI will avoid creating new transformations if fresh
enough versions already exist. By using --rebuild option you could
trick PySMI doing requested transformation for all given MIB modules.

Ignoring transformation errors
------------------------------

By default PySMI will stop on first fatal error occurred during
transformations of a series of MIBs. If you wish PySMI to ignore
fatal errors and therefore skipping failed MIB, use the --ignore-errors
option.

Keep in mind that skipping transformation of MIBs that are imported
by other MIBs might make dependant MIBs inconsistent for use.

Skipping dependencies
---------------------

Most MIBs rely on other MIBs for their operations. This is indicated
by the IMPORT statement in ASN.1 language. PySMI attempts to transform
all MIBs IMPORT'ed by MIB being transformed. That is done in recursive
manner.

By using --no-dependencies flag you can tell PySMI not to transform any
MIBs other than those explicitly requested to be transformed.

Keep in mind that skipping dependencies may make the whole set of
transformed MIBs inconsistent.

Generating MIB texts
--------------------

Most MIBs are very verbose. They contain many human-oriented descriptions
and clarifications written in plain English. Those texts may be useful 
for MIB browser applications (to display those texts to human operator)
but might not make any sense in other applications.

To save space and CPU time, PySMI does not by default include those texts 
into transformed MIBs. However this can be reverted by adding
--generate-mib-texts option.

When MIB texts are generated, whitespaces and new lines are stripped by
default. Sometimes that breaks down ASCII art should it occur in MIB texts.
To preserve original text formatting, --keep-texts-layout option may
be used.

Building MIB indices
--------------------

If --build-index option is given, depending on the destination format chosen,
the *mibdump* tool may create new (or update existing) document containing
MIB information in a form that is convenient for querying cornerstone
properties of MIB files.

For example, building JSON index for
`IP-MIB.json <http://pysnmp.github.io/json/asn1/IP-MIB>`_,
`TCP-MIB.json <http://pysnmp.github.io/json/asn1/TCP-MIB>`_ and
`UDP-MIB.json <http://pysnmp.github.io/json/asn1/UDP-MIB>`_
MIB modules would emit something like this:

.. code-block:: json

   {
      "compliance": {
         "1.3.6.1.2.1.48.2.1.1": [
           "IP-MIB"
         ],
         "1.3.6.1.2.1.49.2.1.1": [
           "TCP-MIB"
         ],
         "1.3.6.1.2.1.50.2.1.1": [
           "UDP-MIB"
         ]
      },
      "identity": {
          "1.3.6.1.2.1.48": [
            "IP-MIB"
          ],
          "1.3.6.1.2.1.49": [
            "TCP-MIB"
          ],
          "1.3.6.1.2.1.50": [
            "UDP-MIB"
          ]
      },
      "oids": {
          "1.3.6.1.2.1.4": [
            "IP-MIB"
          ],
          "1.3.6.1.2.1.5": [
            "IP-MIB"
          ],
          "1.3.6.1.2.1.6": [
            "TCP-MIB"
          ],
          "1.3.6.1.2.1.7": [
            "UDP-MIB"
          ],
          "1.3.6.1.2.1.49": [
            "TCP-MIB"
          ],
          "1.3.6.1.2.1.50": [
            "UDP-MIB"
          ]
      }
   }

Each section maps an OID onto the modules that define it, and answers a
different question:

*identity*
   the *MODULE-IDENTITY*, which is what a module calls itself.

*enterprise*
   the module's enterprise branch, for those that have one.

*compliance*
   the *MODULE-COMPLIANCE* statements an implementation may be held to.

*notification*
   the *NOTIFICATION-TYPE* and *TRAP-TYPE* objects a module may emit. An
   SMIv1 *TRAP-TYPE* is listed under the OID it converts to, so a trap
   received on the wire can be looked up whichever SMI version declared it.

*oids*
   the top-level branches a module defines, collapsed to the shortest
   prefix that still answers a lookup unambiguously.

A *meta* section records the schema version the index is written to, so a
consumer can tell one shape of index from another.

The index is incremental: each run merges the modules it compiled into
whatever index is already in the destination directory, rather than
replacing it. A collection may therefore be built up over many runs. Full
index build over thousands of MIBs could be seen
`here <http://pysnmp.github.io/json/index.json>`_.

To build an index from your own code rather than from *mibdump*, see
:doc:`/examples/build-json-index`.

Minor speedups
--------------

There are a few options that may improve PySMI performance.

The --cache-directory option may be used to point to a temporary
writable directory where PySMI parser (e.g. Ply) would store its 
lookup tables.

By default PySMI performing transformation into pysnmp format will 
also pre-compile Python source into interpreter bytecode. That takes
some time and space. If you wish not to cache Python bytecode
or to do that later, use the --no-python-compile option.

