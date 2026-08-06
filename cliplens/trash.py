"""文件安全与回收站管理模块。

对应《02_详细设计说明书_SDD.md》第 3.4 节：
- 软删除：仅标记 is_deleted，不动磁盘文件。
- 彻底删除：send2trash 移至系统回收站 + 清理 SQLite/LanceDB/缩略图。
"""
from __future__ import annotations

from pathlib import Path

from .models import ThumbSize
from .project_manager import ProjectHandle


class TrashManager:
    """回收站管理。"""

    def __init__(self, project: ProjectHandle):
        self.project = project

    def soft_delete(self, image_ids: list[int]) -> None:
        self.project.metadata_db.soft_delete(image_ids, deleted=True)

    def restore(self, image_ids: list[int]) -> None:
        self.project.metadata_db.soft_delete(image_ids, deleted=False)

    def purge(self, image_ids: list[int]) -> None:
        """彻底删除：send2trash + 清理记录/向量/缩略图。

        双库一致性（见 SAD 5.1）：先移入系统回收站（不可逆的副作用最先做），
        再清向量、最后删元数据记录，并带异常补偿。
        """
        md = self.project.metadata_db
        vs = self.project.vector_store
        thumbs = self.project.thumbnail_store

        # 1. 先把文件移入系统回收站（最易失败且不可逆，优先执行）
        file_map: dict[int, Path] = {}
        for iid in image_ids:
            rec = md.get_image(iid)
            if rec and rec.file_path.exists():
                self._send_to_trash(rec.file_path)
                file_map[iid] = rec.file_path

        # 2. 清理缩略图
        for p in file_map.values():
            for size in (ThumbSize.VIEW_256, ThumbSize.PREVIEW_1024):
                thumbs.abs_path(p, size).unlink(missing_ok=True)

        # 3. 先清向量，再删记录；异常时记录待补偿任务（SAD 5.1）
        try:
            vs.remove(image_ids)
        except Exception:
            md.set_config("pending_cleanup", ",".join(map(str, image_ids)))
            raise
        md.purge(image_ids)

    def empty(self) -> None:
        """清空回收站（通过公共查询获取软删除记录，再走 purge 流程）。"""
        md = self.project.metadata_db
        ids = md.get_soft_deleted_ids()
        if ids:
            self.purge(ids)

    @staticmethod
    def _send_to_trash(path: Path) -> None:
        """将文件移动至系统回收站。优先 send2trash，缺失时降级为普通删除提示。"""
        try:
            import send2trash

            send2trash.send2trash(str(path))
        except ImportError:
            # 原型环境未安装 send2trash 时，仅打印提示，不真实删除以保障安全
            print(f"[Trash] send2trash 未安装，跳过物理删除: {path}")
