# ClipLens 软件详细设计说明书 (Software Design Specification, SDD)

| 项目名称 | ClipLens |
|---------|----------|
| 版本 | v1.0 |
| 状态 | 初稿 |
| 日期 | 2026-08-06 |

---

## 1. 项目概述与设计目标

### 1.1 项目背景与定位

ClipLens 是一款面向个人及专业用户的本地 AI 智能图片浏览与管理工具。软件基于 **Python + PySide6** 框架开发，集成 **Chinese-CLIP** 多模态模型与轻量化嵌入式向量数据库（LanceDB / SQLite），实现基于自然语言文本的本地图片跨模态检索、流式网格浏览、批量快捷打分、智能筛选与安全的本地文件删除管理。

软件以 **Project（项目）** 为核心组织单元：每个项目拥有独立的数据目录（数据库 + 缩略图），图片文件保持原始路径不变。

### 1.2 核心设计原则

1. **完全本地化与隐私保护**：模型推理、向量计算、数据存储与文件操作均在本地完成，无网络数据上传。
2. **高效高响应**：采用单进程多线程架构，GUI 主线程与后台推理/I/O 线程解耦；界面采用虚拟化网格渲染。
3. **架构极简**：去除 C/S 复杂网络开销，原生 Python 直接调用 AI 模型与数据库。
4. **安全防误删**：物理删除对接系统回收站（Soft Delete + SendToTrash）。
5. **项目隔离**：数据库与缩略图按项目隔离，原图路径不变。

---

## 2. 系统总体架构设计

### 2.1 逻辑架构与分层设计

系统采用经典的四层分层架构：

* **UI 表现层 (Presentation Layer)**：PySide6 构建，包含瀑布流/网格图库视图、搜索栏、侧边栏过滤器、详情预览面板、批量评分/删除工具栏、项目切换面板。
* **业务逻辑层 (Business Logic Layer)**：包含 Project 管理器、图库扫描调度器（Scanner Scheduler）、检索控制器（Search Controller）、批量选择与评分管理器（Batch Manager）、软删除/回收站同步器（Trash Manager）。
* **AI 推理与引擎层 (AI Engine Layer)**：基于 Chinese-CLIP (PyTorch / ONNX Runtime) 的图像与文本 Feature Extractor。
* **数据持久化与文件层 (Persistence & Storage Layer)**：
  * **Project 数据目录 (`.cliplens/`)**：每个项目独立的数据目录。
  * **SQLite 数据库**：存储项目内图片元数据。
  * **LanceDB 向量库**：存储项目内图像 Embedding。
  * **缩略图缓存区 (Thumbnail Store)**：WebP 格式，懒加载 + LRU 淘汰。

### 2.2 Project 目录结构

```
<ProjectDataDir>/
├── .cliplens/
│   ├── project.json          # 项目元信息（名称、创建时间、图标等）
│   ├── metadata.db           # SQLite 元数据（本项目的图片信息）
│   ├── vectors.lancedb       # LanceDB 向量库（本项目的 Embedding）
│   └── thumbs/               # 本项目缩略图缓存
│       └── ab/cd/<md5>.webp  # 按 Hash 前两位分层存储
```

### 2.3 线程模型与并发设计

* **主线程 (GUI Event Loop)**：界面事件响应、网格重绘、用户输入捕捉。
* **AI 推理工作线程 (Model Inference Worker)**：CLIP 图片批量编码与文本查询编码，控制 Batch Size 与显存/内存上限。
* **文件与缩略图工作线程池 (I/O Worker Pool)**：磁盘扫描、EXIF 提取、缩略图生成与缓存写入。
* **信号与槽机制 (Qt Signals & Slots)**：跨线程传输处理进度、检索结果与错误信息。

---

## 3. 核心模块详细设计

### 3.0 Project 管理模块 (Project Manager Module)

#### 职责
Project 是数据隔离与组织的基本单位，本模块统一管理其生命周期。

#### 类设计

```python
class ProjectInfo:
    """项目元信息模型"""
    id: int
    name: str
    data_dir: Path          # .cliplens 所在路径
    created_at: datetime
    last_opened_at: datetime

class ProjectManager:
    """项目管理器，管理项目生命周期"""

    def __init__(self, app_db_path: Path): ...
    def create_project(self, name: str, data_dir: Path) -> ProjectHandle: ...
    def open_project(self, project_id: int) -> ProjectHandle: ...
    def close_project(self) -> None: ...
    def list_projects(self) -> list[ProjectInfo]: ...
    def delete_project(self, project_id: int, purge: bool = False) -> None: ...
    def rename_project(self, project_id: int, new_name: str) -> None: ...
    def current(self) -> ProjectHandle | None: ...

class ProjectHandle:
    """已打开项目的访问句柄，持有数据库连接与向量库引用"""
    info: ProjectInfo
    metadata_db: MetadataDB          # SQLite 封装
    vector_store: VectorStore        # LanceDB 封装
    thumbnail_store: ThumbnailStore  # 缩略图封装

    def rebuild_index(self) -> None: ...
```

#### 生命周期状态机

```
[创建] -> [已创建(未打开)] -> [打开] -> [已激活] -> [切换/关闭] -> [已创建]
                                    ^                     |
                                    |-----[删除(仅删数据目录)]----> [已删除]
```

#### 接口方法

| 方法 | 说明 |
|------|------|
| `create_project(name, data_dir)` | 初始化 `.cliplens/` 目录结构与数据库 |
| `open_project(project_id)` | 挂载该项目的数据库与向量库，设为当前激活项目 |
| `close_project()` | 落盘并释放资源 |
| `delete_project(project_id, purge)` | 移除 `.cliplens/`（purge 时连全局注册记录一并删除），不触碰原图 |

---

### 3.1 图库扫描与增量建库模块 (Scanner & Indexer Module)

扫描与建库均在当前激活 Project 内进行。

#### 增量扫描算法
1. 遍历当前 Project 的全部扫描来源目录（`scan_roots`，存于 `system_config`），逐个递归获取 `path`、`size`、`mtime`。
2. 查询当前 Project 的 SQLite：不存在→`NEW`；`mtime`/`size` 不一致→`UPDATED`；磁盘已删→`MISSING`。
3. 仅处理 `NEW` 与 `UPDATED`。

#### 类设计

```python
class ScanResult:
    new: list[Path]
    updated: list[Path]
    missing: list[Path]

class ThumbSize(Enum):
    VIEW_256 = (256, 256)       # 网格缩略图
    PREVIEW_1024 = (1024, 1024) # 预览大图

class ScannerWorker(QObject):
    progress = Signal(int, int)   # (当前数, 总数)
    done = Signal(ScanResult)

    def add_scan_root(self, root: Path) -> None: ...
    def remove_scan_root(self, root: Path) -> None: ...
    def list_scan_roots(self) -> list[Path]: ...
    def scan(self, roots: list[Path] | None = None) -> ScanResult: ...

class ThumbnailGenerator:
    def generate(self, img_path: Path, size: ThumbSize = ThumbSize.VIEW_256) -> Path: ...
    def md5_path(self, file_path: Path) -> Path: ...   # 按 MD5 前两位一层分层

class VectorIndexer:
    def encode_and_store(self, image_paths: list[Path], batch_size: int = 16): ...
```

> **说明**：`scan_roots` 支持多目录；`scan()` 默认遍历全部来源，也可传入指定子集。缩略图统一 256（网格）与 1024（预览）两种规格，懒加载 + 容量上限 + LRU 淘汰。

---

### 3.2 多模态检索与混合查询模块 (Search Engine Module)

#### 文本查询流程（限定在当前激活 Project 内）
1. 用户输入自然语言文本。
2. Chinese-CLIP Text Encoder 编码为 512 维向量 $V_{text}$。
3. 在当前 Project 的 LanceDB 执行 Cosine Distance 检索，获取 Top-N。

#### 混合过滤
$$\text{Final Results} = \text{TopN\_IDs} \cap \{\text{Images} \mid \text{rating} \ge \text{min\_rating} \land \text{is\_deleted} = 0 \land \text{date\_range}\}$$

**超采样策略**：为避免严格过滤导致结果不足，向量检索先取 `top_n × 5`（超采样倍率 `oversample=5`）个候选 ID，再做 SQLite 过滤，最后截断返回 `top_n` 条。超采样倍率可作为 `SearchQuery` 的 `oversample` 参数配置。

#### 类设计

```python
class SearchQuery:
    text: str
    min_rating: int = 0
    tags: list[str] = []
    date_from: datetime | None = None
    date_to: datetime | None = None
    top_n: int = 100
    oversample: int = 5        # 超采样倍率，向量检索取 top_n × oversample

class SearchResultItem:
    image_id: int
    score: float
    file_path: Path
    file_name: str = ""
    rating: int = 0
    status: str = "OK"
    is_deleted: bool = False
    width: int = 0
    height: int = 0
    tags: list[str] = []
    thumbnail_path: Path | None = None
    preview_path: Path | None = None

class SearchEngine:
    def search(self, query: SearchQuery) -> list[SearchResultItem]: ...
```

---

### 3.3 交互与网格视图模块 (UI Virtual Grid Module)

#### 虚拟化网格
基于 `QListView` 重写 `paintEvent` 与 `data()`，仅渲染可见区域卡片。

#### 批量操作与快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl/Cmd + 点击` | 多选 |
| `Shift + 点击` | 范围选择 |
| `Ctrl + A` | 全选 |
| `1`~`5` | 批量设置星级评分 |
| `0` | 清除评分 |
| `Delete` / `Backspace` | 软删除 |
| `Space` | 快速预览大图 |
| `Esc` | 取消选择 / 关闭预览对话框 |

---

### 3.4 文件安全与回收站管理模块 (Trash & File Safety Module)

* **软删除**：仅设置 `is_deleted = 1`，界面实时隐藏。
* **回收站视图**：支持批量恢复 / 彻底删除。
* **物理删除**：`send2trash` 移至系统回收站；同步清理当前 Project 的 SQLite、LanceDB、缩略图缓存。

```python
class TrashManager:
    def soft_delete(self, image_ids: list[int]) -> None: ...
    def restore(self, image_ids: list[int]) -> None: ...
    def purge(self, image_ids: list[int]) -> None: ...   # send2trash + 清理记录
    def empty(self) -> None: ...
```

---

## 4. 数据库表结构设计

详见《03_数据库设计说明书_DB_Design.md》。此处列核心表：

```sql
-- 全局库 ~/.cliplens/app.db
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,
    data_dir TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_opened_at TIMESTAMP
);

-- 各项目独立库 <data_dir>/.cliplens/metadata.db
CREATE TABLE images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    mtime REAL NOT NULL,
    md5_hash VARCHAR(32) NOT NULL,
    rating INTEGER DEFAULT 0,
    status VARCHAR(16) DEFAULT 'OK',
    is_deleted TINYINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_images_path ON images(file_path);
CREATE INDEX idx_images_rating ON images(rating);
CREATE INDEX idx_images_deleted ON images(is_deleted);
CREATE INDEX idx_images_md5 ON images(md5_hash);
```

---

## 5. 异常处理与容错机制

1. **损坏图片**：解码失败标记 `CORRUPTED`，生成占位图，跳过向量提取。
2. **OOM**：自动调低 `batch_size`（16→8→4）或降级 CPU ONNX。
3. **死链/孤儿记录**：启动校验存在性，提示清理或标红。
4. **项目数据损坏**：校验 `.cliplens/` 完整性，提示重建索引或恢复。
5. **项目迁移路径失效**：批量校验，支持"重新定位目录"映射前缀。

---

## 6. 性能指标与优化策略

* **索引吞吐**：CPU 20~40 张/秒；GPU 150+ 张/秒。
* **检索响应**：单项目 10 万张 < 100ms。
* **界面帧率**：60 FPS；内存 < 500MB。
* **缓存淘汰**：LRU 保留最近 500 张缩略图。
* **缩略图**：WebP + 懒加载 + 容量上限淘汰。

---

## 7. 后续可扩展性规划

1. 多模型热切换（`BaseCLIPModel` 抽象基类）。
2. 自动打标与智能聚类。
3. 插件扩展接口。
4. 跨项目检索（多库并行 + MD5 去重）。
5. 项目模板与导入/导出。
