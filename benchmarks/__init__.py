#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Performance benchmarks, measured on every pull request by CodSpeed.

A package rather than a bare directory for the same reason ``tests/`` is one:
the modules here import :py:mod:`benchmarks.workload` by name, and that only
resolves when the directory is a package under the repository root.

The suite is not collected by a plain ``pytest`` run -- ``testpaths`` in
pyproject.toml names ``tests`` and nothing else -- so it costs the unit legs
nothing. Run it explicitly:

    uv run --group test --group bench pytest --codspeed --no-cov benchmarks
"""
