"""Bounded worker pools for the synchronous work the async API depends on.

Every route is declared ``async``, but the workspace store, the task store and
the cover pipeline do synchronous JSON/file work. Running that work on the event
loop means whichever call is in flight delays every other request, so a script
or account switch waits behind an unrelated save or generation step. Blocking
calls therefore run on one of two bounded pools:

* :func:`run_io` - request and storage work (list/read/write a record).
* :func:`run_generation` - heavy generation work (ffmpeg, cover images, uploads).

Generation keeps its own small pool so a burst of jobs queues behind a couple of
workers instead of pushing the switch path to the back of the line.
"""
from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar


IO_WORKERS = 8
GENERATION_WORKERS = 2

_io_pool = ThreadPoolExecutor(max_workers=IO_WORKERS, thread_name_prefix="workbench-io")
_generation_pool = ThreadPoolExecutor(
    max_workers=GENERATION_WORKERS, thread_name_prefix="workbench-generation"
)

T = TypeVar("T")


async def run_io(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run a blocking store/file call off the event loop on the bounded IO pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_io_pool, functools.partial(fn, *args, **kwargs))


async def run_generation(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run heavy generation work off the event loop on the bounded job pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_generation_pool, functools.partial(fn, *args, **kwargs))
