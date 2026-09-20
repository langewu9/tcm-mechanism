# 企业级架构示意图资产清单

本目录为《中医药理智能分析平台计划介绍书》提供可直接排版的正式架构图。图中组件、接口与数据对象均依据 `D:\MMDD\tcm_pharmacology_platform` 当前实现整理，不使用与系统无关的概念性占位模块。

## 统一视觉规范

- 画布：白底，横向 1600 × 960/980 SVG；PNG 按 180 dpi 光栅化为 4000 × 2400/2450。
- 色彩：正文使用黑色与深灰，仅以暗红 `#7f1d1d` 标识受控接口、主链节点和关键持久化对象。
- 线型：实线箭头表示平台内部数据或调用方向；虚线表示异步过程或外部知识服务依赖。
- 信息层级：采用信任区、领域容器、控制面/数据面/状态面、服务总线和治理平面，不使用彩色简单几何流程图。
- 排版：中文采用微软雅黑/Noto Sans CJK 回退，英文与接口标识使用等宽字体；灰度打印时仍可依靠线型、边框和明度区分。

## 图件与建议图题

| 编号 | SVG（可编辑） | PNG（高分辨率） | 建议图题 | 适用章节 |
|---|---|---|---|---|
| 图 1 | `01_system_overall_architecture.svg` | `01_system_overall_architecture.png` | 中医药理智能分析平台系统总体架构 | 总体设计 / 产品架构 |
| 图 2 | `02_dynamic_database_sync_architecture.svg` | `02_dynamic_database_sync_architecture.png` | 动态数据库接入、批次同步与断点恢复架构 | 数据治理 / 数据同步 |
| 图 3 | `03_network_pharmacology_evidence_pipeline.svg` | `03_network_pharmacology_evidence_pipeline.png` | 网络药理分析与可追溯证据链路 | 核心业务流程 / 分析方法 |
| 图 4 | `04_mygene_reactome_enrichment_architecture.svg` | `04_mygene_reactome_enrichment_architecture.png` | MyGene 基因规范化与 Reactome 通路富集架构 | 生物通路 / 外部知识服务 |
| 图 5 | `05_deployment_security_topology.svg` | `05_deployment_security_topology.png` | 本地部署拓扑、数据驻留与纵深安全边界 | 部署说明 / 安全设计 |
| 图 6 | `06_data_model_evidence_lineage.svg` | `06_data_model_evidence_lineage.png` | 核心数据模型与研究证据血缘 | 数据模型 / 可追溯性 |

## 图内实现依据

- Next.js 15、React 19、Route Handlers 与 `qh_session` 会话鉴权。
- FastAPI 8010 本地数据服务、ChEMBL 本地分子活性接口与可选 Qwen 增强。
- Prisma/SQLite 业务库；动态源库通过 `node:sqlite` 只读连接。
- 动态同步采用字段白名单、`rowid > cursor`、250 行批次、Prisma 事务 UPSERT、运行记录与断点续传。
- MyGene 负责 `symbol/alias/name` 到人类基因符号的规范化；Reactome 负责官方人类通路目录与查询级富集。
- 富集结果质量门：FDR ≤ 0.05 且命中实体数 ≥ 2；输入集合去重并限制为 500 个候选标签。
- 业务实体关系依据 Prisma schema：User、MedicalCase、AnalysisTask、AnalysisResult、Herb、Compound、Target、Gene、Pathway、DatabaseSource 与同步/富集运行记录。

## 排版建议

1. 在 Word/LibreOffice 中优先插入 PNG，宽度建议 16.0–16.8 cm，保持纵横比，不添加彩色外框。
2. 若后续需要修改文字或线条，使用对应 SVG；导入排版软件后不得拉伸变形。
3. 图题置于图下方，使用“图 3-x + 图名”，五号宋体；图中文字不再重复作为正文标题。
4. 黑白打印时建议选择“保留灰度”，不要启用纯黑阈值化，以保留浅灰分区层级。

## 可复现源文件

生成源：`D:\MMDD\tcm_pharmacology_platform\tools\generate_enterprise_diagrams.js`

执行：

```powershell
cd D:\MMDD\tcm_pharmacology_platform
node tools\generate_enterprise_diagrams.js
```

SVG 为最终可编辑母版；PNG 是从同一母版统一导出的交付版本。
