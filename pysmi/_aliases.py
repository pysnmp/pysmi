#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Keeping the old camelCase spelling of the API working.

PySMI's methods were camelCase, which PEP 8 does not call for. They are
snake_case now, and every renamed method keeps its old name as an alias that
warns and forwards. The aliases are generated rather than written out, so a
method and its old spelling cannot drift apart.

Subclassing is a documented way to extend PySMI, so a subclass out there may
override a method under its old name. PySMI calls the new name, which would
leave such an override silently unused; :py:func:`deprecated_camel_case`
installs it under the new name instead, and says so.
"""

import functools
import re
import warnings
from collections.abc import Callable
from typing import Any, TypeVar

_CLS = TypeVar("_CLS", bound=type)

#: Names whose camelCase spelling does not follow from the snake_case one.
#: Only acronyms need listing; everything else converts back and forth.
_IRREGULAR: dict[str, str] = {
    "gen_type_declaration_rhs": "genTypeDeclarationRHS",
}

_SNAKE_PART = re.compile(r"_([a-z0-9])")


def to_camel_case(name: str) -> str:
    """Return the camelCase spelling a snake_case name was renamed from.

    Args:
        name: snake_case method name

    Returns:
        The old camelCase name, or the name unchanged if it has no underscores
        to convert.
    """
    if name in _IRREGULAR:
        return _IRREGULAR[name]

    return _SNAKE_PART.sub(lambda match: match.group(1).upper(), name)


def _warn(old: str, new: str, owner: str) -> None:
    """Announce that a camelCase name is on its way out."""
    warnings.warn(
        f"{owner}.{old}() is deprecated and will be removed in a future release; use {new}() instead",
        DeprecationWarning,
        stacklevel=3,
    )


def _makeAlias(old: str, new: str, func: Callable[..., Any]) -> Callable[..., Any]:
    """Build a method that warns and forwards to *new*."""

    @functools.wraps(func)
    def alias(self: Any, *args: Any, **kwargs: Any) -> Any:
        _warn(old, new, type(self).__name__)
        return getattr(self, new)(*args, **kwargs)

    alias.__name__ = old
    alias.__qualname__ = old
    alias.__doc__ = f"Deprecated alias for :py:meth:`{new}`."

    return alias


def _makeStaticAlias(old: str, new: str, cls: type, func: Callable[..., Any]) -> Any:
    """Build a static method that warns and forwards to *new*."""

    @functools.wraps(func)
    def alias(*args: Any, **kwargs: Any) -> Any:
        _warn(old, new, cls.__name__)
        return getattr(cls, new)(*args, **kwargs)

    alias.__name__ = old
    alias.__qualname__ = old
    alias.__doc__ = f"Deprecated alias for :py:meth:`{new}`."

    return staticmethod(alias)


def deprecated_camel_case(cls: _CLS) -> _CLS:
    """Give every public method of *cls* its old camelCase name back.

    The alias warns and forwards, so both spellings do the same thing and only
    the new one is documented. Private methods, and anything whose camelCase
    spelling would collide with a name the class already defines, are skipped.

    Args:
        cls: class whose methods were renamed to snake_case

    Returns:
        The same class, with the aliases installed.
    """
    aliases: dict[str, str] = dict(getattr(cls, "_camelCaseAliases", {}))

    for name, member in list(vars(cls).items()):
        if name.startswith("_"):
            continue

        old = to_camel_case(name)

        if old == name or old in vars(cls):
            continue

        if isinstance(member, staticmethod):
            setattr(cls, old, _makeStaticAlias(old, name, cls, member.__func__))
        elif isinstance(member, classmethod):
            continue  # none today; a wrong guess here would be silent
        elif callable(member):
            setattr(cls, old, _makeAlias(old, name, member))
        else:
            continue

        aliases[old] = name

    cls._camelCaseAliases = aliases  # type: ignore[attr-defined]

    # Chain to whatever hook the class already had. object's is a no-op with no
    # __func__ to reach, which is why this is a lookup rather than a super call.
    inherited = getattr(getattr(cls, "__init_subclass__", None), "__func__", None)

    def initSubclass(subcls: type, /, **kwargs: Any) -> None:
        if inherited is not None:
            inherited(subcls, **kwargs)

        for oldName, newName in aliases.items():
            if oldName in vars(subcls) and newName not in vars(subcls):
                warnings.warn(
                    f"{subcls.__name__} overrides {oldName}(), which is deprecated; rename it to {newName}()",
                    DeprecationWarning,
                    stacklevel=2,
                )
                setattr(subcls, newName, vars(subcls)[oldName])

    cls.__init_subclass__ = classmethod(initSubclass)  # type: ignore[assignment]

    return cls
