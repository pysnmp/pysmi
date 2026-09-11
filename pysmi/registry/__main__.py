#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Reduce a published registry to the fields a corpus wants.

.. code-block:: sh

   python -m pysmi.registry enterprise-numbers.txt > pen-snapshot.csv
   python -m pysmi.registry --fields=number,organization FILE > lean.csv

A downstream repository commits the result, so which fields leave IANA's copy
is that repository's decision. The default is the whole record -- number,
organization, contact and email -- and ``--fields`` narrows it. Nothing is
normalised: an email comes out as ``davej&cisco.com`` because that is what the
registry says. See :py:mod:`pysmi.registry.pen`.

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


def main(argv: list[str]) -> int:
    """Write the reduced registry on standard output."""
    fields = None
    rest = []

    for argument in argv[1:]:
        if argument.startswith("--fields="):
            fields = [x.strip() for x in argument.partition("=")[2].split(",") if x]

        else:
            rest.append(argument)

    if len(rest) != 1:
        sys.stderr.write(
            f"Usage: python -m {__package__} [--fields=A,B] "
            "<enterprise-numbers.txt>\n"
            "Writes the reduced registry on standard output. Fields default "
            f"to all of them: {', '.join(FIELDS)}.\n"
        )
        return EX_USAGE

    try:
        with open(rest[0], encoding="utf-8", errors="replace") as fileObj:
            text = fileObj.read()

    except OSError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EX_NOINPUT

    try:
        reduced = reduce_registry(text, fields)

    except ValueError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return EX_USAGE

    sys.stdout.write(reduced)

    return EX_OK


if __name__ == "__main__":
    sys.exit(main([os.path.basename(sys.argv[0]), *sys.argv[1:]]))
