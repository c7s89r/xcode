from __future__ import annotations

import sys

try:
    import msvcrt
except ImportError:
    msvcrt = None

if msvcrt is None:
    try:
        import select
        import termios
        import tty
        _POSIX = True
    except Exception:
        _POSIX = False
else:
    _POSIX = False


class KeyInterrupt:
    def __init__(self):
        self._fd = None
        self._old = None

    def __enter__(self):
        if _POSIX:
            try:
                if sys.stdin.isatty():
                    self._fd = sys.stdin.fileno()
                    self._old = termios.tcgetattr(self._fd)
                    tty.setcbreak(self._fd)
            except Exception:
                self._fd = None
        return self

    def __exit__(self, *exc):
        if _POSIX and self._fd is not None and self._old is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            except Exception:
                pass

    def pressed(self) -> bool:
        if msvcrt is not None:
            hit = False
            try:
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch == "\x1b":
                        hit = True
                    elif ch in ("\x00", "\xe0"):
                        if msvcrt.kbhit():
                            msvcrt.getwch()
            except Exception:
                return False
            return hit
        if not _POSIX or self._fd is None:
            return False
        hit = False
        try:
            while select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                if not ch:
                    break
                if ch == "\x1b":
                    hit = True
        except Exception:
            return False
        return hit
