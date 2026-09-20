# 书刊正文优化版架构图清单

本目录是正文排版专用版本，与 `diagrams` 中的横向 PPT/展示版图稿并行保留，未覆盖或修改原版资产。

## 统一规格

- 画布比例：3:4（900 × 1200 SVG viewBox），适合 A4 纵向正文中的单栏或窄双栏排版。
- PNG：1800 × 2400 像素，元数据密度 300 dpi，适合正文插图、打印和 PDF 导出。
- 页边距：主体安全区约 x=44–856、y=130–1116；标题、图例和页脚采用统一基线。
- 风格：白底、黑/深灰结构线、暗红强调，不使用彩色卡片或彩虹渐变；暗色信息条使用高对比白字。
- 结构：纵向分层、上下泳道、阶段编号和窄连接线；与横向 PPT 版形成明确的阅读方向差异。

## 图件

| 编号 | SVG 母版 | 300 dpi PNG | 正文建议图题 |
|---|---|---|---|
| 图 1 | `01_system_overall_architecture_book.svg` | `01_system_overall_architecture_book.png` | 系统总体架构（书刊正文版） |
| 图 2 | `02_dynamic_database_sync_book.svg` | `02_dynamic_database_sync_book.png` | 动态数据库接入与同步流程（书刊正文版） |
| 图 3 | `03_network_pharmacology_pipeline_book.svg` | `03_network_pharmacology_pipeline_book.png` | 网络药理分析证据链（书刊正文版） |
| 图 4 | `04_mygene_reactome_enrichment_book.svg` | `04_mygene_reactome_enrichment_book.png` | MyGene—Reactome 通路补全流程（书刊正文版） |
| 图 5 | `05_deployment_security_book.svg` | `05_deployment_security_book.png` | 部署拓扑与安全边界（书刊正文版） |
| 图 6 | `06_data_model_evidence_lineage_book.svg` | `06_data_model_evidence_lineage_book.png` | 核心数据模型与证据血缘（书刊正文版） |

## 排版建议

1. A4 单栏插图建议宽度 15.0–16.0 cm，保持 3:4 比例；图题置于图下方，正文五号宋体。
2. 需要后续编辑时插入 SVG；仅做最终印刷时可使用同名 PNG，避免浏览器或旧版排版软件对 SVG 支持不完整。
3. 图中暗红只承担“主路径/受控对象”语义，灰度打印可通过边框和明度保留层级。
4. 不建议再叠加彩色边框、阴影或页面背景，以保持论文级正文的统一版式。

## 真实实现依据

- Next.js 15 / React 19、FastAPI 8010、Prisma / SQLite 业务库。
- 动态同步：只读源库、字段白名单、rowid 游标、250 行批次、事务 UPSERT、运行记录与断点恢复。
- 分析链路：疾病/方药事实召回、实体标准化、候选靶点交集、证据网络、CSV/PDF/JSON 交付。
- 通路链路：MyGene 人类基因符号规范化、Reactome 人类通路富集与官方目录、FDR ≤ 0.05 且命中实体 ≥ 2 的质量门。
- 数据对象：User、MedicalCase、AnalysisTask、AnalysisResult、Herb、Compound、Target、Gene、Pathway、DatabaseSource、DatabaseSyncRun 与 PathwayEnrichmentRun/Item。

## 可复现源文件

`D:\MMDD\tcm_pharmacology_platform\tools\generate_book_diagrams.js`

执行：

```powershell
cd D:\MMDD\tcm_pharmacology_platform
node tools\generate_book_diagrams.js
```
