"""Pydantic data models for Suno API."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator


class ClipMetadata(BaseModel):
    """Metadata for a Suno clip."""
    prompt: Optional[str] = None
    gpt_description_prompt: Optional[str] = None
    tags: Optional[str] = None
    negative_tags: Optional[str] = None
    type: Optional[str] = None
    continue_at: Optional[float] = None
    continue_clip_id: Optional[str] = None
    concat_history: Optional[List[Dict[str, Any]]] = None
    stem_from_id: Optional[str] = None
    persona_id: Optional[str] = None


class SunoClip(BaseModel):
    """Full song model representing a Suno clip."""
    id: str
    title: Optional[str] = ""
    audio_url: Optional[str] = None
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    image_large_url: Optional[str] = None
    major_model_version: Optional[str] = None
    model_name: Optional[str] = None
    status: Optional[str] = None
    created_at: datetime
    duration: Optional[float] = 0.0
    metadata: Optional[ClipMetadata] = Field(default_factory=ClipMetadata)
    is_liked: Optional[bool] = False
    is_trashed: Optional[bool] = False
    is_public: Optional[bool] = False
    play_count: Optional[int] = 0
    upvote_count: Optional[int] = 0
    display_name: Optional[str] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that the ID is a valid UUID string if possible."""
        try:
            uuid.UUID(v)
        except ValueError:
            pass  # Some IDs might not be strict UUIDs, keep as is
        return v

    @property
    def cdn_mp3_url(self) -> str:
        """Get the CDN MP3 URL for this clip."""
        return f"https://cdn1.suno.ai/{self.id}.mp3"

    @property
    def cdn_mp4_url(self) -> str:
        """Get the CDN MP4 URL for this clip."""
        return f"https://cdn1.suno.ai/{self.id}.mp4"

    @property
    def cdn_image_url(self) -> str:
        """Get the CDN Image URL for this clip."""
        return f"https://cdn2.suno.ai/image_{self.id}.png"


class BillingInfo(BaseModel):
    """Billing and subscription information."""
    tier: Optional[str] = None
    credits_remaining: Optional[int] = 0
    total_credits: Optional[int] = 0
    is_active: Optional[bool] = False


class AlignedWord(BaseModel):
    """Word with precise timing information."""
    start_ms: int
    end_ms: int
    text: str


class AlignedLyrics(BaseModel):
    """Aligned lyrics containing multiple words."""
    words: List[AlignedWord]


class DownloadFormat(str, Enum):
    """Supported download formats."""
    MP3 = "MP3"
    WAV = "WAV"
    MP4 = "MP4"


class DownloadOptions(BaseModel):
    """Options for downloading clips."""
    formats: List[DownloadFormat] = Field(default_factory=lambda: [DownloadFormat.MP3])
    output_dir: str = "~/Music/SunoDownloaderist/"
    include_cover_art: bool = True
    include_lyrics: bool = True
    workers_count: int = 4
    skip_existing: bool = True


class FilterOptions(BaseModel):
    """Options for filtering clips."""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    liked_only: bool = False
    min_plays: int = 0
    title_search: Optional[str] = None


class SongGroup(BaseModel):
    """Group of SunoClips with the same title."""
    title: str
    clips: List[SunoClip]

    @model_validator(mode="after")
    def check_clips(self) -> "SongGroup":
        """Sort clips by created_at by default."""
        self.clips.sort(key=lambda c: c.created_at)
        return self
