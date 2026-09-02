"""
Compile MIBs into JSON
++++++++++++++++++++++

Look up specific ASN.1 MIBs at configured Web and FTP sites,
compile them into JSON documents and print them out to stdout.

Try to support both SMIv1 and SMIv2 flavors of SMI as well as
popular deviations from official syntax found in the wild.
"""  #

from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiStarParser
from pysmi.reader import FileReader, HttpReader
from pysmi.searcher import StubSearcher
from pysmi.writer import CallbackWriter

# from pysmi import debug

# debug.enableDebugLogging('reader', 'compiler')

inputMibs = ["IF-MIB", "IP-MIB"]
srcDirectories = ["/usr/share/snmp/mibs"]
httpSources = ["https://pysnmp.github.io/mibs/asn1/@mib@"]


def printOut(mibName, jsonDoc, cbCtx):
    print(f"\n\n# MIB module {mibName}")
    print(jsonDoc)


# Initialize compiler infrastructure

mibCompiler = MibCompiler(SmiStarParser(), JsonCodeGen(), CallbackWriter(printOut))

# search for source MIBs here
mibCompiler.add_sources(*[FileReader(x) for x in srcDirectories])

# search for source MIBs at Web sites
mibCompiler.add_sources(*[HttpReader(x) for x in httpSources])

# never recompile MIBs with MACROs
mibCompiler.add_searchers(StubSearcher(*JsonCodeGen.baseMibs))

# run recursive MIB compilation
results = mibCompiler.compile(*inputMibs)

print("\n# Results: {}".format(", ".join([f"{x}:{results[x]}" for x in results])))
