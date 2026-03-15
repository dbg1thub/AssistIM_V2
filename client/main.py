"""
AssistIM Desktop Client
Application entry point
"""

import sys
import asyncio
import logging

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from client.storage.database import get_database
from client.network.http_client import get_http_client
from client.network.websocket_client import get_websocket_client

from client.managers.connection_manager import get_connection_manager
from client.managers.message_manager import get_message_manager
from client.managers.session_manager import get_session_manager

from client.ui.controllers.chat_controller import get_chat_controller


logger = logging.getLogger(__name__)


class Application:

    def __init__(self, qt_app: QApplication):

        self.qt_app = qt_app

        self._quit_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

        self.main_window = None

    # =========================================================
    # Task helper
    # =========================================================

    def create_task(self, coro):

        task = asyncio.create_task(coro)

        def _done(t: asyncio.Task):
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background task crashed")

        task.add_done_callback(_done)

        self._tasks.append(task)

        return task

    # =========================================================
    # Initialization
    # =========================================================

    async def initialize(self):

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

    def show_main_window(self):

        from client.ui.windows.main_window import MainWindow

        self.main_window = MainWindow()

        self.main_window.closed.connect(self._on_main_window_closed)

        self.main_window.show()

        logger.info("Main window displayed")

    def _on_main_window_closed(self):

        logger.info("Main window closed")

        self._quit_event.set()

    # =========================================================
    # Background services
    # =========================================================

    async def start_background_services(self):

        logger.info("Starting background services...")

        conn_manager = get_connection_manager()

        self.create_task(conn_manager.connect())

        logger.info("Background services started")

    # =========================================================
    # Shutdown
    # =========================================================

    async def shutdown(self):

        logger.info("Shutting down application...")

        # 停止 websocket 自动重连
        try:
            ws = get_websocket_client()
            ws._intentional_disconnect = True
        except Exception:
            pass

        # cancel tasks
        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # 关闭 controller
        try:
            chat_controller = get_chat_controller()
            await chat_controller.close()
        except Exception:
            logger.exception("Chat controller close failed")

        # 关闭 managers
        try:
            session_manager = get_session_manager()
            await session_manager.close()
        except Exception:
            logger.exception("Session manager close failed")

        try:
            msg_manager = get_message_manager()
            await msg_manager.close()
        except Exception:
            logger.exception("Message manager close failed")

        try:
            conn_manager = get_connection_manager()
            await conn_manager.close()
        except Exception:
            logger.exception("Connection manager close failed")

        # 关闭 websocket
        try:
            ws = get_websocket_client()
            await ws.close()
        except Exception:
            logger.exception("Websocket close failed")

        # HTTP
        try:
            http = get_http_client()
            await http.close()
        except Exception:
            logger.exception("HTTP client close failed")

        # DB
        try:
            db = get_database()
            await db.close()
        except Exception:
            logger.exception("Database close failed")

        logger.info("Shutdown complete")

    # =========================================================
    # Lifecycle
    # =========================================================

    async def run(self):

        await self.initialize()

        self.show_main_window()

        await self.start_background_services()

        await self._quit_event.wait()

        await self.shutdown()


# =========================================================
# Entry
# =========================================================

def main():

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting AssistIM...")

    qt_app = QApplication(sys.argv)

    # 关键：不要让 Qt 自动退出
    qt_app.setQuitOnLastWindowClosed(False)

    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    app = Application(qt_app)

    try:

        with loop:
            loop.run_until_complete(app.run())

    finally:

        if not loop.is_closed():
            loop.close()

    logger.info("Application exited")

    return 0


if __name__ == "__main__":
    sys.exit(main())