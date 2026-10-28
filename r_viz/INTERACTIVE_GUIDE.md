# R 交互式可视化 · 0.4.0

## 页面使用

默认网站入口与登录后的落点为主页，主页可进入中药/靶点检索、蛋白组学和 R 演示。检索结果与网络药理学也使用同一 R 图表目录。数据来源与显示方式分开切换：

- 当前任务图表：只读取本任务产物；新生成的 0.4.0 HTML 支持交互，旧任务默认静态预览，绝不覆盖历史文件。
- 合成演示图表：16 个独立 key，虚构关系/统计数据全程明确标注。新增实体/证据概览与连接度点图；火山图 1,200 点；PPI 60 节点；中药—成分—靶点—疾病网络 61 节点。
- 公开数据示例：STRING 人类预选基因集，不能当作差异蛋白实验或中药疗效证据。无对应公开数据的图明确说明缺失，不用模拟 P 值填补。

数据来源选择由图表目录共享；切换图表保持来源。每次只挂载一个交互窗，完整高度不压缩；“展开大图”可以增加宽度，静态 SVG/PDF/PNG 仍可导出。

## 交互能力

- 网络：圆形弦图 / 力导 / 分层布局，缩放和平移，类型筛选，边评分筛选，名称/ID 定位，邻居高亮和点击详情。
- 网络默认使用 INPUT 风格圆形布局：类别连续分组、外圈径向标签与内圈弧线，蓝色基因圆点 / 砖红通路菱形，图例与节点颜色一致；悬停突出邻居，长标签完整名称保留在详情和数据表中。
- 圆形画布保持 960px 高度，为图例、外圈标签和底部说明预留空间，不挤压图像。双列 / 力导布局保留为可选项，“重置视图”和图内还原按钮均恢复圆形默认。
- 二部图默认收起当前筛选后的孤立节点，状态栏明确显示数量；勾选“显示孤立节点”可恢复，完整原始数据表和下载文件不删节点。
- 过滤后连接度按当前展示图的唯一邻居重新计算，同时保留原始输入连接度，不能称为因果或核心靶点证据。
- 火山图：保存的筛选状态不变，按上/下调方向配色，点详情、名称定位、缩放和框选。框选仅帮助查看，不改写阈值结果。
- 富集气泡图和显著性点图：显示命中数、GeneRatio 和报告 FDR，图例开关、缩放和条目定位；不重新计算或伪造显著性。
- HTML 内含对应数据表；表格默认折叠，避免页面无限拉长。

## 公开数据及复现

官方来源：[STRING API](https://string-db.org/help/api/)，[STRING CC BY 4.0 许可](https://string-db.org/cgi/access)。公开快照位于 `public_data/string_inflammation_v12_5.json`，保留请求基因集、映射、完整返回网络、富集表、参数、UTC 获取时间与 SHA-256。

该许可说明针对 STRING 输出；其中涉及第三方原始资源时仍须尊重原供应方条款，商业部署前另行复核。演示不下载或转授 GO/KEGG/Reactome 整库许可。

冻结版本：STRING 12.5，物种 9606，`network_type=physical`，`required_score=400`，不增加邻居节点。预选基因覆盖炎症/应激信号，仅用于软件演示，选取本身有偏倚，不能外推疾病结论。名称映射保留 API 最佳匹配，真实研究需要人工复核。

物理互作：按无向节点对去重，采用最大返回分数；按分数/ID 排序，最多 500 边；不生成虚构边。连接度按实际展示边重算。未参与返回网络的基因不强行补边。

富集：使用 STRING 原始 `fdr`，默认人类基因组背景，展示每来源最小 FDR 的前 5 个显著条目（FDR ≤ 0.05）。GeneRatio 为命中数 / 已映射预选基因数。基因—通路网络只用 `inputGenes` 返回的实际注释；边值 1 是关系存在标记，不是互作分数。Reactome 来自 STRING 的 `RCTM` 分类，不能冒充本项目 Reactome 外部任务。

生成命令（不访问业务数据库）：

```powershell
./r_viz/prepare_local_demo.ps1
# 仅在明确需要新快照时执行：
./python_app/.venv/Scripts/python.exe r_viz/prepare_public_gallery.py --refresh --fetch-only
```

生成资源在 `public/r-demo` 与 `public/r-public-demo`，不入 Git。`renv.lock` 锁定 echarts4r/htmlwidgets 及依赖；Docker 同时打包 `interactive.R` 和 `interactive.js`。参考交互形式：[INPUT genescore](https://cbcb.cdutcm.edu.cn/INPUT/genescore/)，实现使用 [echarts4r 官方 graph 文档](https://echarts4r.john-coene.com/articles/graph)。没有复制参考站的数据库结果或研究结论。

## 隔离与安全

中药、成分、疾病、通路、实体邻域和名称对照的真实绘图先调用 `POST /api/v1/catalog/visualization-snapshots/`。前端只提交查询参数与 `expectedSha256`；服务端重新检索并核对指纹，来源变化返回 409，要求重新检索。快照保存实体主键、实际关系主键、来源版本/记录及查询结果，不接收前端自编网络。相同用户的重复快照复用；绘图快照冻结，不随目录更新改变。

实体与同名记录按主键区分；边详情保留来源与方向。连接度统计完整有效返回图的唯一邻居；通路覆盖是实际注释计数，不是富集显著性。名称对照只绘名称统计，不构造生物网络。知识库为空时保留真实零计数，网络不可生成，演示图独立展示且不写入知识库。

R 绘图任务路由到独立 `r_visualization` 队列。本地可用 `celery -A config worker --queues=r_visualization --pool=solo --concurrency=1`；Compose worker 同时消费 `celery,r_visualization`。R、后端与 worker 必须使用一致的 `R_VIZ_API_TOKEN`。该路由不修改模型任务。

R 从经过现有验证的图表 payload 生成 htmlwidget，并内联本地依赖，无 CDN、遥测或上传。图表仅接收本任务汇总结果，不接收原始上传文件或医案正文。

前端 iframe 使用 `sandbox="allow-scripts allow-downloads"`，不授予 `allow-same-origin`、表单、弹窗或父窗口导航。私有 HTML 下载仍要求登录/所有权；服务端同时施加沙箱和 `connect-src 'none'`。标签在 JSON 内转义 `<`，标题/表格 HTML 转义，tooltip 使用 richText 而不是 HTML。未改变登录、用户权限或模型配置。

前端通过 `loadRWidgetDocument` 对已登记的本地私有图表/演示图表地址发起鉴权请求，再使用 `srcDoc` 装入上述隔离 iframe。文档头显式加入禁止联网的 CSP，不依赖下载响应头在 srcDoc 中生效。加载错误会显示提示与重试按钮；切换图表、静态预览、隐藏子页或卸载时取消旧请求，旧结果不能覆盖新图。任务成功状态不替代实际图窗验收。

## 验收

R `tests/interactive_contract.R` 检查所有 key 的点数、边数、保存筛选状态和连接度不变、恶意标签往返及离线依赖。Django 可视化测试检查 owner 隔离、HTML inline 和不含 same-origin 的 CSP。前端 `test:r` 检查共享来源、沙箱、旧任务回退与公开/合成数据分离；交付检查验证全部文件哈希。
