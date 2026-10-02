# Python–R 可视化接口契约（草案）

本契约先冻结数据边界，R 服务实现与部署放在后续阶段。Python 是分析结果和用户权限的唯一入口；R 只渲染已整理的图表数据，不直接连接 PostgreSQL、不接收账号或医案身份字段。

## 调用方向

1. Python 分析任务生成带 `contract_version`、`analysis_id`、数据版本和图表数据的 JSON。
2. 内网 R Plumber 服务提供 `GET /health` 与 `POST /v1/render`，验证服务调用令牌、负载大小、字段和允许的图表类型。
3. R 返回图表工件 manifest（工件类型、相对对象键、媒体类型、校验值、生成器版本、摘要），不返回本机绝对路径。
4. Python 验证 manifest，将工件登记为分析结果附件；浏览器只通过 Django 的权限校验下载，不直连 R 服务。

## 请求示例

```json
{
  "contract_version": "1.0",
  "analysis_id": "analysis_01J...",
  "chart_id": "proteomics.volcano",
  "database_releases": [
    {"source": "uniprot", "version": "2026_04"},
    {"source": "reactome", "version": "94"}
  ],
  "data": {
    "points": [
      {"id": "P12345", "label": "GENE1", "log2_fc": 1.4, "adjusted_p": 0.002}
    ]
  },
  "parameters": {
    "log2_fc_threshold": 1.0,
    "adjusted_p_threshold": 0.05,
    "formats": ["svg", "png"]
  }
}
```

## 响应示例

```json
{
  "contract_version": "1.0",
  "analysis_id": "analysis_01J...",
  "renderer": {"name": "tcm-r-viz", "version": "0.1.0"},
  "artifacts": [
    {
      "artifact_id": "artifact_01J...",
      "format": "svg",
      "media_type": "image/svg+xml",
      "object_key": "analyses/analysis_01J.../proteomics.volcano.svg",
      "sha256": "<64-character-lowercase-hex>",
      "bytes": 82411
    }
  ],
  "summary": {"plotted": 1, "excluded": 0}
}
```

## 约束

- `analysis_id` 必须对应已存在且已授权的 Python 任务；请求和响应版本不兼容时明确失败，不做静默字段猜测。
- `data` 仅含绘图所需的最小统计量、标签和证据版本。禁止姓名、联系方式、病例号、原始医案文本、凭证和数据库连接串。
- 阈值、单位、物种、输入/映射数量及来源版本随结果保存，确保表格与图使用同一结果集。
- 工件大小、运行时长、输出格式和图类型由服务端限额；HTML 交互图在展示前做内容安全策略检查。
- 图表失败不应阻断分析表格与结构化结果的查询和 CSV 导出。
