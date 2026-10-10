# R 图表 key 数据与演示图库

此图库只用于产品展示和接口验收。所有数值、名称、互作边及显著性均为**合成演示，非真实实验**，不是 STRING、GO、KEGG 或 Reactome 查询返回，不可作为科研结果引用。不替换正式任务，不写入数据库，不调用任何生物学数据库接口。

## 覆盖目录

| key | 图表 |
| --- | --- |
| ppi_network | PPI 网络 |
| ppi_degree | PPI 连接度排行 |
| evidence_network | 中药—成分—靶点—疾病网络 |
| gene_pathway_network | 基因—通路网络 |
| gene_pathway_distribution | 关联基因分布（非富集检验） |
| proteomics_go_kegg_bar | GO/KEGG 富集条形图 |
| proteomics_go_kegg_enrichment | GO/KEGG 富集气泡图 |
| reactome_enrichment | Reactome 通路气泡图 |
| proteomics_summary | 分析概览 |
| proteomics_top_nodes | 本地网络连接度 |
| overlap | 靶点交集计数 |
| components | 关联成分靶点数 |
| pathways | 关联通路靶点数 |
| proteomics_volcano | 火山图（180 个模拟蛋白） |

每种图表提供包含 key、synthetic 标志、绘图数据、阈值（适用时）、SHA-256 的 JSON，及 R 生成的 SVG/PNG/PDF/HTML。Reactome 图及 HTML 表头按实体计数，不能称为命中基因数。

## 准备与展示

先启动现有 R Plumber 服务；在本地环境设置 `R_VIZ_BASE_URL` 和 `R_VIZ_API_TOKEN`，不要将凭据提交到 Git。然后在仓库根目录运行：

```powershell
python_app\.venv\Scripts\python.exe r_viz\prepare_demo_gallery.py
python_app\.venv\Scripts\python.exe r_viz\test_demo_fixtures.py
```

运行不依赖 Django、Celery 或业务数据库。输出位于 `public/r-demo/`（现有 Vite 配置使用仓库根目录的 public），生成文件不入 Git；源码中的固定随机种子与数据构造规则可以复现它们。部署前先生成，再执行前端 build，Vite 会复制到静态站点。全部绘图成功才发布 manifest；请勿在已有公网流量时原地运行，先在构建目录生成再发布。

蛋白组学与网络药理页面顶部的“R 图表演示图库”可选择全部 14 种图表并下载对应 key 数据。与下方真实任务结果明确分区。尚未实现的 PCA/热图/GSEA 不在当前覆盖范围内，后续实现时同时增加对应演示数据。
