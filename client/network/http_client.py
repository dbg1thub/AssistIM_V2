"""
HTTP Client Module

Async HTTP client using aiohttp with unified request handling,
automatic token management, and error handling.
"""
import asyncio
from typing import Any, AsyncIterator, Callable, Optional

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
        self._refresh_task: Optional[asyncio.Task[bool]] = None
        self._refresh_task_generation = 0
        self._token_generation = 0
        self._token_listeners: list[Callable[[Optional[str], Optional[str]], None]] = []
        self._auth_loss_listeners: list[Callable[[str], None]] = []

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
        self._token_generation += 1
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._notify_token_listeners()
        logger.debug("Tokens updated")

    def clear_tokens(self) -> None:
        """Clear authentication tokens."""
        self._token_generation += 1
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

    def add_auth_loss_listener(self, listener: Callable[[str], None]) -> None:
        """Subscribe to terminal auth-loss notifications."""
        if listener not in self._auth_loss_listeners:
            self._auth_loss_listeners.append(listener)

    def remove_auth_loss_listener(self, listener: Callable[[str], None]) -> None:
        """Remove an auth-loss listener."""
        if listener in self._auth_loss_listeners:
            self._auth_loss_listeners.remove(listener)

    def _notify_token_listeners(self) -> None:
        """Notify all token change listeners."""
        for listener in list(self._token_listeners):
            try:
                listener(self._access_token, self._refresh_token)
            except Exception:
                logger.exception("Token listener error")

    def _notify_auth_loss(self, reason: str) -> None:
        """Notify application-level auth state owner that credentials are no longer valid."""
        normalized_reason = str(reason or "").strip() or "auth_lost"
        for listener in list(self._auth_loss_listeners):
            try:
                listener(normalized_reason)
            except Exception:
                logger.exception("Auth-loss listener error")

    @staticmethod
    def _is_absolute_url(path: str) -> bool:
        """Return whether one request target is already a full URL."""
        return path.startswith("http://") or path.startswith("https://")

    def _resolve_url(self, path: str) -> str:
        """Resolve one relative API path or return one absolute URL unchanged."""
        if self._is_absolute_url(path):
            return path

        normalized_base = self._base_url.rstrip("/")
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{normalized_base}{normalized_path}"

    def _should_use_app_auth(self, path: str, use_auth: Optional[bool]) -> bool:
        """Decide whether one request should inherit the app auth state."""
        if use_auth is not None:
            return use_auth
        return not self._is_absolute_url(path)

    def _build_headers(
            self,
            *,
            include_auth: bool,
            extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        """Build request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if include_auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    async def _request(
            self,
            method: str,
            path: str,
            params: Optional[dict[str, Any]] = None,
            json: Optional[dict[str, Any]] = None,
            headers: Optional[dict[str, str]] = None,
            retry_on_401: bool = True,
            use_auth: Optional[bool] = None,
    ) -> Any:
        """
        Make an HTTP request with unified error handling.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            path: Relative API path or absolute URL
            params: Query parameters
            json: JSON body
            headers: Additional headers
            retry_on_401: Whether to retry on 401 after token refresh
            use_auth: Whether to apply app auth/refresh; defaults to True for relative paths only

        Returns:
            Response data (the 'data' field from API response)

        Raises:
            NetworkError: For network-related errors
            AuthExpiredError: For 401 errors when token refresh fails
            ServerError: For 5xx server errors
            APIError: For other API errors
        """
        url = self._resolve_url(path)
        apply_auth = self._should_use_app_auth(path, use_auth)
        request_headers = self._build_headers(
            include_auth=apply_auth,
            extra_headers=headers,
        )

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
                return await self._handle_response(
                    response,
                    retry_on_401,
                    method,
                    path,
                    params,
                    json,
                    headers,
                    use_auth=apply_auth,
                )

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise NetworkError(f"Request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Request timeout: {url}")
            raise NetworkError(f"Request timeout: {e}") from e

    async def _handle_binary_response(
            self,
            response: aiohttp.ClientResponse,
            retry_on_401: bool,
            path: str,
            headers: Optional[dict[str, str]],
            use_auth: bool,
    ) -> bytes:
        """Handle one binary download response using the standard client error model."""
        if response.status == 401:
            payload, response_text = await self._read_error_response_payload(response)
            if use_auth and retry_on_401 and self._refresh_token:
                success = await self._refresh_access_token()
                if success:
                    return await self.download_bytes(
                        path,
                        headers=headers,
                        retry_on_401=False,
                        use_auth=use_auth,
                    )

            message = self._error_message_from_payload(
                payload,
                response_text,
                fallback="Authentication failed" if use_auth else "Unauthorized",
            )
            if use_auth:
                raise AuthExpiredError(message)
            raise APIError(
                message,
                code=self._error_code_from_payload(payload),
                status_code=response.status,
            )

        if response.status >= 400:
            payload, response_text = await self._read_error_response_payload(response)
            if response.status >= 500:
                raise ServerError(
                    self._error_message_from_payload(payload, response_text, fallback="Server error"),
                    status_code=response.status,
                )
            raise APIError(
                self._error_message_from_payload(
                    payload,
                    response_text,
                    fallback=f"Request failed ({response.status})",
                ),
                code=self._error_code_from_payload(payload),
                status_code=response.status,
            )

        return await response.read()

    async def _handle_response(
            self,
            response: aiohttp.ClientResponse,
            retry_on_401: bool,
            method: str,
            path: str,
            params: Optional[dict[str, Any]],
            json: Optional[dict[str, Any]],
            headers: Optional[dict[str, str]],
            use_auth: bool,
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
            if use_auth and retry_on_401 and self._refresh_token:
                success = await self._refresh_access_token()
                if success:
                    return await self._request(
                        method,
                        path,
                        params=params,
                        json=json,
                        headers=headers,
                        retry_on_401=False,
                        use_auth=use_auth,
                    )

            if use_auth:
                raise AuthExpiredError(data.get("message", "Authentication failed"))

            raise APIError(
                data.get("message", "Unauthorized"),
                code=data.get("code"),
                status_code=status,
            )

        if status >= 500:
            raise ServerError(
                data.get("message", "Server error"),
                status_code=status,
            )

        code = data.get("code", -1)
        message = data.get("message", "Unknown error")
        raise APIError(message, code=code, status_code=status)

    @staticmethod
    def _error_message_from_payload(payload: Any, response_text: str, *, fallback: str) -> str:
        """Return one normalized API error message."""
        if isinstance(payload, dict):
            return str(payload.get("message", fallback) or fallback)
        if response_text:
            return response_text
        return fallback

    @staticmethod
    def _error_code_from_payload(payload: Any) -> int | None:
        """Return one normalized API error code."""
        if not isinstance(payload, dict):
            return None
        code = payload.get("code")
        try:
            return int(code) if code is not None else None
        except (TypeError, ValueError):
            return None

    async def _read_error_response_payload(self, response: aiohttp.ClientResponse) -> tuple[Any, str]:
        """Read one error response body as JSON when possible, falling back to text."""
        try:
            payload = await response.json()
            return payload, ""
        except Exception:
            return None, await response.text()

    async def stream_lines(
            self,
            method: str,
            path: str,
            params: Optional[dict[str, Any]] = None,
            json: Optional[dict[str, Any]] = None,
            headers: Optional[dict[str, str]] = None,
            retry_on_401: bool = True,
            use_auth: Optional[bool] = None,
    ) -> AsyncIterator[str]:
        """Yield decoded non-empty lines from one streaming HTTP response."""
        url = self._resolve_url(path)
        apply_auth = self._should_use_app_auth(path, use_auth)
        request_headers = self._build_headers(
            include_auth=apply_auth,
            extra_headers=headers,
        )
        session = await self._ensure_session()

        try:
            logger.debug(f"{method} {url} (stream)")

            async with session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=request_headers,
            ) as response:
                if response.status == 401:
                    payload, response_text = await self._read_error_response_payload(response)
                    if apply_auth and retry_on_401 and self._refresh_token:
                        success = await self._refresh_access_token()
                        if success:
                            async for line in self.stream_lines(
                                method,
                                path,
                                params=params,
                                json=json,
                                headers=headers,
                                retry_on_401=False,
                                use_auth=apply_auth,
                            ):
                                yield line
                            return

                    message = self._error_message_from_payload(
                        payload,
                        response_text,
                        fallback="Authentication failed" if apply_auth else "Unauthorized",
                    )
                    if apply_auth:
                        raise AuthExpiredError(message)
                    raise APIError(
                        message,
                        code=self._error_code_from_payload(payload),
                        status_code=response.status,
                    )

                if response.status >= 400:
                    payload, response_text = await self._read_error_response_payload(response)
                    if response.status >= 500:
                        raise ServerError(
                            self._error_message_from_payload(payload, response_text, fallback="Server error"),
                            status_code=response.status,
                        )
                    raise APIError(
                        self._error_message_from_payload(
                            payload,
                            response_text,
                            fallback=f"Request failed ({response.status})",
                        ),
                        code=self._error_code_from_payload(payload),
                        status_code=response.status,
                    )

                async for raw_line in response.content:
                    line = raw_line.decode("utf-8").strip()
                    if line:
                        yield line

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise NetworkError(f"Request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Request timeout: {url}")
            raise NetworkError(f"Request timeout: {e}") from e
    async def _handle_upload_response(
            self,
            response: aiohttp.ClientResponse,
            *,
            file_path: str,
            upload_path: str,
            use_auth: bool,
            retry_on_401: bool,
    ) -> dict[str, Any]:
        """Handle multipart upload responses using the standard client error model."""
        status = response.status
        payload: Any = None
        response_text = ""

        try:
            payload = await response.json()
        except Exception:
            response_text = await response.text()

        if status == 200 or status == 201:
            if isinstance(payload, dict) and "data" in payload:
                payload = payload["data"]
            if isinstance(payload, dict):
                return payload
            raise ServerError("Upload response must be a JSON object", status_code=status)

        if status == 401:
            if use_auth and retry_on_401 and self._refresh_token:
                success = await self._refresh_access_token()
                if success:
                    return await self.upload_file(
                        file_path,
                        upload_path=upload_path,
                        use_auth=use_auth,
                    )

            message = self._error_message_from_payload(payload, response_text, fallback="Authentication failed")
            if use_auth:
                raise AuthExpiredError(message)
            raise APIError(
                message,
                code=self._error_code_from_payload(payload),
                status_code=status,
            )

        if status >= 500:
            raise ServerError(
                self._error_message_from_payload(payload, response_text, fallback="Server error"),
                status_code=status,
            )

        raise APIError(
            self._error_message_from_payload(payload, response_text, fallback=f"Upload failed ({status})"),
            code=self._error_code_from_payload(payload),
            status_code=status,
        )

    async def _refresh_access_token(self) -> bool:
        """
        Refresh access token using one single-flight task.

        Returns:
            True if refresh successful, False otherwise
        """
        async with self._token_lock:
            if not self._refresh_token:
                return False

            refresh_token = self._refresh_token
            token_generation = self._token_generation
            refresh_task = self._refresh_task
            if (
                    refresh_task is None
                    or refresh_task.done()
                    or self._refresh_task_generation != token_generation
            ):
                refresh_task = asyncio.create_task(
                    self._perform_token_refresh(refresh_token, token_generation)
                )
                self._refresh_task = refresh_task
                self._refresh_task_generation = token_generation

        try:
            return await refresh_task
        finally:
            async with self._token_lock:
                if self._refresh_task is refresh_task and refresh_task.done():
                    self._refresh_task = None
                    self._refresh_task_generation = 0

    def _is_refresh_context_current(self, refresh_token: str, token_generation: int) -> bool:
        """Return whether one refresh result still belongs to the current auth generation."""
        return (
            token_generation == self._token_generation
            and refresh_token == self._refresh_token
        )

    async def _perform_token_refresh(self, refresh_token: str, token_generation: int) -> bool:
        """Execute one refresh HTTP call and update in-memory tokens."""
        if not refresh_token:
            return False

        try:
            logger.info("Refreshing access token")

            session = await self._ensure_session()
            url = self._resolve_url("/auth/refresh")

            async with session.post(
                    url,
                    json={"refresh_token": refresh_token},
                    headers={"Content-Type": "application/json"},
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    auth_data = data.get("data", {}) if isinstance(data, dict) else {}
                    if not self._is_refresh_context_current(refresh_token, token_generation):
                        logger.info("Ignoring stale token refresh result")
                        return False
                    self.set_tokens(
                        auth_data.get("access_token"),
                        auth_data.get("refresh_token", refresh_token),
                    )
                    logger.info("Token refreshed successfully")
                    return bool(self._access_token)

                logger.warning("Token refresh failed")
                if not self._is_refresh_context_current(refresh_token, token_generation):
                    logger.info("Ignoring stale token refresh failure")
                    return False
                self.clear_tokens()
                self._notify_auth_loss("refresh_rejected")
                return False

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False

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

    async def patch(
            self,
            path: str,
            json: Optional[dict[str, Any]] = None,
            **kwargs,
    ) -> Any:
        """Make PATCH request."""
        return await self._request("PATCH", path, json=json, **kwargs)

    async def delete(
            self,
            path: str,
            **kwargs,
    ) -> Any:
        """Make DELETE request."""
        return await self._request("DELETE", path, **kwargs)

    async def download_bytes(
            self,
            path: str,
            *,
            headers: Optional[dict[str, str]] = None,
            retry_on_401: bool = True,
            use_auth: Optional[bool] = None,
    ) -> bytes:
        """Download one binary payload from an internal or absolute URL."""
        url = self._resolve_url(path)
        apply_auth = self._should_use_app_auth(path, use_auth)
        request_headers = {"Accept": "*/*"}
        if apply_auth and self._access_token:
            request_headers["Authorization"] = f"Bearer {self._access_token}"
        if headers:
            request_headers.update(headers)

        session = await self._ensure_session()

        try:
            logger.debug(f"GET {url} (binary)")

            async with session.request(
                    "GET",
                    url,
                    headers=request_headers,
            ) as response:
                return await self._handle_binary_response(
                    response,
                    retry_on_401,
                    path,
                    headers,
                    apply_auth,
                )

        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            raise NetworkError(f"Request failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Request timeout: {url}")
            raise NetworkError(f"Request timeout: {e}") from e

    async def close(self) -> None:
        """Close the HTTP session."""
        refresh_task = self._refresh_task
        self._refresh_task = None
        if refresh_task and not refresh_task.done():
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
            logger.debug("HTTP client session closed")
        self._session = None
        self._auth_loss_listeners.clear()

    async def upload_file(
            self,
            file_path: str,
            upload_path: str = "/files/upload",
            use_auth: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Upload one file using the same structured error model as normal HTTP requests."""
        import os
        from aiohttp import FormData

        if not file_path:
            raise APIError("file path required")

        url = self._resolve_url(upload_path)
        apply_auth = self._should_use_app_auth(upload_path, use_auth)

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

                headers = {"Accept": "application/json"}
                if apply_auth and self._access_token:
                    headers["Authorization"] = f"Bearer {self._access_token}"

                logger.info(f"Uploading file: {file_path}")

                async with session.post(
                        url,
                        data=form,
                        headers=headers,
                ) as response:
                    return await self._handle_upload_response(
                        response,
                        file_path=file_path,
                        upload_path=upload_path,
                        use_auth=apply_auth,
                        retry_on_401=True,
                    )

        except FileNotFoundError as e:
            logger.error(f"Upload file not found: {file_path}")
            raise APIError(f"file not found: {file_path}") from e
        except OSError as e:
            logger.error(f"Upload file error: {e}")
            raise APIError(f"file upload failed: {e}") from e
        except (APIError, AuthExpiredError, NetworkError, ServerError):
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Upload network error: {e}")
            raise NetworkError(f"Upload failed: {e}") from e
        except asyncio.TimeoutError as e:
            logger.error(f"Upload timeout: {url}")
            raise NetworkError(f"Upload timeout: {e}") from e

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
