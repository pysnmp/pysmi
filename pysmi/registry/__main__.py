#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Reduce a published registry to the rows and fields a corpus wants.

.. code-block:: sh

   python -m pysmi.registry enterprise-numbers.txt > pen-snapshot.csv
   python -m pysmi.registry --fields=number,organization FILE > lean.csv
   python -m pysmi.registry --only=9,171,2011 FILE > used.csv
   python -m pysmi.registry --only-from=arcs.txt FILE > used.csv

A downstream repository commits the result, so what leaves IANA's copy is that
repository's decision. The default is the whole registry, whole records --
number, organization, contact and email -- and ``--fields`` narrows the record
while ``--only`` and ``--only-from`` narrow the rows.

The registry is 66,807 registrations that IANA revises daily, so committing
all of it means a large file and a large monthly diff. ``--only-from`` reads
enterprise numbers one per line, which is what a corpus can produce from its
own arcs, and is the usual way to write the second form: a snapshot of the
registrants this corpus actually uses.

Nothing is normalised: an email comes out as ``davej&cisco.com`` because that
is what the registry says. See :py:mod:`pysmi.registry.pen`.

Not a console script: this is run once when a snapshot is refreshed, by a
repository that keeps one, rather than by anybody who installed pysmi.
"""

import os
import sys
from typing import Final

from pysmi.registry.pen import FIELDS, reduce_registry

# sysexits.h
EX_OK: Final = 0
EX_USAGE: Final = 64
EX_NOINPUT: Final = 66


def _numbers(text: str) -> list[int]:
    """Enterprise numbers from lines, ignoring blanks and ``#`` comments.

    Raises:
        ValueError: a line is neither blank, a comment, nor a number.
    """
    found = []

    for line in text.splitlines():
        entry = line.partition("#")[0].strip()

        if not entry:
            continue

        if not entry.isdigit():
            raise ValueError(f"not an enterprise number: {entry!r}")

        found.append(int(entry))

    return found


def main(argv: list[str]) -> int:
    """Write the reduced registry on standard output."""
    fields = None
    only: list[int] | None = None
    rest = []

    for argument in argv[1:]:
        if argument.startswith("--fields="):
            fields = [x.strip() for x in argument.partition("=")[2].split(",") if x]

        elif argument.startswith("--only="):
            try:
                only = _numbers(argument.partition("=")[2].replace(",", "\n"))

            except ValueError as exc:
                sys.stderr.write(f"ERROR: {exc}\n")
                return EX_USAGE

        elif argument.startswith("--only-from="):
            try:
                with open(argument.partition("=")[2], encoding="utf-8") as fileObj:
                    only = _numbers(fileObj.read())

            except OSError as exc:
                sys.stderr.write(f"ERROR: {exc}\n")
                return EX_NOINPUT

            except ValueError as exc:
                sys.stderr.write(f"ERROR: {exc}\n")
                return EX_USAGE

        else:
            rest.append(argument)

    if len(rest) != 1:
        sys.stderr.write(
            f"Usage: python -m {__package__} [--fields=A,B] [--only=N,N] "
            "[--only-from=FILE] <enterprise-numbers.txt>\n"
            "Writes the reduced registry on standard output. Fields default "
            f"to all of them: {', '.join(FIELDS)}. Rows default to every "
            "registration.\n"
        )
        return EX_USAGE

    try:
        with open(rest[0], encoding="utf-8", errors="replace") as fileObj:
            text = fileObj.read()

    except OSError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EX_NOINPUT

    try:
        reduced = reduce_registry(text, fields, only)

    except ValueError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EX_USAGE

    sys.stdout.write(reduced)

    return EX_OK


if __name__ == "__main__":
    sys.exit(main([os.path.basename(sys.argv[0]), *sys.argv[1:]]))
