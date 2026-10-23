from __future__ import annotations

import asyncio
import fcntl
import os
from pathlib import Path

import pytest

from tunnelgate.locks import LockManager


async def test_lock_serializes_within_process(tmp_path: Path) -> None:
    locks = LockManager(tmp_path)
    order: list[str] = []

    async def worker(name: str) -> None:
        async with locks.hold("waf-zone"):
            order.append(f"{name}-in")
            await asyncio.sleep(0.01)
            order.append(f"{name}-out")

    await asyncio.gather(worker("a"), worker("b"))
    assert order in (["a-in", "a-out", "b-in", "b-out"], ["b-in", "b-out", "a-in", "a-out"])


async def test_lock_waits_for_other_process(tmp_path: Path) -> None:
    locks = LockManager(tmp_path)
    async with locks.hold("tunnel-x"):
        pass
    path = tmp_path / "locks" / "tunnel-x.lock"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    fd = os.open(path, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)  # simulates the CLI holding the lock
    task = asyncio.create_task(_acquire(locks))
    await asyncio.sleep(0.1)
    assert not task.done()
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    await asyncio.wait_for(task, 2)


async def _acquire(locks: LockManager) -> None:
    async with locks.hold("tunnel-x"):
        pass


async def test_lock_rejects_bad_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid lock name"):
        async with LockManager(tmp_path).hold("../evil"):
            pass
