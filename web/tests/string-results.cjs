// Synthetic STRING contracts only: no external API/model calls and no invented app results.
const fs = require('fs');
const path = require('path');
const {createRequire} = require('module');
const assert = require('node:assert/strict');
const webRoot = path.resolve(__dirname, '..');
const load = createRequire(path.join(webRoot, 'package.json'));
const ts = load('typescript');
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX}}).outputText, filename);
const React = load('react');
const {renderToStaticMarkup} = load('react-dom/server');
const {readStringNetwork, stringResultJson, StringNetworkResult, StringTaskResult} = load('./src/components/StringNetworkResult.tsx');
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const nodes = Array.from({length:36}, (_, index) => ({id:`9606.SYN${index}`, label:`SYNTHETIC_${index}`, type:'protein', degree:index, betweenness:index/100}));
const edges = [];
for (let a = 0; a < nodes.length && edges.length < 245; a++) {
  for (let b = a+1; b < nodes.length && edges.length < 245; b++) edges.push({source:nodes[a].id, target:nodes[b].id, score:0.875, scoreOutOf1000:875});
}
const value = {
  analysisKind:'string_ppi', organism:'Homo sapiens', taxonId:9606, source:'STRING', sourceVersion:null,
  sourceVersionKnown:false, sourceEndpoint:'https://synthetic.invalid/api', retrievedAt:'2026-10-04T00:00:00Z',
  networkType:'physical', requiredScore:700, inputCount:207, submittedIdentifierCount:200,
  truncatedIdentifierCount:7, rejectedIdentifierCount:2, interactionCount:edges.length, nodes, edges,
  centralityMethod:'degree=unique_neighbors; betweenness=normalized_unweighted_brandes', consentRecorded:true,
};
const task = {
  id:78, parent_task:51, task_type:'network', status:'succeeded', dataset:null, medical_case:null,
  input_parameters:{analysisKind:'string_ppi', rawTargets:['SYNTHETIC_A','SYNTHETIC_B'], consentRecorded:true},
  source_releases:[9], progress:100, result:value, error_summary:'',
  created_at:'2026-10-04T00:00:00Z', started_at:'2026-10-04T00:00:01Z', finished_at:'2026-10-04T00:00:02Z',
};
assert.equal(readStringNetwork(value), value);
const exported = JSON.parse(stringResultJson(value, task));
assert.equal(exported.formatVersion, 'string-network-export-v1');
assert.deepEqual(exported.result, value);
assert.equal(exported.result.edges.length, 245);
assert.equal(exported.result.nodes.length, 36);
assert.equal(exported.result.sourceVersion, null);
assert.equal(exported.result.sourceEndpoint, value.sourceEndpoint);
assert.equal(exported.task.parent_task, 51);
assert.deepEqual(exported.task.input_parameters, task.input_parameters);
assert.deepEqual(exported.task.source_releases, [9]);
const html = render(StringNetworkResult, {result:value, task});
assert.ok(html.includes('导出 STRING 记录 JSON') && html.includes('来源版本未返回'));
assert.ok(html.includes('全部 245 条') && html.includes('全部 36 个') && html.includes('7 个未发送'));
assert.ok(html.includes('2 个无效或过长标识') && html.includes('当前网络仅覆盖已提交标识'));
assert.equal((html.match(/<tr>/g)||[]).length, 232); // 2 headers + 200 edges + 30 ranked nodes.
const rankingHtml = html.slice(html.indexOf('STRING 网络中心性'));
assert.ok(rankingHtml.indexOf('title="9606.SYN35"') < rankingHtml.indexOf('title="9606.SYN34"'));
assert.equal(nodes[0].id, '9606.SYN0'); // Display sorting must not mutate result evidence.
assert.ok(html.includes('不代表因果结论') && html.includes('875/1000'));
const taskHtml = render(StringTaskResult, {task, sourceTaskId:51});
assert.ok(taskHtml.includes('来源查询任务 #51 已保存在服务端'));
const {parent_task, ...historicalTask} = task;
assert.ok(render(StringTaskResult, {task:historicalTask, sourceTaskId:51}).includes('历史任务尚未保存来源绑定'));
const mismatchHtml = render(StringTaskResult, {task, sourceTaskId:52});
assert.ok(mismatchHtml.includes('来源不一致') && !mismatchHtml.includes('导出 STRING'));
const wrongKind = render(StringTaskResult, {task:{...task, input_parameters:{analysisKind:'reactome_enrichment'}}});
assert.ok(wrongKind.includes('来源不一致') && !wrongKind.includes('导出 STRING'));

const empty = {...value, nodes:[], edges:[], interactionCount:0, inputCount:2, submittedIdentifierCount:2, truncatedIdentifierCount:0, rejectedIdentifierCount:0};
for (const status of ['no_interactions', 'insufficient_identifiers', 'unavailable', 'disabled']) {
  const record = {...empty, status};
  assert.ok(readStringNetwork(record));
  assert.equal(JSON.parse(stringResultJson(record)).result.status, status);
  const markup = render(StringNetworkResult, {result:record});
  assert.ok(!markup.includes('<table') && !markup.includes('STRING 网络中心性'));
  if (status === 'no_interactions') assert.ok(markup.includes('本次查询已完成') && markup.includes('没有返回物理互作边'));
  else assert.ok(!markup.includes('没有返回物理互作边') && !markup.includes('本次查询已完成'));
  if (status === 'unavailable') assert.ok(markup.includes('不能据此判断蛋白之间没有互作'));
  if (status === 'disabled') assert.ok(markup.includes('本次没有生成外部互作结果'));
  if (status === 'insufficient_identifiers') assert.ok(markup.includes('本次未向 STRING 发送查询'));
}
// Standalone external task payloads have no embedded status/count of submitted IDs.
const {status, submittedIdentifierCount, truncatedIdentifierCount, rejectedIdentifierCount, ...standalone} = empty;
assert.ok(readStringNetwork(standalone));
assert.ok(render(StringTaskResult, {task:{...task, result:standalone}}).includes('没有返回物理互作边'));
const {analysisKind, ...proteomicsRecord} = {...empty, status:'no_interactions'};
assert.ok(readStringNetwork(proteomicsRecord)); // Historical proteomics integrations omit analysisKind.
for (const state of ['queued','running','failed','cancelled']) {
  const record = {...task, status:state, error_summary:'Synthetic connector failure'};
  const markup = render(StringTaskResult, {task:record});
  assert.equal(stringResultJson(value, record), null);
  assert.ok(!markup.includes('导出 STRING') && !markup.includes('没有返回物理互作边'));
  if (state === 'failed') assert.ok(markup.includes('Synthetic connector failure') && markup.includes('role="alert"'));
}
for (const invalid of [
  {}, {...value, analysisKind:'reactome_enrichment', status:'succeeded'}, {...value, status:'__proto__'},
  {...value, interactionCount:1}, {...value, requiredScore:1001}, {...value, inputCount:-1},
  {...value, edges:[{...edges[0], source:'UNKNOWN'}], interactionCount:1},
  {...value, edges:[{...edges[0], score:NaN}], interactionCount:1},
  {...value, edges:[{...edges[0], scoreOutOf1000:1001}], interactionCount:1},
  {...value, nodes:[nodes[0],nodes[0]], edges:[], interactionCount:0},
  {...empty, truncatedIdentifierCount:'7'}, {...value, status:'unavailable'},
]) {
  assert.equal(readStringNetwork(invalid), null);
  assert.equal(stringResultJson(invalid, task), null);
  const markup = render(StringNetworkResult, {result:invalid, task});
  assert.ok(markup.includes('结果格式不完整') && !markup.includes('导出 STRING') && !markup.includes('没有返回物理互作边'));
}
console.log('PASS: STRING full 245-edge/36-node JSON provenance; bounded 200-edge/30-node tables; null version and truncation; empty vs unavailable/disabled states; queue/failure/cancel; parent binding/history; invalid payloads rejected, no external calls.');
