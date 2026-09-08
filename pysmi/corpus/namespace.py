#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The input set a corpus is built from.

A corpus is built from *source namespaces*: a vendor's directory of ASN.1
files, the standard modules pysmi bundles, a tree of Internet-Drafts. Each is
named, carries a tier, and is declared rather than discovered -- the build
reads a manifest listing them in order, so the same manifest names the same
inputs in the same order on every run and on every machine.

That ordering is load-bearing. Two namespaces can hold a module of the same
name, and exactly one copy of it can be published; which one is decided by
the compiler's precedence rule, whose tie-break is source order. A build that
discovered its inputs by walking a directory tree would have that decided by
``os.walk`` -- see pysnmp/pysmi#182.
"""

import fnmatch
import json
import os
from dataclasses import dataclass
from typing import Any, Final

from pysmi import error

#: Tier names, in the order that ranks them: a standard module outranks an
#: Internet-Draft, which outranks a vendor's. Used by
#: :py:mod:`pysmi.corpus.index` to decide which module owns an OID that more
#: than one of them defines.
TIERS: Final = ("standard", "draft", "vendor")

#: What a namespace holding no declared tier is taken to be. Vendor is the
#: safe default: it ranks last, so an undeclared namespace cannot take an OID
#: away from a standard module by omission.
DEFAULT_TIER: Final = "vendor"

#: Prefix marking a source as a Python package rather than a directory --
#: ``package:pysmi.mibs.asn1`` for the modules pysmi bundles.
PACKAGE_PREFIX: Final = "package:"

#: The manifest format this module reads.
MANIFEST_VERSION: Final = 1


@dataclass(frozen=True)
class Namespace:
    """One source of MIB modules, as the input manifest declares it.

    Attributes:
        name: what the build calls this namespace in its reports. Unique
            across the input set.
        source: a directory path, or ``package:`` and a dotted package name
            for modules shipped inside a Python package.
        tier: one of :py:data:`TIERS`.
    """

    name: str
    source: str
    tier: str = DEFAULT_TIER

    def __post_init__(self) -> None:
        """Reject a namespace the rest of the build could not act on."""
        if not self.name:
            raise error.PySmiError("namespace with no name")

        if not self.source:
            raise error.PySmiError(f"namespace {self.name} names no source")

        if self.tier not in TIERS:
            raise error.PySmiError(
                f"namespace {self.name} declares unknown tier {self.tier!r}; "
                f"expected one of {', '.join(TIERS)}"
            )

    @property
    def is_package(self) -> bool:
        """Whether this namespace lives in a Python package."""
        return self.source.startswith(PACKAGE_PREFIX)

    @property
    def package(self) -> str:
        """The dotted package name, for a namespace that names one."""
        return self.source[len(PACKAGE_PREFIX) :]

    @property
    def tier_rank(self) -> int:
        """Where this tier sorts, lower being better."""
        return TIERS.index(self.tier)


def _expand(entry: dict[str, Any], root: str) -> list[Namespace]:
    """Turn one manifest entry into the namespaces it declares.

    An entry either names a single source, or an ``include`` glob standing
    for every directory matching it. The glob is expanded here rather than by
    the shell, and sorted, so an entry covering 300 vendor directories still
    names them in one order.
    """
    tier = entry.get("tier", DEFAULT_TIER)

    if "include" in entry:
        if "source" in entry or "name" in entry:
            raise error.PySmiError(
                "manifest entry sets both include and source or name; "
                "an include stands for the directories it matches"
            )

        pattern = entry["include"]

        if pattern.startswith(PACKAGE_PREFIX):
            raise error.PySmiError(f"include cannot name a package: {pattern}")

        base = os.path.join(root, os.path.dirname(pattern))
        leaf = os.path.basename(pattern)

        try:
            names = sorted(os.listdir(base))

        except OSError as exc:
            raise error.PySmiError(
                f"cannot read {base} for include {pattern}: {exc}"
            ) from exc

        return [
            Namespace(name=name, source=os.path.join(base, name), tier=tier)
            for name in names
            if fnmatch.fnmatchcase(name, leaf)
            and os.path.isdir(os.path.join(base, name))
        ]

    try:
        source = entry["source"]

    except KeyError:
        raise error.PySmiError(
            "manifest entry names neither source nor include"
        ) from None

    name = entry.get("name") or (
        source[len(PACKAGE_PREFIX) :]
        if source.startswith(PACKAGE_PREFIX)
        else os.path.basename(os.path.normpath(source))
    )

    if not source.startswith(PACKAGE_PREFIX) and not os.path.isabs(source):
        source = os.path.join(root, source)

    return [Namespace(name=name, source=source, tier=tier)]


def load_manifest(path: str) -> list[Namespace]:
    """Read a corpus manifest and return the namespaces it declares, in order.

    The manifest is JSON::

        {
          "version": 1,
          "namespaces": [
            {"name": "standard", "source": "package:pysmi.mibs.asn1",
             "tier": "standard"},
            {"include": "src/vendor/*", "tier": "vendor"}
          ]
        }

    Relative paths are resolved against the manifest's own directory, so a
    manifest committed beside the sources it names works from any working
    directory.

    Args:
        path: the manifest file

    Returns:
        Every namespace declared, in declaration order.

    Raises:
        PySmiError: the manifest could not be read, is of a version this
            release does not know, or declares a namespace twice.
    """
    try:
        with open(path, encoding="utf-8") as fileObj:
            manifest = json.load(fileObj)

    except (OSError, ValueError) as exc:
        raise error.PySmiError(f"cannot read corpus manifest {path}: {exc}") from exc

    if not isinstance(manifest, dict):
        raise error.PySmiError(f"corpus manifest {path} is not an object")

    version = manifest.get("version", MANIFEST_VERSION)

    if version != MANIFEST_VERSION:
        raise error.PySmiError(
            f"corpus manifest {path} is version {version}; "
            f"this release reads version {MANIFEST_VERSION}"
        )

    entries = manifest.get("namespaces")

    if not isinstance(entries, list) or not entries:
        raise error.PySmiError(f"corpus manifest {path} declares no namespaces")

    root = os.path.dirname(os.path.abspath(path))
    namespaces: list[Namespace] = []

    for entry in entries:
        if not isinstance(entry, dict):
            raise error.PySmiError(f"corpus manifest {path} holds a non-object entry")

        namespaces.extend(_expand(entry, root))

    seen: dict[str, Namespace] = {}

    for namespace in namespaces:
        if namespace.name in seen:
            raise error.PySmiError(
                f"corpus manifest {path} declares namespace "
                f"{namespace.name} more than once"
            )

        seen[namespace.name] = namespace

    return namespaces
