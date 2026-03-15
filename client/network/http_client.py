"""
HTTP Client Module

Async HTTP client using aiohttp with unified request handling,
automatic token management, and error handling.
"""
import asyncio
import logging
from typing import Any, Optional

import aiohttp

from client.core.config import get_config
from client.core.exceptions import APIError, AuthExpiredError, NetworkError, ServerError


logger = logging.getLogger(__name__)


class HTTPClient:
    """
    Async HTTP client with token management and automatic error handling.
    
    All API requests should go through this client to ensure consistent
    error handling and token management.
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize HTTP client.
        
        Args:
            base_url: Base URL for API requests. Defaults to config server.api_base_url
            timeout: Request timeout in seconds
        """
        config = get_config()
        self._base_url = base_url or config.server.api_base_url
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_lock = asyncio.Lock()
        self._refreshing = False
    
    @property
    def is_connected(self) -> bool:
        """Check if client session is active."""
        return self._session is not None and not self._session.closed
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session
    
    def set_tokens(self, access_token: str, refresh_token: Optional[str] = None) -> None:
        """
        Set authentication tokens.
        
        Args:
            access_token: JWT access token
            refresh_token: Optional refresh token
        """
        self._access_token = access_token
        self._refresh_token = refresh_token
        logger.debug("Tokens updated")
    
    def clear_tokens(self) -> None:
        """Clear authentication tokens."""
        self._access_token = None
        self._refresh_token = None
        logger.debug("Tokens cleared")
    
    def _get_headers(self) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        retry_on_401: bool = True,
    ) -> Any:
        """
        Make an HTTP request with unified error handling.
        
        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            path: API path (will be appended to base_url)
            params: Query parameters
            json: JSON body
            headers: Additional headers
            retry_on_401: Whether to retry on 401 after token refresh
        
        Returns:
            Response data (the 'data' field from API response)
        
        Raises:
            NetworkError: For network-related errors
            AuthExpiredError: For 401 errors when token refresh fails
            ServerError: For 5xx server errors
            APIError: For other API errors
        """
        url = f"{self._base_url}{path}"
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)
        
        session = await self._ensure_session()
        
        try:
            logger.debug(f"{method} {url}")
            
            async with session.request(
                method,
                url,
                params=params,
                json=json,
                headers=request_headers,
            ) as response:
                return await self._handle_response(response, retry_on_401, method, url, params, json, request_headers)
        
        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise NetworkError(f"Request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Request timeout: {url}")
            raise NetworkError(f"Request timeout: {e}") from e
    
    async def _handle_response(
        self,
        response: aiohttp.ClientResponse,
        retry_on_401: bool,
        method: str,
        url: str,
        params: Optional[dict[str, Any]],
        json: Optional[dict[str, Any]],
        headers: dict[str, str],
    ) -> Any:
        """Handle HTTP response and errors."""
        status = response.status
        
        try:
            data = await response.json()
        except Exception:
            if status >= 400:
                text = await response.text()
                raise ServerError(
                    f"Server error: {status} - {text}",
                    status_code=status,
                )
            return None
        
        if status == 200 or status == 201:
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            return data
        
        if status == 401:
            if retry_on_401 and self._refresh_token:
                success = await self._refresh_access_token()
                if success:
                    return await self._request(
                        method, url, params, json, headers, retry_on_401=False
                    )
            
            raise AuthExpiredError(data.get("message", "Authentication failed"))
        
        if status >= 500:
            raise ServerError(
                data.get("message", "Server error"),
                status_code=status,
            )
        
        code = data.get("code", -1)
        message = data.get("message", "Unknown error")
        raise APIError(message, code=code, status_code=status)
    
    async def _refresh_access_token(self) -> bool:
        """
        Refresh access token using refresh token.
        
        Returns:
            True if refresh successful, False otherwise
        """
        async with self._token_lock:
            if self._refreshing:
                return False
            
            if not self._refresh_token:
                return False
            
            self._refreshing = True
            
            try:
                logger.info("Refreshing access token")
                
                session = await self._ensure_session()
                url = f"{self._base_url}/auth/refresh"
                
                async with session.post(
                    url,
                    json={"refresh_token": self._refresh_token},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        self._access_token = data.get("data", {}).get("access_token")
                        logger.info("Token refreshed successfully")
                        return True
                    else:
                        logger.warning("Token refresh failed")
                        self.clear_tokens()
                        return False
            
            except Exception as e:
                logger.error(f"Token refresh error: {e}")
                self.clear_tokens()
                return False
            
            finally:
                self._refreshing = False
    
    async def get(
        self,
        path: str,
        params: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """Make GET request."""
        return await self._request("GET", path, params=params, **kwargs)
    
    async def post(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """Make POST request."""
        return await self._request("POST", path, json=json, **kwargs)
    
    async def put(
        self,
        path: str,
        json: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> Any:
        """Make PUT request."""
        return await self._request("PUT", path, json=json, **kwargs)
    
    async def delete(
        self,
        path: str,
        **kwargs,
    ) -> Any:
        """Make DELETE request."""
        return await self._request("DELETE", path, **kwargs)
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("HTTP client session closed")


_http_client: Optional[HTTPClient] = None


def get_http_client() -> HTTPClient:
    """Get the global HTTP client instance."""
    global _http_client
    if _http_client is None:
        _http_client = HTTPClient()
    return _http_client
