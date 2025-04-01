import os
import streamlit as st
from exceptions import ConfigurationError

class APIKeyManager:
    """API 키 관리를 위한 클래스"""
    
    @staticmethod
    def get_openai_api_key() -> str:
        """Get OpenAI API key from environment variables or Streamlit secrets"""
        # First try to get from Streamlit secrets
        try:
            if st.secrets.get("OPENAI_API_KEY"):
                return st.secrets["OPENAI_API_KEY"]
        except:
            pass
            
        # Then try to get from environment variables
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ConfigurationError(
                "OpenAI API key is not set. Please set the OPENAI_API_KEY in one of the following ways:\n"
                "1. For local development: Create a .env file with OPENAI_API_KEY=your-key\n"
                "2. For Streamlit Cloud: Add OPENAI_API_KEY in the app's secrets management\n"
                "3. Set as environment variable: export OPENAI_API_KEY=your-key"
            )
        return api_key 
