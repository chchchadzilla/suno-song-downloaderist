from pathlib import Path
from typing import Any, Dict, Optional

class LyricsWriter:
    @staticmethod
    def write_lrc(aligned_lyrics: Any, title: str, artist: str, dest_path: Path) -> None:
        lines = []
        lines.append(f"[ti:{title}]")
        lines.append(f"[ar:{artist}]")
        
        if hasattr(aligned_lyrics, "words"):
            for w in aligned_lyrics.words:
                start_sec = getattr(w, "start_ms", 0) / 1000.0
                text = getattr(w, "text", "")
                mins = int(start_sec // 60)
                secs = int(start_sec % 60)
                cs = int((start_sec % 1) * 100)
                lines.append(f"[{mins:02d}:{secs:02d}.{cs:02d}]{text}")
        elif isinstance(aligned_lyrics, dict) and 'lines' in aligned_lyrics:
            for line in aligned_lyrics['lines']:
                text = line.get('text', '')
                start_time = line.get('start_time', 0.0)
                mins = int(start_time // 60)
                secs = int(start_time % 60)
                ms = int((start_time - int(start_time)) * 100)
                lines.append(f"[{mins:02d}:{secs:02d}.{ms:02d}]{text}")
                
        if len(lines) > 2:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines))

    @staticmethod
    def write_plain_lyrics(clip: Any, dest_path: Path) -> None:
        if hasattr(clip, "model_dump"):
            clip_dict = clip.model_dump()
        elif isinstance(clip, dict):
            clip_dict = clip
        else:
            clip_dict = dict(clip)

        metadata = clip_dict.get('metadata') or {}
        if hasattr(metadata, "model_dump"):
            metadata = metadata.model_dump()
        elif not isinstance(metadata, dict):
            metadata = {}

        lyrics = metadata.get('lyrics') or metadata.get('prompt') or ''
        if not lyrics:
            return
            
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(lyrics)
