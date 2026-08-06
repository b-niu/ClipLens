"""图库扫描与增量建库模块。

对应《02_详细设计说明书_SDD.md》第 3.1 节：
- 支持多扫描来源目录（scan_roots）。
- 增量识别 NEW / UPDATED / MISSING。
- 缩略图 WebP 懒加载 + 向量提取。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import ImageRecord, ImageStatus, ScanResult, ThumbSize
from .project_manager import ProjectHandle

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


class Scanner:
    """在当前激活 Project 内执行扫描建库。"""

    SCAN_ROOTS_KEY = "scan_roots"

    def __init__(self, project: ProjectHandle):
        self.project = project

    # ---------- 扫描来源目录管理 ----------
    def add_scan_root(self, root: Path) -> None:
        roots = self.list_scan_roots()
        root_str = str(Path(root).resolve())
        if root_str not in roots:
            roots.append(root_str)
            self.project.metadata_db.set_config(
                self.SCAN_ROOTS_KEY, json.dumps(roots)
            )

    def remove_scan_root(self, root: Path) -> None:
        roots = [r for r in self.list_scan_roots()
                 if r != str(Path(root).resolve())]
        self.project.metadata_db.set_config(
            self.SCAN_ROOTS_KEY, json.dumps(roots)
        )

    def list_scan_roots(self) -> list[str]:
        raw = self.project.metadata_db.get_config(self.SCAN_ROOTS_KEY, "[]")
        try:
            return list(json.loads(raw))
        except json.JSONDecodeError:
            return []

    # ---------- 扫描 ----------
    def scan(self, roots: list[Path] | None = None) -> ScanResult:
        roots = roots or [Path(r) for r in self.list_scan_roots()]
        result = ScanResult()

        # 磁盘上存在的文件集合
        disk_files: dict[str, tuple[int, float]] = {}

        def walk(directory: Path) -> None:
            if not directory.exists() or not directory.is_dir():
                return
            for p in directory.rglob("*"):
                if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                    stat = p.stat()
                    disk_files[str(p)] = (stat.st_size, stat.st_mtime)

        for root in roots:
            walk(Path(root))

        # 与数据库比对
        existing = self._load_all_paths()
        for path_str, (size, mtime) in disk_files.items():
            if path_str not in existing:
                result.new.append(Path(path_str))
            elif existing[path_str] != (size, mtime):
                result.updated.append(Path(path_str))

        # 数据库存在但磁盘已删
        for path_str in existing:
            if path_str not in disk_files:
                result.missing.append(Path(path_str))

        return result

    # ---------- 入库 ----------
    def index(self, result: ScanResult, batch_size: int = 16) -> int:
        """对 NEW / UPDATED 建缩略图与向量，返回处理的图片数。"""
        paths = result.new + result.updated
        md = self.project.metadata_db
        count = 0
        pil_available = _pil_available()

        for p in paths:
            rec = self._build_record(p, pil_available)
            image_id = md.upsert_image(rec)
            if rec.status == ImageStatus.OK:
                if pil_available:
                    self.project.thumbnail_store.get_or_generate(
                        p, ThumbSize.VIEW_256
                    )
                # 向量提取在真实实现中调用 CLIP；此处置占位向量以便测试
                self.project.vector_store.store(image_id, _dummy_vector(image_id))
                count += 1

        return count

    @staticmethod
    def _build_record(p: Path, pil_available: bool) -> ImageRecord:
        """构造图片记录。Pillow 缺失或图片损坏时，图片仍以相应状态入库。"""
        mtime = p.stat().st_mtime if p.exists() else 0.0
        size = p.stat().st_size if p.exists() else 0
        md5 = Scanner._md5(p) if p.exists() else ""

        if not p.exists():
            return ImageRecord(
                id=-1, file_path=p, file_name=p.name, file_size=size,
                width=0, height=0, mtime=mtime, md5_hash=md5,
                status=ImageStatus.MISSING,
            )
        if not pil_available:
            # 未安装 Pillow：无法读尺寸，但仍视为 OK 入库（缩略图后续补齐）
            return ImageRecord(
                id=-1, file_path=p, file_name=p.name, file_size=size,
                width=0, height=0, mtime=mtime, md5_hash=md5,
                status=ImageStatus.OK,
            )
        try:
            from PIL import Image

            with Image.open(p) as im:
                w, h = im.size
            return ImageRecord(
                id=-1, file_path=p, file_name=p.name, file_size=size,
                width=w, height=h, mtime=mtime, md5_hash=md5,
                status=ImageStatus.OK,
            )
        except Exception:
            return ImageRecord(
                id=-1, file_path=p, file_name=p.name, file_size=size,
                width=0, height=0, mtime=mtime, md5_hash=md5,
                status=ImageStatus.CORRUPTED,
            )

    def _load_all_paths(self) -> dict[str, tuple[int, float]]:
        # 使用 MetadataDB 公共方法，避免访问私有属性 _conn
        return self.project.metadata_db.list_all_files()

    @staticmethod
    def _md5(path: Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()


def _pil_available() -> bool:
    """检测 Pillow 是否可用。"""
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:
        return False


def _dummy_vector(seed: int) -> list[float]:
    """生成确定性伪向量（512 维），用于原型验证，生产替换为 CLIP 编码。"""
    import math

    rnd = _PseudoRandom(seed)
    v = [rnd.next() for _ in range(512)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


class _PseudoRandom:
    """简单的确定性伪随机（避免引入 numpy 依赖）。"""

    def __init__(self, seed: int):
        self.state = (seed * 2654435761 + 97) % (2**32)

    def next(self) -> float:
        self.state = (self.state * 1664525 + 1013904223) % (2**32)
        return (self.state / (2**32)) * 2.0 - 1.0
