"""Async Suno API client."""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

import httpx
from httpx import HTTPStatusError, RequestError

from .endpoints import (
    get_aligned_lyrics_url, get_billing_url, get_clip_url,
    get_feed_url, get_wav_url
)
from .models import AlignedLyrics, BillingInfo, FilterOptions, SongGroup, SunoClip

logger = logging.getLogger(__name__)


class SunoClient:
    """Async client for interacting with the Suno API."""

    def __init__(self, token_manager: Any, timeout: float = 30.0):
        """Initialize the Suno client.
        
        Args:
            token_manager: Manager that provides Bearer tokens.
            timeout: Default timeout for requests.
        """
        self.token_manager = token_manager
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://suno.com",
            "Referer": "https://suno.com/",
        }
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.headers,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
        )
        self.base_delay = 0.2
        self.current_delay = self.base_delay

    async def _get_auth_headers(self) -> Dict[str, str]:
        """Get headers including the current Bearer token."""
        token = self.token_manager.get_current_token()
        if token is None:
            raise ValueError("No valid auth token available. Please re-authenticate.")
        return {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Make an HTTP request with retry logic and rate limiting."""
        max_retries = 5
        base_backoff = 1.0

        for attempt in range(max_retries):
            try:
                # Apply rate limiting delay
                await asyncio.sleep(self.current_delay)

                headers = kwargs.pop("headers", {})
                auth_headers = await self._get_auth_headers()
                headers.update(auth_headers)

                response = await self.client.request(method, url, headers=headers, **kwargs)
                
                # Check for rate limiting
                if response.status_code == 429:
                    logger.warning(f"Rate limited (429) on {url}. Backing off.")
                    # Adaptive rate limiting: increase delay
                    self.current_delay = min(self.current_delay * 2, 30.0)
                    response.raise_for_status()

                # Decrease delay when healthy
                if response.status_code == 200:
                    self.current_delay = max(self.base_delay, self.current_delay * 0.9)

                response.raise_for_status()
                return response

            except HTTPStatusError as e:
                if e.response.status_code in (429, 500, 502, 503, 504):
                    if attempt == max_retries - 1:
                        logger.error(f"Failed after {max_retries} attempts: {e}")
                        raise
                    
                    backoff = min(base_backoff * (2 ** attempt), 30.0)
                    logger.info(f"Retrying in {backoff} seconds...")
                    await asyncio.sleep(backoff)
                else:
                    raise
            except RequestError as e:
                if attempt == max_retries - 1:
                    logger.error(f"Request failed after {max_retries} attempts: {e}")
                    raise
                
                backoff = min(base_backoff * (2 ** attempt), 30.0)
                logger.info(f"Request error, retrying in {backoff} seconds...")
                await asyncio.sleep(backoff)
                
        raise Exception("Max retries exceeded") # Fallback

    async def close(self) -> None:
        """Close the async client."""
        await self.client.aclose()

    async def get_billing_info(self) -> BillingInfo:
        """Get billing and subscription info."""
        url = get_billing_url()
        response = await self._request("GET", url)
        data = response.json()
        if isinstance(data, dict):
            # Find tier - only accept actual string values
            tier = None
            for key in ("subscription_type", "plan", "tier"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    tier = val
                    break
            return BillingInfo(
                tier=tier or "unknown",
                credits_remaining=data.get("total_credits_left") or data.get("credits_remaining") or 0,
                total_credits=data.get("monthly_limit") or data.get("total_credits") or 0,
                is_active=data.get("is_active", False),
            )
        return BillingInfo()

    async def get_library(self, page: int, page_size: int = 20) -> List[SunoClip]:
        """Get a page of clips from the library."""
        url = get_feed_url(page=page, page_size=page_size)
        response = await self._request("GET", url)
        data = response.json()
        logger.debug(
            "Feed response type: %s, keys: %s",
            type(data).__name__,
            list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]" if isinstance(data, list) else "?",
        )

        # Extract the clips list from whatever format Suno returns
        clips_data: list = []
        if isinstance(data, list):
            clips_data = data
        elif isinstance(data, dict):
            # Try common wrapper keys
            for key in ("clips", "data", "results", "items", "songs", "feed"):
                if key in data and isinstance(data[key], list):
                    clips_data = data[key]
                    logger.debug("Found clips under key '%s' (%d items)", key, len(clips_data))
                    break
            else:
                # Log the actual keys so we can see what Suno returns
                logger.warning("Unexpected feed response format. Keys: %s", list(data.keys()))
                # Maybe the whole dict is a single clip?
                if "id" in data:
                    clips_data = [data]

        parsed = []
        for i, item in enumerate(clips_data):
            try:
                if i == 0:
                    logger.debug("First clip keys: %s", list(item.keys()) if isinstance(item, dict) else "?")
                    logger.debug("First clip is_liked=%s, title=%s", item.get("is_liked"), item.get("title"))
                parsed.append(SunoClip(**item))
            except Exception as exc:
                logger.debug("Failed to parse clip: %s — %s", exc, list(item.keys()) if isinstance(item, dict) else item)
        return parsed

    async def get_all_clips(
        self, 
        filter_options: Optional[FilterOptions] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        refresh_cache: bool = False,
    ) -> List[SunoClip]:
        """Fetch all clips, with smart incremental caching for lightning-fast subsequent runs."""
        from suno_downloaderist.utils import get_config_dir
        cache_file = get_config_dir() / "library_cache.json"
        
        cached_clips_map: Dict[str, dict] = {}
        if not refresh_cache and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                    if isinstance(cached_data, list):
                        for item in cached_data:
                            if isinstance(item, dict) and "id" in item:
                                cached_clips_map[item["id"]] = item
                if cached_clips_map:
                    logger.info(f"Loaded {len(cached_clips_map)} cached songs from local library index.")
            except Exception as e:
                logger.debug("Failed reading library cache: %s", e)

        def _save_cache():
            if not cached_clips_map:
                return
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(list(cached_clips_map.values()), f, default=str)
            except Exception as e:
                logger.warning("Failed to save library cache: %s", e)

        page = 0
        page_size = 20
        new_clips: List[SunoClip] = []

        while True:
            logger.info(f"Scanning library page {page}...")
            clips = await self.get_library(page=page, page_size=page_size)
            if not clips:
                break
                
            known_in_page = 0
            for c in clips:
                if c.id in cached_clips_map:
                    known_in_page += 1
                cached_clips_map[c.id] = c.model_dump()
                    
            new_clips.extend(clips)
            if progress_callback:
                progress_callback(len(new_clips))
                
            # Periodically persist cache every 10 pages
            if page % 10 == 0:
                _save_cache()

            if len(clips) < page_size:
                break
                
            # If all items on this page are already in cache and not doing a full refresh,
            # we've caught up with the user's latest library!
            if not refresh_cache and cached_clips_map and known_in_page == len(clips):
                logger.info(f"Sync complete. Caught up with indexed library at page {page}.")
                break
                
            page += 1

        # Final cache write
        _save_cache()

        # Parse all clips
        all_clips: List[SunoClip] = []
        for item in cached_clips_map.values():
            try:
                all_clips.append(SunoClip(**item))
            except Exception:
                pass

        # Sort newest first
        all_clips.sort(key=lambda c: c.created_at, reverse=True)

        # Apply filters
        if filter_options:
            all_clips = self._apply_filters(all_clips, filter_options)

        return all_clips

    def _apply_filters(self, clips: List[SunoClip], options: FilterOptions) -> List[SunoClip]:
        """Apply filters to a list of clips."""
        filtered = []
        for clip in clips:
            if options.liked_only and not clip.is_liked:
                continue
            if options.min_plays > 0 and (clip.play_count or 0) < options.min_plays:
                continue
            if options.title_search and options.title_search.lower() not in (clip.title or "").lower():
                continue
            if options.date_from and clip.created_at < options.date_from:
                continue
            if options.date_to and clip.created_at > options.date_to:
                continue
            filtered.append(clip)
        return filtered

    async def get_clip_by_id(self, clip_id: str) -> SunoClip:
        """Get details for a specific clip."""
        url = get_clip_url(clip_id)
        response = await self._request("GET", url)
        data = response.json()
        if not data:
            raise ValueError(f"Clip {clip_id} not found")
        return SunoClip(**data[0])

    async def get_aligned_lyrics(self, clip_id: str) -> Optional[AlignedLyrics]:
        """Get aligned lyrics for a clip if available."""
        url = get_aligned_lyrics_url(clip_id)
        try:
            response = await self._request("GET", url)
            data = response.json()
            if not data:
                return None
            
            # Suno sometimes returns just a list, sometimes a dict
            if isinstance(data, list):
                words = [{"start_ms": w.get("start", 0) * 1000, "end_ms": w.get("end", 0) * 1000, "text": w.get("word", "")} for w in data]
                return AlignedLyrics(words=words)
            return None
        except HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_wav_download_url(self, clip_id: str) -> Optional[str]:
        """Get the WAV file download URL for a clip.
        
        Checks if WAV is already ready, or triggers conversion and polls
        until the signed S3 URL is ready.
        """
        wav_url_endpoint = get_wav_url(clip_id)
        try:
            response = await self._request("GET", wav_url_endpoint)
            data = response.json()
            if data and data.get("wav_file_url"):
                return data["wav_file_url"]
            if data and data.get("url"):
                return data["url"]
        except HTTPStatusError as e:
            if e.response.status_code == 403:
                return None
            if e.response.status_code != 404:
                raise

        # Trigger conversion if not ready
        convert_url = f"https://studio-api.prod.suno.com/api/gen/{clip_id}/convert_wav/"
        try:
            await self._request("POST", convert_url)
        except Exception as exc:
            logger.debug("Failed to trigger WAV conversion for %s: %s", clip_id, exc)

        # Poll for readiness (up to 15s)
        for _ in range(8):
            await asyncio.sleep(1.5)
            try:
                response = await self._request("GET", wav_url_endpoint)
                data = response.json()
                if data and data.get("wav_file_url"):
                    return data["wav_file_url"]
                if data and data.get("url"):
                    return data["url"]
            except Exception:
                pass

        return None
            
    def group_by_title(self, clips: List[SunoClip]) -> Dict[str, SongGroup]:
        """Group a list of clips by their title."""
        groups: Dict[str, List[SunoClip]] = {}
        for clip in clips:
            title = clip.title or "Untitled"
            if title not in groups:
                groups[title] = []
            groups[title].append(clip)
            
        return {
            title: SongGroup(title=title, clips=grouped_clips)
            for title, grouped_clips in groups.items()
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
