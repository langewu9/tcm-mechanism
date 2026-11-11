// Synthetic restoration tests. No browser, model or external service is used.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),load=Module.createRequire(path.join(root,'package.json'));
const ts=load('typescript');
const filename=path.join(root,'src/api/task-restoration.ts'),subject=new Module(filename);
let rows=[],details=new Map(),requested=[],listRequested=[],listError=null;
subject.require=name=>{
  assert.equal(name,'./datasets');
  return {
    getAnalysisTaskSummaries:async(...args)=>{listRequested.push(args);if(listError)throw listError;return {results:rows};},
    getAnalysisTask:async id=>{requested.push(id);const detail=details.get(id);if(detail instanceof Error)throw detail;return detail;},
  };
};
subject._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {restoreProteomicsTasks,restoreGalleryJobs,restoreLatestAssistantTask}=subject.exports;
const summary=(id,type='visualization',parent=10,key='proteomics_volcano')=>({
  id,task_type:type,parent_task:parent,status:'succeeded',
  display_parameters:{analysisKind:'r_visualization',parentTaskId:String(parent),chartKey:key},
});
function reset(values){rows=values;requested=[];listRequested=[];listError=null;details=new Map(values.map(item=>[item.id,{
  id:item.id,task_type:item.task_type,parent_task:item.parent_task,status:item.status,
  input_parameters:{full:'ORIGINAL_INPUT',...item.display_parameters},result:{artifacts:[{id:item.id,downloadUrl:'/private/'+item.id}]},
}]));}
(async()=>{
  reset([]);assert.equal((await restoreProteomicsTasks()).task,null);assert.deepEqual(requested,[]);
  assert.equal(await restoreLatestAssistantTask(),null);
  reset([summary(50,'research_assistant',null),summary(49,'research_assistant',null)]);
  assert.equal((await restoreLatestAssistantTask()).id,50);assert.deepEqual(requested,[50]);
  requested=[];assert.equal((await restoreLatestAssistantTask(49)).id,49);assert.deepEqual(requested,[49],'A fixed link reads the requested assistant task');
  for(const id of [0,-1,NaN,1.5]) await assert.rejects(()=>restoreLatestAssistantTask(id),/任务编号无效/);
  details.set(49,{id:49,task_type:'network'});await assert.rejects(()=>restoreLatestAssistantTask(49),/任务编号或类型不一致/);
  details.set(49,new Error('没有权限'));await assert.rejects(()=>restoreLatestAssistantTask(49),/没有权限/);
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

  reset([summary(20,'proteomics',null),summary(10,'proteomics',null),summary(14)]);
  const selected=await restoreProteomicsTasks(10);
  assert.equal(selected.task.id,10,'A fixed link restores task 10 even when task 20 is newer');
  assert.deepEqual(requested,[10,14]);
  assert.deepEqual(listRequested,[[1,10]],'Only figures for the requested parent are listed; latest analysis is not read');
  for(const id of [0,-1,NaN,Infinity,1.5,Number.MAX_SAFE_INTEGER+1]) {
    reset([]);await assert.rejects(()=>restoreProteomicsTasks(id),/任务编号无效/);
    assert.deepEqual(requested,[]);assert.deepEqual(listRequested,[],'Invalid IDs do not read or fall back to recent tasks');
  }
  for(const mismatch of [{id:99,task_type:'proteomics'},{id:10,task_type:'network'}]) {
    reset([summary(20,'proteomics',null)]);details.set(10,mismatch);
    await assert.rejects(()=>restoreProteomicsTasks(10),/任务编号或类型不一致/);
    assert.deepEqual(requested,[10]);assert.deepEqual(listRequested,[],'Mismatched fixed tasks never fall back');
  }
  reset([summary(20,'proteomics',null)]);details.set(10,new Error('没有权限'));
  await assert.rejects(()=>restoreProteomicsTasks(10),/没有权限/);
  assert.deepEqual(requested,[10]);assert.deepEqual(listRequested,[],'An inaccessible fixed task cannot display a newer one');

  // Exercise the real gallery effect when parent navigation changes during hydration.
  const hooks=[],calls=[];let cursor=0,effects=[],dirty=false,tree,currentId=10;
  const fakeReact={
    createContext(value){const context={value};context.Provider={context};return context;},
    useContext(context){return context.value;},
    useId(){return 'synthetic-gallery';},
    useState(initial){const i=cursor++;hooks[i]??={value:initial};return [hooks[i].value,value=>{const next=typeof value==='function'?value(hooks[i].value):value;if(!Object.is(next,hooks[i].value)){hooks[i].value=next;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
  };
  const deferred=name=>(...args)=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});calls.push({name,args,resolve});return promise;};
  const jsx=(type,props)=>({type,props}),galleryFile=path.join(root,'src/components/RAnalysisGallery.tsx'),gallery=new Module(galleryFile);
  gallery.require=name=>{
    if(name==='react')return fakeReact;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(name==='../api/datasets')return {getAnalysisTask:deferred('parent'),getAnalysisTaskSummaries:deferred('summaries')};
    if(name==='../api/task-restoration')return {restoreGalleryJobs:deferred('hydrate')};
    if(name==='../api/network')return {createVisualization:deferred('create')};
    if(name==='../api/client')return {ApiError:Error};
    if(name==='./RDemoGallery')return {RDemoGallery:'RDemoGallery'};
    if(name==='./RChartSource'||name==='./SubviewTabs')return loadUi(name);
    if(name==='./RChartViewer')return {RChartViewer:'RChartViewer',hasInteractiveRenderer:()=>true};
    if(name==='./ArtifactPreview')return {ArtifactPreview:props=>jsx('img',props)};
    throw new Error(name);
  };
  const uiModules=new Map();
  function loadUi(name){
    if(uiModules.has(name))return uiModules.get(name);
    const file=path.join(root,'src/components',name.slice(2)+'.tsx'),child=new Module(file);
    child.require=dependency=>{
      if(dependency==='react')return fakeReact;
      if(dependency==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
      if(dependency==='./SubviewTabs')return loadUi(dependency);
      if(dependency==='./RDemoGallery')return {RDemoGallery:'RDemoGallery'};
      if(dependency==='./RPublicGallery')return {RPublicGallery:'RPublicGallery'};
      throw Error('Unexpected UI dependency '+dependency);
    };
    child._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,file);
    uiModules.set(name,child.exports);return child.exports;
  }
  function expand(value){
    if(Array.isArray(value))return value.map(expand);
    if(!value||typeof value!=='object')return value;
    if(value.type?.context){const context=value.type.context,previous=context.value;context.value=value.props.value;const result=expand(value.props.children);context.value=previous;return result;}
    if(typeof value.type==='function')return expand(value.type(value.props));
    return {...value,props:{...value.props,children:expand(value.props?.children)}};
  }
  function nodes(value){if(!value||typeof value!=='object')return [];if(Array.isArray(value))return value.flatMap(nodes);return [value,...nodes(value.props?.children)];}
  gallery._compile(ts.transpileModule(fs.readFileSync(galleryFile,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,galleryFile);
  function render(){let guard=0;do{assert.ok(guard++<15);dirty=false;cursor=0;effects=[];tree=expand(gallery.exports.RAnalysisGallery({taskId:currentId,additionalCharts:[{key:"statistics",label:"已保存统计",content:jsx("SavedEvidenceStats",{taskId:currentId})}]}));effects.forEach(run=>run());}while(dirty);}
  async function flush(){for(let i=0;i<8;i++)await Promise.resolve();render();}
  const parent=id=>({id,task_type:'network',status:'succeeded',result:{analysisKind:'catalog_evidence',network:{links:[{}]}}});
  render();assert.equal(nodes(tree).filter(node=>node.type==='SavedEvidenceStats').length,1,'Additional evidence statistics render exactly once through the actual subview tabs and source provider');calls[0].resolve(parent(10));calls[1].resolve({results:[]});await flush();
  const oldHydration=calls.find(item=>item.name==='hydrate');assert.ok(oldHydration);
  currentId=20;render();oldHydration.resolve({oldPrivateJob:{id:99}});await flush();
  assert.ok(!hooks.some(hook=>hook?.value?.id===10),'Hydration from an old parent must not restore its private results');
  assert.ok(!hooks.some(hook=>hook?.value?.oldPrivateJob),'Stale hydration cannot populate private figure jobs');
  const newParents=calls.filter(item=>item.name==='parent');newParents.at(-1).resolve(parent(20));
  calls.filter(item=>item.name==='summaries').at(-1).resolve({results:[]});await flush();
  const newHydration=calls.filter(item=>item.name==='hydrate').at(-1);
  const verifiedParent=hooks.find(hook=>hook?.value?.id===20)?.value;assert.equal(verifiedParent?.id,20,'A verified parent remains readable during optional figure hydration');
  const text=value=>typeof value==='string'?value:Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';
  const chartTab=nodes(tree).find(node=>node.type==='button'&&node.props.role==='tab'&&text(node)==='中药—成分—靶点目录关系图');
  assert.ok(chartTab,'The real chart selector is rendered alongside saved statistics');chartTab.props.onClick();render();
  assert.equal(nodes(tree).filter(node=>node.type==='SavedEvidenceStats').length,0,'Inactive statistics are not duplicated behind the selected chart');
  const taskSource=nodes(tree).find(node=>node.type==='button'&&node.props.role==='tab'&&text(node)==='当前任务图表');
  assert.equal(taskSource?.props['aria-selected'],true,'The actual RChartSource reads its gallery provider and selects current task data');
  const generate=nodes(tree).find(node=>node.type==='button'&&text(node)==='生成 R 图表');
  assert.equal(generate?.props.disabled,true,'An unfinished history read cannot enable a duplicate rendering POST');
  generate.props.onClick();assert.equal(calls.filter(call=>call.name==='create').length,0,'Even a stale callback cannot bypass history readiness');
  hooks.forEach(item=>item?.cleanup?.());
  newHydration.resolve({});await Promise.resolve();await Promise.resolve();
  assert.ok(hooks.some(hook=>hook?.value===verifiedParent),'Unmount suppresses the second asynchronous restoration');
  assert.ok(!hooks.some(hook=>hook?.value?.oldPrivateJob),'Unmounted hydration cannot populate private figure jobs');
  console.log('PASS: summary endpoint, selective latest and fixed proteomics hydration, no fallback on invalid/mismatched/inaccessible IDs, full results retained, gallery navigation/unmount isolation.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
