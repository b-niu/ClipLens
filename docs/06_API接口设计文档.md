# ClipLens API / 接口设计文档

| 项目名称 | ClipLens |
|---------|----------|
| 版本 | v1.0 |
| 日期 | 2026-08-06 |

> ClipLens 为桌面应用，无对外网络 API。本文档定义**内部模块接口**（面向开发）与**未来插件扩展接口**（Plugin API）。

---

## 1. Project Manager 接口

### 1.1 项目管理

| 接口 | 签名 | 说明 |
|------|------|------|
| 创建项目 | `create_project(name: str, data_dir: Path) -> ProjectHandle` | 初始化 `.cliplens/` |
| 打开项目 | `open_project(project_id: int) -> ProjectHandle` | 挂载数据库/向量库 |
| 关闭项目 | `close_project() -> None` | 落盘释放 |
| 项目列表 | `list_projects() -> list[ProjectInfo]` | 返回全部项目 |
| 删除项目 | `delete_project(project_id: int, purge: bool=False) -> None` | 删数据目录 |
| 当前项目 | `current() -> ProjectHandle \| None` | 当前激活项目 |

### 1.2 项目信息模型

```python
@dataclass
class ProjectInfo:
    id: int
    name: str
    data_dir: Path
    created_at: datetime
    last_opened_at: datetime | None
```

---

## 2. 扫描与索引接口

| 接口 | 签名 | 说明 |
|------|------|------|
| 添加扫描根目录 | `add_scan_root(root: Path) -> None` | 将目录加入 `scan_roots` |
| 移除扫描根目录 | `remove_scan_root(root: Path) -> None` | 从 `scan_roots` 移除 |
| 列出扫描根目录 | `list_scan_roots() -> list[Path]` | 返回全部来源目录 |
| 扫描全部来源 | `scan(roots: list[Path] \| None = None) -> ScanResult` | 增量扫描（默认扫全部 `scan_roots`） |
| 生成网格缩略图 | `generate_thumbnail(path: Path, size: ThumbSize = ThumbSize.VIEW_256) -> Path` | 返回缓存路径 |
| 编码并入库 | `encode_and_store(paths: list[Path], batch_size=16)` | 向量提取 |

```python
class ThumbSize(Enum):
    VIEW_256 = (256, 256)    # 网格缩略图
    PREVIEW_1024 = (1024, 1024)  # 预览大图

@dataclass
class ScanResult:
    new: list[Path]
    updated: list[Path]
    missing: list[Path]
```

> **说明**：`scan()` 默认遍历 `system_config` 中的 `scan_roots` 全部来源目录；也可传入指定目录子集。缩略图统一两种规格（256 网格 / 1024 预览），按 `MD5(file_path)` 前两位一层分层存储。

---

## 3. 检索接口

| 接口 | 签名 | 说明 |
|------|------|------|
| 语义检索 | `search(query: SearchQuery) -> list[SearchResultItem]` | 文本→向量→检索 |
| 过滤 | 见 `SearchQuery` | 评分/标签/日期组合 |

**性能约定**：
- **超采样（Oversample）**：执行向量检索时以 `top_n × 5` 作为检索量，再经 SQLite 过滤后截断为 `top_n`，避免严格过滤条件下结果不足。
- **批量预取（避免 N+1）**：检索到 ID 列表后，用一次 `WHERE id IN (...)` 批量查询补齐 `SearchResultItem` 的展示字段（文件名、评分、状态、尺寸、标签），并一次性拼接缩略图路径，杜绝逐条查询。

```python
@dataclass
class SearchQuery:
    text: str
    min_rating: int = 0
    tags: list[str] = field(default_factory=list)
    date_from: datetime | None = None
    date_to: datetime | None = None
    top_n: int = 100

@dataclass
class SearchResultItem:
    image_id: int
    score: float
    file_path: Path
    # 以下字段随 SQLite 批量预取，避免 UI 展示时的 N+1 查询
    file_name: str = ""
    rating: int = 0
    status: str = "OK"          # OK / CORRUPTED / MISSING
    is_deleted: bool = False
    width: int = 0
    height: int = 0
    tags: list[str] = field(default_factory=list)
    thumbnail_path: Path | None = None   # 256 网格缩略图路径
    preview_path: Path | None = None     # 1024 预览大图路径（懒加载）
```

---

## 4. 批量操作接口

| 接口 | 签名 | 说明 |
|------|------|------|
| 批量评分 | `set_rating(image_ids: list[int], rating: int) -> None` | 事务写入 |
| 多选状态 | UI 层 `QItemSelectionModel` | 复用 Qt 选择模型 |
| 标签操作 | `add_tag(image_id, name) / remove_tag(image_id, name)` | 标签管理 |

---

## 5. 回收站接口

| 接口 | 签名 | 说明 |
|------|------|------|
| 软删除 | `soft_delete(image_ids: list[int])` | 标记删除 |
| 恢复 | `restore(image_ids: list[int])` | 取消删除标记 |
| 彻底删除 | `purge(image_ids: list[int])` | send2trash + 清理 |
| 清空 | `empty() -> None` | 清空回收站 |

---

## 6. Qt 信号槽接口（跨线程通信）

### 6.1 扫描进度

| 信号 | 签名 | 说明 |
|------|------|------|
| `progress` | `Signal(int, int)` | 当前数, 总数 |
| `scan_done` | `Signal(ScanResult)` | 扫描完成 |

### 6.2 检索结果

| 信号 | 签名 | 说明 |
|------|------|------|
| `search_finished` | `Signal(list)` | 检索结果列表 |

### 6.3 项目切换

| 信号 | 签名 | 说明 |
|------|------|------|
| `project_changed` | `Signal(int)` | 项目切换 |

---

## 7. 插件扩展接口 (Plugin API) —— 未来

```python
class ClipLensPlugin:
    """插件基类"""
    name: str
    version: str

    def on_project_opened(self, project: ProjectHandle): ...
    def on_image_selected(self, image_ids: list[int]): ...
    def on_export(self, image_ids: list[int]): ...

# 注册入口
def register_plugin() -> ClipLensPlugin: ...
```

**插件类型**：自定义导出、图片压缩、滤镜批处理等。

---

## 8. 异常定义

| 异常 | 触发场景 |
|------|---------|
| `ProjectNotFoundError` | 项目不存在 |
| `ProjectCorruptedError` | `.cliplens/` 数据损坏 |
| `UnsupportedImageError` | 不支持/损坏图片 |
| `OOMError` | 显存/内存不足 |
| `DeadLinkError` | 路径失效 |
