# 数据一致性核对（2026-10-19）

本轮基于本地分支 `b0db280`，只核对已导入的 TCMSP 历史样本。没有修改原始工作簿或来源 SQLite，没有扩大导入范围、调用模型或外部生物数据库，也没有推送远程。

## 逐层核对结果

原表 `Sheet1!A1:C101` 包含表头和 100 行数据，列为中药、成分、靶点基因。按原始行号核对字段和关系，不只比较总数。

| 层级 | 本机结果 |
| --- | --- |
| 原表与样本 SQLite | 100 行逐行一致，每行原始文件 SHA-256、工作表、原行号均对应；原件哈希未变化 |
| 样本与 Django 目录 | 1 个中药、55 个成分、17 个靶点名称，共 73 实体、200 条来源关系；无缺失或多余关系 |
| 真实 HTTP 检索与保存的任务 | 实体 ID、关系 ID、名称、两端身份、原始记录号、来源版本和检索哈希一致 |
| 保存的关系与 R 图输入 | 73 个节点、155 对不同端点连线一致；200 条来源记录完整保留，重复端点在 R 图中合并 |
| 私有图表文件 | SVG/PNG/PDF/HTML 四格式字节哈希与记录一致，所有者与父任务一致 |

审计结果为 22 项检查通过，详情在忽略目录 `python_app/var/legacy-consistency-audit.json`。任务为 11、绘图任务为 12。将临时提取副本中的两行靶点交换后，总行数与关系数不变，审计仍报告 2 条缺失/2 条多余并以失败状态退出；原件和数据库未动。这验证核对并非只看总数。

## 与冻结 main 的对照

实际执行 `backend/data_service.py` 的冻结函数，输入为相同 100 行，其他四个来源提供空表，不发现外部目录或读取全量数据。参考代码 SHA-256 为 `7fae7384a64b236d787696fbe1288c583d680df59054e8592cd93f60897aa6f9`。

- main 的 Excel 检索：55 成分、18 靶点、100 条原表链接。
- main 的 SQLite 缓存检索：55 成分、17 个 distinct 靶点、100 条原表链接；但链接数组拆出的靶点为 18 个，内部口径不一致。
- 原因定位到原表 C5：单个蛋白全名中的逗号被旧拆分器当成多靶点分隔符。
- 当前 single 配置保留这个完整名称，得到 17 个靶点名称。该差异保留在审计报告中，不把复制错误统计当作复刻完成。

原工作簿 SHA-256 为 `1482cd795f3396b917bebf74046009a1a529e71c2984d8aa376fa4069777d986`。仅说明所核对样本与原件一致，不证明旧数据库本身的生物学真实性、时效或许可状态。

## 修补的分析问题

通过新增回归先复现了 7 类失败，再修补蛋白组学本地映射路径：

1. 停用的数据源不再通过实体、外部标识别名、关系或通路端点重新进入新分析；这与知识目录的可见范围一致。
2. `identifierStatus=name_only` 的旧库命中保留实体和平台标识溯源，规范基因符号留空，显示为未映射并记录 QC 提示。`unverified_symbol` 仍为未核实候选，不能因为入库就计作已确认的本地基因映射。不会猜测 HGNC/UniProt 身份。
3. 所有逐行结果中输出的有效标识版本均加入任务来源，包括未通过差异筛选的行；通路实体与关系来源不同的版本也保留。停用来源的标识不导出。

算法版本为 `proteomics-py-1.7`。这是新任务的行为修正，不修改既有 `1.6` 任务、原上传文件或历史图表。差异阈值、原始矩阵统计方法和原始标签保持不变。

真实 HTTP/Celery 验收使用明确标记的合成数值 CSV：2 个旧库蛋白名称和 1 个符号候选。任务 13 选择了 3 行，旧名称保留为 2 个未映射命中，TP53 为 1 个未核实候选，已确认本地映射为 0；原始名称、来源及 CSV 导出保留，跨账号读取拒绝。报告在 `python_app/var/mapping-consistency-acceptance.json`。没有用这些合成数值作真实实验验证。

同一数据集再用较高阈值执行任务 14：0 行通过筛选，仍保留 3 行原始结果、2 行平台标识和来源版本 2。报告为 `python_app/var/unselected-mapping-acceptance.json`。353 项 Django 全套回归、迁移漂移和 OpenAPI 检查通过，既有 UI 的状态文字和 QC 原因也补充了中文说明。

## 重跑方式

在仓库根目录执行。第一步使用桌面依赖提供的 Python（含 pandas/openpyxl）；第二步使用项目 Django 虚拟环境。原件和生成 JSON 都在忽略目录，不进 Git。

```sh
<bundled-python> tools/audit_legacy_consistency.py extract \
  python_app/var/legacy-inputs/tcmsp全部数据.xlsx --rows 100 \
  --output python_app/var/legacy-source-extracted-audit.json

python_app/.venv/bin/python tools/audit_legacy_consistency.py compare \
  python_app/var/legacy-source-extracted-audit.json --source-id 5 --task-id 11 --http \
  --output python_app/var/legacy-consistency-audit.json

python_app/.venv/bin/python tools/smoke_mapping_consistency.py
```

`--http` 要求本地预览服务和已有验收管理员凭据；最后一条命令会新增并保留合成数据集和分析任务。审计 compare 不创建分析任务。报告必须是独立 JSON，不能覆盖原输入或写入来源数据库目录。

## 尚未完成的核对

- 其他四个旧来源及 TCMSP 剩余原始行还未逐条对照或全量导入。
- 样本的 17 个靶点均只有名称。跨来源规范 ID、物种、别名、同名歧义仍需与可核验的 HGNC/UniProt 等对照数据匹配，不能凭名称自动确认。
- 真实实验数据的统计结果对照、外部服务实际映射和生产 PostgreSQL 并发不属于本次样本一致性证明。

8 项来源一致性回归覆盖了停用来源、名称与符号状态、来源版本和未筛选行；后端全套检查及实际链路结果记录在本地验收文档中。
