# 疾病检索完整保存与导出验收（2026-10-21）

## 本次完成

将上一轮中药/网络药理的完整证据机制接入已有疾病检索。原疾病别名展开、来源筛选、关系类型与统计算法保留；界面沿用现有工作台、表格和样式，在原结果区补充完整保存、任务进度、历史恢复和完整表下载。

原预览仍最多返回 20 个疾病匹配、1,200 条来源关系，原 CSV/JSON 只代表本次预览响应。新增“保存完整疾病查询”交给 Celery 读取完整范围，保存后通过服务器分页、CSV 或整个任务 JSONL 查看证据，完整导出不受预览的 1,200 条或旧表格 4,000 行限制。

此处“完整”指本次查询在启用来源中的有效输入，仍受后台资源保护，并不代表全世界疾病知识或已核实的生物学真相。

## 身份、一致性和权限

- 预览校验值覆盖显示结果、真实实体 ID、来源关系 ID、来源版本与行号等元数据。排队期间这些输入变化，后台要求重新检索，不把新目录结果冒充原预览。
- PostgreSQL 在同一 repeatable read 事务内重读预览和完整输入；成功状态与冻结表一起提交，失败不发布部分结果。
- 中药—疾病—靶点关联保留疾病、中药、靶点、来源关系和来源版本 ID。同名实体不合并；三元记录只有实际规范关联键能解析到活动中药时才关联，不能解析的记录仍保留，`herbId` 为空，不按名称猜配。
- 冻结四张表：`evidenceRecords`、`entities`、`diseaseLinks`、`queries`。每表有行数和 SHA-256，整个任务也有快照校验值。以后停用来源或修改目录标签，不改变已保存记录和导出。
- 复用既有私有快照接口与敏感访问审计。研究者只能读取自己的任务，其他研究者返回 404，超级管理员沿用已有查看权限。所有者/创建者由后端身份确定，忽略客户端越权字段。
- 后台疾病匹配最多 1,000 个；关系数使用既有 `LOCAL_ANALYSIS_RELATION_LIMIT`（默认 50,000、硬上限 100,000）。超过保护额度明确失败，不截断后标记成功；本轮没有调大容量配置或进行并发测压。
- 无匹配疾病不产生成功快照；确有疾病实体但没有关系时可以保存零关系快照，二者有明确区别。前端无匹配时禁用完整保存。

## 接口和页面

```text
GET  /api/v1/catalog/diseases/evidence-search/?query=疾病名
POST /api/v1/catalog/diseases/evidence-analyses/
     {"query": "疾病名", "expectedResultSha256": "预览返回的64位校验值"}
GET  /api/v1/research/analysis-tasks/{id}/
GET  /api/v1/research/analysis-tasks/{id}/snapshot-rows/?table=diseaseLinks&page=1&page_size=20
GET  /api/v1/research/analysis-tasks/{id}/snapshot-export/?table=diseaseLinks&file_format=csv
GET  /api/v1/research/analysis-tasks/{id}/snapshot-export/?file_format=jsonl
```

新建接口返回 202 和任务编号；队列不可用返回受控 503，保留明确失败记录。任务类型沿用已有 `network`，以 `analysisKind: disease_evidence` 区分，疾病算法适配版本为 `disease-evidence-1`，共用 `complete-local-evidence-1` 快照机制。

`/research?diseaseTask={id}` 可以恢复自己的已有任务；总览近期记录也指向该地址。临时读取失败重试 GET，避免重复提交；旧响应、跨查询响应、错误任务类型和无效编号不会绑定到当前结果。没有增加模型调用、外部请求或新的研究算法。

## 自动化验收

测试均在一次性数据库运行，队列提交统一 mock，不向工作库导入合成目录。

| 项目 | 结果与证明范围 |
| --- | --- |
| PostgreSQL 后端 | 506 项全部通过；包括新增 10 项疾病快照用例及并发目录更新的一致读取 |
| SQLite 后端 | 执行 506 项，503 项通过、3 项跳过；跳过项均依赖 PostgreSQL 并发/行锁机制 |
| 大于预览/旧导出上限 | 4,005 条**合成**疾病—靶点关系：预览 1,200，完整结果/CSV 4,005，关系与靶点 ID 集合、每表哈希、首/中/尾页均一致 |
| 超过疾病预览数量 | 21 个真实匹配的合成实体全部进入完整快照；JSON 同义词字典的键不当作同义词值 |
| 身份与历史 | 同名中药仅按实际稳定关联键解析；未知/停用/缺键不猜配；修改来源行号使预览校验失效；成功后改目录不改导出 |
| 失败与权限 | 超限、无匹配、队列失败、未登录、越权、未知任务种类均明确处理，无部分成功快照 |
| 前端 | `test:api`、`test:research`、`test:network` 通过；覆盖疾病保存防重复、读取重试、刷新恢复、过期响应和错误结果拒绝 |
| 构建与定义 | `build:delivery` 通过，保留 14 类演示图与 56 个已有工件检查；OpenAPI 严格验证通过；无新增数据库迁移，diff 格式检查通过 |

这些测试证明程序在受控样例下的读取、保存、导出和权限行为，不证明疾病来源资料、物种或权威数据库编号已经验收。

## 本地真实链路与数据缺口

当前 PostgreSQL 工作库没有活动的疾病目录记录，因此本轮**没有疾病正式数据成功验收**。没有为演示效果向工作库补造疾病关系。

本地实际会话/CSRF、Vite 代理、Redis、Celery 新建任务 **#23**，查询词为明确标注的 `SYNTHETIC_NOT_IN_CATALOG_DISEASE_20261021`。任务按预期失败，提示“当前启用目录没有匹配疾病，请确认名称或导入数据后重试。”；无冻结行、无结果下载，其他研究者读取返回 404。只保留这一条失败测试记录；原研究任务输入、结果、归属和整个目录内容哈希不变，正常登录/读取审计可新增。

实际浏览器在疾病标签查询“肺纤维化”，显示零匹配及缺少目录记录提示，完整保存按钮禁用。随后通过 `diseaseTask=23` 恢复已失败的测试任务，正确还原查询词及无匹配提示，未重复创建任务。既有内嵌浏览器旧标签连接超时后，使用临时标签完成这项核验，没有修改浏览器认证配置，验收后关闭临时标签。

接口成功、大量导出和生物学结果仍需在导入正式疾病来源后复验。模型及 STRING/Reactome/ChEMBL 等外部业务服务继续暂缓；HIT 62 行缺少靶点名称仍不处理。旧 AI Scientist 专用流程仍待迁移，Reactome 旧历史仍需实际历史数据，不能把本轮疾病快照接入当成这些功能已完成。

## 复核材料与运行

新增自动化：`python_app/apps/core/tests/test_complete_disease_evidence.py`、`web/tests/disease-evidence-snapshot.cjs`；本机链路工具：`tools/smoke_disease_evidence.py`。本机报告与截图放在 Git 忽略目录：

```text
python_app/var/disease-complete-2026-10-21/http-no-match.json
python_app/var/disease-complete-2026-10-21/disease-evidence-empty-section-2026-10-21.jpg
python_app/var/disease-complete-2026-10-21/disease-evidence-restored-2026-10-21.jpg
python_app/var/disease-complete-2026-10-21/  # 本次回归日志
```

API 和 worker 已重启加载改动，前端仍在 `http://127.0.0.1:5174/`；本轮不新增迁移，部署仍依赖上一轮的 `core.0028_analysissnapshotrow`。代码仅保存本地 Git，不推送远程。
