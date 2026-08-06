"""ClipLens 命令行原型入口（不依赖 GUI）。

用于验证 Project / 扫描 / 检索 / 回收站核心流程。

用法示例：
    python -m cliplens.cli new-demo ./demo_images --root ./demo_images
    python -m cliplens.cli search "风景 海边"
    python -m cliplens.cli projects
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import SearchQuery
from .project_manager import ProjectManager
from .scanner import Scanner
from .search import SearchEngine
from .trash import TrashManager

DEFAULT_NAME = "默认项目"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cliplens", description="ClipLens CLI")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("projects", help="列出所有项目")

    p_new = sub.add_parser("new", help="创建并打开项目")
    p_new.add_argument("name", nargs="?", default=DEFAULT_NAME)
    p_new.add_argument("--dir", required=True, help="项目数据目录")

    p_scan = sub.add_parser("scan", help="扫描来源并建库")
    p_scan.add_argument("--project", type=int, required=True)
    p_scan.add_argument("--root", action="append", default=[], help="来源目录(可多个)")

    p_search = sub.add_parser("search", help="语义检索")
    p_search.add_argument("--project", type=int, required=True)
    p_search.add_argument("text", help="检索文本")
    p_search.add_argument("--top", type=int, default=10)

    p_del = sub.add_parser("delete", help="软删除")
    p_del.add_argument("--project", type=int, required=True)
    p_del.add_argument("--ids", required=True, help="逗号分隔的 image id")

    return p


def _resolve_project(pm: ProjectManager, project_id: int):
    return pm.open_project(project_id)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    pm = ProjectManager()

    if args.cmd == "projects":
        for proj in pm.list_projects():
            print(f"[{proj.id}] {proj.name} @ {proj.data_dir}")
        return 0

    if args.cmd == "new":
        handle = pm.create_project(args.name, Path(args.dir))
        print(f"项目已创建: [{handle.info.id}] {handle.info.name}")
        return 0

    if args.cmd == "scan":
        handle = _resolve_project(pm, args.project)
        scanner = Scanner(handle)
        for root in args.root:
            scanner.add_scan_root(Path(root))
        result = scanner.scan()
        n = scanner.index(result)
        print(
            f"扫描完成: new={len(result.new)} updated={len(result.updated)} "
            f"missing={len(result.missing)} 已建索引={n}"
        )
        return 0

    if args.cmd == "search":
        handle = _resolve_project(pm, args.project)
        engine = SearchEngine(handle)
        items = engine.search(SearchQuery(text=args.text, top_n=args.top))
        print(f"共 {len(items)} 条结果:")
        for it in items:
            print(f"  {it.score:.3f}  [{it.image_id}] {it.file_path}  ★{it.rating}")
        return 0

    if args.cmd == "delete":
        handle = _resolve_project(pm, args.project)
        ids = [int(x) for x in args.ids.split(",")]
        TrashManager(handle).soft_delete(ids)
        print(f"已软删除: {ids}")
        return 0

    print("未指定命令，使用 --help 查看。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
