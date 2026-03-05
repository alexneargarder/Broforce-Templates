"""ANSI color codes for terminal output.

Color scheme:
  GREEN - Actions taken (files created/modified)
  CYAN - Key information (version, package name, selected project)
  BLUE - Status info (already correct, no change needed)
  WARNING (yellow) - Warnings and prompts
  FAIL (red) - Errors
"""
import locale
import sys

_colors_initialized = False


def _supports_unicode() -> bool:
    """Check if the terminal likely supports unicode characters."""
    try:
        encoding = (getattr(sys.stdout, 'encoding', None)
                    or locale.getpreferredencoding(False))
        return encoding.lower().replace('-', '') == 'utf8'
    except Exception:
        return False


def init_colors() -> None:
    """Initialize console for ANSI color support on Windows."""
    global _colors_initialized
    if _colors_initialized:
        return
    _colors_initialized = True

    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


_unicode = _supports_unicode()

CHECK = "\u2713" if _unicode else "[OK]"
WARNING_ICON = "\u26a0\ufe0f " if _unicode else "[!] "
ARROW = "\u2192" if _unicode else "->"


class Colors:
    """ANSI color codes."""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
