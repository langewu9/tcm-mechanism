// Offline HTTP boundary checks: no browser, model or external API is contacted.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const assert = require('node:assert/strict');
const webRoot = path.resolve(__dirname, '..');
const load = createRequire(path.join(webRoot, 'package.json'));
const ts = load('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText, filename);
const {apiRequest, apiRequestBlob, ApiError} = load('./src/api/client.ts');
const {runReactomeEnrichment, runStringNetwork} = load('./src/api/network.ts');
const {getAnalysisTaskSummaries} = load('./src/api/datasets.ts');
let replies = [], calls = [];
global.fetch = async (url, options) => {
  calls.push({url, options});
  const reply = replies.shift();
  assert.ok(reply, `Unexpected request ${url}`);
  if (reply instanceof Error) throw reply;
  return reply;
};
const json = (value, status=200) => new Response(JSON.stringify(value), {status, headers:{'Content-Type':'application/json','X-Request-ID':'synthetic-request-id'}});
const csrf = () => json({csrfToken:'synthetic-csrf'});
function reset(values) {replies=values; calls=[];}
async function rejects(action, code, status) {
  await assert.rejects(action, error => error instanceof ApiError && error.code === code && error.status === status);
  assert.equal(replies.length, 0);
}
(async () => {
  reset([json({count:0,next:null,previous:null,results:[]})]);
  await getAnalysisTaskSummaries(2,41);
  assert.equal(calls[0].url,'/api/v1/research/analysis-tasks/summaries/?page=2&parent_task=41&task_type=visualization');
  assert.equal(calls[0].options.credentials,'same-origin');
  reset([json({count:0,next:null,previous:null,results:[]})]);
  await getAnalysisTaskSummaries(1,undefined,'research_assistant');
  assert.equal(calls[0].url,'/api/v1/research/analysis-tasks/summaries/?page=1&task_type=research_assistant');
  for (const [action, endpoint, body] of [
    [() => runReactomeEnrichment(41), '/api/v1/analysis/pathway-enrichment/', {source_task_id:41,consent:true}],
    [() => runStringNetwork(41,700), '/api/v1/analysis/string-network/', {source_task_id:41,required_score:700,consent:true}],
  ]) {
    reset([csrf(), json({id:42,parent_task:41},202)]);
    assert.equal((await action()).parent_task,41);
    assert.equal(calls[0].url,'/api/v1/auth/csrf/');
    assert.equal(calls[1].url,endpoint);
    assert.equal(calls[1].options.credentials,'same-origin');
    assert.equal(calls[1].options.headers.get('X-CSRFToken'),'synthetic-csrf');
    assert.deepEqual(JSON.parse(calls[1].options.body),body);
    assert.ok(!calls[1].options.body.includes('targets'), 'Server derives targets from the private source task');
  }
  reset([new Response('<html>proxy error</html>', {headers:{'X-Request-ID':'synthetic-proxy-id'}})]);
  await assert.rejects(() => apiRequest('/api/test/'), error => error instanceof ApiError && error.code === 'INVALID_RESPONSE' && error.requestId === 'synthetic-proxy-id');
  reset([new Response('<html>proxy error</html>')]);
  await rejects(() => apiRequest('/api/test/',{method:'POST',body:{}}),'INVALID_RESPONSE',200);
  assert.equal(calls.length,1, 'Unsafe request is not submitted when CSRF cannot be parsed');
  for (const payload of [null,{csrfToken:42},{csrfToken:''}]) {
    reset([json(payload)]);
    await rejects(() => apiRequest('/api/test/',{method:'DELETE'}),'CSRF_TOKEN_MISSING',200);
    assert.equal(calls.length,1);
  }
  reset([json({error:{code:'permission_denied',message:'仅可查看本人数据',details:{},requestId:'synthetic-server-id'}},403)]);
  await assert.rejects(() => apiRequest('/api/private/'), error => error instanceof ApiError && error.message === '仅可查看本人数据' && error.requestId === 'synthetic-server-id' && error.status === 403);
  reset([json({error:{code:[],message:{bad:true},requestId:12}},502)]);
  await rejects(() => apiRequest('/api/test/'),'UNEXPECTED_RESPONSE',502);
  reset([new Error('synthetic offline')]);
  await rejects(() => apiRequest('/api/test/'),'NETWORK_ERROR',0);
  reset([new Error('synthetic offline')]);
  await rejects(() => apiRequestBlob('/api/private/download/'),'NETWORK_ERROR',0);
  reset([new Response('synthetic\ncsv\n')]);
  assert.equal(await (await apiRequestBlob('/api/private/download/')).text(),'synthetic\ncsv\n');
  reset([csrf(),new Response(null,{status:204})]);
  assert.equal(await apiRequest('/api/test/',{method:'DELETE'}),undefined);
  console.log('PASS: source-task API requests and CSRF; malformed success/CSRF/error JSON; ownership error and request ID; offline requests; authorized blob and 204.');
})().catch(error => {console.error(error.stack);process.exitCode=1;});
