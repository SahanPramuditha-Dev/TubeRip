import threading
import time
from typing import Callable, Optional

try:
    import tkinter as tk
    _TK_AVAILABLE = True
except ImportError:
    _TK_AVAILABLE = False


class ClipboardMonitor:
    """Polls clipboard for YouTube URLs and fires callback.

    clipboard_get() MUST be called from the Tk main thread.
    We schedule a read via root.after() and collect the result
    through a shared variable + Event to avoid Tkinter thread-safety issues.
    """

    YOUTUBE_PATTERNS = ("youtube.com/watch", "youtu.be/", "youtube.com/shorts",
                        "youtube.com/playlist")

    def __init__(self, on_url: Callable[[str], None], interval: float = 1.5):
        self.on_url = on_url
        self.interval = interval
        self._last = ""
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._root: Optional[object] = None
        # Shared state for main-thread clipboard read
        self._clip_result: str = ""
        self._clip_event = threading.Event()

    def start(self, tk_root):
        self._root = tk_root
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _read_clipboard_main(self):
        """Called on the main thread via after(); stores result and signals event."""
        try:
            self._clip_result = self._root.clipboard_get()
        except Exception:
            self._clip_result = ""
        self._clip_event.set()

    def _loop(self):
        while self._running:
            # Ask the main thread to read the clipboard
            self._clip_event.clear()
            self._root.after(0, self._read_clipboard_main)
            # Wait for the main thread to finish (max 1 s)
            self._clip_event.wait(timeout=1.0)

            text = self._clip_result
            if text != self._last and self._is_youtube(text):
                self._last = text
                self._root.after(0, lambda t=text: self.on_url(t))

            time.sleep(self.interval)

    def _is_youtube(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        text = text.strip()
        return any(p in text for p in self.YOUTUBE_PATTERNS)
