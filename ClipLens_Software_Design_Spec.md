# ClipLens 软件详细设计说明书 (Software Design Specification)

## 1. 项目概述与设计目标

### 1.1 项目背景与定位

ClipLens 是一款面向个人及专业用户的本地 AI 智能图片浏览与管理工具。软件基于 **Python + PySide6** 框架开发，集成 **Chinese-CLIP** 多模态模型与轻量化嵌入式向量数据库（LanceDB / SQLite），实现基于自然语言文本的本地图片跨模态检索、流式网格浏览、批量快捷打分、智能筛选与安全的本地文件删除管理。

软件以 **Project（项目）** 为核心组织单元：用户可以针对不同主题/用途建立独立项目（如"工作素材库""生活相册"），每个项目拥有**自己独立的数据库与缩略图缓存**，而**图片文件本身保持原始路径不变**。项目既是逻辑上的管理边界，也是数据隔离与便携分享的单位。

### 1.2 核心设计原则

1. **完全本地化与隐私保护**：模型推理、向量计算、数据存储与文件操作均在本地完成，无网络数据上传。
2. **高效高响应**：采用单进程多线程架构，界面主线程（GUI Thread）与后台推理/I/O 线程解耦；界面采用虚拟化网格渲染，确保海量图片下流畅运行。
3. **架构极简**：去除客户端-服务端（C/S）复杂网络开销，采用原生 Python 直接调用 AI 模型与数据库。
4. **安全防误删**：物理删除操作对接系统回收站机制（Soft Delete + SendToTrash），防止数据意外丢失。

---

## 2. 系统总体架构设计

### 2.1 逻辑架构与分层设计

系统采用经典的四层分层架构：

* **UI 表现层 (Presentation Layer)**：基于 PySide6 (Qt for Python) 构建，包含瀑布流/网格图库视图、搜索栏、侧边栏过滤器、详情预览面板、批量评分/删除工具栏。
* **业务逻辑层 (Business Logic Layer)**：包含图库扫描调度器（Scanner Scheduler）、检索控制器（Search Controller）、批量选择与评分管理器（Batch Manager）、软删除/回收站同步器（Trash Manager）。
* **AI 推理与引擎层 (AI Engine Layer)**：基于 Chinese-CLIP (PyTorch / ONNX Runtime) 的图像与文本 Feature Extractor，负责图像 Vector Embedding 计算与查询文本 Vector Embedding 计算。
* **数据持久化与文件层 (Persistence & Storage Layer)**：
  * **Project 数据目录 (`.cliplens/`)**：每个项目在其数据目录内保存自己独立的数据库与缩略图缓存，图片本身保持原位。
  * **SQLite 数据库**：存储项目内的图片元数据（路径、尺寸、修改时间、评分、标签、状态等）。
  * **LanceDB 向量库**：持久化存储项目内图像高维 Embedding，提供高性能 Cosine 相似度检索。
  * **缩略图缓存区 (Thumbnail Store)**：磁盘按 Hash 分层存储 256x256 / 1024x1024 格式的压缩缩略图。

### 2.2 Project 目录结构

每个 Project 对应一个数据目录（由用户指定或默认 `~/ClipLens/Projects/<ProjectName>/`），图片文件可分散于磁盘任意路径，通过数据库记录绝对路径索引。典型结构如下：

```
<ProjectDataDir>/
├── .cliplens/
│   ├── project.json          # 项目元信息（名称、创建时间、图标等）
│   ├── metadata.db           # SQLite 元数据（本项目的图片信息）
│   ├── vectors.lancedb       # LanceDB 向量库（本项目的 Embedding）
│   └── thumbs/               # 本项目缩略图缓存
│       ├── 256/ab/<md5>.webp # 网格缩略图，按 MD5 前两位一层分层
│       └── 1024/ab/<md5>.webp# 预览大图，按 MD5 前两位一层分层
```

> **缩略图规范**：统一为两种规格——网格缩略图 **256×256**（WebP，存储于 `thumbs/256/`），预览大图 **1024×1024**（WebP，存储于 `thumbs/1024/`）。目录按 `MD5(file_path)` **前两位**一层分层（如 `ab/`），仅一层，不设二级目录。

> 图片文件（如 `D:\Photos\xxx.jpg`）保持原路径不动，仅被数据库索引；删除/重命名/分享项目时只操作 `.cliplens/` 数据目录，不影响原图。

### 2.3 线程模型与并发设计

* **主线程 (GUI Event Loop)**：负责界面事件响应、网格重绘、用户输入捕捉。主线程不直接执行模型加载、图像解码或向量检索。
* **AI 推理工作线程 (Model Inference Worker)**：专门处理 Chinese-CLIP 图片批量编码任务与文本查询编码任务，控制 Batch Size 与显存/内存上限。
* **文件与缩略图工作线程池 (I/O Worker Pool)**：负责磁盘文件扫描、EXIF 元数据提取、缩略图生成与缓存写入。
* **信号与槽机制 (Qt Signals & Slots)**：用于跨线程传输处理进度、检索结果列表与错误信息。

---

## 3. 核心模块详细设计

### 3.0 Project 管理模块 (Project Manager Module)

Project 是 ClipLens 数据隔离与组织的基本单位，由本模块统一管理其生命周期。

* **项目创建**：指定项目名称与数据目录，生成 `.cliplens/` 结构并初始化 `metadata.db`、`vectors.lancedb`、缩略图目录及 `project.json`。
* **项目打开/切换**：加载目标项目的 `project.json`，挂载其数据库与向量库；同一时刻可多项目切换，检索与操作均限定在当前激活项目内。
* **项目关闭/删除**：关闭时落盘并释放资源；删除项目仅移除 `.cliplens/` 数据目录（含数据库、向量库、缩略图），**不触碰任何原始图片文件**，保证原图安全。
* **项目便携分享**：`.cliplens/` 目录整体拷贝即可迁移/分享项目，图片仍留在原位置，仅记录其绝对路径；对端打开后通过路径校验进行死链提示。

### 3.1 图库扫描与增量建库模块 (Scanner & Indexer Module)

扫描与建库均在**当前激活的 Project 内**进行，所有读写指向该项目的数据目录。

* **增量扫描算法**：
  1. 递归扫描用户指定的图片来源目录，获取文件路径 `path`、大小 `size`、修改时间 `mtime`。
  2. 查询当前 Project 的 SQLite 数据库：若记录不存在，标记为 `NEW`；若 `mtime` 或 `size` 不一致，标记为 `UPDATED`；若数据库存在但磁盘已被删除，标记为 `MISSING`。
  3. 计算增量变更文件列表，仅处理 `NEW` 与 `UPDATED` 图片。

* **缩略图生成流水线**：
  * 使用 Pillow 读取图像并修正 EXIF 旋转方向。
  * 生成 **256×256 WebP** 网格缩略图写入 `thumbs/256/`，文件名使用 `MD5(file_path)`，按 MD5 **前两位一层**分层（如 `thumbs/256/ab/<md5>.webp`）。
  * 预览大图（**1024×1024 WebP**）按需懒生成写入 `thumbs/1024/`，遵循同样的 MD5 前两位一层分层。
  * 两种规格均采用懒加载策略（看一张生成一张），并受容量上限 + LRU 淘汰约束。

* **AI 向量提取流水线**：
  * 将缩略图按 `batch_size=16` 组合为 Tensor Batch。
  * 送入 Chinese-CLIP Vision Encoder 获得 512 维归一化向量，批量写入当前 Project 的 LanceDB。

### 3.2 多模态检索与混合查询模块 (Search Engine Module)

* **文本查询流程**（限定在当前激活的 Project 内）：
  1. 用户输入自然语言文本（如"夕阳下的海边小狗"）。
  2. 调用 Chinese-CLIP Text Encoder 将文本编码为 512 维归一化向量 $V_{text}$。
  3. 在当前 Project 的 LanceDB 中执行 Cosine Distance 向量相似度检索，获取 Top-N 结果 ID 及相似度 Score。

* **混合过滤机制 (Hybrid Query)**：
  * 将向量检索得到的图片 ID 列表与 SQLite 组合过滤：
    $$\text{Final Results} = \text{TopN\_IDs} \cap \{\text{Images} \mid \text{rating} \ge \text{min\_rating} \land \text{is\_deleted} = 0 \land \text{date\_range}\}$$
  * 将融合后的结果集排序并推送到前端视图。

### 3.3 交互与网格视图模块 (UI Virtual Grid Module)

* **虚拟化网格组件 (Virtual ListView)**：
  * 基于 `QListView` 或自定义 `QGraphicsView`，重写 `paintEvent` 和 `data()`。
  * 根据视口滚动位置（Scroll Position）仅渲染当前可见区域（及预加载区域）的卡片节点，避免大体量图片造成内存过载。

* **批量操作与快捷键映射**：
  * 支持 `Ctrl/Cmd + 点击` 多选、`Shift + 点击` 范围选择、`Ctrl + A` 全选。
* **键盘快捷键**：
  * `1`~`5`：直接批量设置当前选中图片的星级评分（同步更新至 SQLite 并刷新 UI）。
  * `0`：清除评分；`Esc`：取消选择/关闭预览对话框。
  * `Delete` 或 `Backspace`：将选中图片标记为"待删除/移入内部回收站"。
  * `Space`：快速预览大图。

### 3.4 文件安全与回收站管理模块 (Trash & File Safety Module)

* **软删除 (Soft Delete)**：
  * 按 `Delete` 时仅在 SQLite 中设置 `is_deleted = 1`，界面实时隐藏该图片，暂不修改磁盘文件。

* **回收站视图与还原**：
  * 提供"回收站"侧边栏，支持批量"恢复"或"彻底删除"。

* **物理删除**：
  * 用户执行"清空回收站"或"物理删除"时，使用 Python `send2trash` 模块将文件移动至操作系统原生回收站（Windows 回收站 / macOS Trash），保障数据的可挽回性。
  * 同步从当前 Project 的 SQLite、LanceDB 和磁盘缩略图缓存中彻底清空记录。

---

## 4. 数据库表结构设计 (Database Schema)

### 4.1 SQLite 关系型数据库结构 (metadata.db)

> 每个 Project 拥有**独立的 `metadata.db`**，存放于其 `.cliplens/` 数据目录中。以下表结构针对单个 Project 内的元数据；`project.json` 额外记录项目全局信息（名称、数据目录、创建时间等）。

```sql
-- 1. 项目信息表（存放于全局配置库 ~/.cliplens/app.db，用于列出/管理所有项目）
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) NOT NULL UNIQUE,    -- 项目名称
    data_dir TEXT NOT NULL,               -- 项目数据目录（.cliplens 所在路径）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_opened_at TIMESTAMP
);

-- 2. 主图片信息表（存放于各项目独立的 metadata.db）
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,       -- 文件绝对路径
    file_name TEXT NOT NULL,              -- 文件名
    file_size INTEGER NOT NULL,           -- 文件大小 (Bytes)
    width INTEGER NOT NULL,               -- 图片原始宽度
    height INTEGER NOT NULL,              -- 图片原始高度
    mtime REAL NOT NULL,                  -- 文件修改时间戳
    md5_hash VARCHAR(32) NOT NULL,        -- 文件哈希（用于全局去重）
    rating INTEGER DEFAULT 0,             -- 评分 (0-5分)
    status VARCHAR(16) DEFAULT 'OK',      -- 状态: OK / CORRUPTED / MISSING
    is_deleted TINYINT DEFAULT 0,         -- 软删除标志 (0:正常, 1:回收站)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_images_path ON images(file_path);
CREATE INDEX idx_images_rating ON images(rating);
CREATE INDEX idx_images_deleted ON images(is_deleted);
CREATE INDEX idx_images_md5 ON images(md5_hash);

-- 3. 标签表
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL
);

-- 4. 图片-标签关联表
CREATE TABLE IF NOT EXISTS image_tags (
    image_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (image_id, tag_id),
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

-- 5. 系统配置表
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL
);
```

### 4.2 LanceDB 向量表结构 (vectors.lancedb)

> 每个 Project 拥有**独立的 `vectors.lancedb`**，存放于其 `.cliplens/` 数据目录中。

* `image_id` (INT64): 关联本项目 SQLite `images.id`
* `vector` (FixedSizeList[512], Float32): CLIP 图像 Embedding
* `updated_at` (TIMESTAMP): 向量创建/更新时间

---

## 5. 异常处理与容错机制

1. **损坏/不支持格式的图片处理**：
   * 扫描解码失败时（如 Pillow 抛出 `UnidentifiedImageError`），在数据库标记 `status = CORRUPTED`，生成默认错误占位图，跳过向量提取。

2. **显存/内存不足 (OOM Handling)**：
   * 自动检测 GPU 显存。若发生 CUDA OOM，自动调低 `batch_size`（16 -> 8 -> 4）或降级至 CPU ONNX Runtime 执行推理。

3. **文件路径失效/孤儿记录**：
   * 启动扫描时校验文件存在性，若已被外部移动或删除，界面提示"清理死链"或在视图中标红展示。

4. **项目数据目录缺失/损坏**：
   * 打开项目时校验 `.cliplens/` 及其中的 `metadata.db`、`vectors.lancedb`。若缺失或损坏，界面提示"项目数据损坏"，提供重建索引或从备份恢复的选项，绝不直接操作原始图片。

5. **项目分享后路径失效**：
   * 项目迁移到其他机器后，原始图片绝对路径可能失效。打开时进行批量路径存在性校验，列出失效项并支持"重新定位目录"将旧路径前缀映射到新位置。

---

## 6. 性能指标与优化策略

* **索引构建吞吐**：CPU (ONNX-INT8) 模式下达到 20~40 张/秒，GPU (CUDA) 模式下达到 150+ 张/秒。
* **检索响应时间**：单项目 10 万张图片规模下，文本特征提取 + 向量检索总耗时小于 **100ms**。
* **界面帧率**：网格快速滚动时保持 **60 FPS**，占用内存控制在 **500MB** 以内。
* **缓存淘汰策略 (LRU Cache)**：内存中仅保留最近浏览的 500 张缩略图对象，防范长时间使用下的内存泄露。
* **项目隔离开销**：因数据库/向量/缩略图按项目隔离，单库规模相对可控；项目切换仅挂载对应数据目录，不影响其他项目。缩略图采用 WebP 并支持懒加载（看一张生成一张）与容量上限 + LRU 淘汰，控制磁盘占用。

---

## 7. 后续可扩展性规划

1. **多模型热切换**：架构上留出 `BaseCLIPModel` 抽象基类，方便后续继承支持 Qwen2-VL、OpenCLIP 或本地人脸识别模型。
2. **自动打标与智能聚类**：利用 Zero-shot 分类能力对导入的图片进行场景（如风景、美食、人像、文档）自动分类打标。
3. **插件扩展接口**：提供简单插件钩子（Plugin Hooks），允许扩展自定义导出、图片压缩或滤镜批处理功能。
4. **跨项目检索**：当前检索限定在单个 Project 内；可扩展"跨项目检索"能力，对多个项目的向量库并行检索后合并去重（按 MD5）返回结果。
5. **项目模板与导入/导出**：支持预设项目模板（如"相册""素材库"），以及将项目导出为可分享包（数据库 + 缩略图），对端导入后自动定位图片路径。
