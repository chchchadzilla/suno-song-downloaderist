"""File and folder organization for downloaded Suno songs.

Handles:
- Creating organized folder structures per song
- Sanitizing filenames for cross-platform compatibility
- Version numbering for same-title songs
- Building download plans for the engine
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from suno_downloaderist.utils import sanitize_filename

logger = logging.getLogger(__name__)


class FileOrganizer:
    """Organizes downloaded files into a clean folder structure.

    Each song gets its own folder containing all associated files:
    - audio (MP3/WAV)
    - video (MP4)
    - metadata (.txt, .json)
    - synced lyrics (.lrc)
    - cover art (.png)

    Multiple versions of the same song (same title) are stored in the
    same folder with version suffixes (_v2, _v3, etc.).
    """

    def organize_clip(
        self,
        clip: Any,
        base_dir: Path,
        version_number: Optional[int] = None,
    ) -> Dict[str, Path]:
        """Create the folder structure and return paths for a clip's files.

        Args:
            clip: A SunoClip instance.
            base_dir: Base output directory.
            version_number: Version suffix (2, 3, etc.) for same-title songs.
                          None means no suffix (first/only version).

        Returns:
            Dict mapping file type to full Path:
                - "folder": Song folder path
                - "mp3": MP3 audio path
                - "mp4": MP4 video path
                - "wav": WAV audio path
                - "txt": Metadata text path
                - "json": Metadata JSON path
                - "lrc": Synced lyrics path
                - "cover": Cover art path
        """
        title = getattr(clip, "title", None) or getattr(clip, "id", "Untitled")
        safe_title = sanitize_filename(title)

        # Build base filename with optional version suffix
        if version_number and version_number > 1:
            base_name = f"{safe_title}_v{version_number}"
        else:
            base_name = safe_title

        # Song folder is always named after the title (no version suffix)
        song_folder = base_dir / safe_title
        song_folder.mkdir(parents=True, exist_ok=True)

        paths = {
            "folder": song_folder,
            "mp3": song_folder / f"{base_name}.mp3",
            "mp4": song_folder / f"{base_name}.mp4",
            "wav": song_folder / f"{base_name}.wav",
            "txt": song_folder / f"{base_name}.txt",
            "json": song_folder / f"{base_name}.json",
            "lrc": song_folder / f"{base_name}.lrc",
            "cover": song_folder / f"{base_name}_cover.png",
        }

        logger.debug("Organized paths for '%s': %s", title, song_folder)
        return paths

    def organize_song_group(
        self,
        group: Any,
        base_dir: Path,
    ) -> List[Tuple[Any, Dict[str, Path]]]:
        """Organize all versions of a song into one folder.

        Args:
            group: A SongGroup instance.
            base_dir: Base output directory.

        Returns:
            List of (clip, paths_dict) tuples.
        """
        results = []
        clips = getattr(group, "clips", [])

        for idx, clip in enumerate(clips):
            version_num = (idx + 1) if len(clips) > 1 else None
            paths = self.organize_clip(clip, base_dir, version_number=version_num)
            results.append((clip, paths))

        return results

    def get_download_plan(
        self,
        clips: List[Any],
        base_dir: Path,
        download_mp3: bool = True,
        download_mp4: bool = False,
        download_wav: bool = False,
        download_cover: bool = True,
    ) -> List[Tuple[str, Path, Optional[Dict[str, str]], Optional[str]]]:
        """Build a flat download plan for the engine.

        Args:
            clips: List of SunoClip instances.
            base_dir: Base output directory.
            download_mp3: Whether to include MP3 downloads.
            download_mp4: Whether to include MP4 downloads.
            download_wav: Whether to include WAV downloads.
            download_cover: Whether to include cover art downloads.

        Returns:
            List of (url, dest_path, auth_headers_or_None, clip_id) tuples.
        """
        plan: List[Tuple[str, Path, Optional[Dict[str, str]], Optional[str]]] = []

        for clip in clips:
            paths = self.organize_clip(clip, base_dir)
            clip_id = clip.id

            if download_mp3:
                url = getattr(clip, "audio_url", None) or clip.cdn_mp3_url
                if url:
                    plan.append((url, paths["mp3"], None, clip_id))

            if download_mp4:
                url = getattr(clip, "video_url", None) or clip.cdn_mp4_url
                if url:
                    plan.append((url, paths["mp4"], None, clip_id))

            if download_cover:
                url = getattr(clip, "image_large_url", None) or getattr(clip, "image_url", None)
                if url:
                    plan.append((url, paths["cover"], None, clip_id))

            # WAV requires auth — handled separately in CLI

        return plan
