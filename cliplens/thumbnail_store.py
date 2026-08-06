"""缩略图缓存管理（thumbs/）。

对应《ClipLens_Software_Design_Spec.md》第 2.2 节目录规范：
- 两种规格：256（网格）与 1024（预览），均为 WebP。
- 按 MD5(file_path) 前两位一层分层存储。
- 懒加载（看一张生成一张）+ 容量上限 + LRU 淘汰。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .models import ThumbSize


class ThumbnailStore:
    """缩略图缓存。依赖 Pillow 生成缩略图。"""

    def __init__(self, thumbs_dir: Path, max_bytes: int = 5 * 1024**3):
        self.thumbs_dir = Path(thumbs_dir)
        self.max_bytes = max_bytes  # 容量上限，默认 5GB

    # ---------- 路径计算 ----------
    @staticmethod
    def _md5_first2(file_path: Path) -> str:
        """取 file_path 的 MD5 前两位作为一层分层目录。"""
        return hashlib.md5(str(file_path).encode("utf-8")).hexdigest()[:2]

    def _rel_path(self, file_path: Path, size: ThumbSize) -> Path:
        sub = "256" if size == ThumbSize.VIEW_256 else "1024"
        return Path(sub) / self._md5_first2(file_path) / f"{self._md5(file_path)}.webp"

    def _md5(self, file_path: Path) -> str:
        return hashlib.md5(str(file_path).encode("utf-8")).hexdigest()

    def abs_path(self, file_path: Path, size: ThumbSize) -> Path:
        return self.thumbs_dir / self._rel_path(file_path, size)

    # ---------- 生成与读取 ----------
    def get_or_generate(self, src: Path, size: ThumbSize) -> Path:
        """懒加载：存在则返回，否则生成（依赖 Pillow，按需导入）。"""
        dest = self.abs_path(src, size)
        if dest.exists():
            return dest
        from PIL import Image  # 延迟导入，核心逻辑不强制依赖 Pillow

        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = ImageOps_exif(im)
            im.thumbnail(size.value, Image.Resampling.LANCZOS)
            # 居中裁剪为正方形
            im = _center_crop(im, size.value)
            im.save(dest, "WEBP", quality=85)
        self._enforce_capacity()
        return dest

    # ---------- 容量控制 ----------
    def _enforce_capacity(self) -> None:
        """超出容量上限时，按最久未使用淘汰（基于 mtime）。"""
        total = sum(f.stat().st_size for f in self.thumbs_dir.rglob("*.webp"))
        if total <= self.max_bytes:
            return
        files = sorted(
            self.thumbs_dir.rglob("*.webp"),
            key=lambda f: f.stat().st_mtime,
        )
        for f in files:
            if total <= self.max_bytes:
                break
            total -= f.stat().st_size
            f.unlink(missing_ok=True)


def ImageOps_exif(im: Image.Image) -> Image.Image:
    """修正 EXIF 旋转方向（简版，未引入 ImageOps 额外依赖）。"""
    exif = im.getexif()
    orientation = exif.get(0x0112, 1)
    ops = {
        3: Image.ROTATE_180,
        6: Image.ROTATE_270,
        8: Image.ROTATE_90,
    }
    if orientation in ops:
        im = im.transpose(ops[orientation])
    return im


def _center_crop(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    """居中裁剪为指定正方形尺寸。"""
    target = max(size)
    w, h = im.size
    left = (w - target) // 2
    top = (h - target) // 2
    return im.crop((max(left, 0), max(top, 0), left + target, top + target))
