#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the parsers."""

from typing import Any


class AbstractParser:
    """Base class for MIB parsers.

    A parser turns ASN.1 MIB text into the nested lists and tuples the code
    generators walk. Subclasses implement :py:meth:`reset` and
    :py:meth:`parse`.
    """

    def reset(self) -> None:
        """Discard state left over from the last parse.

        Called before reusing a parser on another module.
        """
        raise NotImplementedError()

    def parse(self, data: str, **kwargs: Any) -> list[Any]:
        """Parse ASN.1 MIB text.

        Args:
            data (str): ASN.1 MIB text, which may hold several modules

        Returns:
            One parse tree per module found in the text.

        Raises:
            PySmiLexerError: the text could not be tokenised.
            PySmiParserError: the tokens do not fit the SMI grammar.
        """
        raise NotImplementedError()
