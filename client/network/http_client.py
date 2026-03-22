"""
HTTP Client Module

Async HTTP client using aiohttp with unified request handling,
automatic token management, and error handling.
"""
import asyncio
from typing import Any, Callable, Optional

import aiohttp

from client.core import logging
from client.core.config_backend import get_config
from client.core.exceptions import APIError, AuthExpiredError, NetworkError, ServerError
from client.core.logging import setup_logging

setup_logging()
logger = logging.get_logger(__name__)


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
        self._token_listeners: list[Callable[[Optional[str], Optional[str]], None]] = []

    @property
    def is_connected(self) -> bool:
        """Check if client session is active."""
        return self._session is not None and not self._session.closed

    @property
    def access_token(self) -> Optional[str]:
        """Return current access token."""
        return self._access_token

    @property
    def refresh_token(self) -> Optional[str]:
        """Return current refresh token."""
        return self._refresh_token

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    def set_tokens(self, access_token: Optional[str], refresh_token: Optional[str] = None) -> None:
        """
        Set authentication tokens.

        Args:
            access_token: JWT access token
            refresh_token: Optional refresh token
        """
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._notify_token_listeners()
        logger.debug("Tokens updated")

    def clear_tokens(self) -> None:
        """Clear authentication tokens."""
        self._access_token = None
        self._refresh_token = None
        self._notify_token_listeners()
        logger.debug("Tokens cleared")

    def add_token_listener(self, listener: Callable[[Optional[str], Optional[str]], None]) -> None:
        """Add a listener that will be called when auth tokens change."""
        if listener not in self._token_listeners:
            self._token_listeners.append(listener)

    def remove_token_listener(self, listener: Callable[[Optional[str], Optional[str]], None]) -> None:
        """Remove a token change listener."""
        if listener in self._token_listeners:
            self._token_listeners.remove(listener)

    def _notify_token_listeners(self) -> None:
        """Notify all token change listeners."""
        for listener in list(self._token_listeners):
            try:
                listener(self._access_token, self._refresh_token)
            except Exception:
                logger.exception("Token listener error")

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
                return await self._handle_response(response, retry_on_401, method, path, params, json, headers)

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
            path: str,
            params: Optional[dict[str, Any]],
            json: Optional[dict[str, Any]],
            headers: Optional[dict[str, str]],
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
                        method,
                        path,
                        params=params,
                        json=json,
                        headers=headers,
                        retry_on_401=False,
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
                        auth_data = data.get("data", {}) if isinstance(data, dict) else {}
                        self.set_tokens(
                            auth_data.get("access_token"),
                            auth_data.get("refresh_token", self._refresh_token),
                        )
                        logger.info("Token refreshed successfully")
                        return bool(self._access_token)
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
        self._session = None
        self._refreshing = False

    async def upload_file(
            self,
            file_path: str,
            upload_path: str = "/upload",
    ) -> Optional[dict]:
        """
        Upload a file to the server.

        Args:
            file_path: Path to the file to upload
            upload_path: API path for upload endpoint

        Returns:
            Response data with file URL, or None on failure
        """
        import os
        from aiohttp import FormData

        url = f"{self._base_url}{upload_path}"

        try:
            session = await self._ensure_session()

            with open(file_path, "rb") as file_obj:
                form = FormData()
                form.add_field(
                    "file",
                    file_obj,
                    filename=os.path.basename(file_path),
                    content_type=self._get_content_type(file_path),
                )

                headers = {}
                if self._access_token:
                    headers["Authorization"] = f"Bearer {self._access_token}"

                logger.info(f"Uploading file: {file_path}")

                async with session.post(
                        url,
                        data=form,
                        headers=headers,
                ) as response:
                    if response.status == 200 or response.status == 201:
                        data = await response.json()
                        if isinstance(data, dict) and "data" in data:
                            return data["data"]
                        return data

                    text = await response.text()
                    logger.error(f"Upload failed: {response.status} - {text}")
                    return None

        except Exception as e:
            logger.error(f"Upload error: {e}")
            return None

    def _get_content_type(self, file_path: str) -> str:
        """Get content type based on file extension."""
        import os
        ext = os.path.splitext(file_path)[1].lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        return content_types.get(ext, "application/octet-stream")


_http_client: Optional[HTTPClient] = None


def peek_http_client() -> Optional[HTTPClient]:
    """Return the existing HTTP client singleton if it was created."""
    return _http_client


def get_http_client() -> HTTPClient:
    """Get the global HTTP client instance."""
    global _http_client
    if _http_client is None:
        _http_client = HTTPClient()
    return _http_client
