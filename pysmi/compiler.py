#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Driving the transformation of MIB modules.

:class:`MibCompiler` ties together the other parts of PySMI: readers pull ASN.1
text from somewhere, a parser turns it into an AST, a code generator renders it
into the destination format, a writer stores the result, searchers decide what
can be skipped and borrowers supply a pre-compiled module when compilation
fails.
"""

import logging
from typing import Any, Final

from pysmi import __name__ as packageName
from pysmi import __version__ as packageVersion
from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.borrower.base import AbstractBorrower
from pysmi.codegen.base import AbstractCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.mibinfo import MibInfo, source_digest
from pysmi.parser.base import AbstractParser
from pysmi.reader.base import AbstractReader
from pysmi.searcher.base import AbstractSearcher
from pysmi.writer.base import AbstractWriter

logger = logging.getLogger(__name__)

_AT_MIB_SUFFIX: Final = " at MIB %s"


@deprecated_camel_case
class MibStatus(str):
    """Indicate MIB transformation result.

    *MibStatus* is a subclass of Python string type. Some additional
    attributes may be set to indicate the details.

    The following *MibStatus* class instances are defined:

    * *compiled* - MIB is successfully transformed
    * *untouched* - fresh transformed version of this MIB already exisits
    * *failed* - MIB transformation failed. *error* attribute carries details.
    * *unprocessed* - MIB transformation required but waived for some reason
    * *missing* - ASN.1 MIB source can't be found
    * *borrowed* - MIB transformation failed but pre-transformed version was used
    """

    # Set by set_options() when the compiler records an outcome, so which of
    # these exist depends on the status. Reading one that was never set raises
    # AttributeError.

    #: URL the MIB was read from.
    path: str
    #: File the MIB was read from.
    file: str
    #: Name the MIB was found under, when it differs from its module name.
    alias: str
    #: MODULE-IDENTITY OID.
    oid: str
    #: All OIDs defined in the module.
    oids: tuple[str, ...]
    #: MODULE-IDENTITY OID.
    identity: str
    #: MIB revision.
    revision: str
    #: Enterprise OID.
    enterprise: tuple[str, ...]
    #: MODULE-COMPLIANCE OIDs.
    compliance: tuple[str, ...]
    #: NOTIFICATION-TYPE OIDs, including converted TRAP-TYPEs.
    notification: tuple[str, ...]
    #: Why the transformation failed.
    error: error.PySmiError

    def set_options(self, **kwargs: Any) -> "MibStatus":
        """Return a copy of this status carrying extra attributes.

        The module-level statuses are shared constants, so detail about one
        particular MIB is attached to a copy rather than to the original.
        """
        n = self.__class__(self)
        for k in kwargs:
            setattr(n, k, kwargs[k])
        return n


statusCompiled: Final = MibStatus("compiled")
statusUntouched: Final = MibStatus("untouched")
statusFailed: Final = MibStatus("failed")
statusUnprocessed: Final = MibStatus("unprocessed")
statusMissing: Final = MibStatus("missing")
statusBorrowed: Final = MibStatus("borrowed")


@deprecated_camel_case
class MibCompiler:
    """Top-level, user-facing, composite MIB compiler object.

    MibCompiler implements high-level MIB transformation processing logic.
    It executes its actions by calling the following specialized objects:

      * *readers* - to acquire ASN.1 MIB data
      * *searchers* - to see if transformed MIB already exists and no processing is necessary
      * *parser* - to parse ASN.1 MIB into AST
      * *code generator* - to perform actual MIB transformation
      * *borrowers* - to fetch pre-transformed MIB if transformation is impossible
      * *writer* - to store transformed MIB data

    Required components must be passed to MibCompiler on instantiation. Those
    components are: *parser*, *codegenerator* and *writer*.

    Optional components could be set or modified at later phases of MibCompiler
    life. Unlike singular, required components, optional one can be present
    in sequences to address many possible sources of data. They are
    *readers*, *searchers* and *borrowers*.
    """

    indexFile = "index"

    def __init__(self, parser: "AbstractParser", codegen: "AbstractCodeGen", writer: "AbstractWriter") -> None:
        """Creates an instance of *MibCompiler* class.

        Args:
            parser: ASN.1 MIB parser object
            codegen: MIB transformation object
            writer: transformed MIB storing object
        """
        self._parser = parser
        self._codegen = codegen
        self._symbolgen = SymtableCodeGen()
        self._writer = writer
        self._sources: list[AbstractReader] = []
        self._searchers: list[AbstractSearcher] = []
        self._borrowers: list[AbstractBorrower] = []

    def add_sources(self, *sources: "AbstractReader") -> "MibCompiler":
        """Add more ASN.1 MIB source repositories.

        MibCompiler.compile will invoke each of configured source objects
        in order of their addition asking each to fetch MIB module specified
        by name.

        Args:
            sources: reader object(s)

        Returns:
            reference to itself (can be used for call chaining)

        """
        self._sources.extend(sources)

        logger.debug(
            "current MIB source(s): %s",
            ", ".join(str(x) for x in self._sources),
            extra={"sources": [str(x) for x in self._sources]},
        )

        return self

    def add_searchers(self, *searchers: "AbstractSearcher") -> "MibCompiler":
        """Add more transformed MIBs repositories.

        MibCompiler.compile will invoke each of configured searcher objects
        in order of their addition asking each if already transformed MIB
        module already exists and is more recent than specified.

        Args:
            searchers: searcher object(s)

        Returns:
            reference to itself (can be used for call chaining)

        """
        self._searchers.extend(searchers)

        logger.debug(
            "current compiled MIBs location(s): %s",
            ", ".join(str(x) for x in self._searchers),
            extra={"searchers": [str(x) for x in self._searchers]},
        )

        return self

    def add_borrowers(self, *borrowers: "AbstractBorrower") -> "MibCompiler":
        """Add more transformed MIBs repositories to borrow MIBs from.

        Whenever MibCompiler.compile encounters MIB module which neither of
        the *searchers* can find or fetched ASN.1 MIB module can not be
        parsed (due to syntax errors), these *borrowers* objects will be
        invoked in order of their addition asking each if already transformed
        MIB can be fetched (borrowed).

        Args:
            borrowers: borrower object(s)

        Returns:
            reference to itself (can be used for call chaining)

        """
        self._borrowers.extend(borrowers)

        logger.debug(
            "current MIB borrower(s): %s",
            ", ".join(str(x) for x in self._borrowers),
            extra={"borrowers": [str(x) for x in self._borrowers]},
        )

        return self

    def compile(self, *mibnames: str, **options: Any) -> dict[str, MibStatus]:
        """Transform requested and possibly referred MIBs.

        The *compile* method should be invoked when *MibCompiler* object
        is operational meaning at least *sources* are specified.

        Once called with a MIB module name, *compile* will:

        * fetch ASN.1 MIB module with given name by calling *sources*
        * make sure no such transformed MIB already exists (with *searchers*)
        * parse ASN.1 MIB text with *parser*
        * perform actual MIB transformation into target format with *code generator*
        * may attempt to borrow pre-transformed MIB through *borrowers*
        * write transformed MIB through *writer*

        The above sequence will be performed for each MIB name given in
        *mibnames* and may be performed for all MIBs referred to from
        MIBs being processed.

        Args:
            mibnames: list of ASN.1 MIBs names
            options: options that affect the way PySMI components work

        Returns:
            A dictionary of MIB module names processed (keys) and *MibStatus*
            class instances (values)

        """
        processed: dict[str, MibStatus] = {}
        parsedMibs: dict[str, Any] = {}
        failedMibs: dict[str, Any] = {}
        borrowedMibs: dict[str, Any] = {}
        builtMibs: dict[str, Any] = {}
        symbolTableMap: dict[str, Any] = {}
        mibsToParse = [x for x in mibnames]
        canonicalMibNames: dict[str, Any] = {}

        while mibsToParse:
            mibname = mibsToParse.pop(0)

            if mibname in parsedMibs:
                logger.debug("MIB %s already parsed", mibname, extra={"mib": mibname})
                continue

            if mibname in failedMibs:
                logger.debug("MIB %s already failed", mibname, extra={"mib": mibname})
                continue

            for source in self._sources:
                logger.debug("trying source %s", source, extra={"mib": mibname, "source": str(source)})

                try:
                    fileInfo, fileData = source.get_data(mibname)

                    fileInfo.digest = source_digest(fileData)

                    for mibTree in self._parser.parse(fileData):
                        mibInfo, symbolTable = self._symbolgen.gen_code(mibTree, symbolTableMap)

                        symbolTableMap[mibInfo.name] = symbolTable

                        parsedMibs[mibInfo.name] = fileInfo, mibInfo, mibTree

                        failedMibs.pop(mibname, None)

                        mibsToParse.extend(mibInfo.imported)

                        if fileInfo.name in mibnames:
                            if mibInfo.name not in canonicalMibNames:
                                canonicalMibNames[mibInfo.name] = []
                            canonicalMibNames[mibInfo.name].append(fileInfo.name)

                        logger.debug(
                            "%s (%s) read from %s, immediate dependencies: %s",
                            mibInfo.name,
                            mibname,
                            fileInfo.path,
                            ", ".join(mibInfo.imported) or "<none>",
                            extra={
                                "mib": mibInfo.name,
                                "requested_mib": mibname,
                                "path": fileInfo.path,
                                "imported": list(mibInfo.imported),
                            },
                        )

                    break
                except UnicodeDecodeError:
                    logger.debug(
                        "cannot decode %s found at %s",
                        mibname,
                        source,
                        extra={"mib": mibname, "source": str(source)},
                    )
                    continue

                except error.PySmiReaderFileNotFoundError:
                    logger.debug("no %s found at %s", mibname, source, extra={"mib": mibname, "source": str(source)})
                    continue

                except error.PySmiError as exc:
                    exc.source = source
                    exc.mibname = mibname
                    exc.msg += _AT_MIB_SUFFIX % mibname

                    logger.debug(
                        "%serror %s from %s",
                        "ignoring " if options.get("ignoreErrors") else "failing on ",
                        exc,
                        source,
                        extra={
                            "mib": mibname,
                            "source": str(source),
                            "error": str(exc),
                            "ignored": bool(options.get("ignoreErrors")),
                        },
                    )

                    failedMibs[mibname] = exc

                    processed[mibname] = statusFailed.set_options(error=exc)

            else:
                notFound = error.PySmiError(f"MIB source {mibname} not found")
                notFound.mibname = mibname
                logger.debug("no %s found everywhere", mibname, extra={"mib": mibname})

                if mibname not in failedMibs:
                    failedMibs[mibname] = notFound

                if mibname not in processed:
                    processed[mibname] = statusMissing

        logger.debug(
            "MIBs analyzed %d, MIBs failed %d",
            len(parsedMibs),
            len(failedMibs),
            extra={"analyzed": len(parsedMibs), "failed": len(failedMibs)},
        )

        #
        # See what MIBs need generating
        #

        for mibname in tuple(parsedMibs):
            fileInfo, mibInfo, mibTree = parsedMibs[mibname]

            logger.debug("checking if %s requires updating", mibname, extra={"mib": mibname})

            for searcher in self._searchers:
                try:
                    searcher.file_exists(mibname, fileInfo.mtime, rebuild=bool(options.get("rebuild")))

                except error.PySmiFileNotFoundError:
                    logger.debug(
                        "no compiled MIB %s available through %s",
                        mibname,
                        searcher,
                        extra={"mib": mibname, "searcher": str(searcher)},
                    )
                    continue

                except error.PySmiFileNotModifiedError:
                    logger.debug(
                        "will be using existing compiled MIB %s found by %s",
                        mibname,
                        searcher,
                        extra={"mib": mibname, "searcher": str(searcher)},
                    )
                    del parsedMibs[mibname]
                    processed[mibname] = statusUntouched
                    break

                except error.PySmiError as exc:
                    exc.searcher = searcher
                    exc.mibname = mibname
                    exc.msg += _AT_MIB_SUFFIX % mibname
                    logger.debug(
                        "error from %s: %s",
                        searcher,
                        exc,
                        extra={"mib": mibname, "searcher": str(searcher), "error": str(exc)},
                    )
                    continue

            else:
                logger.debug("no suitable compiled MIB %s found anywhere", mibname, extra={"mib": mibname})

                if options.get("noDeps") and mibname not in canonicalMibNames:
                    logger.debug("excluding imported MIB %s from code generation", mibname, extra={"mib": mibname})
                    del parsedMibs[mibname]
                    processed[mibname] = statusUntouched
                    continue

        logger.debug(
            "MIBs parsed %d, MIBs failed %d",
            len(parsedMibs),
            len(failedMibs),
            extra={"parsed": len(parsedMibs), "failed": len(failedMibs)},
        )

        #
        # Generate code for parsed MIBs
        #

        for mibname in parsedMibs.copy():
            fileInfo, mibInfo, mibTree = parsedMibs[mibname]

            logger.debug(
                "compiling %s read from %s", mibname, fileInfo.path, extra={"mib": mibname, "path": fileInfo.path}
            )

            comments = [
                f"ASN.1 source {fileInfo.file or fileInfo.path}",
                f"Source digest {fileInfo.digest}",
                f"Produced by {packageName}-{packageVersion}",
            ]

            try:
                mibInfo, mibData = self._codegen.gen_code(
                    mibTree,
                    symbolTableMap,
                    comments=comments,
                    genTexts=options.get("genTexts"),
                    textFilter=options.get("textFilter"),
                )

                builtMibs[mibname] = fileInfo, mibInfo, mibData
                del parsedMibs[mibname]

                logger.debug(
                    "%s read from %s and compiled by %s",
                    mibname,
                    fileInfo.path,
                    self._writer,
                    extra={"mib": mibname, "path": fileInfo.path, "writer": str(self._writer)},
                )

            except error.PySmiError as exc:
                exc.handler = self._codegen
                exc.mibname = mibname
                exc.msg += _AT_MIB_SUFFIX % mibname

                logger.debug(
                    "error from %s: %s",
                    self._codegen,
                    exc,
                    extra={"mib": mibname, "codegen": str(self._codegen), "error": str(exc)},
                )

                processed[mibname] = statusFailed.set_options(error=exc)

                failedMibs[mibname] = exc
                del parsedMibs[mibname]

        logger.debug(
            "MIBs built %d, MIBs failed %d",
            len(parsedMibs),
            len(failedMibs),
            extra={"built": len(parsedMibs), "failed": len(failedMibs)},
        )

        #
        # Try to borrow pre-compiled MIBs for failed ones
        #

        for mibname in failedMibs.copy():
            if options.get("noDeps") and mibname not in canonicalMibNames:
                logger.debug("excluding imported MIB %s from borrowing", mibname, extra={"mib": mibname})
                continue

            for borrower in self._borrowers:
                logger.debug(
                    "trying to borrow %s from %s", mibname, borrower, extra={"mib": mibname, "borrower": str(borrower)}
                )
                try:
                    fileInfo, fileData = borrower.get_data(mibname, genTexts=options.get("genTexts"))

                    borrowedMibs[mibname] = fileInfo, MibInfo(name=mibname, imported=[]), fileData

                    del failedMibs[mibname]

                    logger.debug(
                        "%s borrowed with %s", mibname, borrower, extra={"mib": mibname, "borrower": str(borrower)}
                    )
                    break

                except error.PySmiError as exc:
                    logger.debug(
                        "error from %s: %s",
                        borrower,
                        exc,
                        extra={"mib": mibname, "borrower": str(borrower), "error": str(exc)},
                    )

        logger.debug(
            "MIBs available for borrowing %d, MIBs failed %d",
            len(borrowedMibs),
            len(failedMibs),
            extra={"borrowed": len(borrowedMibs), "failed": len(failedMibs)},
        )

        #
        # See what MIBs need borrowing
        #

        for mibname in borrowedMibs.copy():
            logger.debug("checking if failed MIB %s requires borrowing", mibname, extra={"mib": mibname})

            fileInfo, mibInfo, mibData = borrowedMibs[mibname]

            for searcher in self._searchers:
                try:
                    searcher.file_exists(mibname, fileInfo.mtime, rebuild=bool(options.get("rebuild")))

                except error.PySmiFileNotFoundError:
                    logger.debug(
                        "no compiled MIB %s available through %s",
                        mibname,
                        searcher,
                        extra={"mib": mibname, "searcher": str(searcher)},
                    )
                    continue

                except error.PySmiFileNotModifiedError:
                    logger.debug(
                        "will be using existing compiled MIB %s found by %s",
                        mibname,
                        searcher,
                        extra={"mib": mibname, "searcher": str(searcher)},
                    )
                    del borrowedMibs[mibname]
                    processed[mibname] = statusUntouched
                    break

                except error.PySmiError as exc:
                    exc.searcher = searcher
                    exc.mibname = mibname
                    exc.msg += _AT_MIB_SUFFIX % mibname

                    logger.debug(
                        "error from %s: %s",
                        searcher,
                        exc,
                        extra={"mib": mibname, "searcher": str(searcher), "error": str(exc)},
                    )

                    continue
            else:
                logger.debug("no suitable compiled MIB %s found anywhere", mibname, extra={"mib": mibname})

                if options.get("noDeps") and mibname not in canonicalMibNames:
                    logger.debug("excluding imported MIB %s from borrowing", mibname, extra={"mib": mibname})
                    processed[mibname] = statusUntouched

                else:
                    logger.debug("will borrow MIB %s", mibname, extra={"mib": mibname})
                    builtMibs[mibname] = borrowedMibs[mibname]

                    processed[mibname] = statusBorrowed.set_options(
                        path=fileInfo.path, file=fileInfo.file, alias=fileInfo.name
                    )

                del borrowedMibs[mibname]

        logger.debug(
            "MIBs built %d, MIBs failed %d",
            len(builtMibs),
            len(failedMibs),
            extra={"built": len(builtMibs), "failed": len(failedMibs)},
        )

        #
        # We could attempt to ignore missing/failed MIBs
        #

        if failedMibs and not options.get("ignoreErrors"):
            logger.debug("failing with problem MIBs %s", ", ".join(failedMibs), extra={"failed_mibs": list(failedMibs)})

            for mibname in builtMibs:
                processed[mibname] = statusUnprocessed

            return processed

        logger.debug(
            "proceeding with built MIBs %s, failed MIBs %s",
            ", ".join(builtMibs),
            ", ".join(failedMibs),
            extra={"built_mibs": list(builtMibs), "failed_mibs": list(failedMibs)},
        )

        #
        # Store compiled MIBs
        #

        for mibname in builtMibs.copy():
            fileInfo, mibInfo, mibData = builtMibs[mibname]

            try:
                if options.get("writeMibs", True):
                    self._writer.put_data(mibname, mibData, dryRun=bool(options.get("dryRun")))

                logger.debug(
                    "%s stored by %s", mibname, self._writer, extra={"mib": mibname, "writer": str(self._writer)}
                )

                del builtMibs[mibname]

                if mibname not in processed:
                    processed[mibname] = statusCompiled.set_options(
                        path=fileInfo.path,
                        file=fileInfo.file,
                        alias=fileInfo.name,
                        oid=mibInfo.oid,
                        oids=mibInfo.oids,
                        identity=mibInfo.identity,
                        revision=mibInfo.revision,
                        enterprise=mibInfo.enterprise,
                        compliance=mibInfo.compliance,
                        notification=mibInfo.notification,
                    )

            except error.PySmiError as exc:
                exc.handler = self._codegen
                exc.mibname = mibname
                exc.msg += _AT_MIB_SUFFIX % mibname

                logger.debug(
                    "error %s from %s",
                    exc,
                    self._writer,
                    extra={"mib": mibname, "writer": str(self._writer), "error": str(exc)},
                )

                processed[mibname] = statusFailed.set_options(error=exc)
                failedMibs[mibname] = exc
                del builtMibs[mibname]

        logger.debug(
            "MIBs modified: %s",
            ", ".join(x for x in processed if processed[x] in ("compiled", "borrowed")),
            extra={"modified": [x for x in processed if processed[x] in ("compiled", "borrowed")]},
        )

        return processed

    def build_index(self, processedMibs: dict[str, MibStatus], **options: Any) -> None:
        """Generate and store an index over the MIBs just compiled.

        Args:
            processedMibs: MIB module names mapped to their compilation results

        Keyword Args:
            dryRun: build the index but do not store it
            ignoreErrors: log a failure to build the index instead of raising

        Raises:
            PySmiError: the index could not be built or stored, unless
                ``ignoreErrors`` is set.
        """
        comments = [
            f"Produced by {packageName}-{packageVersion}",
        ]

        try:
            self._writer.put_data(
                self.indexFile,
                self._codegen.gen_index(
                    processedMibs, comments=comments, old_index_data=self._writer.get_data(self.indexFile)
                ),
                dryRun=bool(options.get("dryRun")),
            )
        except error.PySmiError as exc:
            exc.msg += f" at MIB index {self.indexFile}"

            logger.debug(
                "error %s when building %s",
                exc,
                self.indexFile,
                extra={"index_file": self.indexFile, "error": str(exc)},
            )

            if options.get("ignoreErrors"):
                return

            raise exc
