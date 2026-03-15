"""
Exception Definitions

Custom exceptions for the application.
"""
from typing import Any, Optional


class AppError(Exception):
    """Base exception for all application errors."""
    
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class APIError(AppError):
    """Exception for API-related errors."""
    
    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        status_code: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, details)
        self.code = code
        self.status_code = status_code


class NetworkError(APIError):
    """Exception for network-related errors."""
    
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, code=-1, status_code=None, details=details)


class AuthError(APIError):
    """Exception for authentication errors."""
    
    def __init__(self, message: str, details: Optional[dict[str, Any]] = None):
        super().__init__(message, code=401, status_code=401, details=details)


class AuthExpiredError(AuthError):
    """Exception for expired authentication tokens."""
    
    def __init__(self, message: str = "Authentication token expired"):
        super().__init__(message, details={"reason": "token_expired"})


class ServerError(APIError):
    """Exception for server errors."""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(message, code=-1, status_code=status_code, details=details)


class ValidationError(AppError):
    """Exception for validation errors."""
    
    def __init__(self, message: str, field: Optional[str] = None):
        details = {"field": field} if field else {}
        super().__init__(message, details)
        self.field = field
