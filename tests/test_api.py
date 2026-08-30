"""Tests for the Suno API client and data models."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from suno_downloaderist.api.models import (
    AlignedLyrics,
    AlignedWord,
    BillingInfo,
    ClipMetadata,
    DownloadFormat,
    FilterOptions,
    SongGroup,
    SunoClip,
)


# ─── Sample Data ────────────────────────────────────────────────────────────

SAMPLE_CLIP_JSON = {
    "id": "3a8b29c4-72e1-4c12-9b23-abcdef123456",
    "title": "Neon Horizons",
    "audio_url": "https://cdn1.suno.ai/3a8b29c4-72e1-4c12-9b23-abcdef123456.mp3",
    "video_url": "https://cdn1.suno.ai/3a8b29c4-72e1-4c12-9b23-abcdef123456.mp4",
    "image_url": "https://cdn2.suno.ai/image_3a8b29c4-72e1-4c12-9b23-abcdef123456.png",
    "image_large_url": "https://cdn2.suno.ai/image_large_3a8b29c4-72e1-4c12-9b23-abcdef123456.png",
    "major_model_version": "v4",
    "model_name": "chirp-v4",
    "status": "complete",
    "created_at": "2026-08-15T12:34:56.789Z",
    "duration": 182.4,
    "metadata": {
        "prompt": "[Verse 1]\nDriving through the neon glow...",
        "gpt_description_prompt": "80s synthwave, retro synth leads, nostalgic",
        "tags": "synthwave, 80s, electronic",
        "negative_tags": "acoustic, low quality",
        "type": "gen",
        "continue_at": None,
        "continue_clip_id": None,
        "concat_history": None,
        "stem_from_id": None,
        "persona_id": None,
    },
    "is_liked": True,
    "is_trashed": False,
    "is_public": False,
    "play_count": 42,
    "upvote_count": 5,
    "display_name": "TestUser",
}


# ─── Model Parsing ──────────────────────────────────────────────────────────


class TestSunoClipModel:
    """Tests for the SunoClip Pydantic model."""

    def test_parse_from_json(self):
        """Should parse a complete API response correctly."""
        clip = SunoClip.model_validate(SAMPLE_CLIP_JSON)
        assert clip.id == "3a8b29c4-72e1-4c12-9b23-abcdef123456"
        assert clip.title == "Neon Horizons"
        assert clip.duration == 182.4
        assert clip.is_liked is True
        assert clip.play_count == 42
        assert clip.model_name == "chirp-v4"

    def test_metadata_parsing(self):
        """Metadata nested model should parse correctly."""
        clip = SunoClip.model_validate(SAMPLE_CLIP_JSON)
        assert clip.metadata is not None
        assert clip.metadata.gpt_description_prompt == "80s synthwave, retro synth leads, nostalgic"
        assert clip.metadata.tags == "synthwave, 80s, electronic"
        assert clip.metadata.type == "gen"

    def test_cdn_url_properties(self):
        """Computed CDN URL properties should generate correct URLs."""
        clip = SunoClip.model_validate(SAMPLE_CLIP_JSON)
        assert clip.cdn_mp3_url == "https://cdn1.suno.ai/3a8b29c4-72e1-4c12-9b23-abcdef123456.mp3"
        assert clip.cdn_mp4_url == "https://cdn1.suno.ai/3a8b29c4-72e1-4c12-9b23-abcdef123456.mp4"
        assert clip.cdn_image_url == "https://cdn2.suno.ai/image_3a8b29c4-72e1-4c12-9b23-abcdef123456.png"

    def test_minimal_clip(self):
        """Should handle a clip with only required fields."""
        minimal = {
            "id": "test-id-123",
            "created_at": "2026-01-01T00:00:00Z",
        }
        clip = SunoClip.model_validate(minimal)
        assert clip.id == "test-id-123"
        assert clip.title == ""
        assert clip.duration == 0.0
        assert clip.is_liked is False
        assert clip.play_count == 0

    def test_datetime_parsing(self):
        """Should parse ISO datetime strings correctly."""
        clip = SunoClip.model_validate(SAMPLE_CLIP_JSON)
        assert isinstance(clip.created_at, datetime)
        assert clip.created_at.year == 2026
        assert clip.created_at.month == 8
        assert clip.created_at.day == 15


class TestBillingInfo:
    """Tests for subscription/billing model."""

    def test_free_tier(self):
        info = BillingInfo(tier="free", credits_remaining=10, total_credits=50)
        assert info.tier == "free"

    def test_pro_tier(self):
        info = BillingInfo(tier="pro", credits_remaining=2000, total_credits=2500, is_active=True)
        assert info.tier == "pro"
        assert info.is_active is True

    def test_defaults(self):
        info = BillingInfo()
        assert info.tier is None
        assert info.credits_remaining == 0


class TestAlignedLyrics:
    """Tests for aligned lyrics model."""

    def test_word_parsing(self):
        word = AlignedWord(start_ms=1000, end_ms=1500, text="Hello")
        assert word.start_ms == 1000
        assert word.end_ms == 1500
        assert word.text == "Hello"

    def test_lyrics_with_words(self):
        lyrics = AlignedLyrics(words=[
            AlignedWord(start_ms=0, end_ms=500, text="First"),
            AlignedWord(start_ms=500, end_ms=1000, text="line"),
        ])
        assert len(lyrics.words) == 2


# ─── Filter Logic ────────────────────────────────────────────────────────────


class TestFilterOptions:
    """Tests for filtering clip lists."""

    def _make_clip(self, title: str = "Test", liked: bool = False,
                   plays: int = 0, created: str = "2026-08-15T12:00:00Z") -> SunoClip:
        return SunoClip(
            id="test-id",
            title=title,
            is_liked=liked,
            play_count=plays,
            created_at=created,
        )

    def test_liked_only_filter(self):
        clips = [
            self._make_clip(title="Liked", liked=True),
            self._make_clip(title="Not Liked", liked=False),
        ]
        filtered = [c for c in clips if c.is_liked]
        assert len(filtered) == 1
        assert filtered[0].title == "Liked"

    def test_min_plays_filter(self):
        clips = [
            self._make_clip(title="Popular", plays=100),
            self._make_clip(title="Unpopular", plays=2),
        ]
        min_plays = 10
        filtered = [c for c in clips if (c.play_count or 0) >= min_plays]
        assert len(filtered) == 1
        assert filtered[0].title == "Popular"

    def test_date_filter_since(self):
        clips = [
            self._make_clip(title="Old", created="2026-07-01T00:00:00Z"),
            self._make_clip(title="New", created="2026-08-20T14:30:00Z"),
        ]
        since = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)
        filtered = [c for c in clips if c.created_at.replace(tzinfo=timezone.utc) >= since]
        assert len(filtered) == 1
        assert filtered[0].title == "New"

    def test_date_filter_hour_minute_precision(self):
        """Should filter with hour and minute precision."""
        clips = [
            self._make_clip(title="Morning", created="2026-08-15T09:00:00Z"),
            self._make_clip(title="Afternoon", created="2026-08-15T14:30:00Z"),
            self._make_clip(title="Evening", created="2026-08-15T20:00:00Z"),
        ]
        # Only songs between 12:00 and 18:00
        since = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        until = datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc)
        filtered = [
            c for c in clips
            if since <= c.created_at.replace(tzinfo=timezone.utc) <= until
        ]
        assert len(filtered) == 1
        assert filtered[0].title == "Afternoon"

    def test_title_search_filter(self):
        clips = [
            self._make_clip(title="Love Song"),
            self._make_clip(title="Rock Anthem"),
            self._make_clip(title="Lovely Day"),
        ]
        search = "love"
        filtered = [c for c in clips if search.lower() in (c.title or "").lower()]
        assert len(filtered) == 2

    def test_combined_filters(self):
        clips = [
            self._make_clip(title="Liked Popular", liked=True, plays=50, created="2026-08-20T00:00:00Z"),
            self._make_clip(title="Liked Unpopular", liked=True, plays=2, created="2026-08-20T00:00:00Z"),
            self._make_clip(title="Not Liked Popular", liked=False, plays=50, created="2026-08-20T00:00:00Z"),
            self._make_clip(title="Old Liked Popular", liked=True, plays=50, created="2026-07-01T00:00:00Z"),
        ]
        # Liked + min 10 plays + since Aug 15
        since = datetime(2026, 8, 15, 0, 0, tzinfo=timezone.utc)
        filtered = [
            c for c in clips
            if c.is_liked
            and (c.play_count or 0) >= 10
            and c.created_at.replace(tzinfo=timezone.utc) >= since
        ]
        assert len(filtered) == 1
        assert filtered[0].title == "Liked Popular"


# ─── Song Grouping ──────────────────────────────────────────────────────────


class TestSongGrouping:
    """Tests for grouping clips by title."""

    def test_group_by_title(self):
        clips = [
            SunoClip(id="1", title="Song A", created_at="2026-08-15T10:00:00Z"),
            SunoClip(id="2", title="Song A", created_at="2026-08-15T11:00:00Z"),
            SunoClip(id="3", title="Song B", created_at="2026-08-15T12:00:00Z"),
        ]
        groups: dict[str, list] = {}
        for clip in clips:
            title = clip.title or "Untitled"
            groups.setdefault(title, []).append(clip)

        assert len(groups) == 2
        assert len(groups["Song A"]) == 2
        assert len(groups["Song B"]) == 1

    def test_song_group_sorts_by_date(self):
        group = SongGroup(
            title="Test",
            clips=[
                SunoClip(id="2", title="Test", created_at="2026-08-15T12:00:00Z"),
                SunoClip(id="1", title="Test", created_at="2026-08-15T10:00:00Z"),
            ],
        )
        # model_validator should sort by created_at
        assert group.clips[0].id == "1"
        assert group.clips[1].id == "2"

    def test_empty_title_grouping(self):
        clips = [
            SunoClip(id="1", title="", created_at="2026-08-15T10:00:00Z"),
            SunoClip(id="2", title="", created_at="2026-08-15T11:00:00Z"),
        ]
        groups: dict[str, list] = {}
        for clip in clips:
            title = clip.title or "Untitled"
            groups.setdefault(title, []).append(clip)

        # Empty titles should be grouped as "Untitled" or together
        assert len(groups) == 1
