#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the lexers."""


class AbstractLexer:
    """Base class for MIB lexers.

    A lexer breaks ASN.1 MIB text into the tokens a parser consumes.
    """

    def reset(self) -> None:
        """Discard state left over from the last module.

        Called before reusing a lexer on another module.
        """
        raise NotImplementedError()
