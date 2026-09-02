"""FastAPI web dashboard server for Suno Song Downloaderist.

Provides a local web interface for managing downloads with real-time progress
via WebSocket. Runs on localhost only — no external network access.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ─── Request/Response Models ───────────────────────────────────────────────


class DashboardFilterOptions(BaseModel):
    """Filter options from the dashboard UI."""

    liked_only: bool = False
    since: Optional[str] = None
    until: Optional[str] = None
    search: Optional[str] = None
    min_plays: Optional[int] = None


class DashboardDownloadRequest(BaseModel):
    """Download request from the dashboard UI."""

    formats: List[str] = ["mp3"]
    filters: DashboardFilterOptions = DashboardFilterOptions()
    output_dir: str = ""


# ─── App State ──────────────────────────────────────────────────────────────


def _load_cached_songs() -> List[Dict[str, Any]]:
    """Load cached song library from disk."""
    from suno_downloaderist.utils import get_config_dir
    cache_file = get_config_dir() / "library_cache.json"
    if cache_file.exists():
        try:
            import json
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def _filter_cached_songs(
    songs: List[Dict[str, Any]],
    liked_only: bool = False,
    since: Optional[str] = None,
    until: Optional[str] = None,
    search: Optional[str] = None,
    min_plays: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Filter list of cached song dictionaries."""
    res = []
    for s in songs:
        if liked_only and not s.get("is_liked"):
            continue
        if search and search.lower() not in (s.get("title") or "").lower():
            continue
        if min_plays and (s.get("play_count") or 0) < min_plays:
            continue
        if since:
            try:
                dt = str(s.get("created_at") or "")
                if dt < since:
                    continue
            except Exception:
                pass
        if until:
            try:
                dt = str(s.get("created_at") or "")
                if dt > until:
                    continue
            except Exception:
                pass
        res.append(s)
    return res


class DashboardState:
    """Shared state between the dashboard and download engine."""

    def __init__(self) -> None:
        self.is_downloading: bool = False
        self.subscription_tier: str = "Pro"
        self.total_songs: int = 0
        self.is_authenticated: bool = True
        self.download_progress: Dict[str, Any] = {}
        self.config: Dict[str, Any] = {}


_state = DashboardState()


# ─── App Factory ────────────────────────────────────────────────────────────


def create_app(config: Optional[Any] = None) -> FastAPI:
    """Create the FastAPI dashboard application.

    Args:
        config: Optional AppConfig instance.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Suno Song Downloaderist Dashboard",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from suno_downloaderist.auth.session import SessionManager
    sm = SessionManager()
    try:
        session = sm.load_session()
        _state.is_authenticated = session is not None
    except Exception:
        _state.is_authenticated = False
    all_songs = _load_cached_songs()
    _state.total_songs = len(all_songs)

    if config:
        _state.config = (
            config.model_dump(mode="json")
            if hasattr(config, "model_dump")
            else vars(config)
        )

    # ─── API Routes ─────────────────────────────────────────────────────

    @app.get("/api/status")
    async def get_status() -> Dict[str, Any]:
        """Return current authentication and library status."""
        songs = _load_cached_songs()
        return {
            "authenticated": _state.is_authenticated,
            "total_songs": len(songs),
            "is_downloading": _state.is_downloading,
        }

    @app.get("/api/subscription")
    async def get_subscription() -> Dict[str, str]:
        """Return the user's subscription tier."""
        return {"tier": _state.subscription_tier}

    @app.get("/api/library/count")
    async def get_library_count(
        liked_only: bool = False,
        since: Optional[str] = None,
        until: Optional[str] = None,
        search: Optional[str] = None,
        min_plays: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return song count with filters applied."""
        songs = _load_cached_songs()
        filtered = _filter_cached_songs(
            songs,
            liked_only=liked_only,
            since=since,
            until=until,
            search=search,
            min_plays=min_plays,
        )
        return {"count": len(filtered)}

    @app.get("/api/library")
    async def get_library(
        page: int = 1,
        page_size: int = 20,
        liked_only: bool = False,
        since: Optional[str] = None,
        until: Optional[str] = None,
        search: Optional[str] = None,
        min_plays: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return paginated song library."""
        songs = _load_cached_songs()
        filtered = _filter_cached_songs(
            songs,
            liked_only=liked_only,
            since=since,
            until=until,
            search=search,
            min_plays=min_plays,
        )
        start_idx = (page - 1) * page_size
        page_items = filtered[start_idx : start_idx + page_size]
        return {"songs": page_items, "page": page, "total": len(filtered)}

    @app.get("/api/config")
    async def get_config() -> Dict[str, Any]:
        """Return current configuration."""
        return _state.config

    @app.post("/api/config")
    async def update_config(new_config: Dict[str, Any]) -> Dict[str, str]:
        """Update configuration values."""
        _state.config.update(new_config)
        return {"status": "updated"}

    @app.post("/api/download/start")
    async def start_download(options: DashboardDownloadRequest) -> Dict[str, str]:
        """Start a download with the given options."""
        if _state.is_downloading:
            return {"status": "error", "message": "Download already in progress"}
        _state.is_downloading = True
        return {"status": "started"}

    @app.post("/api/download/pause")
    async def pause_download() -> Dict[str, str]:
        """Pause current download."""
        return {"status": "paused"}

    @app.post("/api/download/resume")
    async def resume_download() -> Dict[str, str]:
        """Resume paused download."""
        return {"status": "resumed"}

    @app.post("/api/download/cancel")
    async def cancel_download() -> Dict[str, str]:
        """Cancel current download."""
        _state.is_downloading = False
        return {"status": "cancelled"}

    @app.get("/api/download/progress")
    async def get_progress() -> Dict[str, Any]:
        """Return current download progress."""
        return _state.download_progress

    # ─── WebSocket ──────────────────────────────────────────────────────

    @app.websocket("/ws/progress")
    async def websocket_progress(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time download progress updates."""
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(_state.download_progress)
                await asyncio.sleep(0.5)
        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected.")
        except Exception as exc:
            logger.debug("WebSocket error: %s", exc)

    # ─── Static Files (must be last) ────────────────────────────────────

    if os.path.isdir(STATIC_DIR):
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


def run_dashboard(config: Any) -> None:
    """Start the dashboard server.

    Args:
        config: AppConfig instance with dashboard_port.
    """
    port = getattr(config, "dashboard_port", 8484)
    app = create_app(config)

    logger.info("Starting dashboard on http://localhost:%d", port)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
