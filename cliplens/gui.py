"""ClipLens GUI 层（PySide6）。

当前为最小可运行骨架：初始化应用窗口与项目面板。
完整 UI（网格视图、搜索、过滤器）按《05_UI_UX界面设计文档》逐步实现。
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """启动 PySide6 GUI。未安装 PySide6 时抛出 ImportError。"""
    from PySide6.QtWidgets import QApplication, QLabel, QMainWindow

    app = QApplication(sys.argv)
    window = QMainWindow()
    window.setWindowTitle("ClipLens")
    window.setMinimumSize(800, 600)
    window.setCentralWidget(QLabel("ClipLens - 本地 AI 图片管理"))
    window.show()
    return app.exec()
