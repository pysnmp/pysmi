#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A second date per module, supplied by the distribution publishing the site.

Every date a MIB carries is the publisher's: LAST-UPDATED and the REVISION
clauses say when the vendor changed the module, which is what the entry point's
recent lists are ordered by. That answers "what has the industry published
lately" and cannot answer "what have we done lately" -- a module taken today
may carry a revision from 1994, and a module corrected today carries whatever
date the publisher last put in it.

That second date is a fact about a distribution rather than about a MIB, so it
arrives from one. A manifest names a JSON file of module to ``YYYY-MM-DD``:

.. code-block:: json

   {"IF-MIB": "2026-09-17", "CISCO-IPMCAST-MIB": "2026-04-02"}

How a distribution knows the date is its own business -- pysnmp/mibs reads the
commit that last touched each file -- and a module the file does not name
simply has no such date and is not listed under one.

See ``site.changed`` in :py:data:`pysmi.corpus.namespace.SITE_SETTINGS`.
"""

import json
import re
from collections.abc import Mapping
from typing import Any, Final, NamedTuple

from pysmi import error

#: A date this can place a module by. The recent lists sort on these and print
#: them verbatim, so anything else is refused rather than rendered: a row
#: reading "last week" sorts nowhere and says nothing a reader can compare.
DATE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: What the entry point calls the list when a manifest names no label. Said
#: from the reader's side -- they are on the distribution's own site -- and
#: neutral about what changed, since taking a module and correcting one both
#: land here.
LABEL: Final = "Updated here"


class Changed(NamedTuple):
    """The distribution's own dates, and what to call them."""

    #: The heading and tab label, e.g. "Added or updated here".
    label: str

    #: Module to ``YYYY-MM-DD``. A module absent from this has no such date.
    dates: Mapping[str, str]


def read_changed(path: str, label: str = "") -> Changed:
    """The dates file a manifest named.

    Args:
        path: the JSON file, as ``site.changed.dates`` names it.
        label: what to call the list, or "" for :py:data:`LABEL`.

    Returns:
        The dates, keyed by module name.

    Raises:
        pysmi.error.PySmiError: the file will not read, is not an object of
            module to date, or carries a date this cannot sort by. A build
            that quietly published an empty list here would state that the
            distribution has changed nothing, which is a different claim from
            "this build was not told".
    """
    try:
        with open(path, encoding="utf-8") as fileObj:
            found = json.load(fileObj)

    except OSError as exc:
        raise error.PySmiError(f"cannot read the site dates at {path}: {exc}") from exc

    except ValueError as exc:
        raise error.PySmiError(f"site dates at {path} are not JSON: {exc}") from exc

    return Changed(label=label or LABEL, dates=_dates(found, path))


def _dates(found: Any, path: str) -> "dict[str, str]":
    """The mapping out of a parsed dates file, checked."""
    if not isinstance(found, dict):
        raise error.PySmiError(
            f"site dates at {path} are {type(found).__name__}, expected an "
            f"object of module name to YYYY-MM-DD"
        )

    dates = {}

    for module, date in found.items():
        if not isinstance(date, str) or not DATE.match(date):
            raise error.PySmiError(
                f"site dates at {path}: {module} is dated {date!r}, which is "
                f"not a YYYY-MM-DD the recent lists can sort by"
            )

        dates[str(module)] = date

    return dates
