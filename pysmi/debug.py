#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Debug logging control.

PySMI logs through the standard :mod:`logging` module. Every module obtains its
logger with ``logging.getLogger(__name__)``, so the logger hierarchy mirrors the
package layout and debug output is selected with ordinary logging configuration::

    logging.getLogger("pysmi.compiler").setLevel(logging.DEBUG)

:func:`enableDebugLogging` is a convenience wrapper over that for command line
tools, mapping the debug category names accepted by ``mibdump --debug`` onto the
loggers they stand for.

The ``Debug``/``Printer``/``setLogger`` API and the ``flag*`` constants predate
this and are deprecated; they remain so that existing code keeps working.
"""

import logging
import warnings
from typing import Any, ClassVar, Final, Optional

from pysmi import __version__, error
from pysmi._aliases import deprecated_camel_case

flagNone: Final = 0x0000
flagSearcher: Final = 0x0001
flagReader: Final = 0x0002
flagLexer: Final = 0x0004
flagParser: Final = 0x0008
flagGrammar: Final = 0x0010
flagCodegen: Final = 0x0020
flagWriter: Final = 0x0040
flagCompiler: Final = 0x0080
flagBorrower: Final = 0x0100
flagAll: Final = 0xFFFF

flagMap: Final = {
    "searcher": flagSearcher,
    "reader": flagReader,
    "lexer": flagLexer,
    "parser": flagParser,
    "grammar": flagGrammar,
    "codegen": flagCodegen,
    "writer": flagWriter,
    "compiler": flagCompiler,
    "borrower": flagBorrower,
    "all": flagAll,
}

#: Debug category name -> logger it enables. Categories are the values accepted
#: by ``mibdump --debug``; each names the subsystem whose logger it turns on.
DEBUG_CATEGORIES: Final = {
    "searcher": "pysmi.searcher",
    "reader": "pysmi.reader",
    "lexer": "pysmi.lexer",
    "parser": "pysmi.parser",
    # Not a module: this is where the PLY grammar traces are sent from both the
    # lexer and the parser, kept separate so they can be enabled on their own.
    "grammar": "pysmi.grammar",
    "codegen": "pysmi.codegen",
    "writer": "pysmi.writer",
    "compiler": "pysmi.compiler",
    "borrower": "pysmi.borrower",
    "all": "pysmi",
}

PACKAGE_LOGGER: Final = "pysmi"

#: Logger carrying the PLY grammar traces, written by the lexer and the parser.
GRAMMAR_LOGGER: Final = DEBUG_CATEGORIES["grammar"]

_DEFAULT_HANDLER_NAME: Final = "pysmi-debug-console"


def enableDebugLogging(*categories: str, handler: logging.Handler | None = None) -> None:
    """Turn on debug logging for the given categories.

    Args:
        categories: names from :data:`DEBUG_CATEGORIES`, each optionally
            prefixed with ``!`` or ``~`` to turn that category off instead
        handler: where to write records; a :class:`logging.StreamHandler` on
            stderr is installed on the ``pysmi`` logger when omitted

    Raises:
        error.PySmiError: if a category is not recognised

    """
    packageLogger = logging.getLogger(PACKAGE_LOGGER)

    if handler is None:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s"))
        # Calling this twice should not make every record appear twice.
        handler.set_name(_DEFAULT_HANDLER_NAME)
        if any(h.get_name() == _DEFAULT_HANDLER_NAME for h in packageLogger.handlers):
            handler = next(h for h in packageLogger.handlers if h.get_name() == _DEFAULT_HANDLER_NAME)

    handler.setLevel(logging.DEBUG)
    if handler not in packageLogger.handlers:
        packageLogger.addHandler(handler)

    # Keep subsystems that were not asked for quiet: they inherit this level,
    # while the ones enabled below set DEBUG on themselves. The handler stays at
    # DEBUG, and records from those reach it regardless of the level set here.
    packageLogger.setLevel(logging.WARNING)

    # Report what was enabled whatever the selection, rather than only when it
    # happens to include this module.
    logging.getLogger(__name__).setLevel(logging.DEBUG)

    for category in categories:
        disable = category[:1] in ("!", "~")
        name = category[1:] if disable else category

        try:
            loggerName = DEBUG_CATEGORIES[name]
        except KeyError as exc:
            raise error.PySmiError(f"bad debug flag {name}") from exc

        logging.getLogger(loggerName).setLevel(logging.WARNING if disable else logging.DEBUG)

        logging.getLogger(__name__).debug(
            "debug category %s %s",
            name,
            "disabled" if disable else "enabled",
            extra={"category": name, "enabled": not disable},
        )

    logging.getLogger(__name__).debug("running pysmi version %s", __version__, extra={"version": __version__})


@deprecated_camel_case
class Printer:
    """Write debug messages to a :mod:`logging` logger.

    .. deprecated::
        Configure the ``pysmi`` logger with :mod:`logging` instead.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        handler: logging.Handler | None = None,
        formatter: logging.Formatter | None = None,
    ) -> None:
        """Create a printer writing to `logger` through `handler`."""
        if logger is None:
            logger = logging.getLogger(PACKAGE_LOGGER)

        logger.setLevel(logging.DEBUG)

        if handler is None:
            handler = logging.StreamHandler()

        if formatter is None:
            formatter = logging.Formatter("%(asctime)s %(name)s: %(message)s")

        handler.setFormatter(formatter)
        handler.setLevel(logging.DEBUG)

        logger.addHandler(handler)

        self.__logger = logger

    def __call__(self, msg: str) -> None:
        """Log `msg` at debug level."""
        self.__logger.debug(msg)

    def __str__(self) -> str:
        """Describe where this printer writes to."""
        return "<python built-in logging>"

    def get_current_logger(self) -> logging.Logger:
        """Return the underlying :class:`logging.Logger`."""
        return self.__logger


NullHandler = logging.NullHandler


@deprecated_camel_case
class Debug:
    """Debug logging switch selected by category flags.

    .. deprecated::
        Use :func:`enableDebugLogging`, or configure the ``pysmi`` logger with
        :mod:`logging` directly.
    """

    defaultPrinter: ClassVar[Optional["Printer"]] = None

    def __init__(self, *flags: str, **options: Any) -> None:
        """Enable debugging for the named `flags`."""
        warnings.warn(
            "pysmi.debug.Debug is deprecated; use pysmi.debug.enableDebugLogging() "
            "or configure the 'pysmi' logger with the logging module",
            DeprecationWarning,
            stacklevel=2,
        )

        self._flags = flagNone
        self._printer: Printer
        if options.get("printer") is not None:
            self._printer = options["printer"]

        elif self.defaultPrinter is not None:
            self._printer = self.defaultPrinter

        else:
            if "loggerName" in options:
                # route our logs to parent logger
                self._printer = Printer(logger=logging.getLogger(options["loggerName"]), handler=NullHandler())
            else:
                self._printer = Printer()

        self(f"running pysmi version {__version__}")

        enabled = set()
        disabled = set()

        for flag in flags:
            inverse = flag and flag[0] in ("!", "~")

            name = flag[1:] if inverse else flag

            try:
                if inverse:
                    self._flags &= ~flagMap[name]
                else:
                    self._flags |= flagMap[name]

            except KeyError as exc:
                raise error.PySmiError(f"bad debug flag {name}") from exc

            # Modules log through their own loggers now, so the flags have to be
            # reflected onto those for this switch to have any effect.
            loggerName = DEBUG_CATEGORIES[name]
            logging.getLogger(loggerName).setLevel(logging.WARNING if inverse else logging.DEBUG)

            if inverse:
                enabled.discard(loggerName)
                disabled.add(loggerName)
            else:
                enabled.add(loggerName)
                disabled.discard(loggerName)

            self(f"debug category '{name}' {'disabled' if inverse else 'enabled'}")

        # Printer leaves the package logger at DEBUG, which is what makes the
        # messages above and any third-party call site work. Levels are what
        # selects output now, so the subsystems that were not asked for have to
        # be quietened one by one rather than through the package logger.
        for loggerName in set(DEBUG_CATEGORIES.values()) - {PACKAGE_LOGGER}:
            if PACKAGE_LOGGER in enabled:
                if loggerName not in disabled:
                    logging.getLogger(loggerName).setLevel(logging.NOTSET)
            elif loggerName not in enabled:
                logging.getLogger(loggerName).setLevel(logging.WARNING)

    def __str__(self) -> str:
        """Describe the printer and enabled flags."""
        return f"logger {self._printer}, flags {self._flags:x}"

    def __call__(self, msg: str) -> None:
        """Log `msg` through the configured printer."""
        self._printer(msg)

    def __and__(self, flag: int) -> int:
        """Test `flag` against the enabled flags."""
        return self._flags & flag

    def __rand__(self, flag: int) -> int:
        """Test `flag` against the enabled flags."""
        return flag & self._flags

    def get_current_printer(self) -> "Printer | None":
        """Return the printer in use."""
        return self._printer

    def get_current_logger(self) -> logging.Logger | None:
        """Return the :class:`logging.Logger` in use, if any."""
        return (self._printer and self._printer.get_current_logger()) or None


# This will yield false from bitwise and with a flag, and save
# on unnecessary calls
logger: Any = 0


def setLogger(logger_instance: Any) -> None:
    """Install `logger_instance` as the debug logging switch.

    .. deprecated::
        Use :func:`enableDebugLogging`, or configure the ``pysmi`` logger with
        :mod:`logging` directly.
    """
    global logger
    logger = logger_instance
