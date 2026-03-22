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

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop
from qfluentwidgets import setTheme, setThemeColor

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

from client.ui.controllers.auth_controller import get_auth_controller, peek_auth_controller
from client.ui.controllers.chat_controller import get_chat_controller, peek_chat_controller
from client.ui.controllers.message_controller import peek_message_controller
from client.ui.controllers.session_controller import peek_session_controller
from client.ui.windows.auth_interface import AuthInterface

setup_logging()
logger = logging.get_logger(__name__)


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

        logger.info("Initializing HTTP client...")
        get_http_client()

        logger.info("Initializing WebSocket client...")
        get_websocket_client()

        logger.info("Initializing connection manager...")
        conn_manager = get_connection_manager()
        await conn_manager.initialize()

        logger.info("Initializing message manager...")
        msg_manager = get_message_manager()
        await msg_manager.initialize()

        logger.info("Initializing session manager...")
        session_manager = get_session_manager()
        await session_manager.initialize()

        logger.info("Initializing chat controller...")
        chat_controller = get_chat_controller()
        await chat_controller.initialize()

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
        if restored_user:
            logger.info("Restored persisted session for user %s", restored_user.get("id"))
            await self._synchronize_authenticated_runtime()
            return True

        loop = asyncio.get_running_loop()
        auth_future: asyncio.Future[bool] = loop.create_future()

        self.auth_window = AuthInterface()

        def _on_authenticated(_user: dict) -> None:
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

        if not authenticated:
            logger.info("Authentication window closed before sign-in")
            return False

        await self._synchronize_authenticated_runtime()
        return True

    async def _synchronize_authenticated_runtime(self) -> None:
        """Reload per-user runtime state after authentication succeeds."""
        conn_manager = get_connection_manager()
        await conn_manager.reload_sync_timestamp()

        session_manager = get_session_manager()
        await session_manager.close()
        await session_manager.initialize()
        await session_manager.refresh_remote_sessions()
    def show_main_window(self) -> None:
        """
        Create and display the main application window.
        """

        from client.ui.windows.main_window import MainWindow

        self.main_window = MainWindow()

        self.main_window.closed.connect(self._on_main_window_closed)
        self.main_window.logoutRequested.connect(self._on_logout_requested)

        self.main_window.show()

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
        self.create_task(self._connect_when_ui_idle(conn_manager))

        logger.info("Background services started")

    async def _connect_when_ui_idle(self, conn_manager) -> None:
        """Defer the first websocket connect until the initial UI paint settles."""
        await asyncio.sleep(0)
        await conn_manager.connect()

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
        self.show_main_window()
        await self.start_background_services()

    async def _teardown_authenticated_runtime(self) -> None:
        """Reset UI and runtime services that are tied to one authenticated user session."""
        if self.main_window:
            self.main_window.hide()
            self.main_window.deleteLater()
            self.main_window = None

        try:
            chat_controller = peek_chat_controller()
            if chat_controller is not None:
                await chat_controller.close()
        except Exception:
            logger.exception("Chat controller close during logout failed")

        try:
            message_controller = peek_message_controller()
            if message_controller is not None:
                await message_controller.close()
        except Exception:
            logger.exception("Message controller close during logout failed")

        try:
            session_controller = peek_session_controller()
            if session_controller is not None:
                await session_controller.close()
        except Exception:
            logger.exception("Session controller close during logout failed")

        try:
            conn_manager = peek_connection_manager()
            if conn_manager is not None:
                await conn_manager.close()
        except Exception:
            logger.exception("Connection manager close during logout failed")

        try:
            ws = peek_websocket_client()
            if ws is not None:
                await ws.close()
        except Exception:
            logger.exception("WebSocket client close during logout failed")

        try:
            msg_manager = peek_message_manager()
            if msg_manager is not None:
                await msg_manager.close()
        except Exception:
            logger.exception("Message manager close during logout failed")

        try:
            session_manager = peek_session_manager()
            if session_manager is not None:
                await session_manager.close()
        except Exception:
            logger.exception("Session manager close during logout failed")

        try:
            db = peek_database()
            if db is not None:
                await db.clear_chat_state()
        except Exception:
            logger.exception("Database chat-state cleanup during logout failed")

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

        # Close controller
        try:
            chat_controller = peek_chat_controller()
            if chat_controller is not None:
                await chat_controller.close()
        except Exception:
            logger.exception("Chat controller close failed")

        try:
            message_controller = peek_message_controller()
            if message_controller is not None:
                await message_controller.close()
        except Exception:
            logger.exception("Message controller close failed")

        try:
            session_controller = peek_session_controller()
            if session_controller is not None:
                await session_controller.close()
        except Exception:
            logger.exception("Session controller close failed")

        try:
            auth_controller = peek_auth_controller()
            if auth_controller is not None:
                await auth_controller.close()
        except Exception:
            logger.exception("Auth controller close failed")

        # Stop network activity before shutting down message/session managers.
        try:
            conn_manager = peek_connection_manager()
            if conn_manager is not None:
                await conn_manager.close()
        except Exception:
            logger.exception("Connection manager close failed")

        try:
            ws = peek_websocket_client()
            if ws is not None:
                await ws.close()
        except Exception:
            logger.exception("WebSocket client close failed")

        # Close managers
        try:
            msg_manager = peek_message_manager()
            if msg_manager is not None:
                await msg_manager.close()
        except Exception:
            logger.exception("Message manager close failed")

        try:
            session_manager = peek_session_manager()
            if session_manager is not None:
                await session_manager.close()
        except Exception:
            logger.exception("Session manager close failed")

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

            if not await self.authenticate():
                return

            self.show_main_window()
            await self.start_background_services()
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
        return 1

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

    logger.info("Application exited")

    return 0


if __name__ == "__main__":
    sys.exit(main())


