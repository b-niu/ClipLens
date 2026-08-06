"""多模态检索与混合查询模块。

对应《02_详细设计说明书_SDD.md》第 3.2 节：
- 文本 → 向量 → LanceDB 余弦检索（当前项目内）。
- 超采样（oversample=5）+ SQLite 组合过滤 + 批量预取展示字段。
"""
from __future__ import annotations

from pathlib import Path

from .models import SearchQuery, SearchResultItem, ThumbSize
from .project_manager import ProjectHandle


class SearchEngine:
    """在当前激活 Project 内执行检索。"""

    def __init__(self, project: ProjectHandle):
        self.project = project

    def search(self, query: SearchQuery) -> list[SearchResultItem]:
        md = self.project.metadata_db
        vs = self.project.vector_store
        thumbs = self.project.thumbnail_store

        # 1. 文本 → 向量（原型用查询哈希伪向量；生产调用 CLIP Text Encoder）
        query_vector = _query_vector(query.text)

        # 2. 超采样向量检索
        oversampled = vs.search(query_vector, query.top_n * query.oversample)

        # 3. SQLite 组合过滤 + 批量预取展示字段
        candidate_ids = [iid for iid, _ in oversampled]
        display = md.fetch_display_fields(candidate_ids)
        items: list[SearchResultItem] = []
        for iid, score in oversampled:
            rec = display.get(iid)
            if rec is None:
                continue  # 向量存在但元数据缺失 → 启动对账时会清理
            if rec["is_deleted"]:
                continue
            if rec["rating"] < query.min_rating:
                continue
            file_path = Path(rec["file_path"])
            items.append(
                SearchResultItem(
                    image_id=iid,
                    score=score,
                    file_path=file_path,
                    file_name=rec["file_name"],
                    rating=rec["rating"],
                    status=rec["status"],
                    is_deleted=bool(rec["is_deleted"]),
                    width=rec["width"],
                    height=rec["height"],
                    tags=md.get_tags(iid),
                    thumbnail_path=thumbs.abs_path(file_path, ThumbSize.VIEW_256),
                    preview_path=thumbs.abs_path(file_path, ThumbSize.PREVIEW_1024),
                )
            )
            if len(items) >= query.top_n:
                break
        return items


def _query_vector(text: str) -> list[float]:
    """原型：基于文本哈希生成伪向量；生产替换为 Chinese-CLIP Text Encoder。"""
    import math

    from .scanner import _PseudoRandom

    seed = abs(hash(text)) % (2**32)
    rnd = _PseudoRandom(seed)
    v = [rnd.next() for _ in range(512)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]
