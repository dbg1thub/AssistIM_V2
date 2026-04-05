"""
AssistIM Desktop Client
Application entry point
"""

import sys
import asyncio
import argparse
import os
from pathlib import Path

if __package__ in {None, ""}:
    workspace_root = Path(__file__).resolve().parents[1]
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop
from qfluentwidgets import InfoBar, setTheme, setThemeColor

from client.core import logging
from client.core.config_backend import get_config
from client.core.config import cfg
from client.core.i18n import initialize_i18n, tr
from client.core.logging import setup_logging
from client.storage.database import get_database, peek_database
from client.network.http_client import get_http_client, peek_http_client
from client.network.websocket_client import get_websocket_client, peek_websocket_client

from client.managers.connection_manager import get_connection_manager, peek_connection_manager
from client.managers.message_manager import get_message_manager, peek_message_manager
from client.managers.session_manager import get_session_manager, peek_session_manager
from client.managers.sound_manager import get_sound_manager, peek_sound_manager

from client.ui.controllers.auth_controller import get_auth_controller, peek_auth_controller
from client.ui.controllers.chat_controller import get_chat_controller, peek_chat_controller
from client.ui.controllers.message_controller import peek_message_controller
from client.ui.controllers.session_controller import peek_session_controller
from client.ui.windows.auth_interface import AuthInterface
setup_logging()
logger = logging.get_logger(__name__)

EXIT_CODE_OK = 0
EXIT_CODE_SINGLE_INSTANCE = 1
EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED = 2


def _sanitize_profile_name(profile: str) -> str:
    """Normalize a runtime profile name for file-system usage."""
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in profile.strip())
    return cleaned or "default"


def _parse_runtime_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse runtime options while leaving unknown arguments for Qt."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--profile", default=os.getenv("ASSISTIM_PROFILE", "").strip())
    return parser.parse_known_args(argv[1:])


def _configure_runtime_profile(profile: str) -> str:
    """Configure an isolated data path for a named runtime profile."""
    normalized = _sanitize_profile_name(profile)

    base_path = Path(os.getenv("ASSISTIM_DB_PATH", "data/assistim.db")).expanduser()
    suffix = "".join(base_path.suffixes)
    stem = base_path.name[:-len(suffix)] if suffix else base_path.name
    profiled_name = f"{stem}.{normalized}{suffix or '.db'}"
    profiled_path = str((base_path.parent / profiled_name).resolve())

    os.environ["ASSISTIM_PROFILE"] = normalized
    os.environ["ASSISTIM_DB_PATH"] = profiled_path

    return normalized


def _acquire_instance_lock(profile: str = "") -> QLockFile | None:
    """Prevent multiple AssistIM desktop instances from running simultaneously."""
    config = get_config()
    lock_dir = Path(config.storage.db_path).expanduser().resolve().parent
    lock_dir.mkdir(parents=True, exist_ok=True)

    suffix = f".{_sanitize_profile_name(profile)}" if profile else ""
    lock = QLockFile(str(lock_dir / f"assistim{suffix}.instance.lock"))
    lock.setStaleLockTime(5000)

    if lock.tryLock(100):
        return lock

    return None


def _show_startup_preflight_block_dialog(preflight: dict) -> None:
    """Show one user-facing dialog for a blocking startup preflight failure."""
    state = str(preflight.get("state", "unknown") or "unknown")
    message = str(preflight.get("message", "") or "").strip()
    body = tr(
        "main.startup_preflight_blocked.message",
        "AssistIM could not start because one startup safety check failed.",
    )
    if message:
        body = f"{body}\n\n[{state}] {message}"
    else:
        body = f"{body}\n\n[{state}]"
    QMessageBox.information(
        None,
        tr("main.startup_preflight_blocked.title", "Startup blocked"),
        body,
    )


class Application:
    """
    Main application class that manages the client lifecycle.

    Responsible for initializing components, managing background services,
    and handling application shutdown.
    """

    def __init__(self, qt_app: QApplication) -> None:

        self.qt_app = qt_app

        self._quit_event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._logout_task: asyncio.Task | None = None
        self._forced_logout_in_progress = False
        self._pending_auth_success_message = ""
        self._exit_code = EXIT_CODE_OK
        self._startup_security_status = {
            "authenticated": False,
            "user_id": "",
            "database_encryption": {
                "state": "unknown",
                "severity": "info",
                "can_start": True,
                "action_required": False,
                "message": "Local database encryption status is unavailable",
            },
        }
        self._e2ee_runtime_diagnostics = {
            "authenticated": False,
            "user_id": "",
            "runtime_security": {
                "authenticated": False,
                "user_id": "",
                "database_encryption": {
                    "state": "unknown",
                    "severity": "info",
                    "can_start": True,
                    "action_required": False,
                    "message": "Local database encryption status is unavailable",
                },
            },
            "history_recovery": {
                "available": False,
                "source_device_count": 0,
            },
            "current_session_security": {
                "available": False,
                "reason": "authentication required",
            },
        }

        self.main_window = None
        self.auth_window = None
    # =========================================================
    # Task helper
    # =========================================================

    def create_task(self, coro) -> asyncio.Task:
        """
        Create and track an asyncio task.

        Args:
            coro: Coroutine to execute.

        Returns:
            The created task.
        """
        task = asyncio.create_task(coro)

        def _done(t: asyncio.Task) -> None:
            self._tasks.discard(t)
            try:
                t.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Background task crashed")

        task.add_done_callback(_done)

        self._tasks.add(task)

        return task

    async def _yield_to_ui(self) -> None:
        """Yield back to qasync without re-entering Qt's event pump manually."""
        await asyncio.sleep(0)

    def get_startup_security_status(self) -> dict:
        """Expose one stable startup/runtime security snapshot for diagnostics and UI handoff."""
        database_encryption = dict(self._startup_security_status.get("database_encryption") or {})
        return {
            "authenticated": bool(self._startup_security_status.get("authenticated")),
            "user_id": str(self._startup_security_status.get("user_id", "") or ""),
            "database_encryption": database_encryption,
        }

    def get_startup_preflight_result(self) -> dict:
        """Return one normalized startup preflight result derived from cached runtime security state."""
        security_status = self.get_startup_security_status()
        database_encryption = dict(security_status.get("database_encryption") or {})
        can_continue = bool(database_encryption.get("can_start", True))
        return {
            "can_continue": can_continue,
            "blocking": not can_continue,
            "action_required": bool(database_encryption.get("action_required")),
            "state": str(database_encryption.get("state", "unknown") or "unknown"),
            "severity": str(database_encryption.get("severity", "info") or "info"),
            "message": str(database_encryption.get("message", "") or ""),
            "runtime_security": security_status,
        }

    def get_e2ee_runtime_diagnostics(self) -> dict:
        """Expose one stable application-level E2EE runtime diagnostics snapshot."""
        return {
            "authenticated": bool(self._e2ee_runtime_diagnostics.get("authenticated")),
            "user_id": str(self._e2ee_runtime_diagnostics.get("user_id", "") or ""),
            "runtime_security": dict(self._e2ee_runtime_diagnostics.get("runtime_security") or {}),
            "history_recovery": dict(self._e2ee_runtime_diagnostics.get("history_recovery") or {}),
            "current_session_security": dict(self._e2ee_runtime_diagnostics.get("current_session_security") or {}),
        }

    def get_exit_code(self) -> int:
        """Expose the current application exit code for outer launchers and tests."""
        return int(self._exit_code)

    def _update_startup_security_status(self, *, db=None, auth_controller=None) -> dict:
        """Refresh the cached startup security status from the best available runtime source."""
        current = self.get_startup_security_status()
        database_encryption = dict(current.get("database_encryption") or {})

        if db is not None:
            db_self_check_getter = getattr(db, "get_db_encryption_self_check", None)
            if callable(db_self_check_getter):
                database_encryption = dict(db_self_check_getter() or {})

        if auth_controller is not None:
            runtime_status_getter = getattr(auth_controller, "get_runtime_security_status", None)
            if callable(runtime_status_getter):
                runtime_status = dict(runtime_status_getter() or {})
                database_encryption = dict(runtime_status.get("database_encryption") or database_encryption)
                self._startup_security_status = {
                    "authenticated": bool(runtime_status.get("authenticated")),
                    "user_id": str(runtime_status.get("user_id", "") or ""),
                    "database_encryption": database_encryption,
                }
                return self.get_startup_security_status()

        self._startup_security_status = {
            "authenticated": bool(current.get("authenticated")),
            "user_id": str(current.get("user_id", "") or ""),
            "database_encryption": database_encryption,
        }
        return self.get_startup_security_status()

    async def _update_e2ee_runtime_diagnostics(self, *, auth_controller=None) -> dict:
        """Refresh the cached application-level E2EE diagnostics from the auth controller when available."""
        current = self.get_e2ee_runtime_diagnostics()
        if auth_controller is not None:
            diagnostics_getter = getattr(auth_controller, "get_e2ee_diagnostics", None)
            if callable(diagnostics_getter):
                try:
                    diagnostics = dict(await diagnostics_getter() or {})
                except Exception:
                    diagnostics = {}
                if diagnostics:
                    self._e2ee_runtime_diagnostics = {
                        "authenticated": bool(diagnostics.get("authenticated")),
                        "user_id": str(diagnostics.get("user_id", "") or ""),
                        "runtime_security": dict(diagnostics.get("runtime_security") or {}),
                        "history_recovery": dict(diagnostics.get("history_recovery") or {}),
                        "current_session_security": dict(diagnostics.get("current_session_security") or {}),
                    }
                    return self.get_e2ee_runtime_diagnostics()
        self._e2ee_runtime_diagnostics = {
            "authenticated": bool(current.get("authenticated")),
            "user_id": str(current.get("user_id", "") or ""),
            "runtime_security": dict(current.get("runtime_security") or {}),
            "history_recovery": dict(current.get("history_recovery") or {}),
            "current_session_security": dict(current.get("current_session_security") or {}),
        }
        return self.get_e2ee_runtime_diagnostics()

    # =========================================================
    # Initialization
    # =========================================================

    async def initialize(self) -> None:
        """
        Initialize all application components.

        Initializes database, HTTP client, WebSocket client, and all managers
        in the correct order.
        """

        logger.info("Initializing database...")
        db = get_database()
        await db.connect()
        self._update_startup_security_status(db=db)
        self._e2ee_runtime_diagnostics = {
            "authenticated": False,
            "user_id": "",
            "runtime_security": self.get_startup_security_status(),
            "history_recovery": {
                "available": False,
                "source_device_count": 0,
            },
            "current_session_security": {
                "available": False,
                "reason": "authentication required",
            },
        }
        db_security = self.get_startup_preflight_result().get("runtime_security", {}).get("database_encryption", {})
        if db_security.get("action_required"):
            logger.warning(
                "Local DB encryption self-check: %s (%s)",
                db_security.get("state"),
                db_security.get("message"),
            )
        else:
            logger.info(
                "Local DB encryption self-check: %s (%s)",
                db_security.get("state"),
                db_security.get("message"),
            )

        logger.info("Initializing HTTP client...")
        get_http_client()

        logger.info("Initializing WebSocket client...")
        get_websocket_client()

        logger.info("Initializing connection manager...")
        conn_manager = get_connection_manager()
        await conn_manager.initialize()
        conn_manager.add_message_listener(self._handle_transport_message)

        logger.info("Initializing message manager...")
        msg_manager = get_message_manager()
        await msg_manager.initialize()

        logger.info("Initializing session manager...")
        session_manager = get_session_manager()
        await session_manager.initialize()

        logger.info("Initializing chat controller...")
        chat_controller = get_chat_controller()
        await chat_controller.initialize()

        logger.info("Initializing sound manager...")
        sound_manager = get_sound_manager()
        await sound_manager.initialize()

        logger.info("Application initialized")

    # =========================================================
    # UI
    # =========================================================

    async def authenticate(self) -> bool:
        """
        Restore an existing session or present the auth interface.

        Returns:
            True when the user is authenticated, False when auth was cancelled.
        """

        auth_controller = get_auth_controller()
        restored_user = await auth_controller.restore_session()
        self._update_startup_security_status(auth_controller=auth_controller)
        await self._update_e2ee_runtime_diagnostics(auth_controller=auth_controller)
        if restored_user:
            logger.info("Restored persisted session for user %s", restored_user.get("id"))
            return True

        loop = asyncio.get_running_loop()
        auth_future: asyncio.Future[bool] = loop.create_future()

        self.auth_window = AuthInterface()

        def _on_authenticated(_user: dict) -> None:
            if self.auth_window is not None:
                self._pending_auth_success_message = str(getattr(self.auth_window, "last_success_message", "") or "")
            if not auth_future.done():
                auth_future.set_result(True)

        def _on_closed() -> None:
            if not auth_future.done():
                auth_future.set_result(False)

        self.auth_window.authenticated.connect(_on_authenticated)
        self.auth_window.closed.connect(_on_closed)
        self.auth_window.show()
        self.auth_window.raise_()
        self.auth_window.activateWindow()

        authenticated = await auth_future

        if self.auth_window:
            self.auth_window.deleteLater()
            self.auth_window = None
            await self._yield_to_ui()

        if not authenticated:
            logger.info("Authentication window closed before sign-in")
            return False

        self._update_startup_security_status(auth_controller=auth_controller)
        await self._update_e2ee_runtime_diagnostics(auth_controller=auth_controller)

        return True

    async def _synchronize_authenticated_runtime(self) -> None:
        """Reload per-user runtime state after authentication succeeds."""
        conn_manager = get_connection_manager()
        await conn_manager.reload_sync_timestamp()
        await self._yield_to_ui()

        session_manager = get_session_manager()
        await session_manager.refresh_remote_sessions()
        await self._yield_to_ui()

    async def _warm_authenticated_runtime(self) -> None:
        """Refresh authenticated runtime state after the main shell is already visible."""
        try:
            await self._synchronize_authenticated_runtime()
            await self.start_background_services()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Authenticated runtime warmup failed")
            return

        if self.main_window is None:
            return

        self.main_window.chat_interface.load_sessions()

    async def show_main_window(self) -> None:
        """
        Create and display the main application window.
        """

        from client.ui.windows.main_window import MainWindow

        self.main_window = MainWindow()
        self.main_window.closed.connect(self._on_main_window_closed)
        self.main_window.logoutRequested.connect(self._on_logout_requested)
        self.main_window.restore_default_geometry()
        self.main_window.show()
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.activateWindow()
        if self._pending_auth_success_message:
            InfoBar.success(
                tr("auth.feedback.title", "Authentication"),
                self._pending_auth_success_message,
                parent=self.main_window,
                duration=1800,
            )
            self._pending_auth_success_message = ""
        QTimer.singleShot(0, self.main_window.raise_)
        QTimer.singleShot(0, self.main_window.activateWindow)
        QTimer.singleShot(80, self.main_window.raise_)
        QTimer.singleShot(80, self.main_window.activateWindow)
        await self._yield_to_ui()
        self.create_task(self._warm_authenticated_runtime())

        logger.info("Main window displayed")

    def _on_main_window_closed(self) -> None:
        """
        Handle main window close event.
        """

        logger.info("Main window closed")

        self._quit_event.set()

    def _on_logout_requested(self) -> None:
        """Start the sign-out flow from the account page."""
        if self._logout_task is not None and not self._logout_task.done():
            return

        self._logout_task = self.create_task(self._perform_logout_flow())
        self._logout_task.add_done_callback(self._clear_logout_task)

    def _clear_logout_task(self, task: asyncio.Task) -> None:
        """Drop logout bookkeeping after the flow finishes."""
        if self._logout_task is task:
            self._logout_task = None


    async def _handle_transport_message(self, message: dict) -> None:
        """Handle raw websocket control messages that should bypass the normal message manager."""
        if not isinstance(message, dict) or message.get("type") != "force_logout":
            return

        reason = str((message.get("data") or {}).get("reason", "") or "")
        if reason != "session_replaced":
            return
        if self._forced_logout_in_progress:
            return

        self._forced_logout_in_progress = True
        logger.warning("Session replaced by another client login")

        try:
            auth_controller = get_auth_controller()
            await auth_controller.clear_session()
        except Exception:
            logger.exception("Failed to clear auth state after forced logout")

        try:
            conn_manager = peek_connection_manager()
            if conn_manager is not None:
                await conn_manager.close()
        except Exception:
            logger.exception("Failed to close connection manager after forced logout")

        if self.main_window is not None:
            self.main_window.show_session_replaced_warning()
            return

        if self.auth_window is not None:
            self.auth_window.close()
            self.auth_window.deleteLater()
            self.auth_window = None

        self._quit_event.set()

    # =========================================================
    # Background services
    # =========================================================

    async def start_background_services(self) -> None:
        """
        Start all background services.

        Starts connection manager and other background tasks.
        """

        logger.info("Starting background services...")

        conn_manager = get_connection_manager()
        try:
            await conn_manager.connect()
        except Exception:
            logger.exception("Initial websocket connect failed")

        logger.info("Background services started")

    async def _perform_logout_flow(self) -> None:
        """Sign out the current user, reset authenticated runtime state, and reopen auth UI."""
        logger.info("Starting logout flow")

        if self.main_window:
            self.main_window.setEnabled(False)
            self.main_window.hide()

        auth_controller = get_auth_controller()
        await auth_controller.logout()
        await self._teardown_authenticated_runtime()

        if not await self.authenticate():
            logger.info("Authentication cancelled after logout")
            self._quit_event.set()
            return

        await self.initialize()
        await self.show_main_window()

    async def _teardown_authenticated_runtime(self) -> None:
        """Reset UI and runtime services that are tied to one authenticated user session."""
        if self.main_window:
            self.main_window.hide()
            self.main_window.deleteLater()
            self.main_window = None

        await self._close_optional_component(
            "Chat controller close during logout failed",
            peek_chat_controller,
        )
        await self._close_optional_component(
            "Message controller close during logout failed",
            peek_message_controller,
        )
        await self._close_optional_component(
            "Session controller close during logout failed",
            peek_session_controller,
        )
        await self._close_optional_component(
            "Message manager close during logout failed",
            peek_message_manager,
        )
        await self._close_optional_component(
            "Session manager close during logout failed",
            peek_session_manager,
        )
        await self._close_optional_component(
            "Connection manager close during logout failed",
            peek_connection_manager,
        )
        await self._close_optional_component(
            "WebSocket client close during logout failed",
            peek_websocket_client,
            skip_if=peek_connection_manager,
        )
        await self._close_optional_component(
            "Sound manager close during logout failed",
            peek_sound_manager,
        )

        try:
            db = peek_database()
            if db is not None:
                await db.clear_chat_state()
        except Exception:
            logger.exception("Database chat-state cleanup during logout failed")

    async def _close_optional_component(
        self,
        failure_message: str,
        getter,
        *,
        timeout: float = 2.0,
        skip_if=None,
    ) -> None:
        """Close one optional singleton component with a timeout guard."""
        try:
            component = getter()
            if component is None:
                return
            if skip_if is not None and skip_if() is not None:
                return
            await asyncio.wait_for(component.close(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("%s (timed out after %.1fs)", failure_message, timeout)
        except Exception:
            logger.exception(failure_message)

    # =========================================================
    # Shutdown
    # =========================================================

    async def shutdown(self) -> None:
        """
        Gracefully shutdown the application.

        Stops all services, cancels tasks, and closes connections in reverse
        order of initialization.
        """

        logger.info("Shutting down application...")

        if self.auth_window:
            self.auth_window.close()
            self.auth_window.deleteLater()
            self.auth_window = None

        if self.main_window:
            self.main_window.hide()
            self.main_window.deleteLater()
            self.main_window = None

        # Stop websocket auto-reconnect
        try:
            ws = peek_websocket_client()
            if ws is not None:
                ws._intentional_disconnect = True
        except Exception:
            pass

        # Cancel tasks
        for task in list(self._tasks):
            task.cancel()

        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

        await self._close_optional_component("Chat controller close failed", peek_chat_controller)
        await self._close_optional_component("Message controller close failed", peek_message_controller)
        await self._close_optional_component("Session controller close failed", peek_session_controller)
        await self._close_optional_component("Auth controller close failed", peek_auth_controller)
        await self._close_optional_component("Message manager close failed", peek_message_manager)
        await self._close_optional_component("Session manager close failed", peek_session_manager)
        await self._close_optional_component("Connection manager close failed", peek_connection_manager)
        await self._close_optional_component(
            "WebSocket client close failed",
            peek_websocket_client,
            skip_if=peek_connection_manager,
        )
        await self._close_optional_component("Sound manager close failed", peek_sound_manager)

        # Close HTTP client
        try:
            http = peek_http_client()
            if http is not None:
                await http.close()
        except Exception:
            logger.exception("HTTP client close failed")

        # Close database
        try:
            db = peek_database()
            if db is not None:
                await db.close()
        except Exception:
            logger.exception("Database close failed")

        self.qt_app.processEvents()
        self.qt_app.quit()

        logger.info("Shutdown complete")

    # =========================================================
    # Lifecycle
    # =========================================================

    async def run(self) -> None:
        """
        Main application run loop.

        Initializes components, displays main window, starts background
        services, and waits for shutdown signal.
        """

        try:
            await self.initialize()
            preflight = self.get_startup_preflight_result()
            if preflight.get("blocking"):
                self._exit_code = EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED
                logger.error(
                    "Startup preflight blocked application launch: %s (%s)",
                    preflight.get("state"),
                    preflight.get("message"),
                )
                return

            if not await self.authenticate():
                return

            await self.show_main_window()
            await self._quit_event.wait()
        finally:
            await self.shutdown()


# =========================================================
# Entry
# =========================================================

def main() -> int:
    """
    Application entry point.

    Sets up Qt application, event loop, initializes all components,
    and runs the application until shutdown.

    Returns:
        Exit code (0 for normal exit).
    """

    args, qt_unknown_args = _parse_runtime_args(sys.argv)
    profile = _configure_runtime_profile(args.profile) if args.profile else ""
    setup_logging()
    logger.info("Starting AssistIM...")

    qt_app = QApplication([sys.argv[0], *qt_unknown_args])
    initialize_i18n(cfg.get(cfg.language))
    qt_app.setApplicationName(tr("common.app_name", "AssistIM"))
    setTheme(cfg.get(cfg.themeMode), lazy=True)
    setThemeColor(cfg.get(cfg.themeColor))
    app_font = qt_app.font()
    if app_font.pointSize() <= 0:
        app_font.setPointSize(10)
        qt_app.setFont(app_font)

    # Prevent Qt from auto-quitting when window is closed
    qt_app.setQuitOnLastWindowClosed(False)

    instance_lock = _acquire_instance_lock(profile)
    if instance_lock is None:
        logger.warning("Another AssistIM instance is already running")
        QMessageBox.information(
            None,
            tr("common.app_name", "AssistIM"),
            tr(
                "main.single_instance.message",
                "AssistIM is already running. Use a different --profile value if you need a second local test instance.",
            ),
        )
        return EXIT_CODE_SINGLE_INSTANCE

    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    app = Application(qt_app)

    try:

        with loop:
            loop.run_until_complete(app.run())

    finally:

        if not loop.is_closed():
            loop.close()

        instance_lock.unlock()

    if app.get_exit_code() == EXIT_CODE_STARTUP_PREFLIGHT_BLOCKED:
        _show_startup_preflight_block_dialog(app.get_startup_preflight_result())

    logger.info("Application exited")

    return app.get_exit_code()


if __name__ == "__main__":
    sys.exit(main())
