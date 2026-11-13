function(el, x) {
  'use strict';
  var status = document.getElementById('chart-status');
  try {
  var chart = echarts.getInstanceByDom(el);
  // Preserve a full-height circular canvas, including when a running worker has old metadata.
  if (x.chartType === 'network' && el.style) { el.style.height = '960px'; chart.resize(); }
  var initial = chart.getOption();
  var originalNodes = x.chartType === 'network' ? initial.series[0].data : [];
  var originalLinks = x.chartType === 'network' ? initial.series[0].links : [];
  var originalCategories = x.chartType === 'network' ? initial.series[0].categories : [];
  var activeTypes = new Set(originalCategories.map(function(c) { return c.name; }));
  var search = document.getElementById('chart-search');
  var details = document.getElementById('chart-details');
  var layout = document.getElementById('chart-layout');
  var score = document.getElementById('chart-score');
  var labels = document.getElementById('chart-labels');
  var isolates = document.getElementById('chart-isolates');
  var defaultLayout = x.defaultLayout || x.layout || 'layered';
  var defaultLabels = originalNodes.length <= 80 && (chart.getWidth() >= 520 || originalNodes.length <= 30);
  var typeLabels = {protein:'蛋白 / 基因',gene:'基因',target:'靶点',pathway:'通路',herb:'中药',ingredient:'成分',compound:'化合物',disease:'疾病',formula:'方剂',syndrome:'证候'};
  function announce(text) { status.textContent = text; }
  function labelOf(node) { return node.displayLabel || (typeof node.label === 'string' && node.label) || node.name || node.id; }
  function updateGraph() {
    var threshold = Number(score.value);
    if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1) { announce('请输入 0–1 之间的边评分。'); return; }
    chart.dispatchAction({type:'downplay'});
    chart.dispatchAction({type:'hideTip'});
    var nodes = originalNodes.filter(function(n) { return activeTypes.has(n.nodeType); }).map(function(n) { return Object.assign({}, n); });
    var ids = new Set(nodes.map(function(n) { return n.id; }));
    var links = originalLinks.filter(function(l) { return ids.has(l.source) && ids.has(l.target) && l.score >= threshold; });
    var neighbors = new Map(nodes.map(function(n) { return [n.id, new Set()]; }));
    links.forEach(function(l) { neighbors.get(l.source).add(l.target); neighbors.get(l.target).add(l.source); });
    var hiddenIsolates = isolates.checked ? 0 : nodes.filter(function(n) { return neighbors.get(n.id).size === 0; }).length;
    if (!isolates.checked) nodes = nodes.filter(function(n) { return neighbors.get(n.id).size > 0; });
    var groups = new Map();
    var compact = chart.getWidth() < 900;
    var leftMargin = layout.value === 'layered' ? (compact ? 155 : 190) : layout.value === 'circular' ? (labels.checked ? (chart.getWidth() < 520 ? 130 : 170) : 30) : 100;
    var rightMargin = layout.value === 'layered' ? (compact ? 175 : 240) : layout.value === 'circular' ? leftMargin : 100;
    var circleDiameter = Math.max(120,Math.min(chart.getWidth()-leftMargin-rightMargin,chart.getHeight()-360));
    function layoutGroup(type) {
      if (type === 'formula' || type === 'herb' || type === 'drug' || type === 'medicine') return 'herb';
      if (type === 'compound' || type === 'ingredient') return 'compound';
      if (type === 'gene' || type === 'protein' || type === 'target') return 'target';
      if (type === 'disease' || type === 'syndrome') return 'disease';
      return type;
    }
    var layerOrder = new Map([['herb',0],['compound',1],['target',2],['disease',3],['pathway',4]]);
    nodes.forEach(function(n) {
      n.displayLabel = labelOf(n);
      var groupKey = layoutGroup(n.nodeType);
      if (!groups.has(groupKey)) groups.set(groupKey, []);
      groups.get(groupKey).push(n);
      n.value = neighbors.get(n.id).size;
      n.symbolSize = chart.getWidth() < 520 && layout.value === 'circular' ? 5 + 1.4 * Math.sqrt(n.value) : 9 + 3 * Math.sqrt(n.value);
    });
    if (layout.value === 'layered') {
      // Standard network-pharmacology layers: herb → compound → target ← disease.
      groups = new Map(Array.from(groups.entries()).sort(function(a,b) {
        return (layerOrder.has(a[0]) ? layerOrder.get(a[0]) : 5) - (layerOrder.has(b[0]) ? layerOrder.get(b[0]) : 5);
      }));
      groups.forEach(function(group) { group.sort(function(a,b) { return labelOf(a).localeCompare(labelOf(b), 'zh-CN', {numeric:true}); }); });
      // Stable barycentric passes reduce crossings without inventing or dropping edges.
      for (var pass = 0; pass < 6; pass++) {
        var positions = new Map();
        groups.forEach(function(group) { group.forEach(function(n,i) { positions.set(n.id, (i+0.5)/group.length); }); });
        groups.forEach(function(group) {
          var prior = new Map(group.map(function(n,i) { return [n.id,i]; }));
          function barycenter(n) {
            var adjacent = Array.from(neighbors.get(n.id)).filter(function(id) { return positions.has(id); });
            return adjacent.length ? adjacent.reduce(function(sum,id) { return sum + positions.get(id); },0)/adjacent.length : 2;
          }
          group.sort(function(a,b) { return barycenter(a) - barycenter(b) || prior.get(a.id) - prior.get(b.id); });
        });
      }
      var typeIndex = 0;
      // Match coordinate and viewport aspect ratios so circles never become tall ellipses.
      var graphWidth = Math.max(60, chart.getWidth() - leftMargin - rightMargin);
      var graphHeight = Math.max(100, chart.getHeight() - 135);
      groups.forEach(function(group) {
        group.forEach(function(n,i) {
          n.x = typeIndex * graphWidth / Math.max(1,groups.size-1);
          n.y = group.length === 1 ? graphHeight/2 : i * graphHeight / (group.length-1);
          n.label = {show:labels.checked, position:typeIndex === 0 ? 'left' : 'right', rotate:0, distance:12,
            width:typeIndex === 0 ? leftMargin-30 : rightMargin-35, overflow:'break', fontSize:13, lineHeight:19, color:'#30343B'};
        }); typeIndex++;
      });
    } else {
      var typeOrder = new Map(originalCategories.map(function(c,i) { return [c.name,i]; }));
      nodes.sort(function(a,b) { return typeOrder.get(a.nodeType) - typeOrder.get(b.nodeType) || labelOf(a).localeCompare(labelOf(b),'zh-CN',{numeric:true}); });
      nodes.forEach(function(n) {
        delete n.x; delete n.y;
        // Let ECharts rotate and flip radial labels; explicit rotate:0 defeats circular labels.
        n.label = {show:labels.checked,position:'right',distance:8,fontSize:nodes.length > 55 ? 12 : 13,
          width:chart.getWidth() < 520 ? 100 : 140,overflow:'truncate',color:'#30343B'};
      });
    }
    var nodeById = new Map(nodes.map(function(n) { return [n.id, n]; }));
    function edgeStyle(link) {
      var source = nodeById.get(link.source), target = nodeById.get(link.target);
      if (!source || !target) return {color:'#AEB8C7', opacity:0.35, curveness:0};
      var pair = [layoutGroup(source.nodeType), layoutGroup(target.nodeType)].sort().join(':');
      var styles = {
        'disease:target': {color:'#B65A50', opacity:0.7},
        'compound:target': {color:'#4E6D9C', opacity:0.48},
        'compound:herb': {color:'#A28A62', opacity:0.62},
        'disease:herb': {color:'#70578B', opacity:0.62},
        'pathway:target': {color:'#8A709B', opacity:0.56}
      };
      var style = styles[pair] || {color:'#AEB8C7', opacity:0.35};
      if (source.targetOverlap || target.targetOverlap) style = Object.assign({}, style, {opacity:Math.min(0.82, style.opacity + 0.14), width:1.6});
      return Object.assign({}, style, {curveness:layout.value === 'layered' ? 0 : 0.32});
    }
    links = links.map(function(l) { return Object.assign({},l,{lineStyle:edgeStyle(l)}); });
    var selectedTypes = {}; originalCategories.forEach(function(c) { selectedTypes[c.name] = activeTypes.has(c.name); });
    chart.setOption({title:{text:(layout.value === 'circular' ? '环形关系图' : layout.value === 'layered' ? '网络药理学证据链' : '力导关系图')+' · 节点大小表示当前连接度',
      top:layout.value === 'circular' ? 180+circleDiameter+155 : null,bottom:layout.value === 'circular' ? null : 10},legend:{selected:selectedTypes},series:[{layout:layout.value === 'layered' ? 'none' : layout.value, data:nodes, links:links,
      left:layout.value === 'circular' ? (chart.getWidth()-circleDiameter)/2 : leftMargin, right:layout.value === 'circular' ? null : rightMargin,
      width:layout.value === 'circular' ? circleDiameter : null,height:layout.value === 'circular' ? circleDiameter : null,
      top:layout.value === 'circular' ? 180 : 70, bottom:layout.value === 'circular' ? null : 65,
      circular:{rotateLabel:true}, label:{show:labels.checked}, center:null, zoom:1}]});
    announce('当前显示 ' + nodes.length + ' 个节点 / ' + links.length + ' 条边；原图 ' + originalNodes.length + ' 个节点 / ' + originalLinks.length + ' 条边。' +
      (hiddenIsolates ? ' 已收起 ' + hiddenIsolates + ' 个孤立节点，可勾选“显示孤立节点”恢复；完整数据未删除。' : '') +
      (chart.getWidth() < 520 && !labels.checked ? ' 可搜索定位节点，或勾选“显示标签”查看名称。' : ''));
  }
  function resetGraphControls() {
    activeTypes = new Set(originalCategories.map(function(c) { return c.name; }));
    document.querySelectorAll('#chart-types input').forEach(function(input) { input.checked = true; });
    score.value = 0; layout.value = defaultLayout; labels.checked = defaultLabels; isolates.checked = !x.hideIsolatesByDefault;
    updateGraph();
  }
  function restoreNetwork() {
    search.value = '';
    // Rebuild the series so emphasis/blur attached to previous graphic objects
    // cannot survive restore + setOption merges with the same node IDs.
    chart.clear();
    chart.setOption(initial, {notMerge:true});
    resetGraphControls();
    details.textContent = '视图已重置；点击图中条目查看详情。';
  }
  if (x.chartType === 'network') {
    originalCategories.forEach(function(category) {
      var label = document.createElement('label'); label.className = 'check';
      var input = document.createElement('input'); input.type = 'checkbox'; input.checked = true;
      input.addEventListener('change', function() { if (input.checked) activeTypes.add(category.name); else activeTypes.delete(category.name); updateGraph(); });
      input.dataset.type = category.name;
      label.append(input, document.createTextNode(typeLabels[category.name] || category.name)); document.getElementById('chart-types').appendChild(label);
    });
    layout.addEventListener('change', updateGraph); score.addEventListener('change', updateGraph); labels.addEventListener('change', updateGraph);
    isolates.addEventListener('change', updateGraph);
    chart.on('legendselectchanged', function(event) {
      originalCategories.forEach(function(c) { if (event.selected[c.name]) activeTypes.add(c.name); else activeTypes.delete(c.name); });
      document.querySelectorAll('#chart-types input').forEach(function(input) { input.checked = activeTypes.has(input.dataset.type); });
      updateGraph();
    });
    document.getElementById('chart-apply').addEventListener('click', updateGraph);
    [['chart-zoom-in','放大网络',1.15],['chart-zoom-out','缩小网络',1/1.15]].forEach(function(item) {
      var button = document.createElement('button'); button.id = item[0]; button.textContent = item[1];
      button.addEventListener('click', function() {
        chart.dispatchAction({type:'graphRoam',seriesIndex:0,zoom:item[2],originX:chart.getWidth()/2,originY:chart.getHeight()/2});
        var series = chart.getOption().series[0];
        announce('当前显示 '+series.data.length+' 个节点 / '+series.links.length+' 条边；缩放 '+Math.round((series.zoom || 1)*100)+'%，数据不变。');
      });
      document.getElementById('r-chart-controls').appendChild(button);
    });
    layout.value = defaultLayout; labels.checked = defaultLabels; isolates.checked = !x.hideIsolatesByDefault; updateGraph();
    chart.on('restore', restoreNetwork);
  } else { announce('交互图表已就绪；可缩放、图例筛选和定位条目。'); }
  function describe(p) {
    var d = p.data;
    if (p.dataType === 'edge') {
      var nodeNames = new Map(originalNodes.map(function(n) { return [n.id,labelOf(n)]; }));
      return (nodeNames.get(d.source)||d.source) + ' ↔ ' + (nodeNames.get(d.target)||d.target) + '\n评分 / 关系标记: ' + d.score +
        (Array.isArray(d.evidence)&&d.evidence.length ? '\n来源证据（最多显示 5 条，完整记录保留在检索快照）：\n'+d.evidence.map(function(e) {
          return (nodeNames.get(e.source)||e.source)+' → '+(nodeNames.get(e.target)||e.target)+' · '+e.relation+'\n'+e.sourceSlug+' · '+e.sourceVersion+' · 记录 '+e.sourceRecordId;
        }).join('\n') : '');
    }
    if (x.chartType === 'network') {
      var links = chart.getOption().series[0].links;
      var neighbors = new Set(); links.forEach(function(l) { if (l.source === d.id) neighbors.add(l.target); if (l.target === d.id) neighbors.add(l.source); });
      var lookup = new Map(originalNodes.map(function(n) { return [n.id, labelOf(n)]; }));
      var identityDetail = d.canonicalTargetKey ? '\n人类标准靶点: ' + d.canonicalTargetKey + ' · 已核验' + (d.targetOverlap ? '\n中药侧与疾病侧的共享靶点' : '') : '';
      var sourceDetail = d.sourceEntityCount > 1 ? '\n合并展示的同名来源实体: ' + d.sourceEntityCount + ' 条（关系证据按来源保留）' : '';
      return labelOf(d) + ' · ' + (typeLabels[d.nodeType] || d.nodeType) + '\n显示连接度: ' + d.value + ' · 原始输入连接度: ' + d.originalDegree + sourceDetail + identityDetail + '\n邻居: ' + Array.from(neighbors).map(function(id) { return lookup.get(id) || id; }).join('、');
    }
    if (x.chartType === 'volcano') return d.label + '\nlog2FC: ' + d.value[0] + ' · P: ' + d.pValue + ' · FDR: ' + (d.fdr == null ? '未提供' : d.fdr) + '\n保存的筛选状态: ' + (d.selected ? '通过' : '未通过');
    if (x.chartType === 'enrichment_bubble') return d.label + '\n' + d.source + ' · GeneRatio: ' + d.value[0] + ' · 命中数: ' + d.value[3] + ' · FDR: ' + d.fdr;
    return d.label + '\n数值: ' + d.value[0];
  }
  chart.on('click', function(p) { if (p.data) details.textContent = describe(p); });
  if (x.chartType === 'volcano') chart.on('brushSelected', function(event) {
    var items = event && event.batch && event.batch[0] && event.batch[0].selected;
    if (!Array.isArray(items)) return; // ECharts also emits empty brush events on resize/restore.
    var selected = items.reduce(function(total, item) { return total + (Array.isArray(item.dataIndex) ? item.dataIndex.length : 0); }, 0);
    announce('框选 ' + selected + ' 个点；仅用于查看，不修改保存的筛选状态。');
  });
  function find() {
    var query = search.value.trim().toLowerCase();
    chart.dispatchAction({type:'downplay'});
    if (!query) { announce('请输入名称或 ID。'); return; }
    var matches = [];
    chart.getOption().series.forEach(function(series, s) { (series.data || []).forEach(function(d, i) { if ((labelOf(d) + ' ' + (d.id || '')).toLowerCase().indexOf(query) >= 0) matches.push({seriesIndex:s,dataIndex:i,data:d}); }); });
    if (!matches.length) { announce('未找到条目（请检查当前筛选范围）。'); return; }
    var match = matches[0]; chart.dispatchAction({type:'highlight',seriesIndex:match.seriesIndex,dataIndex:match.dataIndex});
    // Network details are already shown below. A programmatic graph tooltip
    // also simulates pointer hover, leaving adjacency blur after a reset.
    if (x.chartType !== 'network') chart.dispatchAction({type:'showTip',seriesIndex:match.seriesIndex,dataIndex:match.dataIndex});
    details.textContent = describe({data:match.data,dataType:'node'}); announce('找到 ' + matches.length + ' 个匹配；已定位 ' + labelOf(match.data) + '。');
  }
  document.getElementById('chart-find').addEventListener('click', find);
  search.addEventListener('keydown', function(event) { if (event.key === 'Enter') find(); });
  document.getElementById('chart-reset').addEventListener('click', function() {
    if (x.chartType === 'network') {
      restoreNetwork();
    } else {
      search.value = ''; chart.dispatchAction({type:'restore'}); chart.dispatchAction({type:'downplay'}); chart.dispatchAction({type:'hideTip'});
      announce('视图已重置。');
    }
    details.textContent = '视图已重置；点击图中条目查看详情。';
  });
  var lastWidth = chart.getWidth();
  new ResizeObserver(function() {
    chart.resize();
    var width = chart.getWidth();
    if (x.chartType === 'network' && width !== lastWidth) updateGraph();
    lastWidth = width;
  }).observe(el);
  } catch (error) {
    var message = error && error.message ? error.message : String(error || '未知错误');
    if (status) status.textContent = '交互图表初始化失败：' + message.slice(0, 180) + '。请切换静态预览或重新生成图表。';
    if (window.console && typeof window.console.error === 'function') window.console.error('R interactive chart initialization failed', error);
  }
}
