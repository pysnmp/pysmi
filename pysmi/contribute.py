#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Offering MIBs to a distribution: which ones are worth offering, and how to say so.

A MIB distribution is only as complete as what people send it, and the people
who have the MIBs it is missing are rarely the people who open pull requests.
They have a directory: what a device shipped, what a vendor's support portal
gave them, what a collection they cloned holds. Somewhere in it are modules the
distribution publishes an older copy of, and modules it has never carried, and
nothing tells anybody which.

Comparing the two is a question this package already answers on every compile.
:py:func:`~pysmi.compiler.rank_by_revision` decides which of two copies of a
module wins -- the newest MODULE-IDENTITY revision, with configured order
breaking a tie -- and that is the rule a corpus is built with. Asking it
directly, against a reader pointed at the published corpus, turns a directory
into a list of modules worth sending and the evidence for each:

    a better copy    both hold it, and the offered copy carries the newer
                     revision
    not carried      the distribution's own source does not have it at all

This module does that comparison and composes the GitHub issue that reports
it. :py:mod:`pysmi.scripts.mibcontribute` is the command around it.

Two judgements are deliberately left alone. A copy that wins on source order
rather than on revision is not reported as better unless asked for: two copies
of one name are as often two different modules as two revisions of one, and no
rule can tell them apart. And a module whose text is identical to the
published copy is not reported at all, since there is nothing to offer.
"""

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pysmi import __version__ as packageVersion
from pysmi import error
from pysmi.compiler import PRECEDENCE_NEWEST_REVISION, rank_by_revision, revision_of
from pysmi.mibinfo import module_names, source_digest
from pysmi.reader.base import AbstractReader

#: Where a distribution's published ASN.1 lives when nothing says otherwise.
#: pysmi substitutes ``@mib@`` with the module name it is asking for.
PUBLISHED_CORPUS: Final = "https://pysnmp.github.io/mibs/asn1/@mib@"

#: The repository an offer is made to when nothing says otherwise.
PUBLISHED_REPOSITORY: Final = "pysnmp/mibs"

#: The verdict for a module the distribution carries an older revision of.
NEWER: Final = "newer"

#: The verdict for a module no source of the distribution's holds. Not a
#: precedence decision at all: nothing was passed over, because there was
#: nothing to pass over.
NOT_CARRIED: Final = "not carried"

#: What each ``precedence`` value says about two copies, in the words the issue
#: prints. Anything added later reads as ``differs``, which is the conservative
#: reading of a rule this does not know.
VERDICTS: Final = {
    PRECEDENCE_NEWEST_REVISION: NEWER,
    "source order; equal MODULE-IDENTITY revisions": "same revision, different text",
    "source order; no MODULE-IDENTITY revision to compare": "no revision to compare",
}

#: The marker that makes these issues findable as a set, whoever filed them and
#: whatever the title says. An HTML comment, so a reader never sees it and a
#: maintainer searching the tracker does.
MARKER: Final = "<!-- mib-contribution v1 -->"

#: What that marker says about itself in the form a search matches, once
#: GitHub has tokenised it.
MARKER_TEXT: Final = "mib-contribution"

#: What GitHub accepts in an issue body, in characters.
BODY_LIMIT: Final = 65536

#: What this fills of it. The remainder is the margin between the length
#: counted while choosing what to inline and the length of the rendered result.
INLINE_BUDGET: Final = 60000

#: Longest prefilled issue URL this hands to a browser. GitHub's own front end
#: refuses a request line well before the theoretical limit, and a URL that is
#: refused loses the whole report.
URL_LIMIT: Final = 6000

#: What a duplicate search reads before it stops. GitHub returns 100 results a
#: page, and a tracker with more open contributions than this is one where a
#: maintainer, not a script, should be deciding what is a duplicate.
DUPLICATE_PAGES: Final = 3

#: How many modules are worth one search each, over and above the single search
#: that finds every issue this tool has filed. The search API allows ten
#: unauthenticated requests a minute.
DUPLICATE_SEARCHES: Final = 8

#: Names that are never a MIB, so that pointing this at a checkout does not try
#: to parse its version control.
_SKIP: Final = frozenset({"__pycache__", ".git", ".hg", ".svn", ".tox", "node_modules"})

#: Files larger than this are not MIBs. A MIB is ASN.1 text; the largest in the
#: published corpus is under 2 MB, and reading a DVD image to find that out is
#: a waste of a scan.
_LARGEST: Final = 8 * 1024 * 1024


@dataclass
class Copy:
    """One copy of a module, as an issue describes it."""

    #: Where it came from, in words: a namespace, a source, or the corpus.
    source: str
    #: The file it was read from, named relative to the directory scanned.
    #: Never an absolute path: a path from the scanning machine names that
    #: machine, and an issue is public.
    file: str
    #: Normalised MODULE-IDENTITY revision, or an empty string for a module
    #: carrying none, which is every SMIv1 module.
    revision: str
    #: The digest of the text, as :py:func:`~pysmi.compiler.source_digest`
    #: computes it.
    digest: str
    #: Size of the text, in bytes.
    size: int

    def as_dict(self) -> dict[str, Any]:
        """This copy as plain data, for the block an agent reads."""
        return {
            "file": self.file,
            "revision": self.revision,
            "digest": self.digest,
            "bytes": self.size,
        }


@dataclass
class Finding:
    """One module worth offering, and what decided that."""

    #: Module name, as the module declares it rather than as the file is named.
    module: str
    #: What this module is: :py:data:`NEWER`, :py:data:`NOT_CARRIED`, or one of
    #: :py:data:`VERDICTS`.
    verdict: str
    #: The precedence rule that decided, in the compiler's words. Empty for a
    #: module the distribution does not carry, where nothing was decided.
    precedence: str
    #: The copy being offered.
    offered: Copy
    #: The copy the distribution publishes. ``None`` where it publishes none.
    published: "Copy | None"
    #: The offered text, which is what the issue carries.
    text: str
    #: The offered bytes as they are on disk, which is what the archive
    #: carries. Decoding is lossy for a MIB that is not UTF-8; the archive is
    #: what a pull request should be cut from.
    raw: bytes

    def as_dict(self, *, inline: bool = False) -> dict[str, Any]:
        """This finding as plain data, for the block an agent reads."""
        return {
            "module": self.module,
            "verdict": self.verdict,
            "precedence": self.precedence,
            "offered": self.offered.as_dict(),
            "published": self.published.as_dict() if self.published else None,
            "inline": inline,
        }


def read_source(path: Path) -> tuple[str, bytes]:
    """The MIB at *path*, as text to read and as the bytes to attach.

    A MIB that is not valid UTF-8 is decoded as Latin-1 rather than refused:
    the text is what an issue prints and the bytes are what a pull request
    would be cut from, so a lossy decode costs display and not the offer.

    Args:
        path: the file to read.

    Returns:
        The decoded text, and the bytes exactly as they are on disk.
    """
    raw = path.read_bytes()

    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError:
        return raw.decode("latin-1"), raw


def describe_revision(revision: str) -> str:
    """A normalised ``YYYYMMDDHHMMZ`` revision, as a date to read.

    Args:
        revision: the revision as :py:func:`~pysmi.mibinfo.normalise_revision`
            leaves it.

    Returns:
        The date, or ``none`` for a module carrying no revision at all.
    """
    if not revision or len(revision) < 8:
        return "none"

    return f"{revision[0:4]}-{revision[4:6]}-{revision[6:8]}"


def mib_files(source: Path) -> Iterator[Path]:
    """Every file under *source* that could be a MIB.

    A file, when the caller named one. Otherwise everything in the tree that is
    not version control, not hidden, and not too large to be ASN.1 text.
    Whether a file *is* a MIB is decided by reading it, since a MIB is named
    inside the file and vendors name the files anything at all.

    Args:
        source: a directory to scan, or one file.

    Yields:
        Paths, in a stable order.
    """
    if source.is_file():
        yield source
        return

    if not source.is_dir():
        raise error.PySmiError(f"{source} is neither a file nor a directory")

    root = source.resolve()

    for found in sorted(source.rglob("*")):
        if not found.is_file() or found.name.startswith("."):
            continue

        if _SKIP & set(found.relative_to(source).parts):
            continue

        # A symlink pointing out of the tree is not part of the directory the
        # caller named, and what this reads it may go on to publish. Resolved
        # on both sides, so a scan of a path that is itself reached through a
        # link still sees its own files.
        if not found.resolve().is_relative_to(root):
            continue

        if found.stat().st_size > _LARGEST:
            continue

        yield found


def published_copy(corpus: AbstractReader, mibname: str) -> "tuple[str, str] | None":
    """What the distribution publishes for *mibname*.

    Args:
        corpus: a reader over the published ASN.1.
        mibname: the module to ask for.

    Returns:
        The published text and the file name it came under, or ``None`` where
        the distribution does not carry the module.
    """
    try:
        info, text = corpus.get_data(mibname)
    except error.PySmiReaderFileNotFoundError:
        return None

    return text, info.file or mibname


def compare(
    mibname: str,
    text: str,
    raw: bytes,
    file: str,
    corpus: AbstractReader,
    *,
    source: str = "the scanned set",
) -> "Finding | None":
    """One module, against the copy the distribution publishes.

    The decision is :py:func:`~pysmi.compiler.rank_by_revision`'s, which is
    what a corpus build uses, so a module reported here is a module a build
    would prefer. The offered copy is ranked first, so a tie leaves it first
    and the precedence says that is all that happened.

    Args:
        mibname: the module's declared name.
        text: its ASN.1 source.
        raw: the same source as bytes.
        file: the file it was read from, relative to the scanned directory.
        corpus: a reader over the published ASN.1.
        source: what to call where the offered copy came from.

    Returns:
        The finding, or ``None`` when there is nothing to offer: the
        distribution publishes the same text, or a copy a build would prefer
        to this one.
    """
    mine = source_digest(text)
    theirs = published_copy(corpus, mibname)

    if theirs is None:
        return Finding(
            module=mibname,
            verdict=NOT_CARRIED,
            precedence="",
            offered=Copy(source, file, revision_of(text) or "", mine, len(raw)),
            published=None,
            text=text,
            raw=raw,
        )

    published, publishedFile = theirs

    if source_digest(published) == mine:
        return None

    order, precedence = rank_by_revision([revision_of(text), revision_of(published)])

    if order[0] != 0:
        return None

    return Finding(
        module=mibname,
        verdict=VERDICTS.get(precedence, "differs"),
        precedence=precedence,
        offered=Copy(source, file, revision_of(text) or "", mine, len(raw)),
        published=Copy(
            "the published corpus",
            publishedFile,
            revision_of(published) or "",
            source_digest(published),
            len(published.encode("utf-8")),
        ),
        text=text,
        raw=raw,
    )


@dataclass
class Candidate:
    """One copy of one module, as a scan found it on disk."""

    #: The module's declared name.
    module: str
    #: Its ASN.1 source.
    text: str
    #: The same source as bytes.
    raw: bytes
    #: The file it was read from, relative to the directory scanned.
    file: str


def candidates(
    sources: "list[Path]", on_skip: "Callable[[Path, str], None] | None" = None
) -> dict[str, list[Candidate]]:
    """Every module declared under *sources*, mapped to the copies of it found.

    A module can be found more than once in one collection -- a tree that
    carries a vendor's releases side by side has a copy per release -- so the
    copies are collected before any of them is compared with anything. Which
    one is offered is then the same decision the compiler makes between two
    sources, rather than whichever the directory walk reached first.

    One file can also declare more than one module, which is why the key is the
    module and not the file. Each declared module is a candidate in its own
    right, carrying the whole file as its text, since the file is what would be
    contributed.

    Args:
        sources: directories to scan, or files.
        on_skip: called with a path and a reason for each file that is not a
            MIB, when the caller wants to say so.

    Returns:
        Module name to its copies, in the order they were found.
    """
    found: dict[str, list[Candidate]] = {}

    for source in sources:
        for path in mib_files(source):
            text, raw = read_source(path)
            declared = module_names(text)
            file = (
                path.name
                if path.is_file() and source.is_file()
                else str(path.relative_to(source))
            )

            if not declared:
                if on_skip:
                    on_skip(path, "declares no MIB module")
                continue

            if len(declared) > 1 and on_skip:
                on_skip(
                    path,
                    f"declares {len(declared)} modules: {', '.join(declared)}",
                )

            for mibname in declared:
                found.setdefault(mibname, []).append(
                    Candidate(mibname, text, raw, file)
                )

    return found


def best_of(copies: list[Candidate]) -> Candidate:
    """Which copy of one module a scan offers, when it found several.

    :py:func:`~pysmi.compiler.rank_by_revision`, the same rule that decides
    between two configured sources, with the order they were found in breaking
    a tie. Offering the copy the walk happened to reach first would mean
    offering an older revision than the collection holds.

    Args:
        copies: the copies found, in the order they were found.

    Returns:
        The one to offer.
    """
    if len(copies) == 1:
        return copies[0]

    order, _ = rank_by_revision([revision_of(x.text) for x in copies])

    return copies[order[0]]


def scan(
    sources: "list[Path]",
    corpus: AbstractReader,
    *,
    include_differing: bool = False,
    skip_new: bool = False,
    only: "tuple[str, ...]" = (),
    on_skip: "Callable[[Path, str], None] | None" = None,
) -> list[Finding]:
    """Every module under *sources* the distribution would be better for having.

    Args:
        sources: directories to scan, or files.
        corpus: a reader over the published ASN.1, which is what each module is
            compared against.
        include_differing: also report a module the offered copy won on source
            order rather than on revision.
        skip_new: leave out the modules the distribution does not carry.
        only: report just these modules, when given.
        on_skip: called with a path and a reason for each file that is not a
            MIB, when the caller wants to say so.

    Returns:
        One finding per module, in module name order. Where one file declares
        several modules it can appear in several findings, because each of them
        is a module this distribution either has or has not, and the file is
        what answers for all of them.
    """
    found = []

    for mibname, copies in candidates(sources, on_skip).items():
        if only and mibname not in only:
            continue

        best = best_of(copies)
        finding = compare(mibname, best.text, best.raw, best.file, corpus)

        if finding is None:
            continue

        if finding.verdict == NOT_CARRIED and skip_new:
            continue

        if (
            finding.verdict != NOT_CARRIED
            and finding.precedence != PRECEDENCE_NEWEST_REVISION
            and not include_differing
        ):
            continue

        found.append(finding)

    return sorted(found, key=lambda x: x.module)


def title_for(findings: list[Finding]) -> str:
    """What the issue is called, from what it holds.

    Args:
        findings: the modules the issue offers.

    Returns:
        The title.
    """
    if len(findings) == 1:
        one = findings[0]

        if one.verdict == NOT_CARRIED:
            return f"{one.module}: a module this distribution does not carry"

        if one.verdict == NEWER and one.published:
            return (
                f"{one.module}: a newer copy "
                f"({describe_revision(one.offered.revision)}, against "
                f"{describe_revision(one.published.revision)} published)"
            )

        return f"{one.module}: a copy that differs from the published one"

    named = ", ".join(x.module for x in findings[:3])
    rest = f" and {len(findings) - 3} more" if len(findings) > 3 else ""
    new = len([x for x in findings if x.verdict == NOT_CARRIED])

    if new == len(findings):
        return f"{new} modules this distribution does not carry: {named}{rest}"

    return f"{len(findings)} modules to add or replace: {named}{rest}"


def payload(
    findings: list[Finding], inline: "set[str]", archive: str
) -> dict[str, Any]:
    """The offer as data, for whoever picks the issue up.

    The same facts as the table above it, in the form that does not have to be
    parsed out of prose: a pull request for one of these modules needs the
    name, the two revisions and the digest of the text it should carry.

    Args:
        findings: the modules the issue offers.
        inline: the modules whose ASN.1 the body carries.
        archive: the file name the rest are in.

    Returns:
        The document the issue embeds.
    """
    return {
        "report": "mib-contribution v1",
        "pysmi": packageVersion,
        "archive": archive,
        "modules": [x.as_dict(inline=x.module in inline) for x in findings],
    }


def render(
    findings: list[Finding],
    *,
    inline: "set[str]",
    archive: str,
    gist: str = "",
    sources: bool = True,
    detail: bool = True,
    data: bool = True,
) -> str:
    """The issue, in Markdown.

    Args:
        findings: what to offer, which is at least one module.
        inline: the modules whose ASN.1 text the body carries. The rest are in
            the archive, because an issue body holds 65,536 characters and a
            MIB set can hold more.
        archive: the file name the archive was written under.
        gist: URL the MIB sources were uploaded to, when they were.
        sources: whether the body accounts for the ASN.1 at all. A pull request
            carries it in the diff, where it can be reviewed line by line.
        detail: whether the body carries a section per module. An offer of a
            thousand modules does not fit in an issue with one, and the table
            above says the same thing in a line each.
        data: whether the body carries the findings as JSON. It is the largest
            part of a long offer, and the same document is in the archive.

    Returns:
        The body.
    """
    new = [x for x in findings if x.verdict == NOT_CARRIED]
    better = [x for x in findings if x.verdict != NOT_CARRIED]
    out = [
        f"### {len(findings)} module{'s' if len(findings) != 1 else ''} for this "
        "distribution",
        "",
        MARKER,
        "",
        "A MIB directory was resolved against this distribution's published corpus,",
        "by the rule the corpus is built with: the newest MODULE-IDENTITY revision",
        "wins. What that found:",
        "",
    ]

    if better:
        out.append(
            f"- **{len(better)} module{'s' if len(better) != 1 else ''} published "
            "here in an older copy.**"
        )

    if new:
        out.append(
            f"- **{len(new)} module{'s' if len(new) != 1 else ''} this distribution "
            "does not carry.**"
        )

    out += [
        "",
        "| module | offered | published | what decided |",
        "| --- | --- | --- | --- |",
    ]

    for one in findings:
        published = (
            describe_revision(one.published.revision)
            if one.published
            else "not carried"
        )
        out.append(
            f"| `{one.module}` | {describe_revision(one.offered.revision)} "
            f"| {published} | {one.precedence or 'nothing to compare'} |"
        )

    out += [
        "",
        "#### Where these came from",
        "",
        "A module is carried with its provenance, so that the next revision is",
        "noticed by a build rather than by a reader. If you know it:",
        "",
        "- Publisher, and the URL the files were downloaded from:",
        "- Device and software release they were taken from:",
        "",
    ]

    if gist:
        out += [f"The MIB sources are attached as a gist: {gist}", ""]

    outside = [x for x in findings if x.module not in inline] if sources else []

    if outside and not gist:
        out += [
            f"{len(outside)} of these {'is' if len(outside) == 1 else 'are'} too "
            "long for an issue body. The ASN.1 is in",
            f"`{archive}`, attached to this issue:",
            "",
            *(f"- `{x.module}`" for x in outside),
            "",
        ]

    for one in findings if detail else ():
        out += [
            f"#### {one.module}",
            "",
            "| | offered | published |",
            "| --- | --- | --- |",
            f"| revision | {describe_revision(one.offered.revision)} "
            f"| {describe_revision(one.published.revision) if one.published else 'not carried'} |",
            f"| bytes | {one.offered.size:,} | {one.published.size:,} |"
            if one.published
            else f"| bytes | {one.offered.size:,} | |",
            f"| digest | `{one.offered.digest}` | `{one.published.digest}` |"
            if one.published
            else f"| digest | `{one.offered.digest}` | |",
            "",
        ]

        if sources and one.module in inline:
            out += [
                f"<details><summary>{one.module}, as it was offered</summary>",
                "",
                "```",
                one.text.replace("```", "``\u200b`"),
                "```",
                "",
                "</details>",
                "",
            ]

    out += [
        "#### Report data",
        "",
        *(
            [
                "```json",
                json.dumps(payload(findings, inline, archive), indent=2),
                "```",
            ]
            if data
            else [
                f"Too long for this body. `findings.json` in `{archive}` carries "
                "the same document: every module, both revisions and both digests.",
            ]
        ),
        "",
        "<sub>Written by `mibcontribute`. Revisions and digests are pysmi's, read",
        "from the files themselves.</sub>",
    ]

    return "\n".join(out) + "\n"


def choose_inline(findings: list[Finding], overhead: int) -> "set[str]":
    """Which modules the body carries in full, smallest first until the budget is gone.

    Smallest first because the number of modules an issue states in full is
    worth more than which ones: a reader who has five of six modules in front
    of them is one download from the sixth.

    Args:
        findings: the modules the issue offers.
        overhead: what the body costs before any ASN.1 goes into it.

    Returns:
        The module names to inline.
    """
    room = INLINE_BUDGET - overhead
    inline: set[str] = set()

    for one in sorted(findings, key=lambda x: len(x.text)):
        cost = len(one.text) + 200

        if cost > room:
            continue

        inline.add(one.module)
        room -= cost

    return inline


def inline_choice(findings: list[Finding], archive: str, gist: str = "") -> "set[str]":
    """Which modules a composed body would carry in full.

    The same answer :py:func:`compose` acts on, so that a caller can find out
    what an issue will leave out before it writes one -- which is what decides
    whether the sources have to reach the issue some other way.

    Args:
        findings: the modules the issue offers.
        archive: the file name the archive was written under.
        gist: URL the MIB sources were uploaded to, when they were.

    Returns:
        The module names that fit.
    """
    empty: set[str] = set()
    overhead = len(render(findings, inline=empty, archive=archive, gist=gist))

    return choose_inline(findings, overhead)


def compose(
    findings: list[Finding],
    archive: str,
    gist: str = "",
    *,
    sources: bool = True,
) -> str:
    """The issue body, with as much of the offer in it as GitHub will take.

    Four renderings, each smaller than the last: every module's ASN.1 that
    fits, then none of it, then no section per module, then the table alone
    with the findings left in the archive. An offer that does not fit even
    then is refused rather than submitted, since `gh issue create` would
    refuse it too, and says which flag splits it up.

    Args:
        findings: the modules the issue offers.
        archive: the file name the archive was written under.
        gist: URL the MIB sources were uploaded to, when they were.
        sources: whether the body accounts for the ASN.1 at all.

    Returns:
        The body, never longer than :py:data:`BODY_LIMIT`.

    Raises:
        PySmiError: the offer does not fit in an issue at all.
    """
    empty: set[str] = set()
    attempts = []

    if sources:
        attempts.append(
            {
                "inline": inline_choice(findings, archive, gist),
                "detail": True,
                "data": True,
            }
        )

    attempts += [
        {"inline": empty, "detail": True, "data": True},
        {"inline": empty, "detail": False, "data": True},
        {"inline": empty, "detail": False, "data": False},
    ]

    for attempt in attempts:
        body = render(
            findings,
            inline=attempt["inline"],  # type: ignore[arg-type]
            archive=archive,
            gist=gist,
            sources=sources,
            detail=bool(attempt["detail"]),
            data=bool(attempt.get("data", True)),
        )

        if len(body) <= BODY_LIMIT:
            return body

    raise error.PySmiError(
        f"{len(findings)} modules do not fit in one issue body, which GitHub "
        f"holds to {BODY_LIMIT:,} characters, even with the sources left out. "
        "Offer them as separate issues with --per-module, or narrow the scan "
        "with --module."
    )


def write_bundle(directory: Path, slug: str, findings: list[Finding]) -> Path:
    """Write the issue, the data and the MIBs, and return the archive.

    Args:
        directory: where to write.
        slug: what to call the archive.
        findings: the modules the issue offers.

    Returns:
        The archive, which is what a reporter attaches to the issue.
    """
    mibs = directory / "mibs"
    mibs.mkdir(parents=True, exist_ok=True)

    for one in findings:
        (mibs / one.module).write_bytes(one.raw)

    archive = directory / f"{slug}.zip"

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for one in findings:
            bundle.writestr(one.module, one.raw)

    (directory / "issue.md").write_text(
        compose(findings, archive.name), encoding="utf-8"
    )
    (directory / "findings.json").write_text(
        json.dumps(
            payload(findings, {x.module for x in findings}, archive.name), indent=2
        )
        + "\n",
        encoding="utf-8",
    )

    return archive


def issue_url(
    repository: str, title: str, body: str, labels: "tuple[str, ...]" = ()
) -> str:
    """A GitHub new-issue URL with the offer already in it.

    Args:
        repository: ``owner/name``.
        title: the issue title.
        body: the issue body.
        labels: labels to apply, which the repository must already define.

    Returns:
        The URL.
    """
    query = {"title": title, "body": body}

    if labels:
        query["labels"] = ",".join(labels)

    return f"https://github.com/{repository}/issues/new?" + urllib.parse.urlencode(
        query
    )


def run_gh(arguments: list[str]) -> str:
    """One ``gh`` invocation, with its failure reported as its own message.

    Args:
        arguments: the command line, without ``gh`` itself.

    Returns:
        What it printed.

    Raises:
        PySmiError: ``gh`` is not installed, or exited non-zero.
    """
    if not shutil.which("gh"):
        raise error.PySmiError(
            "this needs the GitHub CLI on PATH. Install it from "
            "https://cli.github.com/, or use --submit=url, which needs no "
            "credentials here."
        )

    finished = subprocess.run(
        ["gh", *arguments], capture_output=True, text=True, check=False
    )

    if finished.returncode:
        raise error.PySmiError(
            f"`gh {' '.join(arguments)}` exited {finished.returncode}: "
            f"{finished.stderr.strip() or 'no error text'}"
        )

    return finished.stdout.strip()


def search_issues(repository: str, query: str, pages: int = 1) -> list[dict[str, Any]]:
    """Issues and pull requests matching a GitHub search.

    Through ``gh`` where it is installed, which spends its authentication and
    the rate limit that comes with it, and over the public API otherwise.
    ``GITHUB_TOKEN`` is used when it is set, for the same reason.

    Args:
        repository: ``owner/name``, which the query should also name.
        query: the search, in GitHub's own syntax.
        pages: how many pages of 100 to read.

    Returns:
        The items, in the order GitHub returned them.

    Raises:
        PySmiError: neither transport could answer.
    """
    results: list[dict[str, Any]] = []

    for page in range(1, pages + 1):
        if shutil.which("gh"):
            answer = run_gh(
                [
                    "api",
                    "-X",
                    "GET",
                    "search/issues",
                    "-f",
                    f"q={query}",
                    "-f",
                    "per_page=100",
                    "-f",
                    f"page={page}",
                ]
            )
        else:
            answer = _over_https(query, page)

        try:
            found = json.loads(answer).get("items", [])
        except json.JSONDecodeError as exc:
            raise error.PySmiError(
                f"the GitHub search answered something else: {exc}"
            ) from exc

        results += found

        if len(found) < 100:
            break

    return results


def _over_https(query: str, page: int) -> str:
    """One search through the public API."""
    request = urllib.request.Request(
        "https://api.github.com/search/issues?"
        + urllib.parse.urlencode({"q": query, "per_page": 100, "page": page}),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"pysmi-mibcontribute/{packageVersion}",
        },
    )
    token = os.environ.get("GITHUB_TOKEN", "")

    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        # The URL is this module's own constant with a query string on it;
        # nothing the caller passes decides the scheme.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return str(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise error.PySmiError(
            f"the GitHub search could not be reached: {exc}"
        ) from exc


def modules_named(issue: dict[str, Any]) -> "set[str]":
    """Which modules an existing issue is about.

    An issue this tool filed carries its findings as JSON, which names them
    exactly. One filed by hand carries whatever its author wrote, so the title
    is read too, for the module-shaped words in it.

    Args:
        issue: one search result.

    Returns:
        The module names it appears to be about.
    """
    body = str(issue.get("body") or "")
    named = set(re.findall(r'"module":\s*"([A-Za-z0-9][\w-]*)"', body))
    title = str(issue.get("title") or "")

    return named | set(re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", title))


def existing_contributions(
    repository: str, modules: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """The issues and pull requests already offering each of *modules*.

    One search finds everything this tool has filed, whoever filed it, because
    every issue it writes carries the same marker. A short offer then spends a
    search per module as well, which is what finds the issue somebody opened by
    hand before this tool existed.

    Args:
        repository: ``owner/name``.
        modules: the modules about to be offered.

    Returns:
        Module name to the issues naming it. Modules nothing names are absent.
    """
    found: dict[str, list[dict[str, Any]]] = {}
    wanted = set(modules)

    for issue in search_issues(
        repository, f'repo:{repository} "{MARKER_TEXT}" in:body', DUPLICATE_PAGES
    ):
        for module in modules_named(issue) & wanted:
            found.setdefault(module, []).append(issue)

    if len(modules) <= DUPLICATE_SEARCHES:
        for module in modules:
            seen = {x["number"] for x in found.get(module, ())}

            for issue in search_issues(
                repository, f'repo:{repository} "{module}" in:title,body'
            ):
                if issue["number"] not in seen:
                    found.setdefault(module, []).append(issue)

    return found


def describe_duplicate(issue: dict[str, Any]) -> str:
    """One existing issue, as the line that says not to file another.

    Args:
        issue: one search result.

    Returns:
        The line.
    """
    # Presence, not truth: GitHub marks a pull request with a "pull_request"
    # key, and what is under it is nobody's business here.
    kind = "pull request" if "pull_request" in issue else "issue"

    return f"{kind} #{issue['number']} ({issue.get('state', 'open')}): {issue.get('title', '')}"
