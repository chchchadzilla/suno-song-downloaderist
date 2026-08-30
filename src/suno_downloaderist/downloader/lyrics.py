from pathlib import Path
from typing import Any, Dict

class LyricsWriter:
    @staticmethod
    def write_lrc(aligned_lyrics: Dict[str, Any], title: str, artist: str, dest_path: Path) -> None:
        lines = []
        lines.append(f"[ti:{title}]")
        lines.append(f"[ar:{artist}]")
        
        if 'lines' in aligned_lyrics:
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
    def write_plain_lyrics(clip: Dict[str, Any], dest_path: Path) -> None:
        lyrics = clip.get('metadata', {}).get('prompt', '')
        if 'lyrics' in clip.get('metadata', {}):
            lyrics = clip['metadata']['lyrics']
            
        if not lyrics:
            return
            
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(lyrics)
