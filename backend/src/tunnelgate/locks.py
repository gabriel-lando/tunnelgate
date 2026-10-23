"""Locks shared by the web server and the break-glass CLI (separate processes)."""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


class LockManager:
    """An asyncio lock (same process) combined with an flock file (other processes)."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory / "locks"
        self._dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._local: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def hold(self, name: str) -> AsyncIterator[None]:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(f"invalid lock name: {name!r}")
        async with self._local[name]:
            fd = os.open(self._dir / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
            try:
                await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
