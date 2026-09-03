"""
Compile SMIv2 MIBs
++++++++++++++++++

Invoke user callback function to provide MIB text,
compile given text string into pysnmp MIB form and pass
results to another user callback function for storing.

Here we expect to deal only with SMIv2-valid MIBs.

We use noDeps flag to prevent MIB compiler from attemping
to compile IMPORT'ed MIBs as well.
"""  #

import sys

from pysmi.codegen import PySnmpCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV2Parser
from pysmi.reader import CallbackReader
from pysmi.searcher import StubSearcher
from pysmi.writer import CallbackWriter

inputMibs = ["IF-MIB", "IP-MIB"]
srcDir = "/usr/share/snmp/mibs/"  # we will read MIBs from here

# Initialize compiler infrastructure

mibCompiler = MibCompiler(
    SmiV2Parser(),
    PySnmpCodeGen(),
    # out own callback function stores results in its own way
    CallbackWriter(lambda m, d, c: sys.stdout.write(d)),
)


# our own callback function serves as a MIB source here
def readMib(mibname, cbCtx):
    """Return the ASN.1 text for *mibname*, read from a ``.txt`` file."""
    with open(srcDir + mibname + ".txt") as srcFile:
        return srcFile.read()


mibCompiler.add_sources(CallbackReader(readMib))

# never recompile MIBs with MACROs
mibCompiler.add_searchers(StubSearcher(*PySnmpCodeGen.baseMibs))

# run non-recursive MIB compilation
results = mibCompiler.compile(*inputMibs, **dict(noDeps=True))

print("Results: " + ", ".join([f"{x}:{results[x]}" for x in results]))
