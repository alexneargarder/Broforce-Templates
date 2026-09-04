"""Tests for standalone helpers in the cli module."""
import pytest

from broforce_tools.cli import _split_editor


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr("broforce_tools.cli.is_windows", lambda: True)


@pytest.fixture
def on_posix(monkeypatch):
    monkeypatch.setattr("broforce_tools.cli.is_windows", lambda: False)


class TestSplitEditor:
    def test_posix_simple(self, on_posix):
        assert _split_editor("code --wait") == ["code", "--wait"]

    def test_posix_backslash_escape(self, on_posix):
        assert _split_editor(r"/opt/my\ editor --wait") == ["/opt/my editor", "--wait"]

    def test_posix_quoted(self, on_posix):
        assert _split_editor('"/opt/my editor" --wait') == ["/opt/my editor", "--wait"]

    def test_windows_simple(self, on_windows):
        assert _split_editor("notepad") == ["notepad"]

    def test_windows_backslashes_preserved(self, on_windows):
        assert _split_editor(r"C:\Windows\notepad.exe") == [r"C:\Windows\notepad.exe"]

    def test_windows_quoted_path_with_spaces(self, on_windows):
        editor = r'"C:\Program Files\Microsoft VS Code\Code.exe" --wait'
        assert _split_editor(editor) == [
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            "--wait",
        ]

    def test_windows_single_quoted_token(self, on_windows):
        assert _split_editor("'C:\\Tools\\my editor.exe'") == ["C:\\Tools\\my editor.exe"]


def test_empty_editor_uses_fallback(monkeypatch):
    monkeypatch.setattr("broforce_tools.cli.is_windows", lambda: False)
    assert _split_editor("", "nano") == ["nano"]
    assert _split_editor("   ", "nano") == ["nano"]
