#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The IANA Private Enterprise Numbers registry, read and reduced.

A corpus knows that ``CISCO-ENTITY-ALARM-MIB`` registers under
``1.3.6.1.4.1.9``. It does not know that ``1.3.6.1.4.1.9`` is Cisco: nothing in
the MIB text says so in a form anything can rely on, and the directory a file
sits in is a filing convention rather than a registration.

The registration is a published fact. Measured against pysnmp/mibs'
``index-frozen.csv`` (5,347 modules, 95,462 rows) and a registry snapshot of
2026-09-10 (66,807 entries):

=========================================  =======
measured over pysnmp/mibs                    count
=========================================  =======
modules registering under ``1.3.6.1.4.1``    5,015
distinct enterprise arcs                       351
arcs the registry names                    **350**
of those, carrying a contact email         **345**
=========================================  =======

One arc does not resolve -- ``1.3.6.1.4.1.1004849``, above anything IANA has
allocated -- and is reported as unregistered rather than guessed at.

Taken as an input. Never bundled, never fetched
-----------------------------------------------

**Reproducibility.** :py:mod:`pysmi.corpus.driver` opens on the property that
the build fetches nothing: a build with the network unplugged produces the same
corpus as one without. A registry that changes daily, fetched at build time,
would end that.

**Size.** 5.1 MB that changes daily is not a thing to vendor into a compiler.

What the reducer keeps is the caller's decision
-----------------------------------------------

A downstream repository commits the reduced snapshot, so
:py:func:`reduce_registry` controls which fields leave IANA's copy. Different
corpora will want different field sets, so it is an argument rather than a
hard-coded projection: :py:data:`FIELDS` is the whole record, and a corpus
wanting less names less.

The contact fields are kept by default, and rendered. The registry is public,
already well indexed, and reproducible from the published file with minimal
effort, and every identifiable person in it submitted their own details as the
registrant of record for an arc they asked IANA to assign.

Two things follow from a corpus site not being a system of record, and none
existing for MIB ownership:

* **Each source is rendered as that source publishes it.** IANA writes
  ``davej&cisco.com`` rather than the ``@`` form. That is reproduced.
  :py:func:`reduce_registry` does not normalise it, because its output is a
  rendering of IANA's record rather than a corrected version of it.
* **The authority link travels with the record.** A correction to a
  registration belongs at IANA, and :py:func:`authority_url` says where.

Remediation is precedence rather than a suppression list. A registrant who does
not want an undated personal registration standing as the contact for their arc
publishes a module carrying current ``ORGANIZATION`` and ``CONTACT-INFO``, and
that source displaces this one on the next build -- see
:py:mod:`pysmi.corpus.entity`. That needs no per-record exclusion mechanism
here, and it improves the corpus.

Why the parser is here
----------------------

There is no maintained Python distribution of this registry -- ``pen-registry``,
``iana-enterprise-numbers`` and ``snmp-enterprise-numbers`` are all unclaimed on
PyPI. So every downstream distribution that wants this writes the same thirty
lines against the same slightly awkward four-line-record text format. It is
generic over corpora, which is the test for living in pysmi.

Reducing a download, once:

.. code-block:: sh

   python -m pysmi.registry enterprise-numbers.txt > pen-snapshot.csv

and the snapshot is what a build is pointed at. ``--fields`` narrows what it
keeps.

What it does not model
----------------------

The registry maps *arcs* to *registrants*, and a company can hold several:
pysnmp/mibs carries Cisco modules under ``1.3.6.1.4.1.9`` and, from the Altiga
acquisition, under ``1.3.6.1.4.1.3076``, which IANA still lists as "Altiga
Networks, Inc.". Nothing in the registry models an acquisition and pysmi does
not infer one. This groups by arc; a consumer saying otherwise is saying it on
its own account.
"""

import csv
import io
import re
from collections.abc import Iterable, Iterator
from typing import Final, NamedTuple

#: The arc every private enterprise registration sits under, as
#: :rfc:`2578` section 8.4 assigns it.
ENTERPRISES: Final = "1.3.6.1.4.1"

#: A record's first line: the decimal number, alone.
_NUMBER: Final = re.compile(r"^(\d+)$")

#: What IANA writes where an organization has none on record. Read as no name
#: rather than as a name, so a consumer renders it as unregistered.
_NONE: Final = "---none---"

#: Every field a record carries, in the order the registry writes them. The
#: default field set for :py:func:`reduce_registry`, and the widest one: a
#: reduced snapshot is a projection of this and never more than it.
FIELDS: Final = ("number", "organization", "contact", "email")

#: Where the registry itself is published, which is where a correction to a
#: registration belongs.
AUTHORITY: Final = "https://www.iana.org/assignments/enterprise-numbers"


class Registrant(NamedTuple):
    """One enterprise number and who holds it, as IANA records it.

    Every field is as the registry writes it, unnormalised. An email is
    ``davej&cisco.com`` here because that is what the file says, and this is a
    rendering of IANA's record rather than a corrected version of it.
    """

    #: The number, as the arc under :py:data:`ENTERPRISES`.
    number: int

    #: The organization IANA records. ``""`` where the registry has none,
    #: which it writes as ``---none---``. For 11% of records this is a named
    #: individual rather than a company.
    organization: str

    #: The contact IANA records for the arc. ``""`` where there is none.
    contact: str = ""

    #: That contact's email, in the registry's own obfuscated form. ``""``
    #: where there is none: 345 of the 350 arcs pysnmp/mibs uses carry one.
    email: str = ""

    @property
    def arc(self) -> str:
        """The OID this registration names, in full."""
        return f"{ENTERPRISES}.{self.number}"

    @property
    def authority(self) -> str:
        """Where this registration is published, and where a correction goes."""
        return authority_url(self.number)


def authority_url(number: int) -> str:
    """Where an enterprise registration is published.

    A corpus site is not a system of record for MIB ownership and none exists,
    so what it can do is say who published the fact and where to have it
    changed.

    Args:
        number: the enterprise number.

    Returns:
        The registry's own URL, anchored at the registration.
    """
    return f"{AUTHORITY}#{number}"


def parse_registry(text: str) -> Iterator[Registrant]:
    """Read the registry as IANA publishes it.

    The format is four lines per record -- number, organization, contact name,
    contact email -- with the number alone at the start of its line and the
    other three indented. The two contact lines are read and dropped: see the
    privacy note in this module's own documentation.

    Args:
        text: the registry file's contents.

    Yields:
        One :py:class:`Registrant` per record, in file order. The prose
        preamble yields nothing: a record is a bare number followed by an
        indented line, and nothing in the preamble is shaped that way.
    """
    lines = text.splitlines()

    for index, line in enumerate(lines):
        found = _NUMBER.match(line)

        if not found:
            continue

        # A number on its own is only a record when something indented follows
        # it. That is what keeps a bare number in the preamble -- or a blank
        # line at the end of the file -- from being read as a registration
        # with no organization.
        if index + 1 >= len(lines):
            continue

        if not lines[index + 1][:1].isspace():
            continue

        # The three lines under the number, in order, as far as the record
        # goes. A record that stops short is read as far as it runs rather
        # than skipped: the number and the organization are the load-bearing
        # part, and a truncated record still has them.
        fields = ["", "", ""]

        for offset in range(3):
            below = index + 1 + offset

            if below >= len(lines) or not lines[below][:1].isspace():
                break

            fields[offset] = lines[below].strip()

        organization, contact, email = ("" if x == _NONE else x for x in fields)

        yield Registrant(int(found[1]), organization, contact, email)


def reduce_registry(text: str, fields: "Iterable[str] | None" = None) -> str:
    """Reduce the published registry to the fields a corpus wants.

    A downstream repository commits the result, so which fields leave IANA's
    copy is that repository's decision rather than this function's. The default
    is the whole record; a corpus wanting less names less.

    Nothing is normalised. An email comes out as ``davej&cisco.com`` because
    that is what the registry says, and the output is a rendering of IANA's
    record rather than a corrected version of it.

    Args:
        text: the registry file's contents, as IANA publishes it.
        fields: which of :py:data:`FIELDS` to keep, in the order they should be
            written. Defaults to all of them. ``number`` is kept whether or not
            it is named -- a row that does not say which arc it is about is not
            a registration.

    Returns:
        The reduced form: a header naming the fields kept, then one row per
        registration in numeric order. Deterministic, so a refresh that changes
        nothing produces no diff.

    Raises:
        ValueError: a field was named that no record has.
    """
    wanted = tuple(fields) if fields is not None else FIELDS

    unknown = [x for x in wanted if x not in FIELDS]

    if unknown:
        raise ValueError(
            f"no such registry field: {', '.join(unknown)}; "
            f"expected some of {', '.join(FIELDS)}"
        )

    if "number" not in wanted:
        wanted = ("number", *wanted)

    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")

    writer.writerow(wanted)

    for registrant in sorted(parse_registry(text), key=lambda x: x.number):
        writer.writerow([getattr(registrant, name) for name in wanted])

    return out.getvalue()


def is_pen_registry(text: str) -> bool:
    """Whether *text* is this registry rather than another.

    ``--oid-registry`` takes more than one kind of file, so something has to
    decide which reader a given one wants. Sniffed from the content rather
    than from the file name, because a snapshot a repository commits is named
    whatever that repository calls it.

    Args:
        text: the file's contents, or enough of the front of it.

    Returns:
        Whether it is the published registry or a reduced snapshot of one.
    """
    head = text.lstrip()

    if head.lower().startswith("number,"):
        return True

    return "PRIVATE ENTERPRISE NUMBERS" in text[:4096]


def load_registry(path: str) -> dict[int, Registrant]:
    """Read a registry from a file, reduced or as published.

    Both forms are accepted, because a caller holding a fresh download should
    not have to reduce it before a build will read it -- and a caller holding a
    reduced snapshot, which is what a repository should commit, should not have
    to keep the original around.

    A reduced snapshot may carry fewer fields than the published file. What it
    does not carry comes back as ``""``, which is the same answer as a
    registration that has no contact on record: either way there is nothing to
    render, and a corpus site is not the place to explain which kind of nothing
    it is.

    Args:
        path: the file. Its first line decides which form it is in.

    Returns:
        The registration per enterprise number.

    Raises:
        OSError: the file cannot be read. A build pointed at a registry that is
            not there is a build misconfigured, not one to carry on with
            quietly.
    """
    with open(path, encoding="utf-8", errors="replace", newline="") as fileObj:
        text = fileObj.read()

    if not text.lstrip().lower().startswith("number,"):
        return {x.number: x for x in parse_registry(text)}

    rows = csv.reader(io.StringIO(text, newline=""))
    header = [x.strip().lower() for x in next(rows, [])]

    found: dict[int, Registrant] = {}

    for row in rows:
        record = dict(zip(header, (x.strip() for x in row), strict=False))
        number = record.get("number", "")

        if number.isdigit():
            found[int(number)] = Registrant(
                int(number),
                record.get("organization", ""),
                record.get("contact", ""),
                record.get("email", ""),
            )

    return found
