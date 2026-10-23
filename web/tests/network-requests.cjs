// Focused deferred-response harness: executes the actual page event callbacks.
// This substitutes hook scheduling and API promises; browser validation is separate.
const fs = require('fs'), path = require('path'), Module = require('module'), assert = require('node:assert/strict');
const webRoot = path.resolve(__dirname, '..');
const load = Module.createRequire(path.join(webRoot, 'package.json'));
const ts = load('typescript');
const hooks = [];
let cursor = 0, dirty = false, writes = 0, tree, effects = [];
const timers = new Map();
let timerId = 0;
global.window = {setTimeout(fn){const id = ++timerId; timers.set(id, fn); return id;}, clearTimeout(id){timers.delete(id);}};
const same = (a,b) => a && b && a.length === b.length && a.every((value,index) => Object.is(value,b[index]));
const fakeReact = {
  useState(initial) {const index = cursor++; if (!hooks[index]) hooks[index] = {value: initial}; return [hooks[index].value, value => {const next = typeof value === 'function' ? value(hooks[index].value) : value; if (!Object.is(next, hooks[index].value)) {hooks[index].value = next; dirty = true; writes++;}}];},
  useRef(initial) {const index = cursor++; if (!hooks[index]) hooks[index] = {value:{current:initial}}; return hooks[index].value;},
  useEffect(callback, deps) {const index = cursor++; const previous = hooks[index]; if (!previous || !same(previous.deps, deps)) {hooks[index] = {deps, cleanup:previous?.cleanup}; effects.push(() => {hooks[index].cleanup?.(); hooks[index].cleanup = callback();});}}
};
const jsx = (type, props, key) => ({type, props, key});
function deferred() {let resolve, reject; const promise = new Promise((yes,no) => {resolve=yes; reject=no;}); return {promise,resolve,reject};}
const localCalls = [], externalCalls = [], pollCalls = [];
const enqueue = list => (...args) => {const value = deferred(); list.push({...value,args}); return value.promise;};
const filename = path.join(webRoot, 'src/pages/NetworkPharmacologyPage.tsx');
const moduleUnderTest = new Module(filename);
moduleUnderTest.require = name => {
  if (name === '../components/ArtifactPreview') return {ArtifactPreview:props=>jsx('img',props)};
  if (name === 'react/jsx-runtime') return {jsx,jsxs:jsx,Fragment:'Fragment'};
  if (name === 'react') return fakeReact;
  if (name === 'react-router-dom') return {Link:'Link', useLocation:()=>({key:'current',state:null}), useSearchParams:()=>[new URLSearchParams(),()=>{}]};
  if (name === '../api/complete-evidence') return {waitForCompleteTask:async task=>task};
  if (name === 'lucide-react') return {Activity:'Activity',ArrowLeft:'ArrowLeft',Network:'Network',RefreshCw:'RefreshCw'};
  if (name === '../api/client') return {ApiError:class extends Error {}};
  if (name === '../api/datasets') return {getAnalysisTask:enqueue(pollCalls)};
  if (name === '../api/network') return {runNetworkPharmacology:enqueue(localCalls), runReactomeEnrichment:enqueue(externalCalls), runStringNetwork:enqueue(externalCalls), createVisualization:enqueue(externalCalls)};
  if (name === '../components/KnowledgeNetworkGraph') return {KnowledgeNetworkGraph:'Graph'};
  if (name === '../components/NetworkPharmacologyCharts') return {NetworkPharmacologyCharts:'Charts'};
  if (name === '../components/NetworkResultDownloads') return {NetworkResultDownloads:'Downloads'};
  if (name === '../components/ReactomeEnrichmentResult') return {ReactomeEnrichmentResult:'ReactomeResult',readReactomeEnrichment:task=>task?.status==='succeeded'?task.result:null};
  if (name === '../components/StringNetworkResult') return {StringTaskResult:'StringResult'};
  if (name === '../components/RAnalysisGallery') return {RAnalysisGallery:'RGallery'};
  if (name === '../components/RDemoGallery') return {RDemoGallery:'DemoGallery'};
  throw new Error('Unexpected import: '+name);
};
moduleUnderTest._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText, filename);
const Page = moduleUnderTest.exports.NetworkPharmacologyPage;
function render() {do {dirty=false; cursor=0; effects=[]; tree=Page(); for (const effect of effects) effect();} while(dirty);}
function nodes(value) {if (!value || typeof value !== 'object') return []; if (Array.isArray(value)) return value.flatMap(nodes); return [value,...nodes(value.props?.children)];}
function find(predicate) {const value=nodes(tree).find(predicate); assert.ok(value,'Expected rendered control'); return value;}
const text = value => typeof value==='string'?value:Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';
const button = label => find(node=>node.type==='button' && text(node).includes(label));
const submit = () => {find(node=>node.type==='form').props.onSubmit({preventDefault(){}}); render();};
const consent = () => {find(node=>node.type==='input' && node.props.type==='checkbox').props.onChange({target:{checked:true}}); render();};
const source = taskId => ({taskId, summary:{herb:'H'+taskId,disease:'D'+taskId,herbTargetCount:2,diseaseTargetCount:2,strictIntersectionCount:2,directAssociationTargetCount:0,candidateTargetCount:2,componentCount:0,unmatchedHerbs:[],unmatchedDiseases:[]}, targets:['AKT1','IL6'].map(target=>({target,normalizedTarget:target,matchType:'交集',components:[],pathways:[],sources:[],herbEvidenceCount:1,diseaseEvidenceCount:1,directEvidenceCount:0})), charts:{overlap:[],components:[],pathways:[]},network:{nodes:[],links:[]},limits:{linksTruncated:false,targetsTruncated:false}});
const task = (id,status='queued',parent_task=2) => ({id,status,parent_task,input_parameters:{analysisKind:'reactome_enrichment'},progress:0,result:{analysisKind:'reactome_enrichment',pathways:[]}});
const flush = async () => {for(let index=0;index<8;index++) await Promise.resolve(); render();};
const tick = () => {const callbacks=[...timers.values()]; timers.clear(); for(const fn of callbacks) fn();};
(async()=> {
  render();
  const firstSubmit = find(node=>node.type==='form').props.onSubmit;
  firstSubmit({preventDefault(){}}); firstSubmit({preventDefault(){}}); render();
  assert.equal(localCalls.length,1,'Synchronous duplicate local task blocked');
  localCalls[0].resolve({...source(1),limits:{...source(1).limits,nodesTruncated:true}}); await flush();
  assert.equal(find(node=>node.type==='Graph').props.knownTruncated,true,'Node-only clipping is disclosed to the existing graph');
  consent(); const firstClick = button('Reactome 通路富集').props.onClick; firstClick(); firstClick(); render();
  assert.equal(externalCalls.length,1,'Synchronous duplicate POST blocked');
  assert.deepEqual(externalCalls[0].args,[1],'External task uses the persisted query ID, not page target labels');
  assert.equal(find(node=>node.type==='input'&&node.props.type==='checkbox').props.checked,false);
  submit(); localCalls[1].resolve(source(2)); await flush();
  firstClick(); assert.equal(externalCalls.length,1,'Stale query handler cannot submit another external task');
  consent(); const secondClick = button('Reactome 通路富集').props.onClick; secondClick(); secondClick(); render();
  assert.equal(externalCalls.length,2);
  externalCalls[0].resolve(task(101,'succeeded',1)); await flush(); secondClick();
  assert.equal(externalCalls.length,2,'Old request completion did not release new query lock');
  assert.equal(find(node=>node.type==='Charts').props.result.taskId,2);
  assert.equal(find(node=>node.type==='Charts').props.reactome,null);
  assert.ok(!nodes(tree).some(node=>node.type==='ReactomeResult'));
  externalCalls[1].resolve(task(102)); await flush(); tick();
  assert.equal(pollCalls[0].args[0],102);
  pollCalls[0].reject(new Error('synthetic transient read failure')); await flush();
  assert.ok(timers.size>0,'Transient failure schedules another read');
  assert.ok(nodes(tree).some(node=>text(node).includes('正在重试读取已有任务')));
  tick(); assert.equal(pollCalls[1].args[0],102); assert.equal(externalCalls.length,2,'Polling retry does not submit another task');
  pollCalls[1].resolve(task(102,'running')); await flush();
  assert.ok(!nodes(tree).some(node=>node.props?.role==='status' && text(node).includes('正在重试读取已有任务')),'Recovered read clears transient error');
  tick(); assert.equal(pollCalls[2].args[0],102);
  submit(); localCalls[2].resolve(source(3)); await flush(); pollCalls[2].resolve(task(102,'succeeded')); await flush();
  assert.equal(find(node=>node.type==='Charts').props.result.taskId,3);
  assert.equal(find(node=>node.type==='Charts').props.reactome,null);
  assert.ok(!nodes(tree).some(node=>node.type==='ReactomeResult'));
  submit(); localCalls[3].reject(new Error('synthetic local query failure')); await flush();
  submit(); assert.equal(localCalls.length,5,'Local query lock released after failure');
  localCalls[4].resolve(source(4)); await flush();
  consent(); button('Reactome 通路富集').props.onClick(); render();
  externalCalls[2].resolve(task(103,'succeeded',999)); await flush();
  assert.ok(!nodes(tree).some(node=>node.type==='ReactomeResult'),'A task bound to another query is not displayed');
  assert.ok(nodes(tree).some(node=>node.props?.role==='alert' && text(node).includes('来源关联不一致')));
  consent(); button('Reactome 通路富集').props.onClick(); render();
  assert.equal(externalCalls.length,4,'A rejected association releases the submit lock');
  for (const hook of hooks) hook?.cleanup?.();
  const previousWrites=writes;
  externalCalls[3].resolve(task(104,'succeeded',4)); for(let index=0;index<8;index++) await Promise.resolve();
  assert.equal(writes,previousWrites);
  console.log('PASS: synchronous duplicate submission; cross-query request lock; old POST and polling suppression; transient read retries without resubmission; recovery clears notice; per-request consent; unmount guard.');
})().catch(error=>{console.error(error.stack); process.exitCode=1;});
