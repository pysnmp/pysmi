"""
Build a JSON index over compiled MIBs
+++++++++++++++++++++++++++++++++++++

Compile a few ASN.1 MIBs into JSON documents, then build an index over
them.

The index answers the question the documents cannot: given an OID, which
module defines it? It is what *mibdump --build-index* writes, and what
`index.json <https://pysnmp.github.io/mibs/json/index.json>`_ is.

The index is incremental. Each run merges its modules into whatever index
is already in the destination directory, so a collection can be built up
over many runs rather than in one pass. Run this script twice, with a
different module in *inputMibs* the second time, and the index will name
both.
"""  #

import json
import os

from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiStarParser
from pysmi.reader import FileReader, HttpReader
from pysmi.searcher import StubSearcher
from pysmi.writer import FileWriter

# from pysmi import debug

# debug.enableDebugLogging('compiler')

inputMibs = ["IF-MIB", "IP-MIB"]
srcDirectories = ["/usr/share/snmp/mibs"]
httpSources = ["https://pysnmp.github.io/mibs/asn1/@mib@"]
dstDirectory = os.path.join(os.path.expanduser("~"), ".pysnmp", "mibs", "json")

# Initialize compiler infrastructure

mibCompiler = MibCompiler(SmiStarParser(), JsonCodeGen(), FileWriter(dstDirectory).set_options(suffix=".json"))

# search for source MIBs here
mibCompiler.add_sources(*[FileReader(x) for x in srcDirectories])

# search for source MIBs at Web sites
mibCompiler.add_sources(*[HttpReader(x) for x in httpSources])

# never recompile MIBs with MACROs
mibCompiler.add_searchers(StubSearcher(*JsonCodeGen.baseMibs))

# run recursive MIB compilation
results = mibCompiler.compile(*inputMibs)

print("# Results: " + ", ".join([f"{x}:{results[x]}" for x in results]))

# Build the index over everything just compiled.
#
# Any index already in dstDirectory is read back and merged into, which is
# why this may be called once per run rather than once per collection. Pass
# ignoreErrors=True to keep a failure here from losing the compilation
# above; pass dryRun=True to build the index without storing it.
mibCompiler.build_index(results, ignoreErrors=True)

# Read back what was written. mibCompiler.indexFile is the name used, and
# the writer's suffix option gives it its extension.
indexPath = os.path.join(dstDirectory, mibCompiler.indexFile + ".json")

with open(indexPath) as fileObj:
    index = json.load(fileObj)

print(f"\n# Index at {indexPath}, schema version {index['meta']['schema']}")

# The sections answer different questions, each mapping an OID to the
# modules that define it:
#
#   identity      MODULE-IDENTITY -- what a module calls itself
#   enterprise    the module's enterprise branch, where it has one
#   compliance    MODULE-COMPLIANCE -- what an implementation is held to
#   notification  NOTIFICATION-TYPE and TRAP-TYPE -- what a module may emit
#   oids          the top-level branches a module defines, shortest first
for section in ("identity", "enterprise", "compliance", "notification", "oids"):
    print(f"\n## {section}")

    for oid, modules in sorted(index[section].items())[:5]:
        print(f"   {oid} -> {', '.join(modules)}")
