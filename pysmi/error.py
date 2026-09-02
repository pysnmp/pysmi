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
    #: Line the offending token was read from, or "?" when it is not known.
    lineno: "int | str" = "?"

    def __str__(self) -> str:
        return self.msg + f", line {self.lineno}"


class PySmiParserError(PySmiLexerError):
    pass


class PySmiSyntaxError(PySmiParserError):
    pass


class PySmiSearcherError(PySmiError):
    pass


class PySmiFileNotModifiedError(PySmiSearcherError):
    pass


class PySmiFileNotFoundError(PySmiSearcherError):
    pass


class PySmiReaderError(PySmiError):
    pass


class PySmiReaderFileNotModifiedError(PySmiReaderError):
    pass


class PySmiReaderFileNotFoundError(PySmiReaderError):
    pass


class PySmiCodegenError(PySmiError):
    pass


class PySmiSemanticError(PySmiCodegenError):
    pass


class PySmiWriterError(PySmiError):
    pass
