// Offline synthetic catalog contracts: never query STRING or invent app evidence.
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { createRequire } = require('module');
const load = createRequire(path.resolve(__dirname, '../package.json'));
const ts = load('typescript');
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, filename);
const { rChartCatalog } = load('./src/components/RAnalysisGallery.tsx');
const parent = { id: 1, task_type: 'proteomics', status: 'succeeded', result: {} };
const empty = rChartCatalog(parent);
assert.equal(empty.filter(chart => chart.available).length, 1);
assert.ok(empty.some(chart => chart.key === 'ppi_network' && !chart.available));
const ppi = { source: 'STRING', networkType: 'physical', status: 'succeeded', edges: [{ source: 'SYN_A', target: 'SYN_B', score: 0.9 }] };
assert.ok(rChartCatalog({ ...parent, result: { externalString: ppi } }).find(chart => chart.key === 'ppi_network').available);
assert.ok(!rChartCatalog({ ...parent, result: { externalString: { ...ppi, status: 'unavailable' } } }).find(chart => chart.key === 'ppi_network').available);
assert.equal(rChartCatalog({ ...parent, task_type: 'network', result: { ...ppi, analysisKind: 'string_ppi' } }).length, 2);
assert.deepEqual(rChartCatalog({ ...parent, task_type: 'case_link' }), []);
console.log('PASS: R catalog exposes real-data prerequisites, PPI failure states, standalone results and unsupported tasks.');
