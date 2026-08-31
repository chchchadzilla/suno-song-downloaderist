import json
from pathlib import Path
from typing import Any, Dict, Union

class MetadataWriter:
    @staticmethod
    def write_metadata_txt(clip: Any, dest_path: Path) -> None:
        if hasattr(clip, "model_dump"):
            clip_dict = clip.model_dump()
        elif isinstance(clip, dict):
            clip_dict = clip
        else:
            clip_dict = dict(clip)

        title = clip_dict.get('title') or 'Unknown'
        display_name = clip_dict.get('display_name') or 'Suno AI'
        
        metadata = clip_dict.get('metadata') or {}
        if hasattr(metadata, "model_dump"):
            metadata = metadata.model_dump()
        elif not isinstance(metadata, dict):
            metadata = {}

        duration = float(metadata.get('duration') or clip_dict.get('duration') or 0)
        mins = int(duration // 60)
        secs = int(duration % 60)
        duration_str = f"{mins}:{secs:02d}"
        
        created_at = str(clip_dict.get('created_at') or 'Unknown')
        model = clip_dict.get('model_name') or 'Unknown'
        clip_id = clip_dict.get('id') or 'Unknown'
        suno_url = f"https://suno.com/song/{clip_id}"
        play_count = clip_dict.get('play_count', 0)
        upvote_count = clip_dict.get('upvote_count', 0)
        
        tags = metadata.get('tags') or ''
        prompt = metadata.get('prompt') or ''
        lyrics = metadata.get('lyrics') or prompt
            
        gen_type = metadata.get('type') or clip_dict.get('type', 'gen')
        concat_history = metadata.get('concat_history') or []
        history_str = ", ".join(str(h) for h in concat_history) if concat_history else "(none)"
        continue_clip_id = metadata.get('continue_clip_id') or '(none)'
        
        content = f"""Title: {title}
Artist: {display_name}
Duration: {duration_str}
Created: {created_at}
Model: {model}
Suno URL: {suno_url}
Play Count: {play_count}
Liked: {"Yes" if upvote_count > 0 or clip_dict.get("is_liked") else "No"}

=== STYLE / GENRE PROMPT ===
{tags}

=== TAGS ===
{tags}

=== LYRICS ===
{lyrics}

=== GENERATION INFO ===
Type: {gen_type}
Clip ID: {clip_id}
Extended from: {continue_clip_id}
Concat history: {history_str}
"""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(content)

    @staticmethod
    def write_metadata_json(clip: Any, dest_path: Path) -> None:
        if hasattr(clip, "model_dump"):
            clip_dict = clip.model_dump()
        elif isinstance(clip, dict):
            clip_dict = clip
        else:
            clip_dict = dict(clip)

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            json.dump(clip_dict, f, indent=2, ensure_ascii=False, default=str)
