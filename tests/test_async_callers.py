#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""pysmi compiles inside somebody else's event loop.

Nothing here is asynchronous, and that is the point. pysmi's largest caller is
pysnmp, whose MIB compiler is reached lazily -- an `await get_cmd(...)` with
`lookupMib=True` resolves a name, the resolution misses, and
`pysnmp.smi.compiler` calls this library. That call happens on the event loop
thread, inside a running loop, which constrains pysmi in one way that no
synchronous test would notice: a library that starts a loop of its own there
raises `RuntimeError: asyncio.run() cannot be called from a running event
loop`, and takes the caller's request down with it.

So there are two halves to this. A compile driven from inside a running loop
finishes and leaves the loop alone -- which needs a loop, and so needs
pytest-asyncio. And nothing in pysmi reaches for a loop at all, which is the
structural gate that catches the import the first test would only catch once
somebody routed a compile through it.
"""

import ast
import asyncio
import pathlib
import sys
import textwrap
import unittest

from pysmi import error
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import CallbackReader
from pysmi.writer import CallbackWriter

PYSMI_ROOT = pathlib.Path(__file__).resolve().parents[1] / "pysmi"

#: Every way of getting a loop that either starts one or rebinds the thread's
#: current one. `get_running_loop` is not among them: it asks for the loop the
#: caller is already on, which is the one thing a library called from inside a
#: coroutine may legitimately do.
LOOP_CALLS = frozenset(
    {
        "run",  # asyncio.run
        "new_event_loop",
        "set_event_loop",
        "run_until_complete",
        "run_forever",
    }
)

MODULE = textwrap.dedent(
    """\
    ASYNC-CALLER-MIB DEFINITIONS ::= BEGIN
    IMPORTS
        MODULE-IDENTITY, enterprises FROM SNMPv2-SMI;

    asyncCallerMI MODULE-IDENTITY
        LAST-UPDATED "202401010000Z"
        ORGANIZATION "test"
        CONTACT-INFO "test"
        DESCRIPTION  "Compiled from inside a running event loop."
        ::= { enterprises 51 }
    END
    """
)


def serve(mibname, context):
    """The one module this file compiles; the base MIBs come from the bundle."""
    if mibname != "ASYNC-CALLER-MIB":
        raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=None)

    return MODULE


def compiler(written):
    """A compiler serving one module from memory and collecting the output."""
    mibCompiler = MibCompiler(
        SmiV1CompatParser(tempdir=""),
        JsonCodeGen(),
        CallbackWriter(lambda mibname, data, context: written.update({mibname: data})),
    )
    mibCompiler.add_sources(CallbackReader(serve))

    return mibCompiler


async def testACompileFromInsideARunningLoopFinishes():
    """The shape of a pysnmp MIB lookup: a compile reached from a coroutine."""
    written = {}
    loop = asyncio.get_running_loop()

    processed = compiler(written).compile("ASYNC-CALLER-MIB", rebuild=True)

    assert str(processed["ASYNC-CALLER-MIB"]) == "compiled"
    assert "ASYNC-CALLER-MIB" in written
    # A compile that had started a loop of its own would have had to install it
    # as the running one, which is the failure this would report as a swap
    # rather than as the RuntimeError the first assertion would have met.
    assert loop is asyncio.get_running_loop()


async def testTheLoopIsStillUsableAfterwards():
    """The caller's loop survives the call, so its other requests do too."""
    ticks = 0

    async def tick():
        nonlocal ticks
        while True:
            await asyncio.sleep(0)
            ticks += 1

    ticking = asyncio.create_task(tick())
    await asyncio.sleep(0)

    compiler({}).compile("ASYNC-CALLER-MIB", rebuild=True)

    before = ticks
    await asyncio.sleep(0)
    ticking.cancel()

    assert ticks > before, "the loop stopped running the tasks it already had"


class NoLoopOfItsOwnTestCase(unittest.TestCase):
    """Structural gate: nothing in pysmi starts or rebinds an event loop.

    The test above only covers the path it drives. This covers the library,
    and is what would fail on the commit that added such a call rather than on
    the release where a caller first reached it.
    """

    def testNothingInPysmiStartsALoop(self):
        found = []

        for path in sorted(PYSMI_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue

                func = node.func

                if not isinstance(func, ast.Attribute) or func.attr not in LOOP_CALLS:
                    continue

                # `asyncio.run(...)` and `loop.run_until_complete(...)` alike:
                # the attribute name is what names the call, whatever it is
                # reached through. `subprocess.run` is not one of these.
                if func.attr == "run" and getattr(func.value, "id", "") != "asyncio":
                    continue

                found.append(f"{path.relative_to(PYSMI_ROOT.parent)}:{node.lineno}")

        self.assertEqual(
            [],
            found,
            "pysmi is called from inside pysnmp's event loop; these would raise "
            "there: " + ", ".join(found),
        )

    def testTheGateSeesACallThatWasPutInFrontOfIt(self):
        """The gate above passes trivially if the walk is wrong, so prove it walks."""
        tree = ast.parse("import asyncio\nasyncio.run(main())\n")
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOOP_CALLS
        ]

        self.assertEqual(1, len(calls))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
