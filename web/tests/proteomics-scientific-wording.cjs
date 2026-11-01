// Render the real result component with React SSR and frozen synthetic legacy
// results. No request, database, external scientific service, or model is used.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const load = Module.createRequire(path.join(root, 'package.json'));
const ts = load('typescript'), React = load('react');
const {renderToStaticMarkup} = load('react-dom/server');
const file = path.join(root, 'src/pages/ProteomicsPage.tsx');
const subject = new Module(file);
// Use the production tabs and React SSR so all keepMounted result panels,
// including the reference-symbol and row-QC pages, render their actual content.
const tabsFile = path.join(root, 'src/components/SubviewTabs.tsx');
const tabs = new Module(tabsFile);
tabs.require = name => name === 'react' ? React : name === 'react/jsx-runtime' ? load(name) : (() => {throw Error('Unexpected tab import ' + name);})();
tabs._compile(ts.transpileModule(fs.readFileSync(tabsFile, 'utf8'), {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
}}).outputText, tabsFile);
const unused = new Proxy({}, {get: () => () => {throw Error('No request is permitted in this component test');}});
const Viewer = () => null;
subject.require = name => {
  if (name === 'react') return React;
  if (name === 'react/jsx-runtime') return load(name);
  if (name === 'lucide-react') return new Proxy({}, {get: () => () => null});
  if (name === 'react-router-dom') return {Link:({to,children,...props})=>React.createElement('a',{...props,href:to},children)};
  if (name === '../api/client') return {ApiError: class extends Error {}};
  if (name.startsWith('../api/')) return unused;
  if (name === '../components/SubviewTabs') return tabs.exports;
  if (name === '../components/RChartViewer') return {RChartViewer:Viewer,hasInteractiveRenderer:()=>false};
  if (name.startsWith('../components/')) return new Proxy({}, {get: () => () => null});
  throw Error('Unexpected import ' + name);
};
// Expose only to this compiled test module; the production module exports and
// component implementation stay unchanged.
const source = fs.readFileSync(file, 'utf8') + '\nexport { ProteomicsResultView, ProteomicsVisualizationResult };\n';
subject._compile(ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
}}).outputText, file);
const legacyResult = () => ({
  algorithmVersion: 'SYNTHETIC_LEGACY', dataset: {sha256: 'a'.repeat(64)},
  summary: {selectedRowCount: 2, uniqueLabelCount: 2, databaseMappedCount: 0,
    unverifiedSymbolCount: 2, unmappedCount: 0, pathwayCount: 0, candidateOverlapCount: 1,
    enrichmentNote: 'SYNTHETIC_LOCAL_ONLY'},
  qc: {inputRowCount: 3, missingIdentifierCount: 0, duplicateIdentifierCount: 0,
    invalidNumericValueRowCount: 0, excludedRowCount: 1, excludedReasonCounts: {}},
  warnings: [], topNodes: [], pathways: [], unmapped: [], rows: [],
  validation: {referenceTargets: ['SHARED', 'REFERENCE_ONLY'], overlap: ['SHARED'],
    proteomicsOnly: ['SELECTED_ONLY'], referenceOnly: ['REFERENCE_ONLY']},
});
const render = (result, overrides = {}) => renderToStaticMarkup(React.createElement(subject.exports.ProteomicsResultView, {
  result, task: {id: 99, source_releases: []}, showRows: false, rowPage: null,
  rowPageNumber: 1, rowReadFailed: false, visualizationTask: null, volcanoVisualizationTask: null,
  visualizationSubmitting: false, onCreateVolcanoVisualization() {}, onCreateGoKeggVisualization() {},
  onToggleRows() {}, onRowPageChange() {}, ...overrides,
}));

const tests = [];
const check = (name, run) => tests.push({name, run});
check('Legacy unverified symbol sets keep their exact groups and count without claiming identity validation', () => {
  const result = legacyResult(), before = JSON.stringify(result), html = render(result);
  assert.ok(html.includes('参考符号对照'));
  assert.match(html, /<span>入选符号重叠<\/span><strong>1<\/strong>/);
  assert.match(html, /<span>入选符号重叠<\/span><p>SHARED<\/p>/);
  assert.match(html, /<span>入选但不在参考集<\/span><p>SELECTED_ONLY<\/p>/);
  assert.match(html, /<span>参考中未入选<\/span><p>REFERENCE_ONLY<\/p>/);
  assert.ok(html.includes('可能包含未核实项'));
  assert.ok(html.includes('名称重叠不代表同物种身份已确认或生物学交叉验证'));
  assert.ok(html.includes('不等于实验未测到'));
  for (const old of ['与候选靶点交叉验证', '共同靶点', '组学特有', '候选未检出', '候选交集']) assert.ok(!html.includes(old), old);
  assert.equal(JSON.stringify(result), before, 'Rendering must not rewrite frozen result sets or scientific values');
});
check('An empty reference set remains readable without implying absent experimental measurements', () => {
  const result = legacyResult();
  result.validation = {referenceTargets: [], overlap: [], proteomicsOnly: ['SELECTED_ONLY'], referenceOnly: []};
  result.summary.candidateOverlapCount = 0;
  const html = render(result);
  assert.ok(html.includes('本次未输入参考符号，只生成蛋白组学内部结果'));
  assert.ok(!html.includes('proteomics-validation-grid'));
  assert.match(html, /<span>入选符号重叠<\/span><strong>0<\/strong>/);
});
check('Actual summary and row-QC rendering explains numeric ambiguity, including safely escaped sample columns', () => {
  const result = legacyResult();
  result.qc.excludedReasonCounts = {ambiguous_numeric_format: 1};
  const reasons = ['ambiguous_log2fc_numeric_format', 'ambiguous_p_value_numeric_format',
    'ambiguous_fdr_numeric_format', 'ambiguous_sample_numeric_format',
    'ambiguous_sample_numeric_format:Sample<1>'];
  const rowPage = {count: 1, next: null, previous: null, results: [{row_index: 0,
    original_label: 'SYNTHETIC_BAD_NUMBER', normalized_symbol: '', mapping_status: 'unmapped',
    log2_fold_change: null, fdr: null, selected: false,
    exclusion_reasons: ['ambiguous_numeric_format'], qc_warnings: reasons}]};
  const html = render(result, {showRows: true, rowPage});
  assert.ok(html.includes('含逗号数值格式，含义不明确，未转换'));
  for (const label of ['log2FC 含逗号数值格式', 'P 值含逗号数值格式', 'FDR 含逗号数值格式', '样本值含逗号数值格式']) assert.ok(html.includes(label), label);
  assert.ok(html.includes('样本列 Sample&lt;1&gt; 含逗号数值格式'));
  assert.ok(!html.includes('ambiguous_'), 'Known machine reasons must render their explanation');
  assert.ok(!html.includes('<1>'), 'Sample names are rendered as text, never markup');
});


check('Each redraw state retains links to its current task and the previous immutable figure', () => {
  for(const status of ['queued','running','failed','cancelled','succeeded']){
    const task={id:102,status,progress:5,error_summary:'SYNTHETIC_R_FAILURE',input_parameters:{previousRenderTaskId:101},
      result:{previousRenderTaskId:101,rendererVersion:'r-viz-0.4.2',artifacts:[]}};
    const html=renderToStaticMarkup(React.createElement(subject.exports.ProteomicsVisualizationResult,{task,title:'R_TEST',alt:'R_TEST'}));
    assert.ok(html.includes('href="/tasks/102"'));assert.ok(html.includes('href="/tasks/101"'));assert.ok(html.includes('查看上一版图表'));
    assert.ok(!html.includes('/r-demo/')&&!html.includes('/r-public-demo/'));
    if(status==='failed')assert.ok(html.includes('SYNTHETIC_R_FAILURE'));
    if(status==='succeeded')assert.ok(html.includes('r-viz-0.4.2'));
  }
});
check('An old static proteomics figure and a new R rendering mount different viewer instances', () => {
  const nodes = node => !node || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
  for(const [id,version] of [[101,'r-viz-0.3.0'],[102,'r-viz-0.4.2']]){
    const task={id,status:'succeeded',input_parameters:{},result:{rendererVersion:version,artifacts:[{id,format:'svg',downloadUrl:`/private/${id}.svg`}]}};
    const rendered=subject.exports.ProteomicsVisualizationResult({task,title:'R_TEST',alt:'R_TEST'});
    const viewer=nodes(rendered).find(node=>node.type===Viewer);
    assert.equal(viewer.key,String(id));assert.equal(viewer.props.svgUrl,`/private/${id}.svg?inline=1`);
  }
});

let failed = 0;
for (const {name, run} of tests) {
  try {run(); console.log('PASS: ' + name);} catch (error) {failed++; console.error('FAIL: ' + name + '\n' + error.stack);}
}
console.log(`${tests.length - failed}/${tests.length} scientific wording regressions passed`);
if (failed) process.exitCode = 1;
