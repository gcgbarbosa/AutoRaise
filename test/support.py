"""Helpers the two test suites share, which pytest puts on the path.

``pyproject.toml`` lists ``test`` beside ``src`` in ``pythonpath``, so
``from support import write`` resolves here: the suites are directories without a
package around them, and this is the one module they share.
"""

import asyncio

from arw.db.fast_wbi import FastWbi


def write(data):
    """Write through the SQL writer, which is a coroutine.

    The driver is asyncmy, so ``FastWbi.write`` is async and this suite is not: each
    call runs the writer on a loop of its own. The suite writes one entity per call,
    so the loop costs nothing beside the statements that call runs.
    """
    return asyncio.run(FastWbi().write(data))
