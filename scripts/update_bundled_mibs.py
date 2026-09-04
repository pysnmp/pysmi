#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Maintain the base MIB ASN.1 sources bundled in ``pysmi/mibs/asn1/``.

This is a maintainer tool, run by hand -- not part of building or installing
pysmi. Fetching from the network and re-verifying every bundled MIB compiles
has no business happening on every ``pip install``, so it stays a separate,
explicit step:

    uv run scripts/update_bundled_mibs.py          # refresh from upstream
    uv run scripts/update_bundled_mibs.py --check   # report drift, change nothing

BUNDLED below is the whole bundle manifest. Adding a MIB later that turns out
to be common enough to bundle -- and stable enough that a frozen copy will
not go stale, see pysnmp/pysmi#113 -- means adding its name here and running
this script; nothing else in the source tree names an individual bundled
MIB.

What belongs here is a MIB that is widely imported and revised rarely, if at
all. Most entries are RFC-frozen and can never drift. IANAifType-MIB is the
exception: IANA does revise it, but only to register ifType values that take
longer to reach shipping hardware than a pysmi release does to reach PyPI,
and .github/workflows/bundled-mibs-freshness.yml re-checks the whole bundle
monthly. A bundled copy trailing upstream by an unused enumeration beats
IF-MIB not resolving at all, which is what the bundle is for.

Frozen is not the same as current, and the difference is the trap here: an
RFC never changes, but a later RFC can obsolete it. That is how the mirror
came to serve an ENTITY-MIB eight years superseded. So a MIB is pinned to an
RFC number, and --check asks the RFC Editor whether that RFC still stands.

A user-supplied copy always wins over a bundled one, so nothing here can
shadow a current MIB the caller already has.

What is here is:

- every module a code generator names in its ``baseMibs``, the modules pysmi
  itself calls foundational, plus SNMPv2-MIB. PYSNMP-USM-MIB is the one
  exception: it is pysnmp's own, not an RFC, and pysnmp ships it.
- every other non-vendor module that 1% or more of the 5523 vendor MIBs in
  https://github.com/pysnmp/mibs name in IMPORTS. That corpus is the best
  evidence available of what a MIB for a real product actually depends on,
  and it is what put Q-BRIDGE-MIB, P-BRIDGE-MIB, BRIDGE-MIB, ENTITY-MIB,
  IPV6-TC and HCNUM-TC here.
- whatever those need to compile. The RMON MIBs are here only because
  Q-BRIDGE-MIB imports RMON2-MIB; a bundled MIB that cannot resolve against
  its siblings is no use as a fallback.
"""

import json
import pathlib
import re
import sys
import tempfile
import urllib.request

UPSTREAM = "https://pysnmp.github.io/mibs/asn1/{}"

RFC = "https://www.rfc-editor.org/rfc/rfc{}.txt"
RFC_METADATA = "https://www.rfc-editor.org/rfc/rfc{}.json"

#: Where a MIB comes from when UPSTREAM is not the copy to trust.
#:
#: The pysnmp mirror carries a 2017 IANAifType-MIB, nine years of ifType
#: registrations behind IANA's own. Bundling that would put a knowingly stale
#: copy in the package and give the freshness check nothing to catch, since
#: the mirror is not moving either. IANA publishes the authoritative text, so
#: IANAifType-MIB is fetched and compared against that instead.
CANONICAL_SOURCES = {
    "IANAifType-MIB": "https://www.iana.org/assignments/ianaiftype-mib/ianaiftype-mib",
}

#: MIBs taken from their RFC because the mirror serves a superseded revision.
#:
#: The mirror is a good source for most of this list, but not a current one
#: for all of it: its ENTITY-MIB is RFC 4133, obsoleted in 2013; its RMON2-MIB
#: predates RFC 2021, let alone RFC 4502; its SNMP-TARGET-MIB is RFC 2573.
#: For these the RFC text is the authority and the module is cut out of it.
#:
#: Only these three. The mirror's copies of the SMI modules are deliberately
#: not verbatim RFC text -- its SNMPv2-CONF, for one, is a stub with the macro
#: definitions removed because a compiler predefines them -- so replacing the
#: rest wholesale would throw away edits that are there on purpose.
RFC_SOURCES = {
    "ENTITY-MIB": 6933,
    "RMON2-MIB": 4502,
    "SNMP-TARGET-MIB": 3413,
}

BUNDLED = (
    "SNMPv2-SMI",
    "SNMPv2-TC",
    "SNMPv2-CONF",
    "SNMPv2-MIB",
    "SNMPv2-TM",
    "IF-MIB",
    "IANAifType-MIB",
    "SNMP-FRAMEWORK-MIB",
    "SNMP-TARGET-MIB",
    "TRANSPORT-ADDRESS-MIB",
    "INET-ADDRESS-MIB",
    "RFC1065-SMI",
    "RFC1155-SMI",
    "RFC1158-MIB",
    "RFC-1212",
    "RFC-1215",
    "RFC1213-MIB",
    # Imported by 1% or more of the vendor MIBs in the pysnmp corpus.
    "Q-BRIDGE-MIB",
    "P-BRIDGE-MIB",
    "BRIDGE-MIB",
    "ENTITY-MIB",
    "IPV6-TC",
    "HCNUM-TC",
    # Only Q-BRIDGE-MIB reaches for these, but it cannot compile without them.
    "RMON-MIB",
    "RMON2-MIB",
    "RFC1271-MIB",
    "TOKEN-RING-RMON-MIB",
)

DEST = pathlib.Path(__file__).resolve().parent.parent / "pysmi" / "mibs" / "asn1"


def download(url: str) -> bytes:
    """Read one URL."""
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return response.read()


def unpaginate(text: str) -> str:
    """Drop the footer and header that straddle each form feed in an RFC."""
    pages = []

    for number, page in enumerate(text.split("\f")):
        lines = page.split("\n")

        if number:
            while lines and not lines[0].strip():
                lines.pop(0)
            if lines:
                lines.pop(0)  # The running header.

        while lines and not lines[-1].strip():
            lines.pop()
        if lines and re.search(r"\[Page\s+\d+\]\s*$", lines[-1]):
            lines.pop()

        pages.append("\n".join(lines))

    return "\n".join(pages)


BEGINS = re.compile(r"^[ \t]*([A-Za-z0-9][\w-]*)[ \t]+DEFINITIONS[ \t]*::=[ \t]*BEGIN\b", re.M)
ENDS = re.compile(r"^[ \t]*END[ \t]*$", re.M)


def extract(mibname: str, rfc: int) -> bytes:
    """Cut one MIB module out of the RFC that defines it.

    An RFC can carry several modules, and a module can carry a MACRO whose
    own END is not the module's, so the module runs from its BEGIN to the
    last END before whatever module comes next.
    """
    body = unpaginate(download(RFC.format(rfc)).decode("utf-8", "replace"))
    starts = [(match.group(1), match.start()) for match in BEGINS.finditer(body)]

    for index, (name, start) in enumerate(starts):
        if name != mibname:
            continue

        stop = starts[index + 1][1] if index + 1 < len(starts) else len(body)
        ends = list(ENDS.finditer(body, start, stop))
        if not ends:
            break

        return body[start : ends[-1].end()].encode()

    raise SystemExit(f"{mibname}: no such module in RFC {rfc}")


def fetch(mibname: str) -> bytes:
    """Download one MIB's canonical ASN.1 text.

    From its RFC if RFC_SOURCES pins it to one, else from CANONICAL_SOURCES
    or, for most of the list, from UPSTREAM.
    """
    if mibname in RFC_SOURCES:
        return extract(mibname, RFC_SOURCES[mibname])

    return download(CANONICAL_SOURCES.get(mibname) or UPSTREAM.format(mibname))


def obsoletedBy(rfc: int) -> list[str]:
    """Name the RFCs that have obsoleted *rfc*, if any."""
    metadata = json.loads(download(RFC_METADATA.format(rfc)))

    return metadata.get("obsoleted_by") or []


def check() -> int:
    """Report any bundled file that no longer matches its source, changing nothing.

    Comparing against the source catches a MIB the mirror has revised, but an
    RFC's text never changes -- a superseded RFC_SOURCES entry would compare
    equal forever. So the RFCs are checked for obsoletion separately, which is
    the way ENTITY-MIB came to be eight years stale in the first place.

    Returns:
        The process exit code: 0 if every bundled file is current, 1 otherwise.
    """
    stale = []

    for mibname, rfc in RFC_SOURCES.items():
        successors = obsoletedBy(rfc)

        if successors:
            stale.append(f"{mibname}: RFC {rfc} obsoleted by {', '.join(successors)}")

    for mibname in BUNDLED:
        path = DEST / mibname

        if not path.is_file():
            stale.append(f"{mibname}: not bundled yet")
            continue

        current = fetch(mibname)

        if path.read_bytes() != current:
            stale.append(f"{mibname}: bundled copy no longer matches its source")

    if stale:
        sys.stderr.write("Bundled MIBs out of date:\n" + "\n".join(f"  {line}" for line in stale) + "\n")
        return 1

    sys.stdout.write(f"All {len(BUNDLED)} bundled MIBs are current.\n")
    return 0


def update() -> int:
    """Refresh every bundled file from upstream, then compile-verify the set.

    Every fetch and the verify compile happen against a staging directory
    first; DEST is only touched once every file has been fetched and the
    whole staged set compiles clean, so a network failure partway through,
    or an upstream MIB that no longer compiles, leaves the existing bundle
    exactly as it was rather than a mix of old and new files.

    Returns:
        The process exit code: 0 on success, 1 if the refreshed set fails to
        compile.
    """
    DEST.mkdir(parents=True, exist_ok=True)

    # Staged on DEST's own filesystem, so committing a file is an atomic
    # rename rather than a copy that could itself be interrupted.
    with tempfile.TemporaryDirectory(dir=DEST.parent) as staging:
        stagingDir = pathlib.Path(staging)

        for mibname in BUNDLED:
            data = fetch(mibname)
            (stagingDir / mibname).write_bytes(data)
            sys.stdout.write(f"{mibname}: {len(data)} bytes\n")

        if verify(stagingDir) != 0:
            sys.stderr.write("Staged bundle failed to verify; leaving the existing bundle untouched.\n")
            return 1

        for mibname in BUNDLED:
            (stagingDir / mibname).replace(DEST / mibname)

    return 0


def verify(source: pathlib.Path | None = None) -> int:
    """Compile every bundled MIB against a directory containing the bundle,
    nothing else.

    A MIB that cannot compile standalone against its bundled siblings would
    make the fallback source useless for exactly the case it exists for.

    Args:
        source: directory holding one file per name in BUNDLED. Defaults to
            the bundle already on disk; *update* passes a staging directory
            to verify a refreshed set before committing it.

    Returns:
        The process exit code: 0 if everything compiles, 1 otherwise.
    """
    from pysmi.codegen import JsonCodeGen
    from pysmi.compiler import MibCompiler
    from pysmi.parser import SmiV1CompatParser
    from pysmi.reader import FileReader
    from pysmi.writer import CallbackWriter

    compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None))
    compiler.add_sources(FileReader(str(source if source is not None else DEST)))
    processed = compiler.compile(*BUNDLED, ignoreErrors=True)

    failed = {name: status for name, status in processed.items() if name in BUNDLED and status != "compiled"}

    if failed:
        sys.stderr.write("Bundled MIBs failed to compile:\n")
        for name, status in sorted(failed.items()):
            sys.stderr.write(f"  {name}: {status}\n")
        return 1

    sys.stdout.write(f"All {len(BUNDLED)} bundled MIBs compile.\n")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv[1:] else update())
