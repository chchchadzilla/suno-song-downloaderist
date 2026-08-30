import logging
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, USLT, COMM, APIC, TLEN, TXXX
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    
logger = logging.getLogger(__name__)

class ID3Tagger:
    @staticmethod
    def tag_mp3(file_path: Path, clip: Dict[str, Any], cover_art_path: Optional[Path] = None) -> bool:
        if not MUTAGEN_AVAILABLE:
            logger.warning("Mutagen not installed. Cannot tag MP3.")
            return False
            
        if not file_path.exists():
            return False
            
        try:
            try:
                audio = MP3(file_path, ID3=ID3)
            except Exception:
                return False
                
            if audio.tags is None:
                audio.add_tags()
                
            tags = audio.tags
            assert tags is not None
            
            title = clip.get('title', 'Unknown')
            artist = clip.get('display_name', 'Suno AI')
            created_at = clip.get('created_at', '')
            year = created_at[:4] if created_at else ''
            
            metadata = clip.get('metadata', {})
            genre = metadata.get('tags', '')
            lyrics = metadata.get('lyrics', metadata.get('prompt', ''))
                
            clip_id = clip.get('id', '')
            model = clip.get('model_name', '')
            duration_ms = int(metadata.get('duration', 0) * 1000)

            tags.add(TIT2(encoding=3, text=[title]))
            tags.add(TPE1(encoding=3, text=[artist]))
            tags.add(TALB(encoding=3, text=["Suno AI Creations"]))
            if year:
                tags.add(TDRC(encoding=3, text=[year]))
            if genre:
                tags.add(TCON(encoding=3, text=[genre]))
            if lyrics:
                tags.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))
            if genre:
                tags.add(COMM(encoding=3, lang='eng', desc='', text=genre))
            if duration_ms > 0:
                tags.add(TLEN(encoding=3, text=[str(duration_ms)]))
                
            tags.add(TXXX(encoding=3, desc='suno_clip_id', text=[clip_id]))
            tags.add(TXXX(encoding=3, desc='suno_model', text=[model]))

            if cover_art_path and cover_art_path.exists():
                mime_type = "image/jpeg" if cover_art_path.suffix.lower() in [".jpg", ".jpeg"] else "image/png"
                with open(cover_art_path, "rb") as f:
                    image_data = f.read()
                tags.add(APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,
                    desc="Cover",
                    data=image_data
                ))

            audio.save()
            return True
            
        except Exception as e:
            logger.warning(f"Failed to tag {file_path}: {e}")
            return False

    @staticmethod
    def embed_cover_art(file_path: Path, image_path: Path) -> bool:
        if not MUTAGEN_AVAILABLE or not file_path.exists() or not image_path.exists():
            return False
            
        try:
            audio = MP3(file_path, ID3=ID3)
            if audio.tags is None:
                audio.add_tags()
                
            tags = audio.tags
            assert tags is not None
            
            mime_type = "image/jpeg" if image_path.suffix.lower() in [".jpg", ".jpeg"] else "image/png"
            with open(image_path, "rb") as f:
                image_data = f.read()
                
            tags.add(APIC(
                encoding=3,
                mime=mime_type,
                type=3,
                desc="Cover",
                data=image_data
            ))
            
            audio.save()
            return True
        except Exception as e:
            logger.warning(f"Failed to embed cover art for {file_path}: {e}")
            return False
