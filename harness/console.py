"""Serialize interactive prompts and redraw after asynchronous output."""

from __future__ import annotations

import threading

try:
    import readline
except ImportError:  # Windows standard Python normally has no readline.
    readline = None


class ConsoleBroker:
    def __init__(self, prompt: str = "\nharness >> "):
        self.prompt = prompt
        self.lock = threading.RLock()

    def ask(self, prompt: str | None = None) -> str:
        with self.lock:
            return input(self.prompt if prompt is None else prompt)

    def print(self, text: str) -> None:
        if threading.current_thread() is threading.main_thread() or readline is None:
            print(text, flush=True)
            return
        try:
            buffered = readline.get_line_buffer()
        except Exception:
            buffered = ""
        print(f"\r\033[K{text}", flush=True)
        print(self.prompt + buffered, end="", flush=True)
