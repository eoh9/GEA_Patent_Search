class ConfigurationError(Exception):
    """Exception for configuration-related errors"""
    pass

class PatentAnalysisError(Exception):
    """Exception for patent analysis-related errors"""
    pass

class APIError(Exception):
    """Exception for API call-related errors"""
    pass

class ValidationError(Exception):
    """Exception for data validation-related errors"""
    pass 
