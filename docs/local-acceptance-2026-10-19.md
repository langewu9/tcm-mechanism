# 本地修补与验收进展（2026-10-19）

基线：`codex/collaboration-priority-fixes@5e0466e`。本轮只在本地继续，未推送或合并远程。

## 按约定顺序完成的内容

| 顺序 | 工作 | 本机结果与范围 |
| --- | --- | --- |
| 1 | 数据长期保留与权限 | 数据集/医案改为归档和恢复，保护原件、用户归属与操作人；原件禁止覆盖。自动测试和真实 HTTP 的 A/B 账号隔离通过。详见 `research-retention.md`。 |
| 2 | 后台任务与导出 | Redis/Celery 已真实启动；合成 CSV 上传、后台筛选、行级结果、CSV/XLSX/PDF 导出通过。 |
| 3 | R 服务和演示图库 | 14 种现有图实际生成 56 份 SVG/PNG/PDF/HTML 产物；manifest、类型和哈希检查及交付构建通过。真实工作区的 R 概览/火山图生成 8 个私有工件，下载哈希与跨账号拒绝访问通过。 |
| 4 | 旧数据导入与字段核对 | 找到用户原先提供的旧项目压缩包，核对了 main 对应的五个药理工作表表头；只取旧 TCMSP 的 100 行做本地试导入，未全量导入。最终有 1 个中药、55 个成分、17 个靶点名称，共 73 个有效实体和 200 条来源关系。 |
| 5 | 模型、外部接口和生产环境 | 继续暂缓。没有调用真实模型或外部生物数据库，没有公网部署。 |

## 本地运行

- 前端 `http://127.0.0.1:5173/`；Django `127.0.0.1:8020`；Redis `127.0.0.1:6389`；私有 R `127.0.0.1:8001`。
- 数据库是 `python_app/var/local-preview.sqlite3`，是本机预览库。迁移和旧数据试导入前已分别备份到 `python_app/var/backups/`。
- `.env`、账号凭据、本地运行依赖、上传文件、数据库、旧表原件及生成图表均不进 Git。
- 本地 Redis 8.0.5、Celery solo worker、R 4.5.2，绘图器仍为 `r-viz-0.2.0`；R 包为 Ubuntu 软件源版本。本次不是生产 Compose 的 Redis 7/R 4.4.3/renv 固定版本容器验收，也不提供多人并发能力证明。
- 当前 Docker 套接字需本机 sudo 认证；本轮使用项目 `var/local-runtime/` 内的 Ubuntu 软件包运行文件，没有安装系统级服务。

重启时在仓库根目录分别开终端运行，每行一个终端：

```sh
python_app/.venv/bin/python tools/local_preview.py redis
python_app/.venv/bin/python tools/local_preview.py r
python_app/.venv/bin/python tools/local_preview.py worker
python_app/.venv/bin/python tools/local_preview.py api
python_app/.venv/bin/python tools/local_preview.py web
```

这些命令复用本机已有依赖和 `.env`，不安装依赖、不初始化数据库。模型和定时同步仍须显式配置。

## 真实链路证据

`tools/smoke_local_workspace.py` 固定访问本机，且要求 DEBUG + SQLite，使用独立的合成验收账号和记录。该脚本会保留新增合成样例，不伪造已完成任务。

- 合成差异表共 4 行：TP53/EGFR 通过阈值，GAPDH 未通过，错误数值行被排除，筛选结果为 2 行。
- CSV、流式 XLSX 和 PDF 均下载验证；XLSX 按实际迭代行检查，不依赖可选的工作表 dimension。
- R 由真实 worker 请求，两个图各产生四种私有文件，验证下载 SHA-256。研究者 B 读取 A 的资料、任务、结果和工件均返回 404。
- 归档后原文件字节仍与上传内容一致；管理员恢复后所有者仍为研究者 A。医案恢复后正文和来源仍在。
- 详细验收记录在忽略目录 `python_app/var/local-acceptance-result.json`。合成样例有清楚标记，不是研究数据或模型输出。

## 旧数据试导入与发现的问题

只读核对的工作表与 main 的 `SOURCE_FILES` 字段映射一致：BATMAN、HERB、HIT、TCMIP、TCMSP。原压缩包和工作簿未被修改。工作表声明行数不等于已核实的有效记录数。

TCMSP 试导入取 `Sheet1` 第 2–101 行。原 XLSX SHA-256 为 `1482cd795f3396b917bebf74046009a1a529e71c2984d8aa376fa4069777d986`；生成 SQLite 中保留原工作表行号和文件哈希，另有来源清单。数据库连接器的快照哈希包含文件名、数据库字节以及存在时的 WAL，与普通文件 SHA-256 的范围不同。

本地来源名称明确为“TCMSP 旧版样本（100 行，仅本地验收）”，没有将它标记为完整或最新数据集。真实 HTTP/worker 通过了连接检查、只读预览、应用、重复应用拒绝和来源版本/记录溯源。

发现并修补：

1. main 的旧缓存构建器重新遍历工作表时会把表头当成数据，三类表均已改为从第二行读取。保留原 `backend/data_service.py` 作为冻结对照，列映射由不依赖 pandas 的独立模块供缓存构建器使用，并通过测试核对与冻结 main 完全一致。
2. “靶点基因”列实际包含蛋白全名；明显的名称不再自动写入 symbol，形似符号的值也明确标为未核实，没有声称 HGNC/UniProt 映射完成。
3. 单个蛋白名称中的逗号曾被拆为两个靶点。新增 `targetCellMode=single|list`，旧缓存默认 list 保持兼容；本样本设为 single，保留名称内标点。来源表单提供相应选择。

第一次 list 配置试导入得到的 74 实体/201 关系属于已纠正的历史结果。single 配置产生新的来源版本，最终有效结果为 73 实体/200 关系，旧错误记录停用且历史保留。最终记录为 `python_app/var/legacy-source-acceptance-final.json`，其中预览 ID 3、应用 ID 4。

全量旧库、跨来源同名歧义、规范基因/蛋白标识、来源许可和真实科研结果对照仍待进一步核实；100 行样本通过不等于五个旧库已完成迁入。源文件和预览准备工具为 `tools/prepare_legacy_preview.py`，它拒绝覆盖已存在的预览文件，不覆盖原工作簿。

## 自动检查

- 最新 338 项 Django 测试、迁移漂移检查、OpenAPI 校验通过。
- 前端全套已有离线回归通过；新增来源选项后，来源管理/演示回归与 TypeScript、交付构建再次通过。
- R 合成 fixture 4 项测试通过；14 key 和 56 导出在源目录及构建目录均通过类型/哈希检查。
- 修正 GitHub workflow 的 job 级 `env` 使用不支持的 `runner.temp` 上下文，改为独立 CI 临时目录。YAML 解析通过；没有推送触发 GitHub，因此不宣称远程 CI 已转绿。依据 GitHub 上下文可用范围说明：<https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability>。

## 尚未通过的正式验收

界面检查已实际加载资产页，确认归档筛选和按钮存在。点击合成样例归档时，浏览器原生确认框使自动控制阻塞，已请求人工取消；本轮没有把浏览器点选归档/恢复或 Blob 文件落盘记录为通过。接口层相应流程已通过。该浏览器工具问题与后台任务或权限接口验收分别记录。

- 全量旧数据导入、规范标识交叉映射和真实研究样例结果对照。
- 实际模型、SMTP、S3、外部 STRING/Reactome/ChEMBL/g:Profiler 查询。
- Linux 生产容器固定依赖、PostgreSQL 并发、TLS、恢复演练、负载及移动端/无障碍完整验收。
- PCA、热图、GSEA、R 交互网络及旧 AI Scientist 缺失依赖仍属于后续开发范围。
