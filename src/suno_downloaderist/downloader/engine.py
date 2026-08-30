"""Async download engine for Suno Song Downloaderist.

Handles parallel file downloads from Suno's CDN and API with:
- Configurable concurrency via asyncio.Semaphore
- Retry logic with exponential backoff
- Skip-existing / resume support
- Progress tracking with speed and ETA
- Clean cancellation support
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

import httpx

from suno_downloaderist.utils import get_user_agent

logger = logging.getLogger(__name__)


@dataclass
class DownloadProgress:
    """Tracks overall download progress."""

    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    current_file: str = ""
    bytes_downloaded: int = 0
    speed_bps: float = 0.0
    eta_seconds: float = 0.0


@dataclass
class DownloadResult:
    """Result of a single file download."""

    success: bool
    file_path: Path
    error_message: Optional[str] = None
    clip_id: Optional[str] = None


class DownloadEngine:
    """Async download engine with parallel workers and rate limiting.

    Features:
    - Concurrent downloads bounded by semaphore
    - Configurable delays between CDN vs API requests
    - Retry with exponential backoff on failures
    - Skip files that already exist on disk
    - Progress tracking with callbacks
    - Cancellation support via asyncio.Event

    Args:
        workers: Number of parallel download workers (1-8).
        cdn_delay: Delay in seconds between CDN downloads.
        skip_existing: Whether to skip already-downloaded files.
        max_retries: Maximum retry attempts per file.
    """

    def __init__(
        self,
        workers: int = 3,
        cdn_delay: float = 0.3,
        skip_existing: bool = True,
        max_retries: int = 5,
    ) -> None:
        self.workers = min(max(1, workers), 8)
        self.cdn_delay = cdn_delay
        self.skip_existing = skip_existing
        self.max_retries = max_retries

        self._semaphore = asyncio.Semaphore(self.workers)
        self._cancel_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Start un-paused

        self._headers = {
            "User-Agent": get_user_agent(),
            "Referer": "https://suno.com/",
            "Origin": "https://suno.com",
        }

        self.progress = DownloadProgress()
        self._start_time: float = 0.0

    async def download_file(
        self,
        url: str,
        dest_path: Path,
        auth_headers: Optional[Dict[str, str]] = None,
    ) -> DownloadResult:
        """Download a single file from a URL.

        Args:
            url: URL to download from.
            dest_path: Local path to save the file to.
            auth_headers: Optional auth headers (e.g., Bearer token for WAV downloads).

        Returns:
            DownloadResult indicating success/failure.
        """
        if self._cancel_event.is_set():
            return DownloadResult(False, dest_path, "Cancelled")

        # Skip if file already exists and is non-empty
        if self.skip_existing and dest_path.exists() and dest_path.stat().st_size > 0:
            logger.debug("Skipping existing file: %s", dest_path.name)
            self.progress.skipped_files += 1
            return DownloadResult(True, dest_path, "skipped")

        # Wait if paused
        await self._pause_event.wait()

        # Apply rate limiting delay
        is_auth = auth_headers is not None
        delay = 2.0 if is_auth else self.cdn_delay
        await asyncio.sleep(delay)

        # Build request headers
        headers = self._headers.copy()
        if auth_headers:
            headers.update(auth_headers)

        # Ensure parent directory exists
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Retry loop
        backoff = 1.0
        for attempt in range(1, self.max_retries + 1):
            if self._cancel_event.is_set():
                return DownloadResult(False, dest_path, "Cancelled")

            try:
                async with self._semaphore:
                    self.progress.current_file = dest_path.name

                    async with httpx.AsyncClient(
                        follow_redirects=True,
                        timeout=httpx.Timeout(60.0, connect=15.0),
                    ) as client:
                        async with client.stream(
                            "GET", url, headers=headers
                        ) as response:
                            if response.status_code == 429:
                                retry_after = float(
                                    response.headers.get("Retry-After", backoff * 2)
                                )
                                logger.warning(
                                    "Rate limited (429). Waiting %.1fs...",
                                    retry_after,
                                )
                                await asyncio.sleep(retry_after)
                                backoff = min(backoff * 2, 30.0)
                                continue

                            response.raise_for_status()

                            # Download to temp file, then rename (atomic)
                            temp_path = dest_path.with_suffix(
                                dest_path.suffix + ".part"
                            )

                            try:
                                with open(temp_path, "wb") as f:
                                    async for chunk in response.aiter_bytes(
                                        chunk_size=65536
                                    ):
                                        if self._cancel_event.is_set():
                                            temp_path.unlink(missing_ok=True)
                                            return DownloadResult(
                                                False, dest_path, "Cancelled"
                                            )
                                        f.write(chunk)
                                        self.progress.bytes_downloaded += len(chunk)

                                # Atomic rename
                                temp_path.rename(dest_path)
                                self.progress.completed_files += 1

                                logger.debug(
                                    "Downloaded: %s (%s)",
                                    dest_path.name,
                                    _format_size(dest_path.stat().st_size),
                                )
                                return DownloadResult(True, dest_path)

                            except Exception:
                                temp_path.unlink(missing_ok=True)
                                raise

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    logger.warning("File not found (404): %s", url)
                    return DownloadResult(False, dest_path, "Not found (404)")
                logger.warning(
                    "HTTP error downloading %s (attempt %d/%d): %s",
                    dest_path.name,
                    attempt,
                    self.max_retries,
                    exc,
                )
            except (httpx.TransportError, OSError) as exc:
                logger.warning(
                    "Download error for %s (attempt %d/%d): %s",
                    dest_path.name,
                    attempt,
                    self.max_retries,
                    exc,
                )

            if attempt < self.max_retries:
                logger.debug("Retrying in %.1fs...", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

        self.progress.failed_files += 1
        return DownloadResult(
            False, dest_path, f"Failed after {self.max_retries} retries"
        )

    async def download_batch(
        self,
        items: list[tuple[str, Path, Optional[Dict[str, str]]]],
        progress_callback: Optional[Callable[[DownloadProgress], Any]] = None,
    ) -> list[DownloadResult]:
        """Download multiple files concurrently.

        Args:
            items: List of (url, dest_path, auth_headers) tuples.
            progress_callback: Optional callback called after each download.

        Returns:
            List of DownloadResult for each item.
        """
        self.progress = DownloadProgress(total_files=len(items))
        self._start_time = time.monotonic()
        self._cancel_event.clear()

        async def _download_one(
            url: str, dest: Path, auth: Optional[Dict[str, str]]
        ) -> DownloadResult:
            result = await self.download_file(url, dest, auth)
            self._update_speed()
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(self.progress)
                else:
                    progress_callback(self.progress)
            return result

        tasks = [_download_one(url, dest, auth) for url, dest, auth in items]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[DownloadResult] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Download task exception: %s", r)
                final.append(DownloadResult(False, Path(""), str(r)))
            else:
                final.append(r)

        return final

    def _update_speed(self) -> None:
        """Recalculate download speed and ETA."""
        elapsed = time.monotonic() - self._start_time
        if elapsed > 0:
            self.progress.speed_bps = self.progress.bytes_downloaded / elapsed

        processed = (
            self.progress.completed_files
            + self.progress.failed_files
            + self.progress.skipped_files
        )
        remaining = self.progress.total_files - processed

        if self.progress.completed_files > 0 and self.progress.speed_bps > 0:
            avg_bytes = self.progress.bytes_downloaded / self.progress.completed_files
            self.progress.eta_seconds = (remaining * avg_bytes) / self.progress.speed_bps
        else:
            self.progress.eta_seconds = 0.0

    async def pause(self) -> None:
        """Pause all downloads."""
        self._pause_event.clear()
        logger.info("Downloads paused.")

    async def resume(self) -> None:
        """Resume paused downloads."""
        self._pause_event.set()
        logger.info("Downloads resumed.")

    async def cancel(self) -> None:
        """Cancel all downloads."""
        self._cancel_event.set()
        self._pause_event.set()  # Unpause to let tasks exit
        logger.info("Downloads cancelled.")

    async def get_progress(self) -> Dict[str, Any]:
        """Return current progress as a dict (for dashboard API)."""
        return {
            "total_files": self.progress.total_files,
            "completed_files": self.progress.completed_files,
            "failed_files": self.progress.failed_files,
            "skipped_files": self.progress.skipped_files,
            "current_file": self.progress.current_file,
            "bytes_downloaded": self.progress.bytes_downloaded,
            "speed_bps": self.progress.speed_bps,
            "eta_seconds": self.progress.eta_seconds,
        }


def _format_size(size_bytes: int) -> str:
    """Quick size formatter for log messages."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} TB"
