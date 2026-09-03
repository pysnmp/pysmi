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

Every entry must be RFC-frozen or otherwise not routinely revised. A MIB an
authority keeps changing (IANAifType-MIB, for instance) does not belong here:
a bundled copy would silently go stale exactly when the real, current source
is unreachable and this one gets used instead.
"""

import pathlib
import sys
import tempfile
import urllib.request

UPSTREAM = "https://pysnmp.github.io/mibs/asn1/{}"

BUNDLED = (
    "SNMPv2-SMI",
    "SNMPv2-TC",
    "SNMPv2-CONF",
    "SNMPv2-MIB",
    "RFC1155-SMI",
    "RFC1158-MIB",
    "RFC-1212",
    "RFC-1215",
    "RFC1213-MIB",
)

DEST = pathlib.Path(__file__).resolve().parent.parent / "pysmi" / "mibs" / "asn1"


def fetch(mibname: str) -> bytes:
    """Download one MIB's canonical ASN.1 text."""
    with urllib.request.urlopen(UPSTREAM.format(mibname), timeout=30) as response:  # noqa: S310
        return response.read()


def check() -> int:
    """Report any bundled file that no longer matches upstream, changing nothing.

    Returns:
        The process exit code: 0 if every bundled file matches, 1 otherwise.
    """
    stale = []

    for mibname in BUNDLED:
        path = DEST / mibname

        if not path.is_file():
            stale.append(f"{mibname}: not bundled yet")
            continue

        current = fetch(mibname)

        if path.read_bytes() != current:
            stale.append(f"{mibname}: bundled copy no longer matches upstream")

    if stale:
        sys.stderr.write("Bundled MIBs out of date:\n" + "\n".join(f"  {line}" for line in stale) + "\n")
        return 1

    sys.stdout.write(f"All {len(BUNDLED)} bundled MIBs match upstream.\n")
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
