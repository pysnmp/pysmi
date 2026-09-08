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
    uv run scripts/update_bundled_mibs.py --check-mirror  # report mirror disagreement
    uv run scripts/update_bundled_mibs.py --verify  # compile the bundle as it stands
    uv run scripts/update_bundled_mibs.py --docs    # rewrite the inventory page
    uv run scripts/update_bundled_mibs.py --promote MODULE ...  # future/ -> asn1/

For the modules listed here pysmi is the source of truth and
https://pysnmp.github.io/mibs/asn1/ follows, not the other way round -- which
matters because that mirror is also what ``mibdump`` and ``mibcopy`` reach for
by default. A caller can be served pysmi's SNMPv2-TC and the mirror's copy of
something that imports it, so the two disagreeing is a compile resolving
against two editions of one specification. ``--check-mirror`` is what says
whether they still agree.

``pysmi/mibs/bundled_mibs.json`` is the whole bundle manifest: one entry per
module, naming where its text comes from and which module replaced it. It sits
in the package, not beside this script, because consumers read the supersession
it records at runtime -- see :py:func:`pysmi.mibs.successor_for`. Adding or
dropping a module means editing that file and re-running this script; no other
file in the source tree names an individual bundled MIB.

Two tiers: carried, and held
----------------------------

The manifest covers two directories, and an entry's ``tier`` says which. Absent
-- the default -- the module is in ``pysmi/mibs/asn1/``: shipped in the wheel,
registered as a compiler source, compiled into ``pysmi/mibs/pysnmp/`` at build
time, and re-fetched by ``--check``. ``"tier": "future"`` means the module is
in ``pysmi/mibs/future/`` instead, and none of that is true of it.

Held modules got there by being unused, not by being unfit. Nothing in the
corpus pysmi is built against imports one: not a module in the ~5,500 at
https://github.com/pysnmp/mibs, not pysnmp, not either project's own code,
tests or documentation. They were added as parser pressure tests -- the point
was to find modules the parser could not read, and it did -- and the bundle
went on carrying them afterwards at the cost of a re-fetch each per ``--check``
run and a compile each per wheel built.

So the tier is a statement about maintenance, not about quality:

- ``--check`` and ``update`` skip the held tier entirely. A copy there may be
  years behind its publisher and nothing will report it. That is the whole
  saving, and it is why holding a module is not free: pysmi vouches for the
  currency of what it ships, and can only keep saying that about a set it
  re-checks.
- ``verify`` compiles the carried tier only, and ``hatch_build.py`` renders
  only that.
- ``--check`` still checks, offline, that both directories hold exactly the
  files their entries say they do. See :py:func:`misfiled`.

Promotion is deliberately cheap, because the bar is deliberately low: **any use
justifies it.** ``--promote MODULE`` moves the file, clears the ``tier``,
re-fetches the module from its publisher -- a held copy is presumed stale --
verifies the enlarged bundle and rewrites the inventory page. Since the
manifest entry never went anywhere, nothing about the module's provenance has
to be established a second time. There is no matching ``--defer``: deferring is
a judgement about the whole corpus rather than about one module, and it belongs
in a reviewed change rather than in a flag.

Every bundled byte is traceable to a publisher
----------------------------------------------

The rule this bundle keeps is that nothing here is hand-authored MIB text. Each
entry names the publisher its text came from in ``source``, and those that can
be re-fetched carry the URL or RFC number to re-fetch them from. The kinds with
machinery behind them:

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

``internet-draft``
    The module is cut out of the IETF draft that defines it, at the archived
    revision the manifest pins in ``draft``. A revision in that archive is
    immutable, so a copy taken from one cannot drift, and ``--check`` re-cuts
    and compares it. The archive serves its text with the form feeds stripped,
    so :py:func:`unpaginate` depaginates on the footer line instead, and the
    draft's module indent comes off so the text sits at the left margin the way
    an RFC prints it.

    An entry naming only a working-group document -- no revision -- is
    ``archived``: there is no single document to re-cut from.

``local``
    Five compatibility modules that no publisher ships, so there is nothing to
    fetch and ``--check`` has nothing to compare against. RFC-1212 and RFC-1215
    exist because those RFCs define a macro in prose rather than as an ASN.1
    module. SNMPv2-SMI-v1, SNMPv2-TC-v1 and SNMPv2-CONF-v1 are SMIC's 1994
    SNMPv1 renderings of RFC 1442, 1443 and 1444, which the SMIv2 RFCs went on
    to obsolete. The manifest records why for each.

``archived``
    Not a source kind but a flag alongside one: the publisher is named and
    real, but does not serve the text at a URL this script can fetch. CableLabs
    modules dropped from the live directory, the ATM Forum set, the IEEE and
    TIA modules absent from any public MIB directory, DMTF and SCTE behind a
    403, IEC behind a paywall, and the Internet-Drafts whose bundled text
    matches no archived revision closely enough to name one all sit here.
    ``--check`` skips them, and :py:func:`refetchable` is the one place that is
    decided.

    Any remaining entry is fetched from ``url``.

A handful of entries also carry a ``patch``. The published text of those
modules does not compile -- a truncated line left in the RFC, an IMPORTS clause
missing a symbol the module goes on to use, a bound one past the top of
Integer32. The patch is applied to the fetched text after every fetch and lives
in ``scripts/mib-patches/`` where it can be read; the manifest's ``reason``
says what defect it repairs. Bundling the pysnmp/mibs mirror's hand-repaired
copy instead would have hidden all of that.

What belongs in the bundle
--------------------------

A module published by a standards body or a multivendor association, whose text
is traceable to that publisher. Provenance is the gate.

Re-fetchability is **not** a condition of membership. It is a property each
entry records -- valuable, because it is what lets ``--check`` report drift,
but its absence disqualifies nothing. A publisher that serves no MIB URL, or
answers automated fetches with a 403, or puts the specification behind a
paywall, has not thereby made its modules unfit to bundle; it has only made
them modules ``--check`` stays quiet about. Roughly half the bundle's non-RFC
entries are ``archived`` for one of those reasons.

What is genuinely out of scope is a vendor's own MIB. The bundle is
vendor-neutral, and the check for that is the module's ORGANIZATION clause, not
the directory a mirror filed it under -- which is how LLDP-EXT-HM-MIB, authored
by Hirschmann, came to sit among the standards. See
``docs/source/bundled-mibs.rst`` for the inventory and for what is deliberately
left out.

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
frozen. Where a publisher serves nothing fetchable the first mechanism is
unavailable, but the second still applies: a caller's dated, newer copy beats
the bundled one regardless of whether ``--check`` could see the difference.

The one place the old argument still holds is a module with no MODULE-IDENTITY:
there is no revision for ``--check`` to report against and none for a caller's
copy to beat, so the bundled copy is simply used. All 37 such entries here are
pre-SMIv2 modules or SMI modules proper -- RFC1213-MIB, SNMPv2-SMI, the PPP and
RFC1xxx-MIB modules, the SMIv1 shims -- whose text an RFC or a 1994 tool run
froze and which cannot be revised
except as a new module under a new name. An undated module that upstream still
revises would shadow a caller's better copy for good; there is no such module
here, and ``tests/test_compiler_bundled_mibs.py`` is what keeps it that way.
"""

import json
import pathlib
import re
import sys
import tempfile
import textwrap
import urllib.request
from functools import cache
from typing import Any

from pysmi.mibinfo import strip_comments

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
DEST = ROOT / "pysmi" / "mibs" / "asn1"
FUTURE = ROOT / "pysmi" / "mibs" / "future"
MANIFEST = ROOT / "pysmi" / "mibs" / "bundled_mibs.json"
PATCHES = HERE / "mib-patches"
INVENTORY = ROOT / "docs" / "source" / "bundled-mibs.rst"

RFC = "https://www.rfc-editor.org/rfc/rfc{}.txt"
RFC_METADATA = "https://www.rfc-editor.org/rfc/rfc{}.json"

#: A module's MODULE-IDENTITY revision, for the inventory page. Read straight
#: off the text rather than parsed: the inventory is a listing, not a compile.
_REVISION = re.compile(r'(?:LAST-UPDATED|REVISION)\s+"(\d{6,14}Z?)"')


def manifest() -> dict[str, dict[str, Any]]:
    """Read the bundle manifest -- both tiers, keyed by module name."""
    modules: dict[str, dict[str, Any]] = json.loads(MANIFEST.read_text())["modules"]

    return modules


def deferred(entry: dict[str, Any]) -> bool:
    """Whether *entry* is held in ``future/`` rather than searched.

    The key is absent on a bundled entry, so being in the search path is the
    default and promoting a module means deleting a key rather than setting
    one. See :py:mod:`pysmi.mibs.future`.
    """
    return entry.get("tier") == "future"


def bundled(
    modules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """The manifest entries in ``asn1/``, which everything downstream reads."""
    return {
        name: entry
        for name, entry in (modules if modules is not None else manifest()).items()
        if not deferred(entry)
    }


def future(
    modules: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """The manifest entries in ``future/``, which nothing reads."""
    return {
        name: entry
        for name, entry in (modules if modules is not None else manifest()).items()
        if deferred(entry)
    }


def directory(entry: dict[str, Any]) -> pathlib.Path:
    """Where *entry*'s text is kept."""
    return FUTURE if deferred(entry) else DEST


def download(url: str) -> bytes:
    """Read one URL."""
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - the URLs come from the manifest in this repository, not from a MIB
        data: bytes = response.read()

    return data


#: The line an RFC or Internet-Draft ends each page with.
PAGINATION_FOOTER = re.compile(r"\[Page\s+\d+\]\s*$")


def unpaginate(text: str) -> str:
    """Drop the footer and header that straddle each page break.

    Both the blank lines a running header sits in and the ones above the page
    footer go with them, so that a module's text reads as it would have without
    the page breaks. Leaving them in produces a file that still compiles but
    diffs badly against every other copy of the same module.

    A document with no form feed in it at all is depaginated on its footer
    lines instead -- see :py:func:`unpaginate_unfed`. Every RFC has form feeds;
    the IETF's Internet-Draft archive serves text that has had them stripped.
    """
    if "\f" not in text:
        return unpaginate_unfed(text)

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
        if lines and PAGINATION_FOOTER.search(lines[-1]):
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()

        pages.append("\n".join(lines))

    return "\n".join(pages)


def unpaginate_unfed(text: str) -> str:
    """Drop page furniture from a document whose form feeds were stripped.

    The footer line is the anchor: everything from it through the running
    header that follows goes, with the blank lines on either side of both. A
    document that never paginated has no footer lines and comes back unchanged.
    """
    lines = text.split("\n")
    out: list[str] = []
    index = 0

    while index < len(lines):
        if not PAGINATION_FOOTER.search(lines[index]):
            out.append(lines[index])
            index += 1
            continue

        while out and not out[-1].strip():
            out.pop()

        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index < len(lines):
            index += 1  # The running header.
        while index < len(lines) and not lines[index].strip():
            index += 1

    # The form-feed path drops the blank lines above every page footer, the
    # document's last page included. Do the same here, so a document reads the
    # same whichever path depaginated it.
    while out and not out[-1].strip():
        out.pop()

    return "\n".join(out)


#: An RFC may put the module name and ``DEFINITIONS`` on separate lines -- RFC
#: 1158 does -- so the two are matched across a newline, not just a space.
BEGINS = re.compile(
    r"^[ \t]*([A-Za-z0-9][\w-]*)[ \t\r\n]+DEFINITIONS"
    r"[ \t\r\n]*(?:IMPLICIT[ \t]+TAGS[ \t\r\n]*)?::=[ \t\r\n]*BEGIN\b",
    re.M,
)
ENDS = re.compile(r"^[ \t]*END[ \t]*$", re.M)


def cut(mibname: str, body: str, document: str) -> bytes:
    """Cut one MIB module out of *body*, an already unpaginated document.

    A document can carry several modules, and a module can carry a MACRO whose
    own END is not the module's, so the module runs from its BEGIN to the
    last END before whatever module comes next.
    """
    starts = [(match.group(1), match.start()) for match in BEGINS.finditer(body)]

    for index, (name, start) in enumerate(starts):
        if name != mibname:
            continue

        stop = starts[index + 1][1] if index + 1 < len(starts) else len(body)
        ends = list(ENDS.finditer(body, start, stop))
        if not ends:
            break

        return (body[start : ends[-1].end()] + "\n").encode()

    raise SystemExit(f"{mibname}: no such module in {document}")


def extract(mibname: str, rfc: int) -> bytes:
    """Cut one MIB module out of the RFC that defines it."""
    body = unpaginate(download(RFC.format(rfc)).decode("utf-8", "replace"))

    return cut(mibname, body, f"RFC {rfc}")


def extract_url(mibname: str, url: str) -> bytes:
    """Cut one MIB module out of the document *url* serves.

    Some publishers ship the module inside a specification rather than as a
    file of its own -- sFlow.org publishes SFLOW-MIB inside the sFlow version
    5 specification. Cutting it out keeps the entry re-fetchable, so
    ``--check`` re-cuts and compares rather than trusting the copy here.
    """
    body = unpaginate(download(url).decode("utf-8", "replace"))

    return textwrap.dedent(cut(mibname, body, url).decode()).encode()


def extract_draft(mibname: str, draft: str) -> bytes:
    """Cut one MIB module out of the Internet-Draft that defines it.

    A draft prints its module indented under the surrounding prose, where an
    RFC prints it at the left margin. The bundle holds every module the way an
    RFC prints it, so the indent every line shares comes off -- otherwise the
    same module would diff against every other copy of itself on whitespace
    alone.
    """
    body = unpaginate(download(DRAFT_ARCHIVE.format(draft)).decode("utf-8", "replace"))

    return textwrap.dedent(cut(mibname, body, draft).decode()).encode()


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

DRAFT_ARCHIVE = "https://www.ietf.org/archive/id/{}.txt"

#: How each ``source`` kind is named on the inventory page. Taken from the
#: module's own ORGANIZATION clause rather than from the directory a mirror
#: filed it under, which is how an LLDP-EXT-\* module authored by a single
#: vendor came to sit among the standards.
PUBLISHERS = {
    "atm-forum": "ATM Forum",
    "cablelabs": "CableLabs",
    "dmtf": "DMTF",
    "fibre-alliance": "Fibre Alliance",
    "hirschmann": "Hirschmann Automation & Control",
    "iana": "IANA",
    "iec": "IEC",
    "ieee802.1": "IEEE 802.1",
    "ieee802.11": "IEEE 802.11",
    "ieee802.17": "IEEE 802.17",
    "ieee802.3": "IEEE 802.3",
    "internet-draft": "IETF Internet-Draft",
    "mef": "MEF",
    "profibus": "PROFIBUS International",
    "scte": "SCTE",
    "sflow": "sFlow.org",
    "tia": "TIA",
    "unattributed": "unattributed",
}

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


def refetchable(entry: dict[str, Any]) -> bool:
    """Whether *entry* names something ``--check`` can re-fetch and diff.

    False for a ``local`` module, which no publisher ships, and for an
    ``archived`` one, whose publisher does not serve the text at a URL. Neither
    is a defect: see the module docstring on why re-fetchability is a property
    the bundle records rather than a condition it imposes.
    """
    return entry["source"] != "local" and not entry.get("archived")


def fetch(mibname: str, entry: dict[str, Any]) -> bytes:
    """Fetch one module's authoritative text and apply its patch, if it has one.

    A module that is not :py:func:`refetchable` has no upstream to fetch, so
    the bundled copy is returned unchanged and ``--check`` has nothing to
    compare it against.
    """
    if not refetchable(entry):
        return (directory(entry) / mibname).read_bytes()

    if entry["source"] == "rfc":
        data = extract(mibname, entry["rfc"])
    elif entry["source"] == "internet-draft":
        data = extract_draft(mibname, entry["draft"])
    elif entry["source"] == "ieee802.1":
        data = as_utf8(download(ieee_current(mibname)[1]))
    elif entry.get("extract"):
        data = extract_url(mibname, entry["url"])
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
    """The newest MODULE-IDENTITY revision in *data*, for the inventory page.

    Comments are stripped first, for the same reason
    :py:func:`pysmi.compiler.revision_of` strips them: ATM-FORUM-MIB and the
    three LAN-EMULATION modules ship a commented-out MODULE-IDENTITY, and
    reading a date out of it made the inventory table date a module that the
    page's own header counts as undated.
    """
    found = _REVISION.findall(strip_comments(data.decode("utf-8", "replace")))
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

    ``future/`` is out of scope for all of that, deliberately: nothing reads
    those copies, so a revision upstream changes nothing until the module is
    promoted, and ``--promote`` re-fetches it at that point. What is still
    checked there is that the directory and the manifest agree about which
    modules it holds -- an offline check, and the one that would otherwise let
    a file go missing unnoticed for years.

    Returns:
        The process exit code: 0 if every bundled file is current, 1 otherwise.
    """
    modules = manifest()
    searched = bundled(modules)
    stale = []

    for rfc in sorted({e["rfc"] for e in searched.values() if e["source"] == "rfc"}):
        pinned = sorted(
            name for name, entry in searched.items() if entry.get("rfc") == rfc
        )
        # Reviewed successors are read off every entry pinned to the RFC, held
        # tier included: an RFC pinned by both tiers has been looked at once,
        # and which directory the reviewer wrote the answer on is an accident.
        reviewed = {
            successor
            for name, entry in modules.items()
            if entry.get("rfc") == rfc
            for successor in entry.get("successors_reviewed", {})
        }
        successors = [rfc_id for rfc_id in obsoleted_by(rfc) if rfc_id not in reviewed]

        if successors:
            stale.append(
                f"RFC {rfc} obsoleted by {', '.join(successors)}"
                f" -- pinned by {', '.join(pinned)}"
            )

    for mibname, entry in sorted(searched.items()):
        path = DEST / mibname

        if not path.is_file():
            continue  # misfiled() reports it below.

        if not refetchable(entry):
            continue

        if path.read_bytes() != fetch(mibname, entry):
            stale.append(f"{mibname}: bundled copy no longer matches its source")

    stale.extend(misfiled(modules))

    if stale:
        sys.stderr.write(
            "Bundled MIBs out of date:\n"
            + "\n".join(f"  {line}" for line in stale)
            + "\n"
        )
        return 1

    sys.stdout.write(
        f"All {len(searched)} bundled MIBs are current; "
        f"{len(modules) - len(searched)} held in future/.\n"
    )
    return 0


def held_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """The MIB files in *directory*, and nothing else it happens to hold.

    A module's file is named exactly as the module, so it never carries an
    extension; ``__init__.py`` and ``README.md`` are the directories' own
    furniture rather than modules.
    """
    return sorted(
        path for path in directory.iterdir() if path.is_file() and "." not in path.name
    )


def misfiled(modules: dict[str, dict[str, Any]]) -> list[str]:
    """Report every module whose file is not where the manifest says it is.

    Both directions and both directories: a file no entry names, a file in the
    tier the entry does not name, an entry with no file at all. Offline, which
    is what lets it cover ``future/`` -- nothing re-fetches those copies, so
    losing one would otherwise go unnoticed until somebody promoted it.
    """
    wrong = []

    for tier, listed in (("asn1", bundled(modules)), ("future", future(modules))):
        held = ROOT / "pysmi" / "mibs" / tier

        for path in held_files(held):
            if path.name not in listed:
                wrong.append(
                    f"{path.name}: in {tier}/ but "
                    + (
                        "the manifest files it under the other tier"
                        if path.name in modules
                        else "not in the manifest"
                    )
                )

        for mibname in listed:
            if not (held / mibname).is_file():
                wrong.append(
                    f"{mibname}: the manifest files it under {tier}/, "
                    "which holds no such file"
                )

    return wrong


MIRROR = "https://pysnmp.github.io/mibs/asn1/{}"


def check_mirror() -> int:
    """Report where the pysnmp/mibs mirror disagrees with the bundle.

    For the modules bundled here pysmi is the source of truth and the mirror
    follows, but the mirror is also what pysmi itself reaches for by default
    when a module is not bundled -- ``mibdump`` and ``mibcopy`` both point at
    it. So a caller can be served pysmi's copy of SNMPv2-TC and the mirror's
    copy of a module that imports it, and if the two disagree that is a compile
    resolving against two different editions of the same specification.

    Separate from ``--check`` because it answers a different question and has a
    different remedy: ``--check`` finding drift means re-run ``update`` here,
    while this finding drift means the mirror needs a pull request. Reported as
    a list rather than one failure per module, since a batch of them usually
    has a single cause.

    Only the searched tier is compared. The mirror publishes what pysmi
    bundles, so a module held in ``future/`` is one the mirror has no copy of
    to disagree with, and asking for 275 of them would be 275 requests for a
    404 apiece.

    Returns:
        The process exit code: 0 if the mirror matches the bundle, 1 otherwise.
    """
    modules = bundled()
    diverged = []
    unreachable = []

    for mibname in sorted(modules):
        try:
            served = download(MIRROR.format(mibname))
        except Exception as exc:  # noqa: BLE001 - one unreachable module must not end the sweep
            unreachable.append(f"{mibname}: {exc}")
            continue

        carried = (DEST / mibname).read_bytes()

        if served == carried:
            continue

        theirs = revision_of(served)
        ours = revision_of(carried)

        if theirs == ours:
            diverged.append(f"{mibname}: same revision ({ours}), different text")
        else:
            diverged.append(f"{mibname}: mirror at {theirs}, bundled {ours}")

    for line, stream in ((unreachable, sys.stderr), (diverged, sys.stderr)):
        if line:
            stream.write("\n".join(f"  {entry}" for entry in line) + "\n")

    if diverged:
        sys.stderr.write(
            f"\n{len(diverged)} of {len(modules)} bundled modules disagree with "
            f"{MIRROR.format('')}\nOpen a pull request against pysnmp/mibs to "
            "bring src/standard back into line.\n"
        )
        return 1

    if unreachable:
        sys.stderr.write("Mirror comparison incomplete.\n")
        return 1

    sys.stdout.write(f"The mirror matches all {len(modules)} bundled MIBs.\n")
    return 0


def update() -> int:
    """Refresh every bundled file from upstream, then compile-verify the set.

    Every fetch and the verify compile happen against a staging directory
    first; DEST is only touched once every file has been fetched and the
    whole staged set compiles clean, so a network failure partway through,
    or an upstream MIB that no longer compiles, leaves the existing bundle
    exactly as it was rather than a mix of old and new files.

    ``future/`` is left alone. Its copies are not maintained -- that is what
    holding a module there means -- and ``--promote`` is what re-fetches one,
    at the point something needs it.

    Returns:
        The process exit code: 0 on success, 1 if the refreshed set fails to
        compile.
    """
    modules = bundled()
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

        for path in held_files(DEST):
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
        if entry["source"] != "ieee802.1" or not refetchable(entry):
            continue

        revision = ieee_current(mibname)[0]

        if stored["modules"][mibname].get("revision") != revision:
            stored["modules"][mibname]["revision"] = revision
            changed = True
            sys.stdout.write(f"{mibname}: now at IEEE revision {revision}\n")

    if changed:
        MANIFEST.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n")


def verify(source: pathlib.Path | None = None, names: list[str] | None = None) -> int:
    """Compile every bundled MIB against a directory containing the bundle,
    nothing else.

    A MIB that cannot compile standalone against its bundled siblings would
    make the fallback source useless for exactly the case it exists for.

    Args:
        source: directory holding one file per name being verified. Defaults
            to the bundle already on disk; *update* and *promote* pass a
            staging directory to verify a set before committing it.
        names: the modules to compile. Defaults to the searched tier;
            *promote* passes that tier plus the modules it is adding, since
            the manifest on disk does not name them as bundled yet.

    Returns:
        The process exit code: 0 if everything compiles, 1 otherwise.
    """
    from pysmi.codegen import JsonCodeGen
    from pysmi.compiler import MibCompiler
    from pysmi.parser import SmiV1CompatParser
    from pysmi.reader import FileReader
    from pysmi.writer import CallbackWriter

    if names is None:
        names = sorted(bundled())

    # One malformed OID can make the code generator walk a cycle, and the
    # default limit turns that into a bare RecursionError a long way from the
    # MIB that caused it. Deep is normal here; unbounded is the bug.
    sys.setrecursionlimit(20000)

    # useBundledMibs=False or this verifies the wrong thing: the compiler
    # registers the *installed* pysmi.mibs.asn1 as a priority source, which
    # would shadow the staging directory update() passes here and quietly
    # re-verify the bundle already on disk.
    compiler = MibCompiler(
        SmiV1CompatParser(),
        JsonCodeGen(),
        CallbackWriter(lambda *a: None),
        useBundledMibs=False,
    )
    compiler.add_sources(FileReader(str(source if source is not None else DEST)))
    processed = compiler.compile(*names, ignoreErrors=True)

    # Every name the compile touched, not just the ones asked for. A bundled
    # module importing something the bundle does not carry shows up here as a
    # name that is "missing" while the module importing it still reports
    # "compiled" -- so filtering to the manifest would report a clean bundle
    # with a dangling import in it, which is how GBOND-MIB shipped needing an
    # IANA-GBOND-TC-MIB nothing provided.
    failed = {
        name: status for name, status in processed.items() if status != "compiled"
    }

    if failed:
        sys.stderr.write("Bundled MIBs failed to compile:\n")
        for name, status in sorted(failed.items()):
            note = "" if name in names else "  (imported by the bundle, not in it)"
            sys.stderr.write(f"  {name}: {status}{note}\n")
        return 1

    sys.stdout.write(f"All {len(names)} bundled MIBs compile.\n")
    return 0


def promote(names: list[str]) -> int:
    """Move modules from ``future/`` into the bundle, and refresh them.

    A held copy is presumed stale -- nothing has re-fetched it since it was
    deferred -- so promotion re-fetches from the publisher the manifest
    records rather than moving bytes of unknown age onto the search path.

    Staged and verified before anything on disk moves, the way *update* is: a
    promoted module that does not compile against the bundle, or that needs an
    import the bundle does not carry, leaves the tree untouched and says so.

    Args:
        names: the modules to promote.

    Returns:
        The process exit code: 0 on success, 1 if a name is not held or the
        enlarged bundle fails to verify.
    """
    stored = json.loads(MANIFEST.read_text())
    modules = stored["modules"]

    unknown = [name for name in names if name not in modules]
    if unknown:
        sys.stderr.write(f"Not in the manifest: {', '.join(sorted(unknown))}\n")
        return 1

    already = [name for name in names if not deferred(modules[name])]
    if already:
        sys.stderr.write(f"Already bundled: {', '.join(sorted(already))}\n")
        return 1

    searched = sorted(bundled(modules))

    with tempfile.TemporaryDirectory(dir=DEST.parent) as staging:
        staging_dir = pathlib.Path(staging)

        for mibname in searched:
            (staging_dir / mibname).write_bytes((DEST / mibname).read_bytes())

        for mibname in sorted(names):
            # The entry as it stands, tier and all, so that fetch() reads a
            # non-refetchable module out of future/ where its only copy is.
            data = fetch(mibname, modules[mibname])
            (staging_dir / mibname).write_bytes(data)
            sys.stdout.write(f"{mibname}: {len(data)} bytes\n")

        if verify(staging_dir, sorted(set(searched) | set(names))) != 0:
            sys.stderr.write(
                "Promoted modules failed to verify; leaving the tree untouched.\n"
            )
            return 1

        for mibname in sorted(names):
            (staging_dir / mibname).replace(DEST / mibname)
            (FUTURE / mibname).unlink()
            del modules[mibname]["tier"]

    MANIFEST.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n")
    sys.stdout.write(f"Promoted {', '.join(sorted(names))}.\n")

    return docs()


def docs() -> int:
    """Rewrite the inventory page from the manifest and the bundled files.

    The page is generated rather than kept by hand so that it cannot drift from
    what is actually bundled -- an inventory nobody trusts is worse than none.
    The held tier is listed too, by name only: a reader wanting to know whether
    pysmi knows about a module needs to find it whichever directory it sits in,
    and a Revision column over text nothing re-fetches would be a number the
    page could not stand behind.

    Returns:
        The process exit code: 0.
    """
    modules = bundled()
    held = future()

    def source_of(mibname: str, entry: dict[str, Any]) -> str:
        if entry["source"] == "rfc":
            return f":rfc:`{entry['rfc']}`"
        if entry["source"] == "local":
            return "maintained here"
        if entry["source"] == "ieee802.1" and refetchable(entry):
            # The pinned revision, not the directory: which file the bundled
            # copy came from is the thing a reader needs.
            revision = entry["revision"]
            return f"`IEEE 802.1 <{IEEE_DIRECTORY}{mibname}-{revision}Z.mib>`__"

        publisher = PUBLISHERS[entry["source"]]

        if "draft" in entry and entry["draft"].rsplit("-", 1)[-1].isdigit():
            # Only a revision the bundled text was matched against gets a link;
            # a bare working-group name has no single document to point at.
            return f"`{publisher} <{DRAFT_ARCHIVE.format(entry['draft'])}>`__"
        if not refetchable(entry):
            return publisher

        # Anonymous, so that thirteen links labelled "IANA" do not each
        # register a duplicate target name.
        return f"`{publisher} <{entry['url']}>`__"

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
    local = sorted(
        name for name, entry in modules.items() if entry["source"] == "local"
    )
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
            total=len(modules),
            patched=len(patched),
            unstamped=unstamped,
            held=len(held),
        ),
        ".. csv-table::",
        '   :header: "Module", "Source", "Revision", "Patched"',
        "   :widths: 34, 22, 12, 8",
        "",
        *rows,
        "",
        PAGE_PATCHES,
        *(f"``{name}``\n    {modules[name]['reason']}\n" for name in patched),
        PAGE_LOCAL,
        *(f"``{name}``\n    {modules[name]['reason']}\n" for name in local),
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
        PAGE_FUTURE.format(held=len(held)),
        textwrap.fill(
            ", ".join(f"``{name}``" for name in sorted(held)),
            width=79,
        )
        + "\n",
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
   manifest, ``pysmi/mibs/bundled_mibs.json``, not this file.

pysmi carries {total} MIB modules of its own, in ``pysmi/mibs/asn1/``. They are
a *source*, not a fallback: they are registered ahead of the sources a caller
configures, and a caller's own copy wins only by carrying a newer
MODULE-IDENTITY revision -- not merely by being the caller's. See
:doc:`/mibdump` for ``--prefer-mib-source`` and ``--no-bundled-mibs``, which
override that outright.

A further {held} modules are *held* rather than carried, in
``pysmi/mibs/future/``. They are listed under :ref:`bundled-mib-future` at the
foot of this page, and everything the rest of this page says about
maintenance, freshness and shipping applies to the {total} below and not to
them.

{unstamped} of the modules below carry no MODULE-IDENTITY at all, so there is
no revision to compare and the bundled copy is the one that gets used. Most are
a pre-SMIv2 module or an SMI module proper, whose text was fixed when its RFC
was published and cannot be revised except as a new module under a new name --
so the copy here cannot go stale under a caller who has a better one. Four are
undated for a different reason: ATM-FORUM-MIB and the three LAN-EMULATION
modules ship their MODULE-IDENTITY commented out, so they declare none.

Every module below is traceable to the publisher its text came from, named in
the Source column: cut out of the RFC that currently defines it, fetched from
IANA's registry or the IEEE 802.1 MIB directory, or taken from the publisher
named there. ``scripts/update_bundled_mibs.py --check`` re-fetches everything
that has somewhere to re-fetch from and reports anything that no longer
matches. RFC-sourced entries are also checked against the RFC Editor for
obsoletion, since an RFC's text never changes but a later RFC can replace it.

A Source shown without a link is ``archived``: the publisher is named and real,
but serves no MIB file this script can fetch -- CableLabs modules dropped from
the live directory, the ATM Forum set, IEEE and TIA modules absent from any
public MIB directory, DMTF and SCTE behind a 403, IEC behind a paywall,
Internet-Drafts whose bundled text matches no archived revision closely enough
to name one. ``--check`` stays quiet about those. Five more are maintained
in this repository outright and listed under :ref:`bundled-mib-local`.

{patched} modules carry a patch, listed under :ref:`bundled-mib-patches` below,
because their published text does not compile as published.

The same modules ship compiled too. A wheel carries ``pysmi/mibs/pysnmp/``,
one pysnmp module per entry below, rendered from the ASN.1 by ``hatch_build.py``
while the wheel is built. A consumer that wants to *load* a standard module
rather than compile it can point pysnmp straight at the package::

   from pysnmp.smi import builder

   mibBuilder = builder.MibBuilder()
   mibBuilder.addMibSources(builder.ZipMibSource("pysmi.mibs.pysnmp"))
   mibBuilder.loadModules("IF-MIB")

Nothing under that directory is in the repository and nothing regenerates it on
a schedule: it is built from the ASN.1 beside it every time a distribution is,
so the two cannot disagree. The ASN.1 stays because it is what the compiler
reads -- resolving an IMPORTS clause means parsing the imported module's source
-- so the compiled form joins it rather than replacing it.

Membership is decided by provenance: a module published by a standards body or
a multivendor association, whose text is traceable to that publisher. Whether
the publisher serves it at a fetchable URL is recorded, not required -- it
decides whether ``--check`` can watch the module, nothing more.

Publication in an RFC *is* that provenance, and it settles the question by
itself. A module cut out of an RFC is bundled on that ground alone -- its
ORGANIZATION clause is not consulted and the arc it roots at is not either, so
``SFLOW-MIB`` under ``enterprises 14706`` and ``IBM-6611-APPN-MIB`` under
``enterprises 2`` are here on the same footing as ``IF-MIB``. The ORGANIZATION
test still decides the modules that reach the bundle from a mirror or a
publisher's own directory, where nothing else says who published them; it was
never the right question to ask of an RFC.

What an RFC does not settle is whether the module is a specification at all,
and four kinds are left out:

- An RFC at Experimental status that nothing depends on. ``TCPIPX-MIB``
  (RFC 1792), ``DPI20-MIB`` (RFC 1592), ``AGGREGATE-MIB`` and
  ``TIME-AGGREGATE-MIB`` (RFC 4498), ``SMF-MIB`` and ``IANA-SMF-MIB``
  (RFC 7367) and ``RSERPOOL-MIB`` (RFC 5525) are all published, none of them
  is a standard, and no module in the pysnmp/mibs corpus imports any of them.
  See :ref:`bundled-mib-experimental` for the ones that are depended on.
- A module an RFC prints to illustrate something. ``COFFEE-POT-MIB``
  (RFC 2325) is an April Fools' RFC; ``FIZBIN-MIB`` is the SMIv2
  specification's own worked example and ends ``::= {{ experimental xx }}``,
  a placeholder rather than a registration; ``BLDG-HVAC-MIB`` is RFC 3512
  section 8, headed "Example MIB Module With Template-based Data". These are
  deliberately excluded and should not be proposed again.
- A module that is not SMI. ``COPS-PR-SPPI`` (RFC 3159) defines the Structure
  of Policy Provisioning Information -- the PIB counterpart of SNMPv2-SMI, not
  a MIB module, and not something an SMI compiler parses.
- A module written against the 1993 SMI that RFC 2578 cannot satisfy.
  ``SNMPv2-PARTY-MIB`` (RFC 1447) imports ``UInteger32`` from SNMPv2-SMI,
  a type RFC 1442 defined and RFC 2578 removed; ``SNMPv2-M2M-MIB`` (RFC 1451)
  imports from ``SNMPv2-PARTY-MIB`` in turn. Substituting ``Unsigned32`` would
  make them compile by rewriting the specification, which is the one thing a
  patch here may not do.

Historic is *not* on that list. An RFC no longer current still published its
module, and sixteen such pins predate this rule -- ``SNMPv2-USEC-MIB``,
``SNA-NAU-MIB``, ``TOKEN-RING-RMON-MIB`` and the rest. What retires a module
here is a *later RFC that replaced it*, which is a different question and the
one :ref:`bundled-mib-historical` answers.

A module its publisher still revises *is* bundled -- IANA's registries and the
IEEE 802.1 directory are tracked at whatever they currently publish, not frozen
at a dated file. Freezing would only make staleness undetectable: the whole
point of ``--check`` is that a revision upstream gets reported, and a caller
who has the newer copy already outranks the bundle on revision. Where a
publisher serves nothing fetchable that first protection is absent, but the
second is not: a caller's dated, newer copy still wins.

.. _bundled-mib-experimental:

Experimental modules the corpus still imports
---------------------------------------------

Experimental status keeps a module out only while nothing needs it. **An
Experimental RFC module is bundled, and counts as current, for as long as
live vendor modules import symbols it alone defines.** The IETF's process
tracks the maturity of a specification; the bundle has to track whether
shipping equipment is still managed through one, and those two go out of step
whenever a protocol outlives the document that first described it.

``PIM-MIB`` is the case that sets the rule. RFC 2934 is Experimental because
the protocol it manages was: PIM-SM was specified in RFC 2362, also
Experimental, and only reached Proposed Standard in 2006 and Internet Standard
in 2016. A MIB cannot outrank what it manages, so the module was registered
under ``experimental 61`` rather than an ``mib-2`` arc, and its status has
been frozen there ever since. RFC 5060 later published ``PIM-STD-MIB`` on the
standards track and says in its own text that it is "to be preferred", but the
RFC Editor records no Obsoletes relation, and the two share neither symbols nor
OIDs -- ``PIM-STD-MIB`` roots at ``mib-2 157`` and ``PIM-BSR-MIB`` at
``mib-2 172``, and the bootstrap-router objects were renamed to a ``pimBsr``
prefix. That is a parallel republication, not a supersession, and RFC 2934
remains the only definition of everything under ``experimental 61``.

Four vendor modules still import from it, and seven of the ten symbols they
name -- ``pimRPSetComponent``, ``pimRPSetAddress``, ``pimCandidateRPEntry``
and the rest of the RP-set group -- exist in neither successor. The one that
settles it is ``HP-ICF-PIM6``: revised October 2017, describing itself as
extensions to *RFC 5060*, and importing ``pimRPSetComponent`` ``FROM PIM-MIB``
while importing nothing from ``PIM-STD-MIB`` at all. Dropping RFC 2934 would
break a module newer than the standard that was supposed to replace it.

``LISP-MIB`` (RFC 7052) and ``MSDP-MIB`` (RFC 4624) are bundled on the same
ground; the seven Experimental modules left out above have no importer between
them, so the rule divides them cleanly.

The evidence runs one way only. An importer is enough to keep a module; the
absence of one is not a reason to remove a module already bundled, and it is
the wrong question entirely for a framework MIB an operator compiles directly
rather than through a vendor extension -- ``SNMP-USM-DH-OBJECTS-MIB``
(RFC 2786) is USM key change, which nothing extends and everything with USM
may want.

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

Two of them were not replaced by one module. RFC 1213's MIB-II, and RFC 1158's
before it, were split up: ``system`` and ``snmp`` went to ``SNMPv2-MIB``,
``interfaces`` to ``IF-MIB``, ``at``, ``ip`` and ``icmp`` to ``IP-MIB``, ``tcp``
to ``TCP-MIB``, ``udp`` to ``UDP-MIB``, while ``egp`` and ``transmission`` were
left with no successor to name. Their manifest entries carry that split as a
per-subtree map, and :py:func:`pysmi.mibs.successor_for` answers from it -- so a
caller holding an OID an old agent reported can be told which module defines it
now, rather than only that the module it came from is gone.
"""

PAGE_FUTURE = """\
.. _bundled-mib-future:

Held, not carried
-----------------

These {held} modules sit in ``pysmi/mibs/future/`` in the repository. Their
provenance is the same as any module above -- each has a manifest entry naming
the publisher its text came from -- and they were fetched, patched where
needed and compile-verified alongside the rest. What separates them is that
nothing needs them: across the roughly 5,500 vendor modules at
https://github.com/pysnmp/mibs, not one imports any module below, pysnmp ships
none of them, and neither project's own code, tests or documentation names
one. They entered the bundle as parser pressure tests, which is work they did,
and stayed after it was done.

Holding them says three things:

- **They are not installed.** A wheel does not carry ``future/``; only the
  repository and the sdist do. The compiler never registers the directory, and
  ``pysmi/mibs/pysnmp/`` holds no compiled form of them. Note that most are not
  at https://pysnmp.github.io/mibs/asn1/ either, since that tree is built from
  this bundle -- the way to get one back is to promote it, below, not to fetch
  it from the mirror.
- **Their freshness is not maintained.** ``--check`` does not re-fetch these
  or ask the RFC Editor whether their pins still stand. A copy here may be
  years behind its publisher, and by design nothing reports it. That is the
  cost this arrangement pays and the reason the modules are held rather than
  bundled: pysmi vouches for the text of what it ships, and it can only
  keep saying so about a set it actually re-checks.
- **They are not gone.** The manifest entry stays, so what the module is and
  where its text comes from are still recorded, and
  :py:func:`pysmi.mibs.future` names them at runtime.

**Any use promotes one.** A module in the corpus that imports it, a consumer
that asks for it, a test that needs it -- each is sufficient on its own, and
no wider case has to be made. ``scripts/update_bundled_mibs.py --promote
MODULE-NAME`` moves the file into ``asn1/``, clears the ``tier`` on its
manifest entry, re-fetches it from its publisher, because a held copy is
presumed stale, re-verifies the enlarged bundle and rewrites this page.

"""

PAGE_FOOTER = """
Not bundled
-----------

What stays out is a vendor's own MIB. Being rooted under ``enterprises`` does
not make a module one: CableLabs' ``DOCS-*`` and ``CLAB-*`` sit under
``enterprises 4491``, SCTE's ``SCTE-HMS-*`` under 5591, MEF's ``MEF-*`` under
15007, and all of them are bundled -- they are published by an association, and
that is what counts. The test is the module's ORGANIZATION clause.

Nor is publisher availability a reason. ATM Forum has dissolved, DMTF and SCTE
answer automated fetches with a 403, IEC 62439-3 is behind a paywall; those
modules are bundled anyway, marked ``archived`` so ``--check`` knows to stay
quiet about them rather than to keep failing.

Draft-named modules are bundled where the published successor renamed the
symbols, because then no substitution is possible: ``MPLS-VPN-MIB``,
``MPLS-LSR-MIB`` and ``MPLS-TE-MIB`` are all imported by current vendor modules
that ``MPLS-L3VPN-STD-MIB`` and friends cannot satisfy. A draft whose successor
kept the symbols -- ``IGMP-MIB`` for ``IGMP-STD-MIB`` -- stays out, since the
successor is already here and serves the same imports.

What an RFC-published module is left out for is set out above the inventory:
Experimental status, being an illustration rather than a specification, not
being SMI at all, or being written against a version of the SMI the bundle's
own SNMPv2-SMI cannot satisfy. Nothing else about an RFC module keeps it out.

Two bundled modules do not come from an RFC and are not a standards body's
either. ``LLDP-EXT-HM-MIB`` declares ORGANIZATION "Hirschmann Automation &
Control"; it came across with the LLDP extension set and is recorded as
``source: hirschmann`` so that the exception is visible rather than buried.

Everything left out remains available from https://pysnmp.github.io/mibs/asn1/,
which is where pysmi looks by default.
"""

PAGE_LOCAL = """\
.. _bundled-mib-local:

Modules maintained here
-----------------------

These five have no publisher to fetch from, so ``--check`` skips them and the
copy in this repository is the only one. That is admissible because none of
them has an upstream to fall behind: two are macros an RFC defined in prose
without ever shipping ASN.1, and three are a 1994 tool's SNMPv1 rendering of
SMIv2 base modules that the SMIv2 RFCs went on to obsolete. Nothing will revise
any of them. Why each is here:
"""


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        sys.exit(check())
    if "--check-mirror" in sys.argv[1:]:
        sys.exit(check_mirror())
    if "--verify" in sys.argv[1:]:
        sys.exit(verify())
    if "--docs" in sys.argv[1:]:
        sys.exit(docs())
    if "--promote" in sys.argv[1:]:
        promoting = sys.argv[sys.argv.index("--promote") + 1 :]
        if not promoting:
            sys.stderr.write("--promote needs at least one module name.\n")
            sys.exit(1)
        sys.exit(promote(promoting))
    sys.exit(update())
