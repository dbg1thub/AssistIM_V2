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
from client.core.logging import setup_logging
from client.storage.database import get_database
from client.network.http_client import get_http_client
from client.network.websocket_client import get_websocket_client

from client.managers.connection_manager import get_connection_manager
from client.managers.message_manager import get_message_manager
from client.managers.session_manager import get_session_manager

from client.ui.controllers.auth_controller import get_auth_controller
from client.ui.controllers.chat_controller import get_chat_controller
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
        self._tasks: list[asyncio.Task] = []

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
            try:
                t.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Background task crashed")

        task.add_done_callback(_done)

        self._tasks.append(task)

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

        return authenticated

    def show_main_window(self) -> None:
        """
        Create and display the main application window.
        """

        from client.ui.windows.main_window import MainWindow

        self.main_window = MainWindow()

        self.main_window.closed.connect(self._on_main_window_closed)

        self.main_window.show()

        logger.info("Main window displayed")

    def _on_main_window_closed(self) -> None:
        """
        Handle main window close event.
        """

        logger.info("Main window closed")

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
        self.create_task(self._connect_when_ui_idle(conn_manager))

        logger.info("Background services started")

    async def _connect_when_ui_idle(self, conn_manager) -> None:
        """Defer the first websocket connect until the initial UI paint settles."""
        await asyncio.sleep(0.6)
        await conn_manager.connect()

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

        # Stop websocket auto-reconnect
        try:
            ws = get_websocket_client()
            ws._intentional_disconnect = True
        except Exception:
            pass

        # Cancel tasks
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close controller
        try:
            chat_controller = get_chat_controller()
            await chat_controller.close()
        except Exception:
            logger.exception("Chat controller close failed")

        # Stop network activity before shutting down message/session managers.
        try:
            conn_manager = get_connection_manager()
            await conn_manager.close()
        except Exception:
            logger.exception("Connection manager close failed")

        # Close managers
        try:
            msg_manager = get_message_manager()
            await msg_manager.close()
        except Exception:
            logger.exception("Message manager close failed")

        try:
            session_manager = get_session_manager()
            await session_manager.close()
        except Exception:
            logger.exception("Session manager close failed")

        # Close HTTP client
        try:
            http = get_http_client()
            await http.close()
        except Exception:
            logger.exception("HTTP client close failed")

        # Close database
        try:
            db = get_database()
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
    qt_app.setApplicationName("AssistIM")
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
            "AssistIM",
            "AssistIM \u5df2\u7ecf\u5728\u8fd0\u884c\u3002\u5982\u9700\u672c\u5730\u591a\u5f00\u6d4b\u8bd5\uff0c\u8bf7\u4f7f\u7528\u4e0d\u540c\u7684 --profile \u53c2\u6570\u3002",
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
