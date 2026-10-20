# PostgreSQL、原始编号与恢复验收（2026-10-20）

基线 `codex/collaboration-priority-fixes@5e3fb99`。本轮完成下一阶段的本地 PostgreSQL 链路、带原始编号的小批量旧数据核对和独立恢复演练；没有扩大业务模块或更改页面布局。代码保留在本地 Git，本轮未推送。

## 实际改动

- 复用 main 的 `backend/source_catalog.py` 列映射和现有 SQLite → Django 预览/人工应用流程。来源配置可选 `rowMetadataColumn`，目前准备工具只对已核对的 HIT 列启用原始编号模式。未选择该参数的来源沿用原规则，不自动重算旧任务。
- 导入保留中药、成分、靶点的来源编号、原工作表行号、文件哈希和全部 16 列原值。同一来源/实体类型的编号区分大小写；同名不同编号分别保留，同一编号断言冲突则拒绝整次应用。编号使用独立 `:id:` 命名空间，避免与旧名称哈希碰撞。
- 编号策略 `source-identifier-namespace-1` 纳入预览配置指纹。规则或配置变化后要求重新预览并创建新的来源版本；旧关系停用、历史保留。重复导入保持实体 ID 不变。
- 查询和保存的图谱快照保留来源编号及断言。蛋白组学新任务版本为 `proteomics-py-1.8`，导出 `source_entity`、`source_reported_uniprot` 等待核对标识；它们不会加入规范外部标识表或作为 accession 自动匹配依据。统计方法和阈值未变，历史任务不重算。
- 开发代理可通过 `TCM_API_PROXY_TARGET` 指向隔离 API，默认仍是 8020。Django 会话和 CSRF Cookie 名称可配置，默认保持不变。前端组件、CSS 和业务页面没有修改。

## 数据依据和边界

只读使用原先提供的压缩包中的 `HIT数据库全部.xlsx`，校验后的本地副本 SHA-256：

```text
8d9f3fa51f6c12d55799acd3cef8cf9a9be3ef99fc3be62a04e093f7614ad1e0
```

核对范围为 `Sheet1!A1:P101`，表头加 100 行数据。100 行共有 10 个中药编号、4 个成分编号、49 个靶点编号，全部原值和行号保留。原工作簿未修改；没有读取或导入患者医案文件。

表中的 `Uniprot`、`Pubchem ID`、`Chembl ID` 是来源提供的断言，没有经过权威目录确认。表内没有靶点物种字段；`Latin_name` 是中药拉丁名，不能当作靶点物种。不能仅凭 MAPK1、Bcl2l1 或 accession 格式认定人类或规范映射。因此 49 个靶点保持物种空缺、符号未核实，规范 `EntityIdentifier` 新增为 0。此处是来源身份保留，不是完成跨库主键统一。

蛋白组学验收 CSV 使用上述表中的三个标签和明确合成的数值，并非实验测量，也不能用来验证生物学结论。

## 独立运行环境

| 项目 | 本轮配置 |
| --- | --- |
| 前端 | `http://127.0.0.1:5174/` |
| API | `127.0.0.1:8021` |
| PostgreSQL | 17.11，`127.0.0.1:55439`，库 `tcm_acceptance` |
| 队列 / 缓存 | 既有 Redis 6389 的独立 DB4 / DB5 |
| 文件 / 来源 | `python_app/var/postgres-acceptance/media/`、`source-databases/` |
| Cookie | `tcm_pg_session`、`tcm_pg_csrf` |
| R | 复用本机私有 8001 服务，仅接收绘图摘要 |

原来的 5173 / 8020 / SQLite 预览及文件继续保留。模型地址置空、定时同步关闭；本轮没有调用模型或外部生物数据库。

Docker 套接字需要本机交互式 sudo，本轮没有修改它。使用官方 PGDG 软件包中提取的 PostgreSQL 17.11 运行文件，以普通用户运行独立集群，未安装系统级 PostgreSQL 服务。包版本及 SHA-256 核对记录在私有目录 `runtime/packages.json`。这不等于生产 Compose 镜像或系统服务已验收。

`tools/postgres_acceptance.py` 是本机已准备环境的启动器，不是全新机器安装器。它要求忽略目录内已有运行文件、集群和私有 `profile.json`；凭据没有写进源码。既有 Redis/R 启动后，分别运行：

```sh
python_app/.venv/bin/python tools/postgres_acceptance.py postgres
python_app/.venv/bin/python tools/postgres_acceptance.py api
python_app/.venv/bin/python tools/postgres_acceptance.py worker
python_app/.venv/bin/python tools/postgres_acceptance.py web
```

每条命令使用一个终端，已运行的服务无需重复启动。验收账号为本机专用账号，随机凭据保存在忽略的 `accounts.json` 中，不沿用原预览账号。

## 验收结果

`tools/smoke_postgres_acceptance.py` 经过真实前端代理、Django、PostgreSQL、Celery 和 R，不是预填健康灯：

| 检查 | 结果 |
| --- | --- |
| 连接检查、预览、人工应用 | 100 行；有效实体 63、来源关系 200 |
| 原始编号及 16 列逐行核对 | 通过，行号与工作簿哈希保留 |
| 重复应用 / 重复导入 | 同一预览重复应用拒绝；重新预览导入后 63 个实体主键保持一致 |
| 中药批量检索和保存图谱 | 63 节点、200 条来源记录、63 对去重端点连线 |
| R 关系图与火山图 | 各生成 SVG/PNG/PDF/HTML，共 8 份，下载哈希一致 |
| 合成数值分析 | 3 行未核实候选，规范数据库映射为 0；原编号与待核对 UniProt 保留 |
| CSV/XLSX/PDF 导出 | 实际下载通过，CSV 含来源编号 |
| 私有权限 | 研究者 B 读取 A 的任务、导出、图表返回 404；管理员读取仍保留 A 的所有权 |
| 数据集归档/恢复 | 原件字节不变，管理员恢复后仍属于 A |

最终图谱任务 5、R 子任务 6、数据集 2、蛋白组学任务 7、火山图子任务 8。编号命名空间修正前产生的本机历史任务 1–4 保留，旧实体/关系已停用，未覆盖历史快照。上述来源编号 5 仅属于本轮 PostgreSQL 数据库，不能与旧 SQLite 数据库的相同数字混用。

最终自动检查：PostgreSQL **383 项**、独立 SQLite **383 项**全部通过；Django check、迁移漂移、OpenAPI 校验通过；前端所有 `test:*` 脚本及 `build:delivery` 通过，14 图/56 演示工件完整。初次直接执行构建字符串时缺少 pnpm 注入的 `node_modules/.bin`，随后用 pnpm 正式脚本构建通过。实际 R 火山图 PNG 已查看，中文和阈值可读；三行合成数据数值相同，因此点重叠，不能据此评估真实密集数据绘图效果。

本轮接口验收与离线前端回归不等于新增浏览器点选验收；全站像素对照、浏览器文件落盘及多人并发仍未宣称通过。

## 备份和独立恢复

`tools/rehearse_postgres_restore.py` 用 PostgreSQL 17 的 `pg_dump` 自定义格式，备份验收库及私有媒体、来源 SQLite/manifest；恢复到新库和新目录，没有删除或覆盖原库。

实测恢复库 `tcm_acceptance_restore_20261020_010243_777055`：

- 27 张 public 表逐行排序哈希、行数，以及 26 个序列的值/调用状态完全一致。
- 157 个私有目录文件、2 个来源文件的大小与 SHA-256 完全一致。其中 18 个数据库登记的原件/图表文件再次逐项核对。
- 恢复库经真实 Django 视图再次验证原件及图表下载、B 账号拒绝、管理员读取保留原所有者、历史图谱来源快照。
- 恢复完成后再次核对原库、原媒体和来源文件，均未变化。

备份在本机 `python_app/var/postgres-acceptance/backups/20261020_010243_777055/`。这证明本机恢复路径可用，不是异地备份、加密备份、定时保留策略或生产灾难恢复验收。

可在验收环境空闲时重跑下列命令；它们会保留新增验收记录及新的恢复库，不会自动清理旧版本：

```sh
python_app/.venv/bin/python tools/smoke_postgres_acceptance.py
python_app/.venv/bin/python tools/rehearse_postgres_restore.py
```

详细机器记录均在忽略目录 `python_app/var/postgres-acceptance/`：`acceptance-result.json`、`restore-result.json`、`tests-final.log`、`tests-sqlite.log`、`frontend-tests.log`、`frontend-build.log`、`schema-checks.log` 和备份 manifest。凭据、数据库、原表、上传文件及图表未进入 Git。

## 下一步

先扩大同输入的 main ↔ 新平台查询、计数和逐行结果对照，再考虑扩大旧数据导入。需继续核对跨库同名歧义、物种、正式 accession 与来源许可；不能把当前保存的编号直接提升为规范身份。真实实验数据、模型/外部数据接口、固定版本生产容器、SMTP/S3/TLS、并发压测及异地恢复仍按原计划单独验收。
