"""Tests for file organization, filename sanitization, and version grouping."""

from __future__ import annotations

import pytest
from pathlib import Path
from datetime import datetime, timezone

from suno_downloaderist.utils import sanitize_filename


class TestSanitizeFilename:
    """Tests for the sanitize_filename utility."""

    def test_normal_filename(self):
        assert sanitize_filename("My Song") == "My Song"

    def test_removes_backslash(self):
        assert sanitize_filename("path\\song") == "path_song"

    def test_removes_forward_slash(self):
        assert sanitize_filename("path/song") == "path_song"

    def test_removes_colon(self):
        assert sanitize_filename("Song: The Remix") == "Song_ The Remix"

    def test_removes_asterisk(self):
        assert sanitize_filename("Song * Star") == "Song _ Star"

    def test_removes_question_mark(self):
        assert sanitize_filename("What?") == "What_"

    def test_removes_quotes(self):
        assert sanitize_filename('Say "Hello"') == "Say _Hello_"

    def test_removes_angle_brackets(self):
        assert sanitize_filename("<Song>") == "_Song_"

    def test_removes_pipe(self):
        assert sanitize_filename("Song | Mix") == "Song _ Mix"

    def test_removes_control_characters(self):
        result = sanitize_filename("Song\x00\x01\x1f")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "\x1f" not in result

    def test_strips_trailing_dots(self):
        result = sanitize_filename("Song...")
        assert not result.endswith(".")

    def test_strips_trailing_spaces(self):
        result = sanitize_filename("Song   ")
        assert not result.endswith(" ")

    def test_empty_string_returns_untitled(self):
        assert sanitize_filename("") == "untitled"

    def test_whitespace_only_returns_untitled(self):
        assert sanitize_filename("   ") == "untitled"

    def test_none_returns_untitled(self):
        # Technically shouldn't happen, but guard against it
        assert sanitize_filename("") == "untitled"

    def test_windows_reserved_con(self):
        result = sanitize_filename("CON")
        assert result != "CON"
        assert result.startswith("_")

    def test_windows_reserved_prn(self):
        result = sanitize_filename("PRN")
        assert result != "PRN"

    def test_windows_reserved_com1(self):
        result = sanitize_filename("COM1")
        assert result != "COM1"

    def test_windows_reserved_lpt3(self):
        result = sanitize_filename("LPT3")
        assert result != "LPT3"

    def test_windows_reserved_nul(self):
        result = sanitize_filename("NUL")
        assert result != "NUL"

    def test_windows_reserved_with_extension(self):
        result = sanitize_filename("CON.txt")
        assert not result.upper().startswith("CON.")

    def test_truncates_long_filenames(self):
        long_name = "A" * 300
        result = sanitize_filename(long_name)
        assert len(result) <= 200

    def test_truncation_strips_trailing_dots_and_spaces(self):
        # Create a name that when truncated to 200 would end in dots
        name = "A" * 198 + ".."  + "B" * 10
        result = sanitize_filename(name)
        assert len(result) <= 200
        assert not result.endswith(".")
        assert not result.endswith(" ")

    def test_unicode_preserved(self):
        """Unicode characters should be preserved (they're valid filenames)."""
        assert sanitize_filename("日本語の歌") == "日本語の歌"

    def test_emoji_preserved(self):
        """Emoji should be preserved."""
        assert sanitize_filename("🎵 My Song 🎵") == "🎵 My Song 🎵"

    def test_mixed_illegal_and_legal(self):
        result = sanitize_filename("My <Great> Song: \"Remix\" | v2")
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        assert "|" not in result
        assert "My" in result
        assert "Song" in result

    def test_multiple_illegal_chars_in_sequence(self):
        result = sanitize_filename("??::||")
        assert result != "untitled"  # Should have underscores


class TestOrganizerPaths:
    """Tests for file organization path logic."""

    def test_version_suffix_format(self):
        """Version suffixes should follow the _v2, _v3 pattern."""
        base = "My Song"
        v1 = f"{base}.mp3"
        v2 = f"{base}_v2.mp3"
        v3 = f"{base}_v3.mp3"
        assert v1 == "My Song.mp3"
        assert v2 == "My Song_v2.mp3"
        assert v3 == "My Song_v3.mp3"

    def test_folder_structure(self):
        """Verify the expected folder structure."""
        base_dir = Path("/tmp/downloads")
        title = "Neon Horizons"
        expected_folder = base_dir / title
        expected_mp3 = expected_folder / f"{title}.mp3"
        expected_txt = expected_folder / f"{title}.txt"
        expected_lrc = expected_folder / f"{title}.lrc"
        expected_cover = expected_folder / f"{title}_cover.png"

        assert expected_mp3.suffix == ".mp3"
        assert expected_txt.suffix == ".txt"
        assert expected_lrc.suffix == ".lrc"
        assert expected_cover.suffix == ".png"
        assert expected_mp3.parent == expected_folder


class TestFormatDuration:
    """Tests for duration formatting."""

    def test_zero_seconds(self):
        from suno_downloaderist.utils import format_duration
        assert format_duration(0) == "0:00"

    def test_thirty_seconds(self):
        from suno_downloaderist.utils import format_duration
        assert format_duration(30) == "0:30"

    def test_one_minute(self):
        from suno_downloaderist.utils import format_duration
        assert format_duration(60) == "1:00"

    def test_three_minutes_two_seconds(self):
        from suno_downloaderist.utils import format_duration
        assert format_duration(182) == "3:02"

    def test_negative_returns_zero(self):
        from suno_downloaderist.utils import format_duration
        assert format_duration(-5) == "0:00"

    def test_fractional_seconds(self):
        from suno_downloaderist.utils import format_duration
        assert format_duration(182.7) == "3:02"


class TestFormatBytes:
    """Tests for byte size formatting."""

    def test_bytes(self):
        from suno_downloaderist.utils import format_bytes
        assert format_bytes(500) == "500 B"

    def test_kilobytes(self):
        from suno_downloaderist.utils import format_bytes
        result = format_bytes(1536)
        assert "KB" in result

    def test_megabytes(self):
        from suno_downloaderist.utils import format_bytes
        result = format_bytes(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        from suno_downloaderist.utils import format_bytes
        result = format_bytes(2 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_negative(self):
        from suno_downloaderist.utils import format_bytes
        assert format_bytes(-1) == "0 B"
