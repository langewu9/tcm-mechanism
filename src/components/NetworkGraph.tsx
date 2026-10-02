type NodeKind = "syndrome" | "formula" | "herb" | "compound" | "target" | "pathway" | string;

export type NetworkNode = {
  id: string;
  label: string;
  type: NodeKind;
};

export type NetworkLink = {
  source: string;
  target: string;
  relation: string;
};

export type NetworkData = {
  nodes: NetworkNode[];
  links: NetworkLink[];
};

const palette: Record<string, string> = {
  syndrome: "#9c2b22",
  formula: "#7a3326",
  herb: "#c89b3c",
  compound: "#b7682f",
  target: "#8b5a2b",
  pathway: "#e0bd67"
};

const order: NodeKind[] = ["syndrome", "formula", "herb", "compound", "target", "pathway"];
const labels: Record<string, string> = {
  syndrome: "证候",
  formula: "方剂",
  herb: "中药",
  compound: "成分",
  target: "靶点",
  pathway: "通路"
};

function trimLabel(label: string, size = 9) {
  return label.length > size ? `${label.slice(0, size)}...` : label;
}

function limitByType(nodes: NetworkNode[]) {
  const grouped = new Map<string, NetworkNode[]>();
  nodes.forEach((node) => {
    const items = grouped.get(node.type) ?? [];
    items.push(node);
    grouped.set(node.type, items);
  });
  return order.flatMap((type) => (grouped.get(type) ?? []).slice(0, type === "syndrome" ? 2 : 9));
}

export function NetworkGraph({ network, title = "药理链路拓扑", description = "按证候、方剂、中药、成分、靶点和通路分层展示最近一次分析生成的网络证据。" }: { network: NetworkData; title?: string; description?: string }) {
  const nodes = limitByType(network.nodes.length ? network.nodes : [{ id: "empty", label: "暂无分析", type: "syndrome" }]);
  const nodeIds = new Set(nodes.map((node) => node.id));
  const links = network.links
    .filter((link) => nodeIds.has(link.source) && nodeIds.has(link.target))
    .slice(0, 80);
  const width = 1180;
  const height = 620;
  const stageWidth = width / Math.max(order.length, 1);

  const byType = new Map<string, NetworkNode[]>();
  nodes.forEach((node) => {
    const items = byType.get(node.type) ?? [];
    items.push(node);
    byType.set(node.type, items);
  });

  const positioned = nodes.map((node) => {
    const typeIndex = Math.max(order.indexOf(node.type), 0);
    const siblings = byType.get(node.type) ?? [node];
    const siblingIndex = siblings.findIndex((item) => item.id === node.id);
    const gap = height / (siblings.length + 1);
    return {
      ...node,
      x: 72 + typeIndex * stageWidth,
      y: gap * (siblingIndex + 1)
    };
  });

  const byId = new Map(positioned.map((node) => [node.id, node]));
  const counts = order.map((type) => ({ type, value: byType.get(type)?.length ?? 0 }));

  return (
    <section className="figure-card overflow-hidden">
      <div className="figure-heading">
        <span>Figure G</span>
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      <div className="network-summary">
        {counts.map((item) => (
          <div key={item.type}>
            <span style={{ backgroundColor: palette[item.type] }} />
            <strong>{labels[item.type]}</strong>
            <em>{item.value}</em>
          </div>
        ))}
      </div>
      <div className="network-canvas">
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="药理链路拓扑图">
          <rect width={width} height={height} rx="8" fill="rgba(255,250,241,0.76)" />
          {order.map((type, index) => (
            <g key={type}>
              <line x1={72 + index * stageWidth} y1={42} x2={72 + index * stageWidth} y2={height - 36} stroke="#ded3c2" strokeDasharray="4 6" />
              <text x={72 + index * stageWidth} y={24} textAnchor="middle" fill="#6d5b4c" fontSize="14" fontWeight="700">
                {labels[type]}
              </text>
            </g>
          ))}
          {links.map((link, index) => {
            const source = byId.get(link.source);
            const target = byId.get(link.target);
            if (!source || !target) return null;
            const midX = (source.x + target.x) / 2;
            return (
              <path
                key={`${link.source}-${link.target}-${index}`}
                d={`M ${source.x} ${source.y} C ${midX} ${source.y}, ${midX} ${target.y}, ${target.x} ${target.y}`}
                fill="none"
                stroke="#9aa18f"
                strokeOpacity="0.42"
                strokeWidth="1.25"
              >
                <title>{`${source.label} -${link.relation}-> ${target.label}`}</title>
              </path>
            );
          })}
          {positioned.map((node) => (
            <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
              <circle r={node.type === "syndrome" ? 28 : 22} fill={palette[node.type] ?? "#9c2b22"} opacity="0.94" />
              <text y="4" textAnchor="middle" fontSize="10.5" fill="white" fontWeight="800">
                {trimLabel(node.label)}
              </text>
              <title>{`${labels[node.type] ?? node.type}: ${node.label}`}</title>
            </g>
          ))}
        </svg>
      </div>
    </section>
  );
}
