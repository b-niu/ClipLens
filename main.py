"""ClipLens 应用统一入口。

用法：
    python main.py --cli ...        # 进入 CLI 模式
    python main.py                  # 尝试启动 GUI（未安装 PySide6 时给出提示）

CLI 模式透传参数到 cliplens.cli，例如：
    python main.py --cli new demo --dir ./my_project
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cliplens", description="ClipLens 本地 AI 图片管理工具"
    )
    parser.add_argument(
        "--cli", action="store_true", help="以 CLI 模式运行"
    )
    args, rest = parser.parse_known_args(argv)

    if args.cli:
        from cliplens.cli import main as cli_main

        return cli_main(rest)

    # 默认尝试启动 GUI；未安装 PySide6 时降级提示
    try:
        from cliplens.gui import main as gui_main

        return gui_main()
    except ImportError as e:
        if "PySide6" in str(e):
            print("未安装 PySide6。请先: pip install -r requirements.txt")
            print("或以 CLI 模式运行: python main.py --cli --help")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
