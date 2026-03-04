"""ESC-to-abort: raw terminal listener for cancelling graph execution."""
from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

_IS_WINDOWS = sys.platform == "win32"


@asynccontextmanager
async def esc_listener(abort_event: asyncio.Event) -> AsyncIterator[None]:
    """Listen for bare ESC on stdin and set *abort_event* when detected.

    On Unix: switches stdin to raw mode so individual key bytes can be read.
    On Windows: uses msvcrt for non-blocking key reads.
    No-op when stdin is not a TTY (Telegram, piped input, tests).
    """
    if not sys.stdin.isatty():
        yield
        return

    if _IS_WINDOWS:
        async with _esc_listener_windows(abort_event):
            yield
    else:
        async with _esc_listener_unix(abort_event):
            yield


@asynccontextmanager
async def _esc_listener_unix(abort_event: asyncio.Event) -> AsyncIterator[None]:
    """Unix implementation using termios raw mode + select."""
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        loop = asyncio.get_running_loop()

        async def _reader() -> None:
            while not abort_event.is_set():
                try:
                    ready = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, lambda: select.select([fd], [], [], 0.2)[0],
                        ),
                        timeout=0.5,
                    )
                except asyncio.TimeoutError:
                    continue

                if not ready:
                    continue

                byte = os.read(fd, 1)

                if byte == b"\x1b":
                    # Got ESC byte — wait 50ms for a follow-up.
                    # If nothing follows it's a bare ESC press.
                    try:
                        follow = await asyncio.wait_for(
                            loop.run_in_executor(
                                None, lambda: select.select([fd], [], [], 0.05)[0],
                            ),
                            timeout=0.1,
                        )
                    except asyncio.TimeoutError:
                        follow = []

                    if follow:
                        _drain_sync(fd)
                        continue

                    abort_event.set()
                    return

                if byte == b"\x03":
                    # Ctrl+C in raw mode (SIGINT won't fire)
                    abort_event.set()
                    return

        reader_task = asyncio.create_task(_reader())
        try:
            yield
        finally:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@asynccontextmanager
async def _esc_listener_windows(abort_event: asyncio.Event) -> AsyncIterator[None]:
    """Windows implementation using msvcrt for non-blocking key reads."""
    import msvcrt

    loop = asyncio.get_running_loop()

    async def _reader() -> None:
        while not abort_event.is_set():
            try:
                hit = await asyncio.wait_for(
                    loop.run_in_executor(None, msvcrt.kbhit),
                    timeout=0.3,
                )
            except asyncio.TimeoutError:
                continue

            if not hit:
                await asyncio.sleep(0.1)
                continue

            byte = await loop.run_in_executor(None, msvcrt.getch)

            if byte == b"\x1b":
                # ESC — check for follow-up (arrow keys send ESC + more)
                await asyncio.sleep(0.05)
                if await loop.run_in_executor(None, msvcrt.kbhit):
                    # Part of escape sequence — drain and ignore
                    while await loop.run_in_executor(None, msvcrt.kbhit):
                        await loop.run_in_executor(None, msvcrt.getch)
                    continue
                abort_event.set()
                return

            if byte == b"\x03":
                # Ctrl+C
                abort_event.set()
                return

    reader_task = asyncio.create_task(_reader())
    try:
        yield
    finally:
        reader_task.cancel()
        try:
            await reader_task
        except asyncio.CancelledError:
            pass


def _drain_sync(fd: int) -> None:
    """Consume remaining bytes of an escape sequence (up to 8, 10ms each)."""
    import select
    for _ in range(8):
        ready, _, _ = select.select([fd], [], [], 0.01)
        if ready:
            os.read(fd, 1)
        else:
            break
