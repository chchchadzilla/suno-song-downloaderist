"""API module for Suno Downloaderist."""

from .client import SunoClient
from .endpoints import (
    SUNO_BASE_URL, CLERK_BASE_URL, CDN_BASE_URL, CDN2_BASE_URL,
    get_feed_url, get_clip_url, get_aligned_lyrics_url, get_wav_url,
    get_billing_url, get_cdn_mp3_url, get_cdn_mp4_url, get_cdn_image_url,
    get_cdn_image_large_url
)
from .models import (
    ClipMetadata, SunoClip, BillingInfo, AlignedWord, AlignedLyrics,
    DownloadFormat, DownloadOptions, FilterOptions, SongGroup
)

__all__ = [
    "SunoClient",
    "SUNO_BASE_URL", "CLERK_BASE_URL", "CDN_BASE_URL", "CDN2_BASE_URL",
    "get_feed_url", "get_clip_url", "get_aligned_lyrics_url", "get_wav_url",
    "get_billing_url", "get_cdn_mp3_url", "get_cdn_mp4_url", "get_cdn_image_url",
    "get_cdn_image_large_url",
    "ClipMetadata", "SunoClip", "BillingInfo", "AlignedWord", "AlignedLyrics",
    "DownloadFormat", "DownloadOptions", "FilterOptions", "SongGroup"
]
