"""Reentrant file lock for task mutations on Windows and POSIX."""

from __future__ import annotations

import os
import threading
from pathlib import Path


class FileRLock:
    def __init__(self, path: Path):
        self.path = path
        self.thread_lock = threading.RLock()
        self.local = threading.local()

    def __enter__(self):
        self.thread_lock.acquire()
        depth = getattr(self.local, "depth", 0)
        if depth == 0:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                handle = self.path.open("a+b")
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                self.local.handle = handle
            except Exception:
                self.thread_lock.release()
                raise
        self.local.depth = depth + 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self.local.depth -= 1
        if self.local.depth == 0:
            handle = self.local.handle
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            del self.local.handle
        self.thread_lock.release()
