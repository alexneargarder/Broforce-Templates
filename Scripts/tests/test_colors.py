"""Tests for colors module - unicode detection."""
import sys

from broforce_tools.colors import _supports_unicode


class TestSupportsUnicode:
    def test_utf8(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", type("FakeStdout", (), {"encoding": "utf-8"})())
        assert _supports_unicode()

    def test_utf8_uppercase(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", type("FakeStdout", (), {"encoding": "UTF-8"})())
        assert _supports_unicode()

    def test_ascii(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", type("FakeStdout", (), {"encoding": "ascii"})())
        assert not _supports_unicode()

    def test_cp1252(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", type("FakeStdout", (), {"encoding": "cp1252"})())
        assert not _supports_unicode()

    def test_no_encoding_attr(self, monkeypatch):
        monkeypatch.setattr(sys, "stdout", type("FakeStdout", (), {})())
        # Falls back to locale, which on this system is likely utf-8
        # Just verify it doesn't crash
        result = _supports_unicode()
        assert isinstance(result, bool)
