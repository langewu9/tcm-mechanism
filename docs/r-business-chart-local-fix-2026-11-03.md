# R 业务图表本地修复与验收（2026-11-03）

本次针对“演示图库能看见，但自己的分析缺少同样图表”检查并修复本地实现。对照远程 `origin/main` 提交 `455a3096929daa7c56295f9cc0bab8b8b45201e7`，保留本地已存在的任务归属校验、重新运行及历史记录保护。未整体覆盖本地分支，未推送远程。

## 证实的问题及修复

| 问题 | 依据 | 本次处理 |
| --- | --- | --- |
| 连接度图缺少业务生成入口 | main 的 visualization.py 支持 `proteomics_top_nodes`，RAnalysisGallery.tsx 未列出该类型 | 加入“本地通路网络连接度”，复用已有后台适配与 R 绘图逻辑 |
| 缺数据时只显示通用文字 | main 的生成按钮仅显示“缺少所需分析数据” | 显示保存结果中实际的缺失条件、外部服务状态和后续操作 |
| 火山图不能在提交前解释完整输入是否可绘图 | 结果预览仅含入选行，后台火山图却读取完整持久化行 | 新分析增加可选 `qc.volcanoEligibleRowCount`；旧任务不依据预览判空，仍交后台核验 |
| 无效火山图阈值在绘图时才被发现 | 分析允许 P 阈值为 0，火山图的负对数阈值线要求 P > 0 | 依据任务保存阈值禁用生成并解释需重新分析，不悄悄改变历史阈值 |
| GO 气泡图仅检查 terms 非空 | 失败状态或缺少 GeneRatio、FDR、命中数的条目不符合后台绘图要求 | 提交前及按钮处同时检查成功状态与必要字段 |
| 部分图表入口与后台要求不一致 | 如仅有通路节点但没有基因—通路边、空概览结果 | 按保存的计数、有效富集字段和实际通路关联边判断；零计数仍有效 |

`proteomics_top_nodes` 的 degree 为 0 是合法数据，表示本任务未登记通路关联。候选符号不因此变成已验证蛋白，不把连接度图解释为 STRING PPI、因果或核心蛋白结论。

## 火山图计数口径

- 从完整分析行统计，包括未入选行，不使用前 500 条入选行预览。
- 要求有限 log2FC、有限原始 P 值，且 `0 <= P <= 1`。
- 不要求已映射标识、入选状态或有效 FDR；这些不是后台火山图的必要条件。
- 原始 P 值为 0、1 以及 log2FC 为 0 均能计入；图中的 P 阈值须满足 `0 < pValueMax <= 1`。
- 只有 FDR 的差异表可以分析，但不能用 FDR 冒充原始 P 值绘制火山图。
- 历史结果没有新字段时仍可提交给后台检查完整持久化行，不批量改写历史结果。

## 自动验证

后端使用临时内存 SQLite，未使用业务数据库，70 项全部通过：

```text
manage.py test
  apps.proteomics.tests.test_volcano_eligibility
  apps.proteomics.tests.test_services
  apps.proteomics.tests.test_invalid_statistics
  apps.core.tests.test_visualization
  apps.core.tests.test_visualization_regeneration
  apps.core.tests.test_r_analysis_catalog
  apps.core.tests.test_catalog_visualization
  --noinput
```

其中新增 4 项测试实际执行分析 worker、落库，并对比完整行 SQL、图表 payload 与鉴权后的任务详情接口；覆盖未入选行、无标识、P=0/1、非有限值、只有 FDR 的 500 行预览以及没有入选行的原始矩阵。

前端 `test:r`、`test:research`、`test:api`、`test:network` 全部通过；TypeScript 检查和 Vite 生产构建通过。新增图表检查 7/7，页面处理流程回归 29/29，科研文案与生成条件检查 7/7。

新增检查已纳入 `test:r`。GO 重新绘图测试使用字段完整的合成成功结果；未放宽生产校验去迁就旧的空测试结果。

## 本地运行验收

使用已有隔离预览数据库 `tcm_merged_preview_20261029` 与已上传的合成数据集 #7。没有上传新研究数据，没有运行外部映射、STRING、g:Profiler、Reactome 或模型推理。

| 任务 | 实际结果 |
| --- | --- |
| 新分析 #52 | 1,200 行输入、306 行入选、1,200 行可用于火山图；3 个外部开关均为 false |
| 火山图 #53 | 本地绘图服务 `r-viz-0.4.2` 成功；实际显示 1200/1200 行；SVG、PDF、PNG、HTML 四格式 |
| 连接度图 #54 | 新入口提交成功；本地 R 成功生成四格式；30 个合成候选的 degree 全为 0 |
| 浏览器下载 | PNG 产物 #75 下载后 SHA-256 与后台保存值相同 |

静态图由已有 R/ggplot2 逻辑生成，交互 HTML 由已有 R/echarts4r 逻辑生成。本次通过业务任务重新运行 R，没有拿演示图库的成品图片充当分析结果。验收输入本身是明确标识的合成数值数据，不能当成真实蛋白组学实验。

对修复前记录逐条核对 SHA-256：原 51 个任务、7 个数据集、1,236 条原始数据行、2,443 条分析结果行、68 条图表记录及 68 个文件均未变化。本次新增 3 个任务、1,200 条分析结果行、8 条图表记录和 8 个产物。

本地证据保存在被 Git 忽略的 `python_app/var/r-business-chart-fix-2026-11-03/`：

- `backend-verified-tests.log`：70 项后端测试。
- `frontend-tests.log`、`frontend-tests.json`：前端回归、类型检查、构建。
- `runtime-before.json`、`runtime-verification.json`：历史校验值、任务与 8 个产物校验。
- `browser-download-verification.json`：PNG 下载核验。
- `task-52-volcano-53-static-page.png`：实际业务页静态图截图。
- `task-52-volcano-53-visible.png`：交互图在展开视图中的可见截图。
- `live-r-task-53.png`、`live-r-task-54.png`：本次 R 输出的 PNG。

## 本次没有证明的内容

本地知识库尚未给这份合成输入提供已验证靶点或通路关联，因此不能据此验收真实 PPI、GO/KEGG 或 Reactome 研究结论。缺少相应成功结果时，页面解释原因并禁用生成；未补造映射、关系、显著性数值。未修改 R 样式、基础 UI 设计、分析筛选算法或业务数据库表结构。

本地查看：`http://127.0.0.1:5175/proteomics?proteomicsTask=52`，选择“分析结果 → R 图表 → 当前任务图表”。
