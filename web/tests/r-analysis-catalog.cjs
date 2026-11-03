// Offline synthetic catalog contracts: never query STRING or invent app evidence.
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { createRequire } = require('module');
const load = createRequire(path.resolve(__dirname, '../package.json'));
const ts = load('typescript');
require.extensions['.css'] = () => {};
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, filename);
const { rChartCatalog } = load('./src/components/RAnalysisGallery.tsx');
const parent = { id: 1, task_type: 'proteomics', status: 'succeeded', result: {} };
const empty = rChartCatalog(parent);
assert.equal(empty.filter(chart => chart.available).length, 0, 'An empty result has no persisted statistics to plot');
assert.ok(empty.every(chart => chart.unavailableReason && chart.nextStep));
assert.ok(empty.some(chart => chart.key === 'ppi_network' && !chart.available));
const ppi = { source: 'STRING', networkType: 'physical', status: 'succeeded', edges: [{ source: 'SYN_A', target: 'SYN_B', score: 0.9 }] };
assert.ok(rChartCatalog({ ...parent, result: { externalString: ppi } }).find(chart => chart.key === 'ppi_network').available);
assert.ok(!rChartCatalog({ ...parent, result: { externalString: { ...ppi, status: 'unavailable' } } }).find(chart => chart.key === 'ppi_network').available);
assert.equal(rChartCatalog({ ...parent, task_type: 'network', result: { ...ppi, analysisKind: 'string_ppi' } }).length, 2);
assert.deepEqual(rChartCatalog({ ...parent, task_type: 'case_link' }), []);
const catalogTask = { ...parent, task_type:'network', result:{analysisKind:'catalog_evidence',queryType:'herb',catalogSummary:[{label:'中药',value:0}],network:{nodes:[],links:[]}} };
assert.ok(rChartCatalog(catalogTask).find(chart=>chart.key==='catalog_summary').available);
assert.ok(!rChartCatalog(catalogTask).find(chart=>chart.key==='evidence_network').available);
assert.deepEqual(rChartCatalog({...catalogTask,result:{...catalogTask.result,queryType:'comparison'}}).map(chart=>chart.key),['catalog_summary']);
const catalogue = rChartCatalog({ ...parent, task_type: 'network', result: { analysisKind: 'catalog_evidence', network: { links: [{source:'one',target:'two'}] } } });
assert.equal(catalogue.length, 1);
assert.equal(catalogue[0].key, 'evidence_network');
assert.equal(catalogue[0].available, true);
assert.ok(!catalogue[0].label.includes('疾病'), 'A herb-only query must not imply disease evidence');
console.log('PASS: R catalog exposes real-data prerequisites, PPI failure states, standalone results and unsupported tasks.');

const { SubviewTabs, nextSubview } = load('./src/components/SubviewTabs.tsx');
const { createElement } = load('react');
const { renderToStaticMarkup } = load('react-dom/server');
const views = ['volcano', 'ppi', 'enrichment'].map(key => ({key, label:key, content:createElement('img', {src:`/${key}.svg`, alt:key})}));
const renderTabs = (value, keepMounted = false) => renderToStaticMarkup(createElement(SubviewTabs, {label:'测试图表', views, value, keepMounted, onChange:()=>{}}));
for (const value of views.map(view => view.key)) {
  const html = renderTabs(value);
  assert.equal((html.match(/<img /g) || []).length, 1);
  assert.ok(html.includes(`src="/${value}.svg"`));
  assert.equal((html.match(/role="tabpanel"/g) || []).length, 1);
  assert.equal((html.match(/aria-selected="true"/g) || []).length, 1);
  assert.ok(html.includes('aria-controls=') && html.includes('aria-labelledby='));
}
assert.ok(renderTabs('unknown').includes('src="/volcano.svg"'));
const mounted = renderTabs('ppi', true);
assert.equal((mounted.match(/role="tabpanel"/g) || []).length, 3);
assert.equal((mounted.match(/ hidden=""/g) || []).length, 2);
const keys = views.map(view => view.key);
assert.equal(nextSubview(keys, 'volcano', 'ArrowLeft'), 'enrichment');
assert.equal(nextSubview(keys, 'enrichment', 'ArrowRight'), 'volcano');
assert.equal(nextSubview(keys, 'ppi', 'Home'), 'volcano');
assert.equal(nextSubview(keys, 'ppi', 'End'), 'enrichment');
assert.equal(nextSubview(keys, 'ppi', 'Tab'), undefined);
assert.equal(nextSubview([], '', 'ArrowRight'), undefined);
const css = fs.readFileSync(path.resolve(__dirname, '../src/styles/app.css'), 'utf8');
const previewRule = css.match(/\.visualization-preview\s*\{([^}]+)\}/)[1];
assert.ok(previewRule.includes('height: auto') && previewRule.includes('max-height: none'));
assert.ok(css.includes('.subview-panel[hidden] { display: none; }'));
console.log('PASS: single-chart subpages, hidden preserved result state, fallback selection, keyboard navigation and unrestricted image aspect ratio.');

const { RChartSource, RChartSourceProvider } = load('./src/components/RChartSource.tsx');
const chartKeys = ['proteomics_volcano', 'proteomics_go_kegg_enrichment', ...empty.map(chart => chart.key)];
for (const source of ['demo', 'task', 'public', 'demo', 'task']) {
  for (const chartKey of chartKeys) {
    const html = renderToStaticMarkup(createElement(RChartSourceProvider, {source, onChange:()=>{}},
      createElement(RChartSource, {chartKey}, createElement('p', null, `TASK_CONTENT_${chartKey}`))));
    const selectedTab = html.match(/<button[^>]*aria-selected="true"[^>]*>(.*?)<\/button>/)[1];
    assert.equal(selectedTab, source === 'demo' ? '合成演示图表' : source === 'public' ? '公开数据示例' : '当前任务图表');
    assert.equal(html.includes(`TASK_CONTENT_${chartKey}`), source === 'task');
    assert.equal(html.includes(`aria-label="${chartKey} 合成演示"`), source === 'demo');
    assert.ok(!html.includes('合成演示与 key'));
  }
}
assert.throws(() => renderToStaticMarkup(createElement(RChartSource, {chartKey:chartKeys[0]}, 'task')), /source selection provider/);
console.log('PASS: all chart viewers use gallery-wide task/demo selection, including remounted additional charts, and the renamed demo tab.');

const { RChartViewer, hasInteractiveRenderer } = load('./src/components/RChartViewer.tsx');
assert.equal(hasInteractiveRenderer('r-viz-0.3.0'), false);
assert.equal(hasInteractiveRenderer('r-viz-0.4.0'), true);
const widget = renderToStaticMarkup(createElement(RChartViewer,{title:'TEST',interactive:true,svgUrl:'/chart.svg',htmlUrl:'/chart.html'}));
assert.ok(widget.includes('sandbox="allow-scripts allow-downloads"'));
assert.ok(!widget.includes('allow-same-origin'));
assert.equal((widget.match(/<iframe /g)||[]).length,1);
assert.equal((widget.match(/<img /g)||[]).length,0);
const historical = renderToStaticMarkup(createElement(RChartViewer,{title:'OLD',interactive:false,svgUrl:'/chart.svg',htmlUrl:'/chart.html'}));
assert.ok(!historical.includes('<iframe '));
assert.ok(historical.includes('<img '));
const hiddenViewer = renderToStaticMarkup(createElement(SubviewTabs,{label:'Keep state',value:'form',keepMounted:true,onChange:()=>{},views:[
  {key:'form',label:'Form',content:createElement('input')},
  {key:'chart',label:'Chart',content:createElement(RChartViewer,{title:'Hidden',interactive:true,htmlUrl:'/chart.html'})},
]}));
assert.ok(hiddenViewer.includes('<input'));
assert.ok(!hiddenViewer.includes('<iframe'));
const { readPublicManifest } = load('./src/components/RPublicGallery.tsx');
const publicManifest = {synthetic:false,publicExample:true,disclaimer:'Public',provenance:{source:'STRING',networkType:'physical',license:'CC BY 4.0',contentSha256:'a'.repeat(64)},charts:[{key:'ppi_network',label:'PPI',rendererVersion:'r-viz-0.4.0',inputSha256:'b'.repeat(64),artifacts:{html:'c'.repeat(64)}}]};
assert.equal(readPublicManifest(publicManifest).charts.length,1);
for (const invalid of [{...publicManifest,synthetic:true},{...publicManifest,provenance:{...publicManifest.provenance,networkType:'functional'}},{...publicManifest,charts:[{...publicManifest.charts[0],key:'../../private'}]}]) assert.throws(()=>readPublicManifest(invalid));
console.log('PASS: offline interactive iframe, opaque sandbox, historical fallback and separately labelled public data.');
