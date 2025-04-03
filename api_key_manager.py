import os
from dotenv import load_dotenv
import streamlit as st
from exceptions import ConfigurationError
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

class APIKeyManager:
    """Class to manage API keys with enhanced security"""
    
    def __init__(self):
        """Initialize the API key manager with encryption key"""
        self.encryption_key = self._get_encryption_key()
        self.cipher_suite = Fernet(self.encryption_key)
    
    def _get_encryption_key(self) -> bytes:
        """Generate or retrieve encryption key"""
        # Use a salt for key derivation
        salt = b'fixed_salt'  # In production, use a secure random salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        # Use a secret key for derivation
        secret_key = os.getenv('ENCRYPTION_SECRET', 'default_secret_key')
        return base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    
    def _encrypt_api_key(self, api_key: str) -> str:
        """Encrypt the API key"""
        return self.cipher_suite.encrypt(api_key.encode()).decode()
    
    def _decrypt_api_key(self, encrypted_key: str) -> str:
        """Decrypt the API key"""
        return self.cipher_suite.decrypt(encrypted_key.encode()).decode()
    
    def get_openai_api_key(self) -> str:
        """Get OpenAI API key from environment variables or session state"""
        try:
            # Load API key from environment variables
            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
            
            if not api_key:
                # Check API key in Streamlit session
                encrypted_key = st.session_state.get("openai_api_key")
                if encrypted_key:
                    api_key = self._decrypt_api_key(encrypted_key)
                else:
                    raise ConfigurationError("OpenAI API key is not set")
            
            return api_key
            
        except Exception as e:
            raise ConfigurationError(f"Failed to load API key: {str(e)}")
    
    def set_openai_api_key(self, api_key: str) -> None:
        """Set OpenAI API key in session state and environment"""
        try:
            # Encrypt the API key
            encrypted_key = self._encrypt_api_key(api_key)
            
            # Save encrypted API key to Streamlit session
            st.session_state["openai_api_key"] = encrypted_key
            
            # Save API key to environment variable (temporary)
            os.environ["OPENAI_API_KEY"] = api_key
            
        except Exception as e:
            raise ConfigurationError(f"Failed to set API key: {str(e)}")
    
    @staticmethod
    def validate_api_key(api_key: str) -> bool:
        """Validate the API key format"""
        if not api_key or not isinstance(api_key, str):
            return False
        
        # Validate API key format (should start with sk-)
        if not api_key.startswith("sk-"):
            return False
        
        return True

