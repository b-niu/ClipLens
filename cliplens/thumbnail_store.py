"""缩略图缓存管理（thumbs/）。

对应《ClipLens_Software_Design_Spec.md》第 2.2 节目录规范：
- 两种规格：256（网格）与 1024（预览），均为 WebP。
- 按 MD5(file_path) 前两位一层分层存储。
- 懒加载（看一张生成一张）+ 容量上限 + LRU 淘汰。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅类型检查时导入，避免运行期强制依赖 Pillow
    from PIL import Image

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
        # 延迟导入 Pillow，核心逻辑不强制依赖
        from PIL import Image, ImageOps

        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = _exif_transpose(im)
            # 等比缩放至目标尺寸内
            im.thumbnail(size.value, Image.Resampling.LANCZOS)
            # 使用 ImageOps.pad 填充到固定正方形，保证输出尺寸一致
            im = ImageOps.pad(im, size.value, color=(0, 0, 0), centering=(0.5, 0.5))
            im.save(dest, "WEBP", quality=85)
        self._enforce_capacity()
        return dest

    # ---------- 容量控制 ----------
    def _enforce_capacity(self) -> None:
        """超出容量上限时，按最久未使用淘汰（基于 mtime）。"""
        files = list(self.thumbs_dir.rglob("*.webp"))
        total = sum(f.stat().st_size for f in files)
        if total <= self.max_bytes:
            return
        files.sort(key=lambda f: f.stat().st_mtime)
        for f in files:
            if total <= self.max_bytes:
                break
            total -= f.stat().st_size
            f.unlink(missing_ok=True)


def _exif_transpose(im: "Image.Image") -> "Image.Image":
    """修正 EXIF 旋转方向（使用 Pillow 内置 ImageOps.exif_transpose 更可靠）。"""
    from PIL import ImageOps

    return ImageOps.exif_transpose(im)
