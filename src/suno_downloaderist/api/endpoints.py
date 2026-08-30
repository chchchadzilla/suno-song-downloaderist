"""Centralized API endpoint definitions for Suno Downloaderist."""

SUNO_BASE_URL = "https://studio-api.prod.suno.com"
CLERK_BASE_URL = "https://clerk.suno.com"
CDN_BASE_URL = "https://cdn1.suno.ai"
CDN2_BASE_URL = "https://cdn2.suno.ai"


def get_feed_url(page: int, page_size: int = 20) -> str:
    """Get the URL for the feed endpoint."""
    return f"{SUNO_BASE_URL}/api/feed/?page={page}&page_size={page_size}"


def get_clip_url(clip_id: str) -> str:
    """Get the URL for a specific clip."""
    return f"{SUNO_BASE_URL}/api/feed/?ids={clip_id}"


def get_aligned_lyrics_url(clip_id: str) -> str:
    """Get the URL for the aligned lyrics endpoint."""
    return f"{SUNO_BASE_URL}/api/gen/{clip_id}/aligned_lyrics/v2/"


def get_wav_url(clip_id: str) -> str:
    """Get the URL for the WAV file download endpoint."""
    return f"{SUNO_BASE_URL}/api/gen/{clip_id}/wav_file/"


def get_billing_url() -> str:
    """Get the URL for the billing info endpoint."""
    return f"{SUNO_BASE_URL}/api/billing/info/"


def get_cdn_mp3_url(clip_id: str) -> str:
    """Get the CDN URL for the MP3 file."""
    return f"{CDN_BASE_URL}/{clip_id}.mp3"


def get_cdn_mp4_url(clip_id: str) -> str:
    """Get the CDN URL for the MP4 file."""
    return f"{CDN_BASE_URL}/{clip_id}.mp4"


def get_cdn_image_url(clip_id: str) -> str:
    """Get the CDN URL for the small image file."""
    return f"{CDN2_BASE_URL}/image_{clip_id}.png"


def get_cdn_image_large_url(clip_id: str) -> str:
    """Get the CDN URL for the large image file."""
    return f"{CDN2_BASE_URL}/image_large_{clip_id}.png"
