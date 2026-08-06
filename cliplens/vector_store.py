"""向量库封装（vectors.lancedb）。

对应《03_数据库设计说明书_DB_Design.md》第 4 节：
- image_id 关联 SQLite images.id
- vector 为 512 维 Float32

说明：LanceDB 为第三方可选依赖。本模块通过抽象接口隔离，
未安装 lancedb 时提供内存版实现（MemoryVectorStore），
便于原型验证与离线测试；生产环境使用 LanceVectorStore。
"""
from __future__ import annotations

import math
from pathlib import Path

try:
    import lancedb
    _HAS_LANCE = True
except ImportError:  # pragma: no cover
    _HAS_LANCE = False


class VectorStore:
    """向量库抽象接口。"""

    def store(self, image_id: int, vector: list[float]) -> None: ...
    def search(
        self, query_vector: list[float], top_n: int
    ) -> list[tuple[int, float]]:
        """返回 [(image_id, cosine_similarity)]，按相似度降序。"""

    def remove(self, image_ids: list[int]) -> None: ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度，用于内存版实现。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class MemoryVectorStore(VectorStore):
    """内存版向量库，无需第三方依赖，用于原型与测试。"""

    def __init__(self) -> None:
        self._data: dict[int, list[float]] = {}

    def store(self, image_id: int, vector: list[float]) -> None:
        self._data[image_id] = vector

    def search(self, query_vector: list[float], top_n: int) -> list[tuple[int, float]]:
        scored = [
            (iid, cosine_similarity(query_vector, vec))
            for iid, vec in self._data.items()
        ]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:top_n]

    def remove(self, image_ids: list[int]) -> None:
        for iid in image_ids:
            self._data.pop(iid, None)


def create_vector_store(uri: Path) -> VectorStore:
    """工厂：优先返回 LanceDB 实现，否则回退内存实现。"""
    if _HAS_LANCE:
        return LanceVectorStore(uri)
    return MemoryVectorStore()


class LanceVectorStore(VectorStore):
    """基于 LanceDB 的实现。"""

    def __init__(self, uri: Path):
        self._uri = Path(uri)
        self._uri.parent.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self._uri))
        self._table = self._db.open_table("vectors")
        if self._table is None:
            self._table = self._db.create_table(
                "vectors", data=[{"image_id": -1, "vector": [0.0] * 512}]
            )

    def store(self, image_id: int, vector: list[float]) -> None:
        self._table.add([{"image_id": image_id, "vector": vector}])

    def search(self, query_vector: list[float], top_n: int) -> list[tuple[int, float]]:
        result = self._table.search(query_vector).limit(top_n).to_list()
        return [(int(r["image_id"]), float(r["_distance"])) for r in result]

    def remove(self, image_ids: list[int]) -> None:
        for iid in image_ids:
            self._table.delete(f"image_id = {iid}")
