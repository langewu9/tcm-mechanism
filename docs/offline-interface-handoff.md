# 当前可测功能与待接服务接口

2026-10-22 最新状态：`POST /api/v1/research/assistant/` 已支持 `mode=scientist_hypothesis`，明确填写问题、疾病和中药组成，本地模式拒绝模型同意；复用已有任务、完整证据及私有导出。管理员 Scientist 检查现为实际本地只读诊断，旧 501 已移除。工作库、浏览器和 PostgreSQL 验收详见 [本地报告验收](scientist-local-acceptance-2026-10-22.md)。下方初期“未迁移/服务未实测”是历史状态，模型和外部分析仍暂缓。

2026-10-04 范围：以 `origin/main@078d374` 的已有源码为参考，先完成当前能以本地目录、合成输入和离线契约验证的功能。真实模型、外部研究数据、R/队列/生产服务的实测暂缓；接口代码、输入校验、用户权限、任务状态、统一错误和模拟响应验证继续完成。main 没有的扩展业务不在本轮新增。

“接口已准备”表示路由、任务及连接器已有实现并可用模拟响应验证，不表示真实服务已连通，也不表示历史数据已导入。源码/真实输入尚不能核对的旧功能继续标明未迁入。

## 本轮完成

- 后续检索批次已补回 main 逐项中药汇总；成分/靶点导出按 ID 去重且保留不同身份。检索/交集/分页的同步锁、旧响应与卸载保护、详情身份校验已补齐；ChEMBL 按本次调用消费同意，改词与换标签清除旧同意。
- 新迁移 `core.0020` 给 `AnalysisTask` 增加只读输出 `parent_task`，使用可空、受保护的父任务外键；历史任务不猜测、不回填来源。
- Reactome/STRING 关联请求由后端从成功的本地网络药理任务提取候选标识，前端只提交来源任务 ID；若另传 targets，必须与持久完整候选集一致。别人的任务、失败/外部任务、不完整候选集和超过服务上限的完整候选集均拒绝。
- 子任务保持发起者归属，继承医案/数据集及来源版本。任务保存父查询输入、结果和候选标识的 SHA-256、来源 release ID/version/checksum；worker 验证输入摘要并把来源快照写入结果。管理员能查看全平台任务，但不得通过本接口把他人的私有输入创建为自己的外部分析。
- 新 R 图表任务同样保存父外键；复用只针对已保存该绑定的任务。历史只有 JSON 参数的图表不冒充已绑定记录，新请求创建可追溯任务；worker 拒绝 FK 与参数来源不一致。
- 修复蛋白组学“生成 R 火山图”的路由参数遗漏：`proteomics_volcano` 现在可被请求序列化器接收，排队和跨账号拒绝已有回归；真实 R 绘图仍等待接入。
- 前端检查创建/轮询任务的父查询与分析类型，拒绝展示另一查询的结果。Reactome 完整 JSON 标明持久绑定或历史页面关联；STRING 共用结果表格、状态和完整 JSON 导出，预览上限明确。main 没有 STRING 专用图，本轮不新增该图。
- 恢复 main 的 Prep B 候选构成环图及原两色；分为“严格交集”和“仅直接关联”，两类证据重叠只计一次。候选截断/统计不完整时不生成比例，空候选有明确提示。这是对旧环图重复计数的修正。
- 医案和助手模型接口拒绝明确截断、拒答、非 JSON、非有限数字或错误结构；允许旧兼容模型省略可选 finish_reason。助手空回答不计为成功，引用仍受本次证据白名单约束。
- MyGene/Reactome 使用原官方地址，但拒绝 HTTP 跳转并有响应字节上限。无效通路列表、标识、统计或物种结构不会伪装为空成功；可选版本查询失败保留未知版本。外部富集失败保留已完成本地蛋白组学结果。
- 前端收到代理 HTML、无效成功 JSON 或错误 CSRF 响应时，使用 `ApiError` 统一报错；保留 HTTP 状态与 request ID，不再泄漏原始解析异常。

## 待接服务的已有入口

所有路径为当前 Django `/api/v1/` 契约，不沿用旧 FastAPI 的匿名、前端自报账号或客户端自定模型地址。

| 依赖 | 现有入口及接入要求 | 当前验证边界 |
|---|---|---|
| 本地医案模型 | `POST /api/v1/research/cases/{id}/analysis/`，`confirmLocalModel: true`；由部署者配置 `CASE_MODEL_BASE_URL/NAME/VERSION/API_KEY` | 真实模型暂缓，脱敏字段、引文、候选、权限及失败状态已有模拟验证 |
| 科研助手模型 | `POST /api/v1/research/assistant/`，`question/entityIds/useModel/confirmModelSharing`；默认不调用模型 | 证据冻结、引用白名单及模型异常已离线验证；真实回答质量不作保证 |
| MyGene + Reactome | `POST /api/v1/analysis/pathway-enrichment/`，关联请求 `{source_task_id, consent:true}` | 最多 500 个完整候选；接口/任务/HTTP响应模拟验证，真实富集与旧真实样例对照暂缓 |
| STRING | `POST /api/v1/analysis/string-network/`，关联请求 `{source_task_id, consent:true, required_score:700}` | 最多 200 个完整候选；原有物理互作连接器、中心性与导出离线验证，实际查询暂缓 |
| ChEMBL | `POST /api/v1/analysis/chembl/molecules/` 的 `query/consent`，及 `chembl/activities/` 的 `chemblId/consent` | 复用 main 字段与名称展开，登录/逐次同意/限流及返回契约已有测试，真实连接暂缓 |
| 旧 SQLite 与外部目录 | 管理员 `sources/{id}/test/`、`sources/{id}/sync/`、`sync-runs/{id}/apply/`；配置经批准目录/相对文件或已有官方 connector | SQLite 三表/Reactome/UniProt/PubChem/STRING 已有预览、人工应用、版本与幂等测试；真实文件、项目映射及生产库应用暂缓 |
| R 绘图 | `POST /api/v1/research/analysis-tasks/{id}/visualizations/`，`chartKey`；配置 `R_VIZ_BASE_URL/API_TOKEN` | 已有柱图/富集气泡图/火山图任务及私有工件契约；图表渲染字节使用模拟响应，真实 R 容器暂缓 |
| 后台任务 | Celery + Redis，`CELERY_BROKER_URL` | API 保留排队/执行/成功/失败和队列不可用错误，真实 worker 联调暂缓 |

独立 Reactome/STRING 请求仍兼容 `{targets, consent:true}`，但 `parent_task=null`，不能称为有父查询的完整溯源。由网络页面发起的新请求必须使用 `source_task_id`。各服务的公开查询只发送经同意的必要字段，不提交账号、医案原文或完整上传文件。

任务统一从 `GET /api/v1/research/analysis-tasks/{id}/` 读取。错误封装沿用 `{error:{code,message,details,requestId}}`；异步失败通过 task `status/error_summary` 返回。浏览器状态变更必须携带 Django session 与 CSRF。完整字段以 `/api/schema/` 和当前序列化器为准。

## 保留但不冒充完成

- 旧 AI Scientist 规则报告仍依赖缺失的 Excel/SQLite，管理员接口监测明确返回未迁移状态；不把硬编码参考文献、无交集回退靶点或通用实验文本冒充可复核研究结果。
- 旧全局富集历史表及真实 SQLite/Excel 用户数据尚未迁入。
- 更广文献/语义 RAG、PCA/相关性、热图、额外交互网络和生产部署验收按用户当前范围暂缓。
- UI 指定结构已复用，但全站旧版逐像素对照、常规浏览器 Blob 落盘和真实生物学结果一致性尚未验收。

## 本地验证

最终 281 项 Django 测试通过，覆盖原有本地业务及新增关联、所有者隔离、输入冻结、历史兼容、队列/模型/外部响应失败契约；使用 SQLite 测试库，不访问外部研究服务。系统检查、无待生成迁移和无警告 OpenAPI 校验通过。

前端新增 `pnpm run test:research` 检索回归、`pnpm run test:network` 的五份回归与 `pnpm run test:api` 均通过；TypeScript/Vite 生产构建通过。网络回归覆盖完整导出、构成重叠、错误结果拒绝及过时响应；这些替代 hook/静态渲染检查不能替代全站浏览器验收。Vite 的单个 JS chunk 超过 500kB 提示仍存在，本轮不扩展加载优化。

最新代码还通过 15 项实际本地 HTTP 检查，包括会话/CSRF、权限、目录与任务接口、合成网络查询、不同意外发的拒绝和未配置 R 服务的错误响应。浏览器已运行合成查询并核对 Prep B：候选并集 3、严格交集 2、仅直接关联 1、证据重叠 1；没有浏览器控制台警告或错误。该展示不代表真实研究数据或生物学结论已验收。最新隔离预览为 `http://127.0.0.1:5195/`。

检索批次的六个本地检索入口及双击仅创建一个任务已通过真实浏览器与临时库检查，详细输入/输出和验证限制见 [UI 与结果核验](main-ui-and-result-parity.md)。这批未改数据库/API，281 项后端测试沿用上一轮记录。

新代码需要先执行 `python manage.py migrate` 应用 `core.0020`，再重启 Django/worker。合成预览仅更新隔离测试数据库，不修改正式研究数据库。
