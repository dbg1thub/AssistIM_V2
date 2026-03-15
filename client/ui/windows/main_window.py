
from PySide6.QtWidgets import QMainWindow, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import Signal

from client.core import logging
from client.core.logging import setup_logging

setup_logging()
logger = logging.get_logger(__name__)


class MainWindow(QMainWindow):
    """主窗口"""
    
    closed = Signal()
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AssistIM")
        self.resize(800, 600)
        
        # 简单布局
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        
        # 测试按钮
        btn = QPushButton("测试按钮")
        layout.addWidget(btn)
        
        self.setCentralWidget(central_widget)
        
        logger.info("MainWindow created")
    
    def closeEvent(self, event):
        logger.info("MainWindow closeEvent, accepting close")
        self.closed.emit()
        super().closeEvent(event)
