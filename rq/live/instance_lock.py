"""Non-blocking single-instance lock for the persistent live bot process."""
from __future__ import annotations

import os
from pathlib import Path


class InstanceLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        if os.name == "nt":
            import msvcrt

            if self.path.stat().st_size == 0:
                self._file.seek(0)
                self._file.write(b"\0")
                self._file.flush()
            self._file.seek(0)
            try:
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                self._file.close()
                self._file = None
                raise RuntimeError(f"another bot instance holds {self.path}") from exc
        else:
            import fcntl

            try:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._file.close()
                self._file = None
                raise RuntimeError(f"another bot instance holds {self.path}") from exc

    def release(self) -> None:
        if self._file is None:
            return
        if os.name == "nt":
            import msvcrt

            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        self._file = None

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
