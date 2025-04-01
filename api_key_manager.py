import os
from dotenv import load_dotenv
import streamlit as st
from exceptions import ConfigurationError

class APIKeyManager:
    """Class to manage API keys"""
    
    @staticmethod
    def get_openai_api_key() -> str:
        """Get OpenAI API key from environment variables or session state"""
        try:
            # Load API key from environment variables
            load_dotenv()
            api_key = os.getenv("OPENAI_API_KEY")
            
            if not api_key:
                # Check API key in Streamlit session
                api_key = st.session_state.get("openai_api_key")
                
                if not api_key:
                    raise ConfigurationError("OpenAI API key is not set")
            
            return api_key
            
        except Exception as e:
            raise ConfigurationError(f"Failed to load API key: {str(e)}")
    
    @staticmethod
    def set_openai_api_key(api_key: str) -> None:
        """Set OpenAI API key in session state and environment"""
        try:
            # Save API key to Streamlit session
            st.session_state["openai_api_key"] = api_key
            
            # Save API key to environment variable
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
