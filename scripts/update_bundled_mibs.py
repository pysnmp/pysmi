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

    uv run scripts/update_bundled_mibs.py           # refresh from upstream
    uv run scripts/update_bundled_mibs.py --check   # report drift, change nothing
    uv run scripts/update_bundled_mibs.py --verify  # compile the bundle as it stands
    uv run scripts/update_bundled_mibs.py --docs    # rewrite the inventory page

``bundled_mibs.json`` beside this file is the whole bundle manifest: one entry
per module, naming where its text comes from and nothing else. Adding or
dropping a module means editing that file and re-running this script; no other
file in the source tree names an individual bundled MIB.

Every bundled byte is traceable to a publisher
----------------------------------------------

The rule this bundle keeps is that nothing here is hand-authored MIB text. Each
entry names one of four sources:

``rfc``
    The module is cut out of the RFC that currently defines it. An RFC's text
    never changes, so a copy taken from one cannot drift -- but a *later* RFC
    can obsolete it, which is how the mirror came to serve an ENTITY-MIB eight
    years superseded. ``--check`` therefore asks the RFC Editor whether each
    pinned RFC still stands, as well as re-cutting the module and comparing.

``iana``
    IANA publishes the authoritative text at a registry URL and revises it
    continuously. The URL is the source, and ``--check`` re-fetches and
    compares.

``ieee802.1``
    IEEE 802.1 publishes its MIB modules at a stable directory, one file per
    dated revision. The *newest* revision in that directory is the source, so
    ``--check`` reports a new one the way it reports a revised IANA registry.
    The manifest records the revision each bundled copy came from, and
    ``update`` writes back the one it fetched.

    Pinning the dated file instead would make the copy here unfalsifiable: the
    URL is immutable, so ``--check`` would compare equal forever while IEEE
    moved on, and the module would trail upstream with nothing able to say so.

``local``
    Only RFC-1212 and RFC-1215. Both RFCs define a macro in prose rather than
    shipping an ASN.1 module, so no publisher has a copy to fetch and the
    compat module is maintained in this repository. The manifest records why.

A handful of entries also carry a ``patch``. The published text of those
modules does not compile -- a truncated line left in the RFC, an IMPORTS clause
missing a symbol the module goes on to use, a bound one past the top of
Integer32. The patch is applied to the fetched text after every fetch and lives
in ``scripts/mib-patches/`` where it can be read; the manifest's ``reason``
says what defect it repairs. Bundling the pysnmp/mibs mirror's hand-repaired
copy instead would have hidden all of that.

What belongs in the bundle
--------------------------

A vendor-neutral module with a publisher we can re-fetch and diff. That is what
decides membership -- not which directory a mirror happens to file it under,
which is how CableLabs, DMTF, MEF and SCTE modules end up misfiled as standard
ones. A module with no live authoritative source is not bundled, however widely
imported, because there would be no way to tell a stale copy from a current
one. See ``docs/source/bundled-mibs.rst`` for the inventory and for what is
deliberately left out.

"Upstream still revises it" is not a reason to leave a module out
----------------------------------------------------------------

It reads like one, and pysmi used to treat it as one -- the bundle was
restricted to RFC-frozen modules on the grounds that anything still being
revised would go stale in the package. Two mechanisms have since made that
argument obsolete for any module carrying a MODULE-IDENTITY:

- ``--check`` re-fetches every entry from its publisher on a schedule, so a
  revision upstream is reported rather than sat on. That is what the source
  must be a *live* URL for: pinning IANA or IEEE 802.1 to an immutable dated
  file would buy apparent stability by making staleness undetectable.
- A caller who supplies a properly dated, genuinely newer copy wins on the
  MODULE-IDENTITY comparison. A bundled copy that has fallen a revision behind
  loses to their current one; it does not shadow it.

So a revised-upstream module is bundled like any other, and IANA's registries
and the IEEE 802.1 directory are tracked at their current revision rather than
frozen. What is actually disqualifying is having no publisher to re-fetch from
at all, because then neither mechanism has anything to work with.

The one place the old argument still holds is a module with no MODULE-IDENTITY:
there is no revision for ``--check`` to report against and none for a caller's
copy to beat, so the bundled copy is simply used. All 34 such entries here are
pre-SMIv2 modules or SMI modules proper -- RFC1213-MIB, SNMPv2-SMI, the PPP and
RFC1xxx-MIB modules -- whose text an RFC froze and which cannot be revised
except as a new module under a new name. An undated module that upstream still
revises would shadow a caller's better copy for good; there is no such module
here, and ``tests/test_compiler_bundled_mibs.py`` is what keeps it that way.
"""

import json
import pathlib
import re
import sys
import tempfile
import urllib.request
from functools import cache
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
DEST = ROOT / "pysmi" / "mibs" / "asn1"
MANIFEST = HERE / "bundled_mibs.json"
PATCHES = HERE / "mib-patches"
INVENTORY = ROOT / "docs" / "source" / "bundled-mibs.rst"

RFC = "https://www.rfc-editor.org/rfc/rfc{}.txt"
RFC_METADATA = "https://www.rfc-editor.org/rfc/rfc{}.json"

#: A module's MODULE-IDENTITY revision, for the inventory page. Read straight
#: off the text rather than parsed: the inventory is a listing, not a compile.
_REVISION = re.compile(r'(?:LAST-UPDATED|REVISION)\s+"(\d{6,14}Z?)"')


def manifest() -> dict[str, dict[str, Any]]:
    """Read the bundle manifest."""
    modules: dict[str, dict[str, Any]] = json.loads(MANIFEST.read_text())["modules"]

    return modules


def download(url: str) -> bytes:
    """Read one URL."""
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - the URLs come from the manifest in this repository, not from a MIB
        data: bytes = response.read()

    return data


def unpaginate(text: str) -> str:
    """Drop the footer and header that straddle each form feed in an RFC.

    Both the blank lines a running header sits in and the ones above the page
    footer go with them, so that a module's text reads as it would have without
    the page breaks. Leaving them in produces a file that still compiles but
    diffs badly against every other copy of the same module.
    """
    pages = []

    for number, page in enumerate(text.split("\f")):
        lines = page.split("\n")

        if number:
            while lines and not lines[0].strip():
                lines.pop(0)
            if lines:
                lines.pop(0)  # The running header.
            while lines and not lines[0].strip():
                lines.pop(0)

        while lines and not lines[-1].strip():
            lines.pop()
        if lines and re.search(r"\[Page\s+\d+\]\s*$", lines[-1]):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()

        pages.append("\n".join(lines))

    return "\n".join(pages)


#: An RFC may put the module name and ``DEFINITIONS`` on separate lines -- RFC
#: 1158 does -- so the two are matched across a newline, not just a space.
BEGINS = re.compile(
    r"^[ \t]*([A-Za-z0-9][\w-]*)[ \t\r\n]+DEFINITIONS"
    r"[ \t\r\n]*(?:IMPLICIT[ \t]+TAGS[ \t\r\n]*)?::=[ \t\r\n]*BEGIN\b",
    re.M,
)
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

        return (body[start : ends[-1].end()] + "\n").encode()

    raise SystemExit(f"{mibname}: no such module in RFC {rfc}")


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply_patch(text: bytes, patch: str, mibname: str) -> bytes:
    """Apply a unified diff, refusing anything whose context has moved.

    Deliberately strict and dependency-free: a patch that no longer matches the
    text it was cut against means the source moved, which is a thing to look
    at, not to fuzz past.
    """
    lines = text.decode("utf-8", "replace").split("\n")
    out: list[str] = []
    cursor = 0

    for chunk in patch.split("\n"):
        if chunk.startswith(("--- ", "+++ ")):
            continue

        header = HUNK.match(chunk)
        if header:
            start = int(header.group(1)) - 1
            if start < cursor:
                raise SystemExit(f"{mibname}: overlapping hunks in its patch")
            out.extend(lines[cursor:start])
            cursor = start
            continue

        if not chunk:
            continue

        mark, body = chunk[0], chunk[1:]

        if mark == "+":
            out.append(body)
        elif mark in " -":
            if cursor >= len(lines) or lines[cursor] != body:
                found = lines[cursor] if cursor < len(lines) else "<end of file>"
                raise SystemExit(
                    f"{mibname}: its patch no longer applies -- line {cursor + 1} "
                    f"reads {found!r}, the patch expects {body!r}"
                )
            if mark == " ":
                out.append(body)
            cursor += 1
        elif mark == "\\":
            continue
        else:
            raise SystemExit(f"{mibname}: unreadable line in its patch: {chunk!r}")

    out.extend(lines[cursor:])

    return "\n".join(out).encode()


IEEE_DIRECTORY = "https://www.ieee802.org/1/files/public/MIBs/"

#: A file in the IEEE 802.1 MIB directory: module name, then the revision it
#: carries. A few of the oldest are missing the trailing Z.
IEEE_FILE = re.compile(r'href="((.+?)-(\d{12})Z?\.mib)"')


@cache
def ieee_index() -> dict[str, tuple[str, str]]:
    """The newest published revision of every module in the IEEE directory.

    Returns:
        Module name mapped to its newest ``(revision, filename)``.
    """
    listing = download(IEEE_DIRECTORY).decode("utf-8", "replace")
    newest: dict[str, tuple[str, str]] = {}

    for filename, mibname, revision in IEEE_FILE.findall(listing):
        if mibname not in newest or revision > newest[mibname][0]:
            newest[mibname] = (revision, filename)

    if not newest:
        raise SystemExit(f"{IEEE_DIRECTORY}: no MIB files found in the listing")

    return newest


def ieee_current(mibname: str) -> tuple[str, str]:
    """The revision and URL of the newest published copy of *mibname*."""
    published = ieee_index().get(mibname)

    if published is None:
        raise SystemExit(f"{mibname}: no longer published at {IEEE_DIRECTORY}")

    revision, filename = published

    return revision, IEEE_DIRECTORY + filename


def as_utf8(data: bytes) -> bytes:
    """Re-encode a publisher's text as UTF-8 if it is not already.

    IEEE 802.1 serves at least one module (IEEE8021-PAE-MIB) with Windows-1252
    smart quotes in its DESCRIPTIONs. Bundling those bytes verbatim would put a
    file in the package that ``read_text()`` cannot open, and pysmi's own
    reader decodes with ``errors="ignore"``, which would silently drop the
    characters out of the descriptions it generates. Transcoding is
    deterministic, so ``--check`` still compares byte for byte.
    """
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252").encode("utf-8")

    return data


def fetch(mibname: str, entry: dict[str, Any]) -> bytes:
    """Fetch one module's authoritative text and apply its patch, if it has one.

    A ``local`` module has no upstream to fetch, so the bundled copy is
    returned unchanged and ``--check`` has nothing to compare it against.
    """
    if entry["source"] == "local":
        return (DEST / mibname).read_bytes()

    if entry["source"] == "rfc":
        data = extract(mibname, entry["rfc"])
    elif entry["source"] == "ieee802.1":
        data = as_utf8(download(ieee_current(mibname)[1]))
    else:
        data = as_utf8(download(entry["url"]))

    if "patch" in entry:
        data = apply_patch(data, (PATCHES / entry["patch"]).read_text(), mibname)

    return data


def obsoleted_by(rfc: int) -> list[str]:
    """Name the RFCs that have obsoleted *rfc*, if any."""
    metadata = json.loads(download(RFC_METADATA.format(rfc)))

    return metadata.get("obsoleted_by") or []


def revision_of(data: bytes) -> str:
    """The newest MODULE-IDENTITY revision in *data*, for the inventory page."""
    found = _REVISION.findall(data.decode("utf-8", "replace"))
    if not found:
        return "--"

    newest = max(stamp.rstrip("Z") for stamp in found)
    if len(newest) < 12:
        century = "19" if int(newest[:2]) >= 70 else "20"
        newest = century + newest

    return f"{newest[:4]}-{newest[4:6]}-{newest[6:8]}"


def check() -> int:
    """Report any bundled file that no longer matches its source, changing nothing.

    Comparing against the source catches a MIB whose publisher has revised it,
    but an RFC's text never changes -- an RFC-sourced entry would compare equal
    forever even once a later RFC had replaced it. So the pinned RFCs are
    checked for obsoletion separately, which is the way ENTITY-MIB came to be
    eight years stale in the first place.

    An obsoleted RFC is not on its own a stale pin. Half the time the successor
    publishes the module under a *different* name -- RFC 1757 obsoletes RFC 1271
    but calls the module RMON-MIB, so RFC1271-MIB only ever existed in RFC 1271
    and pinning it there is the only thing that can be right. Those successors
    are recorded in the manifest as ``successors_reviewed``, naming what each
    one publishes instead, and are not reported again; a successor nobody has
    looked at yet still is.

    Returns:
        The process exit code: 0 if every bundled file is current, 1 otherwise.
    """
    modules = manifest()
    stale = []

    for rfc in sorted({e["rfc"] for e in modules.values() if e["source"] == "rfc"}):
        pinned = sorted(
            name for name, entry in modules.items() if entry.get("rfc") == rfc
        )
        reviewed = {
            successor
            for name in pinned
            for successor in modules[name].get("successors_reviewed", {})
        }
        successors = [rfc_id for rfc_id in obsoleted_by(rfc) if rfc_id not in reviewed]

        if successors:
            stale.append(
                f"RFC {rfc} obsoleted by {', '.join(successors)}"
                f" -- pinned by {', '.join(pinned)}"
            )

    for mibname, entry in sorted(modules.items()):
        path = DEST / mibname

        if not path.is_file():
            stale.append(f"{mibname}: not bundled yet")
            continue

        if entry["source"] == "local":
            continue

        if path.read_bytes() != fetch(mibname, entry):
            stale.append(f"{mibname}: bundled copy no longer matches its source")

    for path in sorted(DEST.iterdir()):
        if path.is_file() and not path.name.startswith("__"):
            if path.name not in modules:
                stale.append(f"{path.name}: bundled but not in the manifest")

    if stale:
        sys.stderr.write(
            "Bundled MIBs out of date:\n"
            + "\n".join(f"  {line}" for line in stale)
            + "\n"
        )
        return 1

    sys.stdout.write(f"All {len(modules)} bundled MIBs are current.\n")
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
    modules = manifest()
    DEST.mkdir(parents=True, exist_ok=True)

    # Staged on DEST's own filesystem, so committing a file is an atomic
    # rename rather than a copy that could itself be interrupted.
    with tempfile.TemporaryDirectory(dir=DEST.parent) as staging:
        staging_dir = pathlib.Path(staging)

        for mibname, entry in sorted(modules.items()):
            data = fetch(mibname, entry)
            (staging_dir / mibname).write_bytes(data)
            sys.stdout.write(f"{mibname}: {len(data)} bytes\n")

        if verify(staging_dir) != 0:
            sys.stderr.write(
                "Staged bundle failed to verify; leaving the existing bundle untouched.\n"
            )
            return 1

        for path in DEST.iterdir():
            if path.is_file() and not path.name.startswith("__"):
                if path.name not in modules:
                    path.unlink()

        for mibname in modules:
            (staging_dir / mibname).replace(DEST / mibname)

    record_ieee_revisions(modules)

    return docs()


def record_ieee_revisions(modules: dict[str, dict[str, Any]]) -> None:
    """Write back the IEEE 802.1 revision each bundled copy was taken from.

    The source is the newest file in the directory rather than a fixed URL, so
    the manifest is where the answer to "which revision is in the package"
    lives. Recorded after the refresh, from the same cached listing the fetches
    used, so the two cannot disagree.
    """
    stored = json.loads(MANIFEST.read_text())
    changed = False

    for mibname, entry in modules.items():
        if entry["source"] != "ieee802.1":
            continue

        revision = ieee_current(mibname)[0]

        if stored["modules"][mibname].get("revision") != revision:
            stored["modules"][mibname]["revision"] = revision
            changed = True
            sys.stdout.write(f"{mibname}: now at IEEE revision {revision}\n")

    if changed:
        MANIFEST.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n")


def verify(source: pathlib.Path | None = None) -> int:
    """Compile every bundled MIB against a directory containing the bundle,
    nothing else.

    A MIB that cannot compile standalone against its bundled siblings would
    make the fallback source useless for exactly the case it exists for.

    Args:
        source: directory holding one file per name in the manifest. Defaults
            to the bundle already on disk; *update* passes a staging directory
            to verify a refreshed set before committing it.

    Returns:
        The process exit code: 0 if everything compiles, 1 otherwise.
    """
    from pysmi.codegen import JsonCodeGen
    from pysmi.compiler import MibCompiler
    from pysmi.parser import SmiV1CompatParser
    from pysmi.reader import FileReader
    from pysmi.writer import CallbackWriter

    names = sorted(manifest())

    # One malformed OID can make the code generator walk a cycle, and the
    # default limit turns that into a bare RecursionError a long way from the
    # MIB that caused it. Deep is normal here; unbounded is the bug.
    sys.setrecursionlimit(20000)

    compiler = MibCompiler(
        SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None)
    )
    compiler.add_sources(FileReader(str(source if source is not None else DEST)))
    processed = compiler.compile(*names, ignoreErrors=True)

    failed = {
        name: status
        for name, status in processed.items()
        if name in names and status != "compiled"
    }

    if failed:
        sys.stderr.write("Bundled MIBs failed to compile:\n")
        for name, status in sorted(failed.items()):
            sys.stderr.write(f"  {name}: {status}\n")
        return 1

    sys.stdout.write(f"All {len(names)} bundled MIBs compile.\n")
    return 0


def docs() -> int:
    """Rewrite the inventory page from the manifest and the bundled files.

    The page is generated rather than kept by hand so that it cannot drift from
    what is actually bundled -- an inventory nobody trusts is worse than none.

    Returns:
        The process exit code: 0.
    """
    modules = manifest()

    def source_of(mibname: str, entry: dict[str, Any]) -> str:
        if entry["source"] == "rfc":
            return f":rfc:`{entry['rfc']}`"
        if entry["source"] == "local":
            return "maintained here"
        if entry["source"] == "ieee802.1":
            # The pinned revision, not the directory: which file the bundled
            # copy came from is the thing a reader needs.
            revision = entry["revision"]
            return f"`IEEE 802.1 <{IEEE_DIRECTORY}{mibname}-{revision}Z.mib>`__"
        # Anonymous, so that thirteen links labelled "IANA" do not each
        # register a duplicate target name.
        return f"`IANA <{entry['url']}>`__"

    # A csv-table rather than an aligned one: the cells hold URLs, and padding
    # every row out to the longest of those would make the source unreadable
    # for no gain in what Sphinx renders.
    rows = [
        '   "{}", "{}", "{}", "{}"'.format(
            mibname,
            source_of(mibname, entry),
            revision_of((DEST / mibname).read_bytes()),
            "yes" if "patch" in entry else "",
        )
        for mibname, entry in sorted(modules.items())
    ]

    patched = sorted(name for name, entry in modules.items() if "patch" in entry)
    historical = sorted(
        name for name, entry in modules.items() if "successors_reviewed" in entry
    )
    # Counted rather than stated: these are the entries the compiler cannot
    # adjudicate on revision, so the page must not understate how many.
    unstamped = sum(
        1 for mibname in modules if revision_of((DEST / mibname).read_bytes()) == "--"
    )

    text = [
        PAGE_HEADER.format(
            total=len(modules), patched=len(patched), unstamped=unstamped
        ),
        ".. csv-table::",
        '   :header: "Module", "Source", "Revision", "Patched"',
        "   :widths: 34, 22, 12, 8",
        "",
        *rows,
        "",
        PAGE_PATCHES,
        *(f"``{name}``\n    {modules[name]['reason']}\n" for name in patched),
        PAGE_HISTORICAL,
        *(
            f"``{name}``\n    "
            + "; ".join(
                f"obsoleted by RFC {successor[3:]}, which publishes ``{instead}``"
                for successor, instead in sorted(
                    modules[name]["successors_reviewed"].items()
                )
            )
            + ".\n"
            for name in historical
        ),
        PAGE_FOOTER,
    ]

    INVENTORY.write_text("\n".join(text))
    sys.stdout.write(f"Wrote {INVENTORY.relative_to(ROOT)}.\n")

    return 0


PAGE_HEADER = """\

.. _bundled-mibs:

Bundled base MIBs
=================

.. warning::

   This page is generated by ``scripts/update_bundled_mibs.py``. Edit the
   manifest, ``scripts/bundled_mibs.json``, not this file.

pysmi carries {total} MIB modules of its own, in ``pysmi/mibs/asn1/``. They are
a *source*, not a fallback: they are registered ahead of the sources a caller
configures, and a caller's own copy wins only by carrying a newer
MODULE-IDENTITY revision -- not merely by being the caller's. See
:doc:`/mibdump` for ``--prefer-mib-source`` and ``--no-bundled-mibs``, which
override that outright.

{unstamped} of the modules below carry no MODULE-IDENTITY at all, so there is
no revision to compare and the bundled copy is the one that gets used. Every
one of them is a pre-SMIv2 module or an SMI module proper, whose text was fixed
when its RFC was published and cannot be revised except as a new module under a
new name -- so the copy here cannot go stale under a caller who has a better
one. That is the whole reason membership is restricted the way it is below.

Every module below is traceable to a publisher: the text is cut out of the RFC
that currently defines it, or fetched from IANA's registry, or fetched from the
IEEE 802.1 MIB directory. Nothing here is hand-authored MIB text, and
``scripts/update_bundled_mibs.py --check`` re-fetches all of it and reports
anything that no longer matches. RFC-sourced entries are also checked against
the RFC Editor for obsoletion, since an RFC's text never changes but a later
RFC can replace it.

{patched} modules carry a patch, listed under :ref:`bundled-mib-patches` below,
because their published text does not compile as published.

Membership is decided by whether a module has a publisher we can re-fetch and
diff -- not by which directory a mirror files it under, and not by whether that
publisher still revises it. MIB collections routinely file CableLabs, DMTF, MEF
and SCTE modules as "standard", and a bundled copy of a module nobody publishes
could never be told apart from a stale one. Modules with no live authoritative
source are therefore not bundled, however widely they are imported; they remain
available from https://pysnmp.github.io/mibs/asn1/ as before.

A module its publisher still revises *is* bundled -- IANA's registries and the
IEEE 802.1 directory are tracked at whatever they currently publish, not frozen
at a dated file. Freezing would only make staleness undetectable: the whole
point of ``--check`` is that a revision upstream gets reported, and a caller
who has the newer copy already outranks the bundle on revision.

Inventory
---------
"""

PAGE_PATCHES = """\
.. _bundled-mib-patches:

Patched modules
---------------

The published text of these modules does not compile. Each is bundled as its
publisher's text with a patch applied, kept in ``scripts/mib-patches/`` and
re-applied on every refresh; a patch whose context has moved makes the refresh
fail rather than silently fuzzing. The defect each one repairs:
"""

PAGE_HISTORICAL = """\
.. _bundled-mib-historical:

Modules pinned to an obsoleted RFC
----------------------------------

An obsoleted RFC is not on its own a stale pin. For these modules the successor
RFC publishes the replacement under a *different* module name, so the pinned
RFC is the only one that ever defined the module named here and pinning it
there is the only thing that can be right. Each successor below has been looked
at and recorded in the manifest, so ``--check`` does not report it again -- a
successor nobody has looked at yet still is.
"""

PAGE_FOOTER = """
Not bundled
-----------

Modules with no live authoritative source are left out, including every module
that only a defunct or paywalled body ever published (ATM Forum, DMTF, IEC),
vendor modules that MIB collections misfile as standard (CableLabs ``DOCS-*``
and ``CLAB-*``, SCTE ``SCTE-HMS-*``, MEF ``MEF-*``, Novell ``TCPIPX-MIB``), and
draft-named predecessors of modules the IETF went on to publish under a
different name -- ``MPLS-LSR-MIB`` for ``MPLS-LSR-STD-MIB``, ``IGMP-MIB`` for
``IGMP-STD-MIB``, and so on. Two modules are left out despite having an RFC:
``COFFEE-POT-MIB`` (RFC 2325, an April Fools' RFC whose ASN.1 does not parse)
and ``TCPIPX-MIB`` (RFC 1792, rooted under ``enterprises`` and so a vendor
module in any case).

All of them remain available from https://pysnmp.github.io/mibs/asn1/, which is
where pysmi looks by default.
"""


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    if "--verify" in sys.argv[1:]:
        sys.exit(verify())
    if "--docs" in sys.argv[1:]:
        sys.exit(docs())
    sys.exit(update())
