#!/usr/bin/env python3
#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
# SNMP SMI/MIB contribution tool
#
"""The *mibcontribute* tool: send the MIBs you have to the distribution that lacks them.

Point it at a directory. It reads every module in it, asks a MIB distribution
what it publishes for each, and reports the ones worth sending: the modules the
distribution carries an older revision of, and the modules it has never carried
at all. The comparison is :py:func:`~pysmi.compiler.rank_by_revision`, which is
the rule a corpus is built with, so a module reported here is a module a build
would prefer.

    mibcontribute ./my-mibs

That run reads the published corpus over HTTPS and writes what it found into
``mib-contribution/``, and sends nothing. ``--submit`` files it: ``url`` prints
a GitHub issue URL with the whole report in it, for a browser to post under its
own account and with no credential passing through here, and ``gh`` files it
with the GitHub CLI. Either way the tracker is searched first, so a module
somebody has already offered is left out instead of reported twice.

``--corpus`` decides what it is compared against. The default is the published
site, which needs one request per module; a local directory, or an unpacked
release archive, needs none and is what a scan of a large collection should
use.
"""

import getopt
import logging
import os
import sys
import webbrowser
from pathlib import Path
from typing import Final

from pysmi import contribute, debug, error
from pysmi.reader import DEFAULT_MIB_SOURCES

logger = logging.getLogger(__name__)

# sysexits.h
EX_OK: Final = 0
EX_USAGE: Final = 64
EX_SOFTWARE: Final = 70
EX_UNAVAILABLE: Final = 69


def _skipped(path: Path, why: str) -> None:
    """Say that one file was not read as a module."""
    logger.info("%s: %s", path, why, extra={"path": str(path), "reason": why})


def _describe(findings: "list[contribute.Finding]") -> str:
    """What was found, as the summary the run prints."""
    new = [x for x in findings if x.verdict == contribute.NOT_CARRIED]
    better = [x for x in findings if x.verdict != contribute.NOT_CARRIED]
    lines = [
        f"{len(findings)} module(s) worth offering: "
        f"{len(better)} the distribution carries an older copy of, "
        f"{len(new)} it does not carry.",
        "",
    ]

    for one in findings:
        published = (
            contribute.describe_revision(one.published.revision)
            if one.published
            else "not carried"
        )
        lines.append(
            f"    {one.module:<40} {contribute.describe_revision(one.offered.revision)}"
            f"  against {published}"
        )

    return "\n".join(lines) + "\n"


def _without_duplicates(
    findings: "list[contribute.Finding]",
    repository: str,
    *,
    required: bool,
) -> "list[contribute.Finding]":
    """The findings nothing has been filed about yet, with a word about the rest.

    An open issue naming a module is reason not to file a second one: the
    module is already somebody's to deal with. A closed one is not, since it
    was closed for a reason nothing here can read, so the module is offered
    again with the old issue named beside it.
    """
    try:
        existing = contribute.existing_contributions(
            repository, [x.module for x in findings]
        )

    except error.PySmiError as exc:
        if required:
            raise

        sys.stderr.write(
            f"WARNING: the duplicate check could not run ({exc}). Going on; "
            "check the tracker yourself.\r\n"
        )
        return findings

    keep = []

    for one in findings:
        filed = existing.get(one.module, [])
        opened = [x for x in filed if x.get("state") == "open"]

        if opened:
            sys.stderr.write(
                f"{one.module} is already open here, so it is left out:\r\n"
            )

            for issue in opened:
                sys.stderr.write(f"    {contribute.describe_duplicate(issue)}\r\n")

            continue

        for issue in filed:
            sys.stderr.write(
                f"{one.module} was offered before and closed, and is offered "
                f"again: {contribute.describe_duplicate(issue)}\r\n"
            )

        keep.append(one)

    return keep


def _submit_gh(
    directory: Path,
    title: str,
    findings: "list[contribute.Finding]",
    repository: str,
    labels: "list[str]",
    *,
    gist: bool,
) -> str:
    """File the issue with the GitHub CLI, under the account it is signed in as.

    Where the body cannot hold every module's ASN.1, the sources go to a gist
    whether or not one was asked for. A browser can attach the archive to the
    issue it is posting and the API cannot, so the alternative is an issue that
    names an attachment nobody attached.
    """
    contribute.run_gh(["auth", "status"])
    left_out = {x.module for x in findings} - contribute.inline_choice(
        findings, f"{directory.name}.zip"
    )

    if left_out and not gist:
        sys.stderr.write(
            f"{len(left_out)} module(s) are too long for an issue body, and "
            "`gh` cannot attach the archive. Uploading the sources as a secret "
            "gist instead.\r\n"
        )
        gist = True

    if gist:
        url = contribute.run_gh(
            [
                "gist",
                "create",
                "--desc",
                f"MIB sources for {title}",
                *[str(directory / "mibs" / x.module) for x in findings],
            ]
        ).splitlines()[-1]
        (directory / "issue.md").write_text(
            contribute.compose(findings, "", gist=url), encoding="utf-8"
        )

    arguments = [
        "issue",
        "create",
        "--repo",
        repository,
        "--title",
        title,
        "--body-file",
        str(directory / "issue.md"),
    ]

    for label in labels:
        arguments += ["--label", label]

    return contribute.run_gh(arguments).splitlines()[-1]


def _submit_url(
    directory: Path,
    title: str,
    body: str,
    archive: Path,
    repository: str,
    labels: "list[str]",
    *,
    openFlag: bool,
) -> str:
    """Print the issue URL for a browser to post, and say what to attach."""
    url = contribute.issue_url(repository, title, body, tuple(labels))

    if len(url) > contribute.URL_LIMIT:
        url = contribute.issue_url(
            repository,
            title,
            f"{contribute.MARKER}\n\nPaste the contents of `issue.md` here and "
            f"attach `{archive.name}`.",
            tuple(labels),
        )
        sys.stderr.write(
            f"The report is too long to carry in a URL. Open the URL below, paste "
            f"{directory / 'issue.md'} into the body, and attach {archive}.\r\n"
        )

    else:
        sys.stderr.write(
            f"Open this, read it, and post it. Attach {archive} for the MIB "
            "sources.\r\n"
        )

    if openFlag:
        webbrowser.open(url)

    return url


def start() -> None:
    """Scan the directories named by the command line and offer what is in them."""
    sourceDirectories: list[str] = []
    corpus = ""
    repository = contribute.PUBLISHED_REPOSITORY
    outputDirectory = "mib-contribution"
    modules: list[str] = []
    labels: list[str] = []
    submit = "none"
    verboseFlag = True
    includeDifferingFlag = False
    skipNewFlag = False
    perModuleFlag = False
    allowDuplicatesFlag = False
    requireDuplicateCheckFlag = False
    gistFlag = False
    openFlag = False

    helpMessage = """\
    Usage: {} [--help]
        [--version]
        [--quiet]
        [--debug=<{}>]
        [--source=<DIRECTORY>]
        [--corpus=<URI>]
        [--repository=<OWNER/NAME>]
        [--module=<MIB-NAME>]
        [--include-differing]
        [--skip-new]
        [--per-module]
        [--output-directory=<DIRECTORY>]
        [--submit=<none|url|gh>]
        [--label=<LABEL>]
        [--gist]
        [--open]
        [--allow-duplicates]
        [--require-duplicate-check]
        [DIRECTORY ...]
    Where:
        --source - a directory of ASN.1 MIB modules to offer, or one file.
                Repeatable, and the same thing as a positional argument.
                Every file in it is read as a module, and the name a module
                gives itself is what it is offered as, not the name of the
                file it was found in.
        --corpus - what to compare against: a directory, a .zip, or a URL
                with "@mib@" where the module name goes. It has to be a
                distribution: a path that is not there, or holds nothing, is
                refused rather than read as a distribution carrying no
                modules. Left out, the modules pysmi bundles are read first
                and then {}, which is one
                request per module; a local copy is what a large scan should
                use.
        --repository - where the issue is filed. Defaults to "{}".
        --module - offer only this module, repeatable. Without it every
                module worth offering is.
        --include-differing - also offer a module whose copy here won on
                source order rather than on a newer revision. Off by
                default: two copies of one name are as often two different
                modules as two revisions of one.
        --skip-new - offer only better copies of modules the distribution
                already carries.
        --per-module - write one issue per module rather than one issue for
                all of them. One module per issue is one module per pull
                request.
        --output-directory - where the issue, the findings and the MIBs go.
                Defaults to "mib-contribution" under the working directory.
        --submit - "none" writes those files and sends nothing, which is the
                default. "url" prints a GitHub issue URL with the report
                already in it, for you to read and post in your browser: no
                credential is read or sent by this tool. "gh" files the
                issue with the GitHub CLI, which must already be
                authenticated.
        --label - a label to apply, repeatable. The repository must already
                define it.
        --gist - with --submit=gh, upload the MIBs as a secret gist and link
                it from the issue rather than inlining them.
        --open - with --submit=url, open the URL in a browser.
        --allow-duplicates - offer a module even where an issue for it is
                already open.
        --require-duplicate-check - submit nothing if the tracker cannot be
                searched. For unattended runs, where filing duplicates every
                time is worse than filing nothing until the search works.
    """.format(
        os.path.basename(sys.argv[0]),
        "|".join(sorted(debug.flagMap)),
        " and ".join(DEFAULT_MIB_SOURCES),
        contribute.PUBLISHED_REPOSITORY,
    )

    try:
        opts, remaining = getopt.getopt(
            sys.argv[1:],
            "hv",
            [
                "help",
                "version",
                "quiet",
                "debug=",
                "source=",
                "corpus=",
                "repository=",
                "module=",
                "include-differing",
                "skip-new",
                "per-module",
                "output-directory=",
                "submit=",
                "label=",
                "gist",
                "open",
                "allow-duplicates",
                "require-duplicate-check",
            ],
        )

    except getopt.GetoptError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    for opt in opts:
        if opt[0] in ("-h", "--help"):
            sys.stderr.write(f"""\
    Synopsis:
    Offer the MIBs in a directory to the distribution that publishes them
    Documentation:
    https://github.com/pysnmp/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] in ("-v", "--version"):
            from pysmi import __version__

            sys.stderr.write(f"""\
    SNMP SMI/MIB library version {__version__}
    Python interpreter: {sys.version}
    Software documentation and support at https://github.com/pysnmp/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] == "--quiet":
            verboseFlag = False

        if opt[0] == "--debug":
            debug.enableDebugLogging(*opt[1].split(","))

        if opt[0] == "--source":
            sourceDirectories.append(opt[1])

        if opt[0] == "--corpus":
            corpus = opt[1]

        if opt[0] == "--repository":
            repository = opt[1]

        if opt[0] == "--module":
            modules.append(opt[1])

        if opt[0] == "--include-differing":
            includeDifferingFlag = True

        if opt[0] == "--skip-new":
            skipNewFlag = True

        if opt[0] == "--per-module":
            perModuleFlag = True

        if opt[0] == "--output-directory":
            outputDirectory = opt[1]

        if opt[0] == "--submit":
            submit = opt[1]

        if opt[0] == "--label":
            labels.append(opt[1])

        if opt[0] == "--gist":
            gistFlag = True

        if opt[0] == "--open":
            openFlag = True

        if opt[0] == "--allow-duplicates":
            allowDuplicatesFlag = True

        if opt[0] == "--require-duplicate-check":
            requireDuplicateCheckFlag = True

    sourceDirectories += list(remaining)

    if verboseFlag:
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if not sourceDirectories:
        sys.stderr.write(
            f"ERROR: no MIBs to offer; name a directory\r\n{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    if submit not in ("none", "url", "gh"):
        sys.stderr.write(
            f"ERROR: --submit takes none, url or gh, not {submit!r}\r\n"
            f"{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    try:
        readers = (
            contribute.require_corpus(corpus) if corpus else contribute.default_corpus()
        )
        findings = contribute.scan(
            [Path(x) for x in sourceDirectories],
            readers,
            include_differing=includeDifferingFlag,
            skip_new=skipNewFlag,
            only=tuple(modules),
            on_skip=_skipped if verboseFlag else None,
        )

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_SOFTWARE)

    if not findings:
        sys.stderr.write(
            "Every module here is one the distribution already carries, in a copy "
            "a build would prefer. Nothing to offer.\r\n"
        )
        sys.exit(EX_OK)

    if submit != "none" and not allowDuplicatesFlag:
        try:
            findings = _without_duplicates(
                findings, repository, required=requireDuplicateCheckFlag
            )

        except error.PySmiError as exc:
            sys.stderr.write(f"ERROR: {exc}\r\n")
            sys.exit(EX_UNAVAILABLE)

        if not findings:
            sys.stderr.write(
                "Everything here is already open on the tracker. Nothing to file.\r\n"
            )
            sys.exit(EX_OK)

    out = Path(outputDirectory)
    offers = (
        [(x.module, [x]) for x in findings]
        if perModuleFlag
        else [("contribution", findings)]
    )

    if verboseFlag:
        sys.stderr.write(_describe(findings))

    for slug, held in offers:
        directory = out / slug if perModuleFlag else out
        title = contribute.title_for(held)

        try:
            archive = contribute.write_bundle(directory, slug, held)

        except OSError as exc:
            sys.stderr.write(f"ERROR: {exc}\r\n")
            sys.exit(EX_SOFTWARE)

        body = (directory / "issue.md").read_text(encoding="utf-8")

        if submit == "none":
            sys.stderr.write(f"Wrote {directory / 'issue.md'}\r\n")
            continue

        try:
            if submit == "gh":
                filed = _submit_gh(
                    directory, title, held, repository, labels, gist=gistFlag
                )
            else:
                filed = _submit_url(
                    directory,
                    title,
                    body,
                    archive,
                    repository,
                    labels,
                    openFlag=openFlag,
                )

        except error.PySmiError as exc:
            sys.stderr.write(f"ERROR: {exc}\r\n")
            sys.exit(EX_UNAVAILABLE)

        sys.stdout.write(f"{filed}\n")

    if submit == "none":
        sys.stderr.write(
            "Read it, then run again with --submit=url to post it from your "
            "browser, or --submit=gh to file it with the GitHub CLI.\r\n"
        )

    sys.exit(EX_OK)


if __name__ == "__main__":
    start()
