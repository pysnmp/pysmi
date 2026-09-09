# Runtime behavior for bundled modules

One file per MIB module, named exactly as the module plus `.py`.
`PySnmpCodeGen` appends the file to what it renders for that module, after the
`mibBuilder.exportSymbols()` call, so the fragment runs in the generated
module's own namespace and reaches every symbol the module defined by name.

Nothing here is a patch. The Python above a fragment is regenerated from the
ASN.1 on every build, and the fragment is appended to whatever that produced,
so the two cannot drift apart the way a hand-edited copy of generated output
does. See pysnmp/pysmi#231 for the eight years of drift that motivated this.

## What belongs here

A runtime relation the ASN.1 cannot state, and that therefore no code
generator can derive. The canonical one is RFC 4001 section 4: the encoding of
an `InetAddress` index depends on the value of the `InetAddressType` index
preceding it in the same row. SMIv2 has no syntax for "the encoding of index A
is determined by index B"; the RFC says it in a DESCRIPTION clause, in prose.

## What does not

Anything derivable from the module. If the generator is not emitting something
the SYNTAX, DISPLAY-HINT, SIZE clause or IMPORTS already determine, that is a
code generator bug and the fix goes in `pysmi/codegen/`. A fragment that
supplies it instead hides the bug for one module and leaves every other module
wrong -- which is the failure mode this directory exists to end, not repeat.

## Writing one

The fragment is executed, not imported: it has no module scope of its own, and
its names land in the generated module's namespace beside the symbols the MIB
defined. So

- prefix every helper with `_`, and alias every import (`import os as _os`),
  so a fragment cannot shadow a symbol the MIB defines;
- attach methods after the class rather than in it -- `Foo.prettyIn = _prettyIn`
  -- since the class body is generated and closed by then. Zero-argument
  `super()` will not work in a function defined outside a class body: name the
  base explicitly, `TextualConvention.prettyIn(self, value)`;
- do not rely on private name mangling. `self.__x` inside a function defined
  outside a class body is `self.__x`, not `self._Foo__x`;
- re-seed anything already built from a class attribute the fragment sets. The
  splice point is after the module constructed its objects, so setting an
  attribute the constructor reads -- `defaultValue`, `subtypeSpec` -- fixes the
  class and leaves every instance made from it as it was.
  `SNMP-FRAMEWORK-MIB` sets `SnmpEngineID.defaultValue` and so rebuilds
  `snmpEngineID.syntax` after it; a fragment that only attaches methods needs
  nothing, since attribute lookup on a method happens at call time. See
  pysnmp/pysmi#236;
- cite the RFC and section that states the relation, in a comment at the top.

`tests/test_behavior.py` checks that every fragment is attached to a module
pysmi bundles and that the emitted module parses; `tests/test_pysnmp_consumer.py`
checks what the behavior actually does, under pysnmp.
