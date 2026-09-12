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
from dataclasses import dataclass, field
from typing import Any, Final

from pysmi import error

#: Tier names in the order that ranks them. A standard module outranks an
#: Internet-Draft and an Internet-Draft outranks a vendor's. Used by
#: :py:mod:`pysmi.corpus.index` to decide which module owns an OID that more
#: than one of them defines.
TIERS: Final[tuple[str, ...]] = ("standard", "draft", "vendor")

#: What a namespace holding no declared tier is taken to be. Vendor is the
#: safe default: it ranks last, so an undeclared namespace cannot take an OID
#: away from a standard module by omission.
DEFAULT_TIER: Final[str] = "vendor"

#: Prefix marking a source as a Python package rather than a directory --
#: ``package:pysmi.mibs.asn1`` for the modules pysmi bundles.
PACKAGE_PREFIX: Final[str] = "package:"

#: The manifest format this module reads.
MANIFEST_VERSION: Final[int] = 1

#: The expectations a manifest may declare, mapped to the shape each takes:
#: ``bound`` is an object of ``min`` and ``max``, ``names`` a list of strings.
#: Declared rather than free-form, so that a misspelled expectation is an
#: error at load time. An expectation silently ignored is worse than none:
#: the publisher believes it is being checked.
EXPECTATIONS: Final[dict[str, str]] = {
    "modules": "bound",
    "failures": "bound",
    "namespaces-present": "names",
}


@dataclass(frozen=True)
class Namespace:
    """One source of MIB modules, as the input manifest declares it.

    Attributes:
        name: what the build calls this namespace in its reports. Unique
            across the input set.
        source: a directory path, or ``package:`` and a dotted package name
            for modules shipped inside a Python package.
        tier: one of :py:data:`TIERS`.
        publish: whether the corpus carries this namespace's modules, as
            against merely resolving against them. A namespace declared
            ``"publish": false`` supplies whatever the published modules
            import and contributes nothing to the output: nothing of its is
            staged, compiled or indexed, and it is stubbed in every output
            format so that it cannot arrive as a dependency either.

            This is what separates the two corpora built from one source
            set. The corpus pysnmp/mibs publishes carries the standard
            modules, because its consumers fetch them from it -- sc4snmp
            resolves ``asn1/@mib@`` for every module it meets. A corpus
            built for a runtime that already has the standard modules --
            pysmi bundles 210 of them and the wheel ships their compiled
            form -- carries only what that runtime does not have, and says
            so by declaring the standard namespace unpublished rather than
            by leaving it out, which would break every vendor module that
            imports ``SNMPv2-SMI``.
    """

    name: str
    source: str
    tier: str = DEFAULT_TIER
    publish: bool = True

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
    publish = entry.get("publish", True)

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
            Namespace(
                name=name,
                source=os.path.normpath(os.path.join(base, name)),
                tier=tier,
                publish=publish,
            )
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

    if not source.startswith(PACKAGE_PREFIX):
        # Normalised, and against the manifest's own directory when relative.
        # A manifest is written with "/" whatever it will be read on, so
        # without this a namespace on Windows carries a source spelled half
        # one way and half the other -- which still opens, but is what the
        # report records and what an overlapping-directory check compares.
        source = os.path.normpath(
            source if os.path.isabs(source) else os.path.join(root, source)
        )

    return [Namespace(name=name, source=source, tier=tier, publish=publish)]


@dataclass(frozen=True)
class Manifest:
    """What a corpus manifest declares.

    A manifest used to declare which sources a corpus is built from and
    nothing else, which left the definition of a distribution split between
    a JSON file pysmi reads and a build script pysmi has never seen. The
    emit set and the expectations are the rest of that definition -- see
    pysnmp/pysmi#263.

    Attributes:
        namespaces: the input set, in declaration order.
        emit: the artifacts this corpus carries, in ``--emit`` syntax --
            an artifact name, optionally ``:`` and a path of its own.
            ``None`` where the manifest does not say, which is the full
            published layout. A command line naming ``--emit`` overrides
            this, as flags override files.
        expect: what must be true of the build, keyed by
            :py:data:`EXPECTATIONS`. Empty where the manifest declares none.
        site: how ``--emit=site`` renders and publishes, keyed by
            :py:data:`SITE_SETTINGS`. Empty where the manifest declares none,
            which gives the built-in theme and no crawl surface. See
            pysnmp/pysmi#284.
    """

    namespaces: list[Namespace]
    emit: list[str] | None = None
    expect: dict[str, Any] = field(default_factory=dict)
    site: dict[str, Any] = field(default_factory=dict)


#: The settings ``site`` may declare, mapped to the shape each takes.
#:
#: ``base-url`` is what makes a build a **distribution site** rather than a
#: subtree somebody else will assemble: given, the whole crawl surface is
#: written, and without it there is nothing to put in a canonical link. The
#: rest are the page frame, which a distribution replaces so that this looks
#: like the documentation it is published beside.
SITE_SETTINGS: Final[dict[str, type | tuple[type, ...]]] = {
    "base-url": str,
    "description": str,
    "name": str,
    "template": str,
    "stylesheet": str,
    "page-size": (int, dict),
    "crawl": dict,
}


def _read_site(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    """The ``site`` key, checked.

    A setting this release does not know is refused rather than ignored. A
    manifest saying ``base_url`` where the key is ``base-url`` would otherwise
    publish a site with no canonical links and no sitemap, and say nothing
    about why.
    """
    if "site" not in manifest:
        return {}

    declared = manifest["site"]

    if not isinstance(declared, dict):
        raise error.PySmiError(f"corpus manifest {path}: site is not an object")

    unknown = sorted(set(declared) - set(SITE_SETTINGS))

    if unknown:
        raise error.PySmiError(
            f"corpus manifest {path}: site declares "
            f"{', '.join(unknown)}; expected some of "
            f"{', '.join(sorted(SITE_SETTINGS))}"
        )

    for name, value in declared.items():
        if not isinstance(value, SITE_SETTINGS[name]) or isinstance(value, bool):
            expected = SITE_SETTINGS[name]
            spelled = (
                " or ".join(x.__name__ for x in expected)
                if isinstance(expected, tuple)
                else expected.__name__
            )

            raise error.PySmiError(
                f"corpus manifest {path}: site {name} is "
                f"{type(value).__name__}, expected {spelled}"
            )

    # A relative path in a manifest is relative to the manifest, like every
    # other path one carries: a theme file sits beside the manifest that names
    # it, not beside whatever directory the build was started from.
    where = os.path.dirname(os.path.abspath(path))
    settings = dict(declared)

    for name in ("template", "stylesheet"):
        if settings.get(name) and not os.path.isabs(settings[name]):
            settings[name] = os.path.normpath(os.path.join(where, settings[name]))

    return settings


def _read_emit(manifest: dict[str, Any], path: str) -> list[str] | None:
    """The ``emit`` key, checked."""
    if "emit" not in manifest:
        return None

    emitted = manifest["emit"]

    if not isinstance(emitted, list) or not all(isinstance(x, str) for x in emitted):
        raise error.PySmiError(
            f"corpus manifest {path} declares emit as something other than "
            f"a list of artifact names"
        )

    if not emitted:
        raise error.PySmiError(
            f"corpus manifest {path} declares an empty emit set; a corpus "
            f"carrying no artifact is not a corpus"
        )

    return emitted


def _read_expect(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    """The ``expect`` key, checked against :py:data:`EXPECTATIONS`."""
    if "expect" not in manifest:
        return {}

    expect = manifest["expect"]

    if not isinstance(expect, dict):
        raise error.PySmiError(f"corpus manifest {path} declares expect as non-object")

    for key, value in expect.items():
        try:
            shape = EXPECTATIONS[key]

        except KeyError:
            raise error.PySmiError(
                f"corpus manifest {path} expects {key!r}, which is not "
                f"something a build reports; expected one of "
                f"{', '.join(sorted(EXPECTATIONS))}"
            ) from None

        if shape == "bound":
            if not isinstance(value, dict) or not value:
                raise error.PySmiError(
                    f"corpus manifest {path} expects {key} as something "
                    f"other than an object of min and max"
                )

            for bound, limit in value.items():
                if bound not in ("min", "max") or not isinstance(limit, int):
                    raise error.PySmiError(
                        f"corpus manifest {path} bounds {key} by "
                        f"{bound!r}; expected min or max, as an integer"
                    )

        elif not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise error.PySmiError(
                f"corpus manifest {path} expects {key} as something other "
                f"than a list of names"
            )

    return expect


def load_manifest(path: str) -> list[Namespace]:
    """Read a corpus manifest and return the namespaces it declares, in order.

    The manifest is JSON::

        {
          "version": 1,
          "emit": ["asn1", "index-v2", "report"],
          "expect": {"modules": {"min": 8000}},
          "namespaces": [
            {"name": "standard", "source": "package:pysmi.mibs.asn1",
             "tier": "standard"},
            {"include": "src/vendor/*", "tier": "vendor"}
          ]
        }

    A namespace may declare ``"publish": false``, which makes it a resolution
    source and nothing else -- see :py:class:`Namespace`.

    Relative paths are resolved against the manifest's own directory, so a
    manifest committed beside the sources it names works from any working
    directory.

    This is :py:func:`read_manifest` with everything but the namespaces
    dropped, which is what a caller supplying its own artifact selection
    wants. ``emit`` and ``expect`` are still validated: a manifest this
    refuses is refused whichever way it is read.

    Args:
        path: the manifest file

    Returns:
        Every namespace declared, in declaration order.

    Raises:
        PySmiError: the manifest could not be read, is of a version this
            release does not know, or declares a namespace twice.
    """
    return read_manifest(path).namespaces


def _read_namespaces(manifest: dict[str, Any], path: str) -> list[Namespace]:
    """The ``namespaces`` key, expanded and checked."""
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


def read_manifest(path: str) -> Manifest:
    """Read a corpus manifest whole: its sources, its artifacts, its policy.

    Args:
        path: the manifest file

    Returns:
        The manifest as declared.

    Raises:
        PySmiError: the manifest could not be read, is of a version this
            release does not know, declares a namespace twice, or declares
            an ``emit`` or ``expect`` a build could not act on.
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

    return Manifest(
        namespaces=_read_namespaces(manifest, path),
        emit=_read_emit(manifest, path),
        expect=_read_expect(manifest, path),
        site=_read_site(manifest, path),
    )
