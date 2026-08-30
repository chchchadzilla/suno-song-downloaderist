import json
from pathlib import Path
from typing import Any, Dict

class MetadataWriter:
    @staticmethod
    def write_metadata_txt(clip: Dict[str, Any], dest_path: Path) -> None:
        title = clip.get('title', 'Unknown')
        display_name = clip.get('display_name', 'Suno AI')
        
        duration = clip.get('metadata', {}).get('duration', 0)
        mins = int(duration // 60)
        secs = int(duration % 60)
        duration_str = f"{mins}:{secs:02d}"
        
        created_at = clip.get('created_at', 'Unknown')
        model = clip.get('model_name', 'Unknown')
        clip_id = clip.get('id', 'Unknown')
        suno_url = f"https://suno.com/song/{clip_id}"
        play_count = clip.get('play_count', 0)
        upvote_count = clip.get('upvote_count', 0)
        
        tags = clip.get('metadata', {}).get('tags', '')
        prompt = clip.get('metadata', {}).get('prompt', '')
        
        lyrics = clip.get('metadata', {}).get('lyrics', prompt)
            
        gen_type = clip.get('type', 'gen')
        concat_history = clip.get('metadata', {}).get('concat_history', [])
        history_str = ", ".join(concat_history) if concat_history else "(none)"
        
        content = f"""Title: {title}
Artist: {display_name}
Duration: {duration_str}
Created: {created_at}
Model: {model}
Suno URL: {suno_url}
Play Count: {play_count}
Liked: {"Yes" if upvote_count > 0 else "No"}

=== STYLE / GENRE PROMPT ===
{tags}

=== TAGS ===
{tags}

=== LYRICS ===
{lyrics}

=== GENERATION INFO ===
Type: {gen_type}
Clip ID: {clip_id}
Extended from: {clip.get('metadata', {}).get('continue_clip_id', '(none)')}
Concat history: {history_str}
"""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(content)

    @staticmethod
    def write_metadata_json(clip: Dict[str, Any], dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            json.dump(clip, f, indent=2, ensure_ascii=False)
