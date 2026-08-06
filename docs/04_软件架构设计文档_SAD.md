# ClipLens 软件架构设计文档 (Software Architecture Design, SAD)

| 项目名称 | ClipLens |
|---------|----------|
| 版本 | v1.0 |
| 日期 | 2026-08-06 |

---

## 1. 架构目标

| 目标 | 说明 |
|------|------|
| 完全本地化 | 无网络依赖，数据与推理全本地 |
| 高响应 | 海量图片下流畅检索与浏览 |
| 项目隔离 | 数据按 Project 隔离，原图不动 |
| 可扩展 | 预留多模型、插件、跨项目检索扩展点 |

---

## 2. 架构风格

采用**分层架构 + 事件驱动（Qt 信号槽）**的组合风格，单进程多线程。

### 2.1 逻辑分层

```
┌─────────────────────────────────────────────┐
│               UI 表现层 (PySide6)             │
│  网格视图 | 搜索栏 | 过滤器 | 预览 | 项目面板   │
└──────────────────┬──────────────────────────┘
                   │ Qt 信号/槽
┌──────────────────▼──────────────────────────┐
│              业务逻辑层                       │
│ ProjectManager | Scanner | SearchEngine      │
│ BatchManager | TrashManager                  │
└──────────────────┬──────────────────────────┘
                   │ 调用
┌──────────────────▼──────────────────────────┐
│            AI 推理与引擎层                    │
│  Chinese-CLIP Feature Extractor (PyTorch/ONNX)│
└──────────────────┬──────────────────────────┘
                   │ 读写
┌──────────────────▼──────────────────────────┐
│        数据持久化与文件层                     │
│  SQLite | LanceDB | 缩略图文件系统            │
└─────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
main.py
 └── AppController（应用入口，初始化项目管理器与主窗口）
      ├── ProjectManager ──> MetadataDB / VectorStore / ThumbnailStore
      ├── MainWindow (UI)
      │     ├── VirtualGridView
      │     ├── SearchBar
      │     └── SidebarFilter
      ├── SearchEngine ──> CLIPTextEncoder / VectorStore
      ├── ScannerController ──> ScannerWorker / ThumbnailGenerator / VectorIndexer
      ├── BatchManager ──> MetadataDB
      └── TrashManager ──> MetadataDB / send2trash
```

---

## 3. 线程与并发架构

| 线程 | 职责 | 关键约束 |
|------|------|---------|
| GUI 主线程 | 界面事件、重绘 | 不执行模型加载/解码/检索 |
| Model Inference Worker | CLIP 批量编码 | 控制 batch_size，OOM 降级 |
| I/O Worker Pool | 扫描、缩略图、缓存 | 与 UI 信号槽通信 |

**并发控制**：
- 模型推理串行化，避免多线程争用 GPU。
- 缩略图生成走线程池，结果经信号回传主线程更新网格。
- **SQLite 单写者模型**：所有 SQLite 写入操作（评分、标签、删除、扫描入库）必须经过唯一的 **DB Writer 线程**串行执行；SQLite 连接采用 `check_same_thread=False` 且由该写线程独占。读取可并行，但跨线程仍通过 Qt 信号传递结果。
- **缩略图写入不涉及元数据更新**：缩略图只是纯文件写入，磁盘路径由其自身的 `MD5` 决定，无状态冲突；不更新 `images.updated_at`，避免与 DB Writer 竞争。若未来需要记录缩略图状态，统一交由 DB Writer 执行。
- **双库（SQLite + LanceDB）一致性**：向量写入与元数据写入放入同一事务流程——先写 SQLite，再写 LanceDB；若 LanceDB 写入失败，回滚 SQLite 并记录待补偿任务（见可靠性设计），避免"有元数据无向量"的孤儿记录。物理删除同理：先清理 LanceDB 向量，再删 SQLite 记录，失败则进入补偿队列重试。

---

## 4. 关键技术决策

### 4.1 为什么用 SQLite + LanceDB 双库？
- **SQLite**：关系型元数据（评分/标签/状态），事务支持好，轻量无服务。
- **LanceDB**：专为向量近邻检索设计，嵌入式，支持持久化，检索性能优。
- 两者以 `image_id` 关联。

### 4.2 为什么按 Project 隔离数据库？
- 逻辑隔离：不同项目互不干扰，删除项目只删 `.cliplens/`。
- 便携分享：项目数据目录整体拷贝即可迁移。
- 单库规模可控，检索性能稳定。

### 4.3 为什么缩略图用 WebP + 懒加载？
- WebP 压缩比高，省磁盘；懒加载按需生成，避免一次性全量生成 10 万张。
- LRU + 容量上限控制无界增长。

---

## 5. 可靠性设计

- **容错**：损坏图片、OOM、死链、项目损坏均有兜底策略（见 SDD 第 5 章）。
- **防误删**：软删除先行，物理删除走系统回收站。
- **事务**：批量写操作包在事务中，保证一致性。

### 5.1 SQLite + LanceDB 双库一致性保障

采用**事务补偿 + 启动校验**两层机制：

1. **写入侧（补偿日志）**：
   - 新建索引：先写 SQLite，再写 LanceDB 向量。若 LanceDB 失败，回滚 SQLite 记录，并将该 `image_id` 写入 `system_config` 的 `pending_index`（JSON 数组），由后台重试。
   - 物理删除：先清 LanceDB 向量，再删 SQLite 记录。任一步失败，记录到 `pending_cleanup` 待重试。
2. **启动校验（对账）**：
   - 启动时比对 SQLite `images.id` 与 LanceDB `image_id` 集合，找出"有元数据无向量"与"有向量无元数据"的孤儿记录，自动清理或重建。
3. **检索兜底**：向量检索返回的 `image_id` 若在 SQLite 中不存在（或 `is_deleted=1`），过滤掉并触发对账清理。

---

## 6. 扩展性设计

| 扩展点 | 方案 |
|--------|------|
| 多模型 | `BaseCLIPModel` 抽象基类，可插拔 Qwen2-VL/OpenCLIP |
| 插件 | Plugin Hooks 钩子接口 |
| 跨项目检索 | 多向量库并行检索 + MD5 去重 |
| 自动打标 | Zero-shot 分类，扩展 tags 写入 |

---

## 7. 部署形态

- 打包为桌面应用（PyInstaller/PyOxidizer）。
- 运行时按需下载/使用本地 Chinese-CLIP 权重。
- 数据库目录遵循平台约定（Windows `%USERPROFILE%/.cliplens`，macOS/Linux `~/.cliplens`）。

详见《08_部署与发布说明.md》。
