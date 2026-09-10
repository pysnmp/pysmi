#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the readers, and the MIB file name guessing they share."""

import logging
import os
from collections.abc import Iterable
from typing import Any

from pysmi._aliases import deprecated_camel_case
from pysmi.mibinfo import MibInfo
from pysmi.patches import APPLIED, PatchSet

logger = logging.getLogger(__name__)


@deprecated_camel_case
class AbstractReader:
    """Base class for MIB source readers.

    A reader fetches ASN.1 MIB text from one place -- a directory, a web
    server, a ZIP archive. The compiler tries its readers in the order they
    were added and takes the first that produces the module.

    Subclasses implement :py:meth:`fetch_data`. The file name guessing in
    :py:meth:`get_mib_variants` is shared by all of them, since a MIB module is
    named inside the file but a reader only has the file name to go on.
    """

    #: Whether asking this reader for a module it may not have is cheap.
    #:
    #: The compiler consults every source that can supply an authoritative
    #: module, rather than stopping at the first, so that it can pick the
    #: newest revision and report what it passed over. That is a filesystem
    #: lookup for a directory, an archive or a package, and a network round
    #: trip for a web server -- so only local readers are consulted that way,
    #: and a remote one keeps its place in plain first-match order.
    isLocal = False

    #: Whether to offer each module the patch for it, if there is one.
    #:
    #: On, because a MIB that does not compile is not what the caller asked for
    #: and pysmi knows how to fix twelve of them. Turn it off to see exactly
    #: what a source holds -- which is what the bundle refresh wants, since its
    #: job is to notice when a publisher's text has moved.
    usePatches = True

    #: Which patches to offer, or ``None`` for the set pysmi ships.
    #:
    #: A caller with patches of their own points this at a
    #: :py:class:`~pysmi.patches.PatchSet` built from their directory. Ignored
    #: when ``usePatches`` is off.
    patchSet: PatchSet | None = None

    maxMibSize = 10000000  # MIBs can't be that large
    fuzzyMatching = True  # try different file names while searching for MIB
    originalMatching = uppercaseMatching = lowcaseMatching = True
    exts: list[str] = [
        "",
        os.path.extsep + "txt",
        os.path.extsep + "mib",
        os.path.extsep + "my",
    ]
    exts.extend([x.upper() for x in exts if x])

    def set_options(self, **kwargs: Any) -> "AbstractReader":
        """Set reader options as attributes.

        Keyword Args:
            kwargs: option names and values, each assigned to the reader

        Returns:
            The reader, so calls can be chained.
        """
        for k, v in kwargs.items():
            setattr(self, k, v)
        return self

    def get_mib_variants(
        self, mibname: str, **options: Any
    ) -> Iterable[tuple[str, str]]:
        """Guess the file names a MIB module might be stored under.

        A module is named inside the file, not by it, so the same MIB turns up
        as ``IF-MIB``, ``if-mib.txt``, ``IF-MIB.my`` and so on. This produces
        the spellings to try, honouring the ``originalMatching``,
        ``uppercaseMatching``, ``lowcaseMatching`` and ``fuzzyMatching``
        attributes, each combined with every extension in ``exts``.

        Args:
            mibname (str): MIB module name to look for

        Keyword Args:
            exts: extensions to try instead of the ``exts`` attribute

        Returns:
            Pairs of MIB alias and candidate file name.
        """
        filenames = []

        if self.originalMatching:
            filenames.append(mibname)

        if self.uppercaseMatching:
            filenames.append(mibname.upper())

        if self.lowcaseMatching:
            filenames.append(mibname.lower())

        if self.fuzzyMatching:
            part = filenames[-1].find("-mib")
            if part != -1:
                filenames.extend([x[:part] for x in filenames])
            else:
                suffixed = mibname + "-mib"
                filenames.append(suffixed.upper())
                filenames.append(suffixed.lower())

        return ((x, x + y) for x in filenames for y in options.get("exts", self.exts))

    def get_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Fetch the ASN.1 source of a MIB module, patched if it needs it.

        Subclasses implement :py:meth:`fetch_data`; this adds the part every
        source needs alike. Some published MIBs do not compile, and the fix for
        each is a small diff kept in :py:mod:`pysmi.patches`. Applying it here
        rather than to pysmi's own bundled copies is what makes the fix reach a
        caller's own copy of the module too -- see that module for why that
        matters to source precedence.

        Args:
            mibname (str): MIB module name to fetch

        Keyword Args:
            options: passed through to :py:meth:`get_mib_variants`

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and its ASN.1 text.
            :py:attr:`~pysmi.mibinfo.MibInfo.patch` records what the patch for
            this module did, if there is one.

        Raises:
            PySmiReaderFileNotFoundError: this source does not have the MIB.
            PySmiReaderFileNotModifiedError: the source is older than requested.
        """
        mibinfo, data = self.fetch_data(mibname, **options)

        if not self.usePatches:
            return mibinfo, data

        available = self.patchSet if self.patchSet is not None else PatchSet.bundled()

        # The name the module is filed under here, not the alias the file name
        # happened to spell, since a patch is cut against the module.
        data, mibinfo.patch = available.apply(mibname, data)

        if mibinfo.patch == APPLIED:
            logger.info(
                "patched MIB %s from %s",
                mibname,
                mibinfo.path,
                extra={"mib": mibname, "path": mibinfo.path},
            )

        return mibinfo, data

    def fetch_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Fetch the ASN.1 source of a MIB module from this source.

        The part of :py:meth:`get_data` that differs per source. Implement this
        rather than *get_data*, so the module comes back patched.

        Args:
            mibname (str): MIB module name to fetch

        Keyword Args:
            options: passed through to :py:meth:`get_mib_variants`

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and its ASN.1 text,
            exactly as this source holds them.

        Raises:
            PySmiReaderFileNotFoundError: this source does not have the MIB.
            PySmiReaderFileNotModifiedError: the source is older than requested.
        """
        raise NotImplementedError

    def list_mibs(self) -> Iterable[str]:
        """Names of the MIB modules this source holds.

        Enumeration is what lets a caller compile a whole collection without
        naming every module in it. Only a source that can be listed answers:
        a web server given a ``@mib@`` URL template answers for a name it is
        handed and cannot be asked what it has, so it returns nothing here
        rather than guessing.

        The names come from the module headers in the text, not from the file
        names, because a MIB module is named inside the file and one file may
        hold several.

        Returns:
            Module names, each appearing once. Empty when this source cannot
            be enumerated -- which is not the same as being empty, and callers
            that need the distinction should ask ``isLocal``.
        """
        return ()

    def clear_cache(self) -> None:
        """Discard anything this reader has cached about what exists where.

        A no-op by default. :py:class:`~pysmi.reader.localfile.FileReader`
        remembers each directory it lists for its own lifetime, so a MIB
        deleted after that listing was taken stays invisible to it until
        this is called -- which is exactly wrong for
        :py:meth:`~pysmi.compiler.MibCompiler.prune`, whose one job is to
        notice a MIB is gone. *prune* calls this on every source before
        checking what still exists, so a reader already warmed up by an
        earlier *compile* in the same run does not mask a removal.
        """
