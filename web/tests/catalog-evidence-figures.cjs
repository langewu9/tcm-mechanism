// Exercise the real binding component with deferred requests, including refresh
// restoration and responses that arrive after the user replaces a search.
const fs=require('node:fs'), path=require('node:path'), Module=require('node:module');
const assert=require('node:assert/strict');
const webRoot=path.resolve(__dirname,'..'), load=Module.createRequire(path.join(webRoot,'package.json'));
const ts=load('typescript');
const hooks=[], calls=[];
let cursor=0, dirty=false, tree, effects=[], evidence=null, params=new URLSearchParams(), writes=0;
const fakeReact={
  useState(initial){const i=cursor++;hooks[i]??={value:initial};return [hooks[i].value,value=>{const next=typeof value==='function'?value(hooks[i].value):value;if(!Object.is(next,hooks[i].value)){hooks[i].value=next;dirty=true;writes++;}}];},
  useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
  useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
};
const deferred=name=>(...args)=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});calls.push({name,args,resolve,reject});return promise;};
const jsx=(type,props)=>({type,props});
const filename=path.join(webRoot,'src/components/CatalogEvidenceFigures.tsx'),subject=new Module(filename);
subject.require=name=>{
  if(name==='react')return fakeReact;
  if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
  if(name==='react-router-dom')return {Link:'Link',useSearchParams:()=>[params,value=>{params=typeof value==='function'?value(params):value;dirty=true;}]};
  if(name==='../api/catalog')return {saveHerbEvidenceAnalysis:deferred('save')};
  if(name==='../api/datasets')return {getAnalysisTask:deferred('restore')};
  if(name==='./KnowledgeNetworkGraph')return {KnowledgeNetworkGraph:'KnowledgeNetworkGraph'};
  if(name==='./RAnalysisGallery')return {RAnalysisGallery:'RAnalysisGallery'};
  if(name==='./SnapshotEvidence')return {SnapshotEvidence:'SnapshotEvidence'};
  throw new Error('Unexpected import '+name);
};
subject._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,filename);
const Page=subject.exports.CatalogEvidenceFigures;
function render(){let limit=0;do{assert.ok(limit++<20,'Render loop');dirty=false;cursor=0;effects=[];tree=Page({evidence});effects.forEach(callback=>callback());}while(dirty);}
function nodes(value){if(!value||typeof value!=='object')return [];if(Array.isArray(value))return value.flatMap(nodes);return [value,...nodes(value.props?.children)];}
const text=value=>typeof value==='string'||typeof value==='number'?String(value):Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';
const button=()=>nodes(tree).find(node=>node.type==='button');
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();render();};
const query=hash=>({queryType:'herb',resultSha256:hash,results:[{query:'合成测试药',relations:[{id:1}]}]});
const task=(id,hash='a'.repeat(64))=>({id,task_type:'network',status:'succeeded',result:{analysisKind:'catalog_evidence',queries:['合成测试药'],resultSha256:hash,network:{nodes:[],links:[]},counts:{nodes:2,evidenceRecords:1,returnedEvidenceRecords:1,uniqueEdges:1},limits:{queryTruncated:false,graphTruncated:false}}});
(async()=>{
  render();assert.equal(tree,null,'No result means no placeholder chart');
  evidence=query('a'.repeat(64));render();
  const old=button().props.onClick;old();old();render();assert.equal(calls.length,1,'Double click saves only one snapshot');
  evidence=query('b'.repeat(64));render();calls[0].resolve(task(9));await flush();
  assert.ok(!nodes(tree).some(node=>node.type==='RAnalysisGallery'),'Old save cannot attach a figure to a new query');
  old();assert.equal(calls.length,1,'Cached button from a prior search cannot save old data');
  const currentSave=button().props.onClick;currentSave();render();assert.equal(calls[1].args[0].resultSha256,'b'.repeat(64));
  calls[1].resolve(task(10,'b'.repeat(64)));await flush();
  currentSave();assert.equal(calls.length,2,'Cached button cannot duplicate an already saved snapshot');
  assert.ok(nodes(tree).some(node=>node.type==='KnowledgeNetworkGraph'));
  assert.equal(nodes(tree).find(node=>node.type==='RAnalysisGallery').props.taskId,10,'Reuse actual R gallery');
  assert.equal(params.get('catalogTask'),'10','Saved task can be reopened');
  evidence=null;render();assert.equal(calls.at(-1).name,'restore');assert.equal(calls.at(-1).args[0],10);
  calls.at(-1).reject(new Error('没有权限或记录不存在'));await flush();
  assert.ok(nodes(tree).some(node=>node.props?.role==='alert'));
  assert.ok(!nodes(tree).some(node=>node.type==='RAnalysisGallery'),'Failed restoration cannot show prior private images');
  params=new URLSearchParams('catalogTask=11');render();calls.at(-1).resolve({...task(11),task_type:'case_link'});await flush();
  assert.ok(text(tree).includes('不是已保存的目录关系查询'));
  params=new URLSearchParams('catalogTask=invalid');render();const count=calls.length;
  assert.ok(text(tree).includes('编号无效'));assert.equal(calls.length,count);
  params=new URLSearchParams();evidence=query('c'.repeat(64));render();button().props.onClick();render();
  const request=calls.at(-1);hooks.forEach(hook=>hook?.cleanup?.());const previousWrites=writes;
  request.resolve(task(12));for(let i=0;i<10;i++)await Promise.resolve();assert.equal(writes,previousWrites,'Unmounted view does not receive saved results');
  console.log('PASS: existing graph/gallery binding; single snapshot submission; stale search isolation; private task restoration; malformed task rejection; cleanup.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
