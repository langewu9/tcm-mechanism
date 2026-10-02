from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(r"D:\mini\envs\py310\python.exe")
PORT = 8010
URL = f"http://127.0.0.1:{PORT}"


def backend_ready() -> bool:
    try:
        return requests.get(f"{URL}/api/health", timeout=1.5).ok
    except requests.RequestException:
        return False


class DesktopShell(QMainWindow):
    def __init__(self):
        super().__init__()
        self.proc: subprocess.Popen | None = None
        self.setWindowTitle("中医药理数据库与可视化分析平台 - 优化版 PyQt")
        self.resize(1360, 860)
        self.setMinimumSize(1180, 760)
        self.setStyleSheet("""
            QMainWindow { background: #f5f7fa; }
            QLabel#title { color: #18202a; font-size: 18px; font-weight: 700; }
            QLabel#sub { color: #667085; font-size: 12px; }
            QPushButton { background: #245b8f; color: white; border: 0; padding: 8px 14px; border-radius: 6px; }
            QPushButton#ghost { background: white; color: #245b8f; border: 1px solid #d9e0e8; }
        """)
        self._build_ui()
        self._ensure_backend()
        self.web.load(QUrl(URL))

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("中医药理数据库与可视化分析平台")
        title.setObjectName("title")
        title.setFont(QFont("Microsoft YaHei", 11))
        sub = QLabel("优化版 PyQt 桌面入口：统一加载 Web 前端和 FastAPI 后端")
        sub.setObjectName("sub")
        title_box.addWidget(title)
        title_box.addWidget(sub)

        self.state = QLabel("后端检查中")
        self.reload_btn = QPushButton("刷新")
        self.reload_btn.setObjectName("ghost")
        self.reload_btn.clicked.connect(lambda: self.web.reload())
        self.docs_btn = QPushButton("接口文档")
        self.docs_btn.clicked.connect(lambda: self.web.load(QUrl(f"{URL}/docs")))
        self.home_btn = QPushButton("平台首页")
        self.home_btn.clicked.connect(lambda: self.web.load(QUrl(URL)))

        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(self.state)
        header.addWidget(self.home_btn)
        header.addWidget(self.docs_btn)
        header.addWidget(self.reload_btn)

        self.web = QWebEngineView()
        self.web.setContextMenuPolicy(Qt.NoContextMenu)

        layout.addLayout(header)
        layout.addWidget(self.web, 1)
        self.setCentralWidget(root)

    def _ensure_backend(self):
        if backend_ready():
            self.state.setText("后端已连接")
            return
        self.proc = subprocess.Popen(
            [str(PYTHON), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        for _ in range(40):
            if backend_ready():
                self.state.setText("后端已启动")
                return
            time.sleep(0.25)
        self.state.setText("后端启动失败")

    def closeEvent(self, event):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = DesktopShell()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

