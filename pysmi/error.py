#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
# Package exception model:
# Here we subclass base Python exception overriding its constructor to
# accomodate error message string as its first parameter and an open
# set of keyword arguments that become exception object attributes.
# While exception object is bubbling up the call stack, intermediate
# exception handlers may insert their own attributes into exception
# object.
#
"""Exceptions raised by PySMI.

Every exception carries a *msg* and accepts arbitrary keyword arguments that
become attributes, so a handler part-way up the stack can attach context to an
error it is not ready to report.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pysmi.reader.base import AbstractReader
    from pysmi.searcher.base import AbstractSearcher
    from pysmi.writer.base import AbstractWriter


class PySmiError(Exception):
    """Base class for every error PySMI raises.

    Subclasses identify which stage failed. Catch this to catch them all.
    """

    #: The error message. Handlers extend it as the error travels up the stack.
    msg: str

    # Context attached at the raise site or by a handler on the way up. Each is
    # present only when something set it, so reading one that was never set
    # raises AttributeError.

    #: MIB module the error concerns.
    mibname: str
    #: MIB file the error concerns.
    file: str
    #: Reader the MIB was being fetched from.
    reader: "AbstractReader"
    #: Reader that supplied the MIB, as recorded by the compiler.
    source: "AbstractReader"
    #: Searcher that was consulted.
    searcher: "AbstractSearcher"
    #: Writer that was storing the MIB.
    writer: "AbstractWriter"
    #: Component that was handling the MIB when it failed.
    handler: Any

    def __init__(self, *args: object, **kwargs: object) -> None:
        Exception.__init__(self, *args)
        self.msg = str(args[0]) if args else ""
        for k in kwargs:
            setattr(self, k, kwargs[k])

    def __getattr__(self, name: str) -> Any:
        """Report the context attributes handlers attach as they re-raise.

        Attributes are set from keyword arguments, so which ones exist depends
        on where the error came from and who handled it on the way up. Missing
        ones still raise AttributeError, as they always did.
        """
        raise AttributeError(name)

    def __repr__(self) -> str:
        return "{}({})".format(
            self.__class__.__name__,
            ", ".join([f"{k}={getattr(self, k)!r}" for k in dir(self) if k[0] != "_" and k != "args"]),
        )

    def __str__(self) -> str:
        return self.msg


class PySmiLexerError(PySmiError):
    """A MIB could not be broken into tokens.

    Raised for input the SMI grammar forbids outright: a reserved word used as
    an identifier, or an identifier ending in a hyphen.
    """

    #: Line the offending token was read from, or "?" when it is not known.
    lineno: "int | str" = "?"

    def __str__(self) -> str:
        return self.msg + f", line {self.lineno}"


class PySmiParserError(PySmiLexerError):
    """A MIB tokenised but did not parse.

    Raised when the token stream does not fit the grammar. Carries the line
    number of the offending token, inherited from :class:`PySmiLexerError`.
    """


class PySmiSyntaxError(PySmiParserError):
    """A more specific parse failure.

    Nothing in PySMI raises this; it exists so callers can distinguish a
    syntax error from other parser errors should a parser start reporting one.
    """


class PySmiSearcherError(PySmiError):
    """A searcher could not determine whether a compiled MIB is current.

    Raised when the stored MIB exists but cannot be examined -- unreadable
    file, or an unparsable timestamp in a compiled module.
    """


class PySmiFileNotModifiedError(PySmiSearcherError):
    """The compiled MIB is already up to date.

    Not a failure: searchers raise it to tell the compiler it can skip this
    MIB, and the compiler marks the module *untouched*.
    """


class PySmiFileNotFoundError(PySmiSearcherError):
    """No usable compiled MIB was found.

    Raised when nothing is stored for the module, or what is stored is older
    than the source and must be rebuilt.
    """


class PySmiReaderError(PySmiError):
    """Base class for failures fetching MIB source.

    Nothing raises this directly; catch it to catch any reader failure.
    """


class PySmiReaderFileNotModifiedError(PySmiReaderError):
    """The MIB source is older than the caller asked for.

    Raised when a reader is given a modification time to beat and the source
    it found does not beat it.
    """


class PySmiReaderFileNotFoundError(PySmiReaderError):
    """A reader has no source for this MIB.

    Every source is tried in turn, so this is the ordinary "not here, try the
    next one" signal; it only reaches the caller when no source has the MIB.
    """


class PySmiCodegenError(PySmiError):
    """A code generator could not produce output for a MIB.

    Raised when generation reaches an unusable state -- a symbol left without
    generated code, or an existing MIB index that cannot be read back.
    """


class PySmiSemanticError(PySmiCodegenError):
    """A MIB parsed but does not mean anything consistent.

    Raised for a MIB that is syntactically valid yet self-contradictory: a
    duplicate symbol, a second module identity, or a reference to a module
    absent from the symbol table.
    """


class PySmiWriterError(PySmiError):
    """Generated output could not be stored.

    Raised when the destination cannot be created or written, or when a
    caller-supplied callback raises while receiving the output.
    """
