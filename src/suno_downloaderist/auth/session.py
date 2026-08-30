"""
Encrypted session persistence.
"""
import os
import json
import socket
import getpass
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from .browser import SessionData

logger = logging.getLogger(__name__)

class SessionManager:
    """Manages encrypted session persistence."""
    
    def __init__(self, directory: str = "~/.suno_downloaderist"):
        self.directory = Path(directory).expanduser()
        self.session_file = self.directory / "session.enc"
        self._key = self._generate_machine_key()
        self._fernet = Fernet(self._key)
        
        if not self.directory.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            
    def _generate_machine_key(self) -> bytes:
        """Generates a machine-specific encryption key based on hostname and username."""
        hostname = socket.gethostname()
        username = getpass.getuser()
        unique_string = f"{hostname}:{username}:suno_downloaderist_salt"
        # Generate a 32-byte hash and url-safe base64 encode it for Fernet
        hash_bytes = hashlib.sha256(unique_string.encode('utf-8')).digest()
        import base64
        return base64.urlsafe_b64encode(hash_bytes)

    def save_session(self, session_data: SessionData) -> None:
        """Encrypts and saves session data to file."""
        logger.info(f"Saving session to {self.session_file}")
        data = {
            "cookie": session_data.cookie,
            "session_id": session_data.session_id,
            "timestamp": session_data.timestamp,
            "user_agent": session_data.user_agent
        }
        json_data = json.dumps(data).encode('utf-8')
        encrypted_data = self._fernet.encrypt(json_data)
        
        with open(self.session_file, 'wb') as f:
            f.write(encrypted_data)

    def load_session(self) -> Optional[SessionData]:
        """Loads and decrypts session data, returns None if invalid."""
        if not self.session_file.exists():
            logger.debug("Session file does not exist.")
            return None
            
        try:
            with open(self.session_file, 'rb') as f:
                encrypted_data = f.read()
                
            decrypted_data = self._fernet.decrypt(encrypted_data)
            data = json.loads(decrypted_data.decode('utf-8'))
            
            session = SessionData(
                cookie=data["cookie"],
                session_id=data.get("session_id"),
                timestamp=data["timestamp"],
                user_agent=data["user_agent"]
            )
            
            if not self.is_session_valid(session):
                logger.info("Session expired, clearing.")
                self.clear_session()
                return None
                
            logger.info("Successfully loaded valid session.")
            return session
            
        except InvalidToken:
            logger.warning("Failed to decrypt session (possibly changed machine/user).")
            self.clear_session()
            return None
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None

    def clear_session(self) -> None:
        """Deletes the saved session file."""
        if self.session_file.exists():
            try:
                self.session_file.unlink()
                logger.info("Session cleared.")
            except Exception as e:
                logger.error(f"Failed to clear session: {e}")

    def is_session_valid(self, session: Optional[SessionData] = None) -> bool:
        """Checks if a session exists and hasn't expired (7 days)."""
        if session is None:
            if not self.session_file.exists():
                return False
            
            try:
                with open(self.session_file, 'rb') as f:
                    encrypted_data = f.read()
                decrypted_data = self._fernet.decrypt(encrypted_data)
                data = json.loads(decrypted_data.decode('utf-8'))
                timestamp = data["timestamp"]
            except Exception:
                return False
        else:
            timestamp = session.timestamp
            
        # 7 days expiration
        seven_days_seconds = 7 * 24 * 60 * 60
        current_time = time.time()
        
        return (current_time - timestamp) < seven_days_seconds
