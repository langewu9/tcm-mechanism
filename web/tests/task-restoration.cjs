// Synthetic restoration tests. No browser, model or external service is used.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),load=Module.createRequire(path.join(root,'package.json'));
const ts=load('typescript');
const filename=path.join(root,'src/api/task-restoration.ts'),subject=new Module(filename);
let rows=[],details=new Map(),requested=[],listError=null;
subject.require=name=>{
  assert.equal(name,'./datasets');
  return {
    getAnalysisTaskSummaries:async()=>{if(listError)throw listError;return {results:rows};},
    getAnalysisTask:async id=>{requested.push(id);const detail=details.get(id);if(detail instanceof Error)throw detail;return detail;},
  };
};
subject._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {restoreProteomicsTasks,restoreGalleryJobs,restoreLatestAssistantTask}=subject.exports;
const summary=(id,type='visualization',parent=10,key='proteomics_volcano')=>({
  id,task_type:type,parent_task:parent,status:'succeeded',
  display_parameters:{analysisKind:'r_visualization',parentTaskId:String(parent),chartKey:key},
});
function reset(values){rows=values;requested=[];listError=null;details=new Map(values.map(item=>[item.id,{
  id:item.id,task_type:item.task_type,parent_task:item.parent_task,status:item.status,
  input_parameters:{full:'ORIGINAL_INPUT',...item.display_parameters},result:{artifacts:[{id:item.id,downloadUrl:'/private/'+item.id}]},
}]));}
(async()=>{
  reset([]);assert.equal((await restoreProteomicsTasks()).task,null);assert.deepEqual(requested,[]);
  assert.equal(await restoreLatestAssistantTask(),null);
  reset([summary(50,'research_assistant',null),summary(49,'research_assistant',null)]);
  assert.equal((await restoreLatestAssistantTask()).id,50);assert.deepEqual(requested,[50]);
  reset([summary(17,'network',null),summary(16,'visualization',10,'unneeded-chart'),summary(15,'visualization',99),
    summary(14,'visualization',10,'proteomics_go_kegg_enrichment'),summary(13),summary(12),summary(10,'proteomics',null),summary(5,'proteomics',null)]);
  const restored=await restoreProteomicsTasks();
  assert.deepEqual(requested,[10,14,13],'Only the selected analysis and its latest two displayed figures need details');
  assert.equal(restored.task,details.get(10));assert.equal(restored.visualizationTask,details.get(14));
  assert.equal(restored.volcanoVisualizationTask,details.get(13));
  assert.ok(restored.task.result.artifacts,'Full saved results remain intact');
  requested=[];
  const jobs=await restoreGalleryJobs(rows,10,new Set(['proteomics_volcano']));
  assert.deepEqual(requested,[13]);assert.deepEqual(Object.keys(jobs),['proteomics_volcano']);
  reset([summary(10,'proteomics',null)]);details.set(10,{...details.get(10),id:999});
  await assert.rejects(restoreProteomicsTasks,/任务详情与列表记录不一致/);
  reset([summary(10,'proteomics',null)]);details.set(10,new Error('没有权限'));
  await assert.rejects(restoreProteomicsTasks,/没有权限/);
  reset([]);listError=new Error('离线');await assert.rejects(restoreProteomicsTasks,/离线/);
  assert.deepEqual(requested,[],'No fallback to downloading a full task list');

  // Exercise the real gallery effect when parent navigation changes during hydration.
  const hooks=[],calls=[];let cursor=0,effects=[],dirty=false,tree,currentId=10;
  const fakeReact={
    useState(initial){const i=cursor++;hooks[i]??={value:initial};return [hooks[i].value,value=>{const next=typeof value==='function'?value(hooks[i].value):value;if(!Object.is(next,hooks[i].value)){hooks[i].value=next;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
  };
  const deferred=name=>(...args)=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});calls.push({name,args,resolve});return promise;};
  const jsx=(type,props)=>({type,props}),galleryFile=path.join(root,'src/components/RAnalysisGallery.tsx'),gallery=new Module(galleryFile);
  gallery.require=name=>{
    if(name==='react')return fakeReact;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx};
    if(name==='../api/datasets')return {getAnalysisTask:deferred('parent'),getAnalysisTaskSummaries:deferred('summaries')};
    if(name==='../api/task-restoration')return {restoreGalleryJobs:deferred('hydrate')};
    if(name==='../api/network')return {};
    if(name==='../api/client')return {ApiError:Error};
    if(name==='./RDemoGallery')return {RDemoGallery:'RDemoGallery'};
    throw new Error(name);
  };
  gallery._compile(ts.transpileModule(fs.readFileSync(galleryFile,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,galleryFile);
  function render(){let guard=0;do{assert.ok(guard++<15);dirty=false;cursor=0;effects=[];tree=gallery.exports.RAnalysisGallery({taskId:currentId});effects.forEach(run=>run());}while(dirty);}
  async function flush(){for(let i=0;i<8;i++)await Promise.resolve();render();}
  const parent=id=>({id,task_type:'network',status:'succeeded',result:{analysisKind:'catalog_evidence',network:{links:[{}]}}});
  render();calls[0].resolve(parent(10));calls[1].resolve({results:[]});await flush();
  const oldHydration=calls.find(item=>item.name==='hydrate');assert.ok(oldHydration);
  currentId=20;render();oldHydration.resolve({oldPrivateJob:{id:99}});await flush();
  assert.equal(hooks[0].value,null,'Hydration from an old parent must not restore its private results');
  const newParents=calls.filter(item=>item.name==='parent');newParents.at(-1).resolve(parent(20));
  calls.filter(item=>item.name==='summaries').at(-1).resolve({results:[]});await flush();
  const newHydration=calls.filter(item=>item.name==='hydrate').at(-1);hooks.forEach(item=>item?.cleanup?.());
  newHydration.resolve({});await Promise.resolve();await Promise.resolve();
  assert.equal(hooks[0].value,null,'Unmount suppresses the second asynchronous restoration');
  console.log('PASS: summary endpoint, selective latest task hydration, full results retained, ownership errors, gallery navigation/unmount isolation.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
