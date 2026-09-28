"""Cross-platform shell execution with process-tree cleanup."""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import threading
from pathlib import Path


_active: set[subprocess.Popen] = set()
_lock = threading.RLock()


def stop_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def stop_all() -> None:
    with _lock:
        processes = list(_active)
    for process in processes:
        stop_tree(process)


atexit.register(stop_all)


def run_shell(command: str, cwd: Path, timeout: int) -> str:
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen(command, shell=True, cwd=cwd,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", **options)
    with _lock:
        _active.add(process)
    try:
        output, _ = process.communicate(timeout=timeout)
        return f"exit_code={process.returncode}\n{output}"
    except subprocess.TimeoutExpired:
        stop_tree(process)
        process.communicate()
        return f"Error: 命令超过 {timeout} 秒，已终止"
    finally:
        with _lock:
            _active.discard(process)
