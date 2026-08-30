"""Tests for the download engine."""

from __future__ import annotations

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from suno_downloaderist.downloader.engine import (
    DownloadEngine,
    DownloadProgress,
    DownloadResult,
)


class TestDownloadProgress:
    """Tests for the DownloadProgress dataclass."""

    def test_default_values(self):
        progress = DownloadProgress()
        assert progress.total_files == 0
        assert progress.completed_files == 0
        assert progress.failed_files == 0
        assert progress.skipped_files == 0
        assert progress.current_file == ""
        assert progress.bytes_downloaded == 0
        assert progress.speed_bps == 0.0
        assert progress.eta_seconds == 0.0

    def test_custom_values(self):
        progress = DownloadProgress(
            total_files=100,
            completed_files=50,
            failed_files=2,
            skipped_files=10,
            current_file="song.mp3",
            bytes_downloaded=1024 * 1024,
            speed_bps=500000.0,
            eta_seconds=120.0,
        )
        assert progress.total_files == 100
        assert progress.completed_files == 50
        assert progress.current_file == "song.mp3"


class TestDownloadResult:
    """Tests for the DownloadResult dataclass."""

    def test_success_result(self):
        result = DownloadResult(
            success=True,
            file_path=Path("/tmp/song.mp3"),
        )
        assert result.success is True
        assert result.error_message is None

    def test_failure_result(self):
        result = DownloadResult(
            success=False,
            file_path=Path("/tmp/song.mp3"),
            error_message="Connection timeout",
            clip_id="abc-123",
        )
        assert result.success is False
        assert result.error_message == "Connection timeout"
        assert result.clip_id == "abc-123"


class TestDownloadEngine:
    """Tests for the DownloadEngine class."""

    def test_default_workers(self):
        engine = DownloadEngine()
        assert engine.workers == 3

    def test_max_workers_capped(self):
        engine = DownloadEngine(workers=100)
        assert engine.workers == 8

    def test_min_workers_enforced(self):
        engine = DownloadEngine(workers=0)
        assert engine.workers == 1

    def test_negative_workers_enforced(self):
        engine = DownloadEngine(workers=-5)
        assert engine.workers == 1

    def test_custom_settings(self):
        engine = DownloadEngine(
            workers=5,
            cdn_delay=0.5,
            skip_existing=False,
            max_retries=3,
        )
        assert engine.workers == 5
        assert engine.cdn_delay == 0.5
        assert engine.skip_existing is False
        assert engine.max_retries == 3

    @pytest.mark.asyncio
    async def test_skip_existing_file(self, tmp_path):
        """Should skip download when file already exists."""
        existing_file = tmp_path / "song.mp3"
        existing_file.write_bytes(b"fake audio data")

        engine = DownloadEngine(skip_existing=True)
        result = await engine.download_file(
            url="https://cdn1.suno.ai/test.mp3",
            dest_path=existing_file,
        )
        assert result.success is True
        assert result.error_message == "skipped"
        assert engine.progress.skipped_files == 1

    @pytest.mark.asyncio
    async def test_skip_existing_disabled(self, tmp_path):
        """Should NOT skip when skip_existing is False."""
        existing_file = tmp_path / "song.mp3"
        existing_file.write_bytes(b"fake audio data")

        engine = DownloadEngine(skip_existing=False)
        # This will fail since we can't actually download, but it shouldn't skip
        result = await engine.download_file(
            url="https://fake.invalid/test.mp3",
            dest_path=existing_file,
        )
        # It will fail on the network request, not skip
        assert result.error_message != "skipped"

    @pytest.mark.asyncio
    async def test_cancel_stops_download(self):
        """Cancellation should stop download immediately."""
        engine = DownloadEngine()
        await engine.cancel()

        result = await engine.download_file(
            url="https://cdn1.suno.ai/test.mp3",
            dest_path=Path("/tmp/test.mp3"),
        )
        assert result.success is False
        assert result.error_message == "Cancelled"

    @pytest.mark.asyncio
    async def test_pause_resume(self):
        """Pause and resume should toggle the pause state."""
        engine = DownloadEngine()
        assert engine._pause_event.is_set()  # Not paused initially

        await engine.pause()
        assert not engine._pause_event.is_set()  # Paused

        await engine.resume()
        assert engine._pause_event.is_set()  # Resumed

    @pytest.mark.asyncio
    async def test_get_progress_returns_dict(self):
        """get_progress should return a serializable dict."""
        engine = DownloadEngine()
        engine.progress.total_files = 10
        engine.progress.completed_files = 3

        progress = await engine.get_progress()
        assert isinstance(progress, dict)
        assert progress["total_files"] == 10
        assert progress["completed_files"] == 3
        assert "speed_bps" in progress
        assert "eta_seconds" in progress

    @pytest.mark.asyncio
    async def test_creates_parent_directory(self, tmp_path):
        """Should create parent directories for the destination file."""
        dest = tmp_path / "deep" / "nested" / "dir" / "song.mp3"
        engine = DownloadEngine(max_retries=1)

        # Will fail on network but should create the directory
        result = await engine.download_file(
            url="https://fake.invalid/test.mp3",
            dest_path=dest,
        )
        assert dest.parent.exists()
