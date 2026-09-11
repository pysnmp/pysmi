
SNMP MIB parser
---------------

[![Python Versions](https://img.shields.io/pypi/pyversions/pysnmp-pysmi.svg)](https://pypi.org/project/pysnmp-pysmi/)
[![Build status](https://github.com/pysnmp/pysmi/actions/workflows/build-test-release.yml/badge.svg)](https://github.com/pysnmp/pysmi/actions/workflows/build-test-release.yml)
[![Coverage Status](https://img.shields.io/codecov/c/github/pysnmp/pysmi.svg)](https://codecov.io/github/pysnmp/pysmi)
[![GitHub license](https://img.shields.io/badge/license-BSD-blue.svg)](https://raw.githubusercontent.com/pysnmp/pysmi/main/LICENSE.rst)

PySMI is a pure-Python implementation of
[SNMP SMI](https://en.wikipedia.org/wiki/Management_information_base) MIB parser.
This tool is designed to turn ASN.1 MIBs into various formats. As of this moment,
JSON and [pysnmp](https://pysnmp.github.io/pysnmp/) modules can be generated
from ASN.1 MIBs.

Features
--------

* Understands SMIv1, SMIv2 and de-facto SMI dialects
* Turns MIBs into pysnmp classes and JSON documents
* Maintains an index of MIB objects over many MIB modules
* Automatically pulls ASN.1 MIBs from local directories, ZIP archives,
  HTTP and FTP servers
* 100% Python, requires Python 3.10 or newer



How to use PySMI
----------------

If you are using pysnmp, you might never notice pysmi presence - pysnmp
calls pysmi for MIB download and compilation behind the scenes (you can
still can do that manually by invoking *mibdump* tool).

To turn ASN.1 MIB into a JSON document, call *mibdump* tool like this:

```
$ mibdump --generate-mib-texts --destination-format json IF-MIB
Source MIB repositories: https://pysnmp.github.io:443/mibs/asn1/@mib@
    Borrow missing/failed MIBs from: 
    Existing/compiled MIB locations: 
    Compiled MIBs destination directory: /home/you/.pysnmp/mibs
    MIBs excluded from code generation: 
    MIBs to compile: IF-MIB
    Destination format: json
    Parser grammar cache directory: not used
    Also compile all relevant MIBs: yes
    Search pysmi's bundled base MIBs, newest revision winning: yes
    Prefer --mib-source where no revision decides: no
    Base MIBs eligible to be written out from the bundle: RFC-1212, RFC-1215, RFC1065-SMI, RFC1155-SMI, RFC1158-MIB, RFC1213-MIB, SNMPv2-CONF, SNMPv2-SMI, SNMPv2-TC, SNMPv2-TM
    Rebuild MIBs regardless of age: no
    Prune stored MIBs with no remaining source: no
    Dry run mode: no
    Create/update MIBs: yes
    Byte-compile Python modules: no (optimization level no)
    Report a failed MIB as an error: yes
    Generate OID->MIB index: no
    Generate texts in MIBs: yes
    Keep original texts layout: no
    Try various file names while searching for MIB module: yes
    Created/updated MIBs: IANAifType-MIB, IF-MIB, SNMPv2-CONF, SNMPv2-MIB, SNMPv2-SMI, SNMPv2-TC
Pre-compiled MIBs borrowed: 
Up to date MIBs: 
Missing source MIBs: 
Omitted MIBs (they import a failed MIB): 
Repaired MIBs: 
MIBs found in more than one source: 
Failed MIBs: 
```

The `Borrow missing/failed MIBs from:` line is empty because there is no
default borrower. Pass `--mib-borrower` to use the feature; the trees pysmi
used to default to were compiled pysnmp modules, and those were withdrawn for
the reason the [MIB distribution](https://pysnmp.github.io/mibs/channels.html)
gives.

JSON document build from
[IF-MIB module](https://pysnmp.github.io/mibs/asn1/IF-MIB)
would hold information such as:

```
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
        "nodetype": "table",
        "class": "objecttype",
        "maxaccess": "not-accessible"
      },
      "ifTestEntry": {
        "name": "ifTestEntry",
        "oid": "1.3.6.1.2.1.31.1.3.1",
        "nodetype": "row",
        "class": "objecttype",
        "maxaccess": "not-accessible",
        "augmention": {
          "name": "ifTestEntry",
          "module": "IF-MIB",
          "object": "ifEntry"
        }
      },
      "ifTestId": {
        "name": "ifTestId",
        "oid": "1.3.6.1.2.1.31.1.3.1.1",
        "nodetype": "column",
        "class": "objecttype",
        "syntax": {
          "type": "TestAndIncr",
          "class": "type"
        },
        "maxaccess": "read-write"
      },
      ...
   }
```

In general, converted MIBs capture all aspects of original (ASN.1) MIB contents
and layout. The snippet above is just a partial example, but here is the
complete [IF-MIB.json](https://pysnmp.github.io/mibs/json/IF-MIB.json)
file.

Besides one-to-one MIB conversion, PySMI library can produce JSON index to
facilitate fast MIB information lookup across large collection of MIB files.
For example, JSON index for
[IP-MIB.json](https://pysnmp.github.io/mibs/json/IP-MIB.json),
[TCP-MIB.json](https://pysnmp.github.io/mibs/json/TCP-MIB.json) and
[UDP-MIB.json](https://pysnmp.github.io/mibs/json/UDP-MIB.json)
modules would keep information like this:

```
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
```

With this example, *compliance* and *identity* keys point to
*MODULE-COMPLIANCE* and *MODULE-IDENTITY* MIB objects, *oids*
list top-level OIDs branches defined in MIB modules.

The published distribution no longer carries a JSON index of its own. What it
publishes is [`index-v2.csv`](https://pysnmp.github.io/mibs/index-v2.csv), OID
to module, and `core.db`, which answers per node rather than per module — see
[the MIB distribution](https://pysnmp.github.io/mibs/channels.html).

The PySMI library can automatically fetch required MIBs from HTTP, FTP sites
or local directories. You could configure any MIB source available to you (including
[the MIB distribution](https://pysnmp.github.io/mibs/)) for that purpose.

How to get PySMI
----------------

The pysmi package is distributed under terms and conditions of 2-clause
BSD [license](https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst). Source code is freely
available as a GitHub [repo](https://github.com/pysnmp/pysmi).

Run `uv add pysnmp-pysmi` or `pip install pysnmp-pysmi`, or download it from
[PyPI](https://pypi.org/project/pysnmp-pysmi/). Note the name: `pysmi` is the original,
unmaintained package.

To try the command-line tools without installing anything permanently:

```
$ uvx --from pysnmp-pysmi mibdump --help
```

How to develop PySMI
--------------------

PySMI uses [uv](https://docs.astral.sh/uv/) for dependency management, builds and
releases.

```
$ uv sync            # create .venv and install everything, including dev tools
$ uv run pytest      # run the test suite
$ uv run mibdump --help
```

Linting, formatting and type checking are run through pre-commit, which is what CI
checks:

```
$ uv run pre-commit install     # optional, to run these on every commit
$ uv run pre-commit run --all-files
```

That covers [ruff](https://docs.astral.sh/ruff/) for linting and formatting, and
[mypy](https://mypy-lang.org/) for type checking. To build the documentation:

```
$ uv run sphinx-build -b html docs/source docs/build
```

If something does not work as expected,
[open an issue](https://github.com/pysnmp/pysmi/issues) at GitHub or
post your question [on Stack Overflow](http://stackoverflow.com/questions/ask).

Copyright (c) 2015-2020, [Ilya Etingof](mailto:etingof@gmail.com).
Copyright (c) 2024-2026, the PySNMP maintainers.
All rights reserved.
