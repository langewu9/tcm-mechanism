// Exercise real page handlers with deferred, synthetic API responses. No live services.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),load=Module.createRequire(path.join(root,'package.json')),ts=load('typescript');
const compile=file=>ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
require.extensions['.ts']=(module,file)=>module._compile(compile(file),file);
const {ApiError}=load('./src/api/client.ts');
// Expand only the hook-free tab stub. Executing arbitrary child components in
// this harness would consume the page's hook slots and corrupt its state.
const jsx=(type,props,key)=>{
  if(type==='SubviewTabs'){
    const active=props.views.some(view=>view.key===props.value)?props.value:props.views[0]?.key;
    return {type,props:{...props,children:props.views.filter(view=>props.keepMounted||view.key===active)
      .map(view=>({type:'div',props:{role:'tabpanel',hidden:view.key!==active,children:view.content}}))}};
  }
  return {type,props,key};
};
const deferred=(name,calls)=>(...args)=>new Promise((resolve,reject)=>calls.push({name,args,resolve,reject}));
function harness(relative,imports,router={Link:'Link',useSearchParams:()=>[new URLSearchParams(),()=>{}]}){
  const hooks=[];let cursor=0,effects=[],dirty=false,value,writes=0;
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:typeof initial==='function'?initial():initial};return [hooks[i].value,next=>{writes++;const current=typeof next==='function'?next(hooks[i].value):next;if(!Object.is(current,hooks[i].value)){hooks[i].value=current;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((item,index)=>!Object.is(item,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
    useMemo(fn){return fn();},useCallback(fn){return fn;},
  };
  const file=path.join(root,relative),subject=new Module(file);
  subject.require=name=>name.endsWith('/SubviewTabs')?{SubviewTabs:'SubviewTabs'}:name.endsWith('/RChartSource')?{RChartSource:'RChartSource',RChartSourceProvider:'RChartSourceProvider'}:name.endsWith('/RChartViewer')?{RChartViewer:'RChartViewer',hasInteractiveRenderer:()=>false}:name==='react'?react:name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name.endsWith('/ArtifactPreview')?{ArtifactPreview:props=>jsx('img',props)}:name==='lucide-react'?new Proxy({},{get:(_,key)=>key}):name==='react-router-dom'?router:name==='../api/client'?{ApiError}:imports[name]??(()=>{throw new Error(name);})();
  subject._compile(compile(file),file);
  return {get value(){return value;},get writes(){return writes;},render(name){this.name=name??this.name;let guard=0;do{assert.ok(guard++<25,'Unbounded render');dirty=false;cursor=0;effects=[];value=subject.exports[this.name](this.props??{});effects.forEach(run=>run());}while(dirty);},cleanup(){hooks.forEach(item=>item?.cleanup?.());}};
}
const nodes=node=>!node||typeof node!=='object'?[]:Array.isArray(node)?node.flatMap(nodes):[node,...nodes(node.props?.children)];
const text=node=>node==null||typeof node==='boolean'?'':typeof node==='string'||typeof node==='number'?String(node):Array.isArray(node)?node.map(text).join(''):text(node.props?.children);
const find=(h,predicate)=>{const node=nodes(h.value).find(predicate);assert.ok(node,'Expected element is missing');return node;};
const flush=async h=>{for(let i=0;i<15;i++)await Promise.resolve();h.render();};
const page=(results,next=null)=>({results,count:results.length,next,previous:null});
const task=(id,status='queued',type='proteomics',parent=null)=>({id,task_type:type,status,parent_task:parent,dataset:10,progress:0,input_parameters:{analysisKind:type==='visualization'?'r_visualization':undefined},result:{},created_at:'2026-10-20T00:00:00Z'});
const dataset=id=>({id,name:'SYNTHETIC '+id,original_filename:'synthetic.csv',columns:['Gene','log2FC','PValue'],archived_at:null});
let timers,id=0;
function clock(){timers=new Map();global.window={setTimeout(fn){timers.set(++id,fn);return id;},clearTimeout(key){timers.delete(key);}};}
function tick(){const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());}
function proteomics(initialSearch=''){
  clock();const calls=[],navigations=[];let params=new URLSearchParams(initialSearch);
  const h=harness('src/pages/ProteomicsPage.tsx',{
    '../api/datasets':Object.fromEntries(['getDatasets','getDataset','getAnalysisTask','getProteomicsRows','runProteomicsAnalysis','exportProteomicsResults'].map(name=>[name,deferred(name,calls)])),
    '../api/task-restoration':{restoreProteomicsTasks:deferred('restore',calls)},
    '../api/network':{createVisualization:deferred('chart',calls)},
    '../components/StringNetworkResult':{StringNetworkResult:'StringNetworkResult'},
    '../components/RAnalysisGallery':{RAnalysisGallery:'RAnalysisGallery'},
    '../components/RDemoGallery':{RDemoGallery:'RDemoGallery'},
  },{Link:'Link',useSearchParams:()=>[params,(next,options)=>{params=typeof next==='function'?next(params):new URLSearchParams(next);navigations.push({search:params.toString(),replace:options?.replace});}]});
  h.render('ProteomicsPage');
  const called=name=>calls.filter(call=>call.name===name);
  const ready=async(saved=null,next=null,figures={})=>{called('getDatasets')[0].resolve(page([dataset(10)],next));called('restore')[0].resolve({task:saved,visualizationTask:null,volcanoVisualizationTask:null,...figures});await flush(h);};
  return {h,calls,called,ready,navigations,navigate(search){params=new URLSearchParams(search);h.render();}};
}
const checks=[];
function check(name,run){checks.push({name,run});}
check('Latest proteomics is found independently of newer tasks; figures are restored across child pages',async()=>{
  const file=path.join(root,'src/api/task-restoration.ts'),subject=new Module(file),calls=[];
  const summary=(id,type,parent,key)=>({id,task_type:type,parent_task:parent,display_parameters:{analysisKind:'r_visualization',parentTaskId:parent,chartKey:key}});
  const protein=summary(1,'proteomics',null),bubble=summary(60,'visualization',1,'proteomics_go_kegg_enrichment'),volcano=summary(2,'visualization',1,'proteomics_volcano');
  subject.require=()=>({getAnalysisTaskSummaries:async(number=1,parent,type)=>{calls.push([number,parent,type]);if(type==='proteomics')return page([protein]);if(parent===1)return number===1?page([bubble],'next'):page([volcano]);return page([summary(99,'network',null)]);},getAnalysisTask:async id=>({...task(id,'succeeded',id===1?'proteomics':'visualization',id===1?null:1)})});
  subject._compile(compile(file),file);
  const restored=await subject.exports.restoreProteomicsTasks();
  assert.equal(restored.task?.id,1);assert.equal(restored.visualizationTask?.id,60);assert.equal(restored.volcanoVisualizationTask?.id,2);
  assert.ok(calls.some(args=>args[1]===1),'Figure reads must be scoped to the saved parent');
});
check('Fixed proteomics restores its own figures across pages without reading the newest parent',async()=>{
  const file=path.join(root,'src/api/task-restoration.ts'),subject=new Module(file),calls=[],details=[];
  const figure=(id,parent,key)=>({id,task_type:'visualization',parent_task:parent,display_parameters:{analysisKind:'r_visualization',parentTaskId:parent,chartKey:key}});
  subject.require=()=>({
    getAnalysisTaskSummaries:async(number,parent,type)=>{calls.push([number,parent,type]);assert.equal(parent,10);return number===1?page([figure(11,10,'proteomics_volcano')],'next'):page([figure(12,10,'proteomics_go_kegg_enrichment')]);},
    getAnalysisTask:async id=>{details.push(id);return task(id,'succeeded',id===10?'proteomics':'visualization',id===10?null:10);},
  });subject._compile(compile(file),file);
  const restored=await subject.exports.restoreProteomicsTasks(10);
  assert.equal(restored.task.id,10);assert.equal(restored.volcanoVisualizationTask.id,11);assert.equal(restored.visualizationTask.id,12);
  assert.deepEqual(details,[10,11,12]);assert.deepEqual(calls,[[1,10,undefined],[2,10,undefined]]);
});
check('Proteomics blocks duplicate submits before a rerender',async()=>{
  const {h,called,ready}=proteomics();try{await ready();const submit=find(h,n=>n.type==='form').props.onSubmit;submit({preventDefault(){}});submit({preventDefault(){}});assert.equal(called('runProteomicsAnalysis').length,1);}finally{h.cleanup();}
});
check('Creating from an older fixed task updates the URL without losing the new saved result',async()=>{
  const {h,called,ready,navigations}=proteomics('proteomicsTask=10&keep=1');
  try{
    await ready(task(10,'succeeded'));
    find(h,node=>node.type==='form').props.onSubmit({preventDefault(){}});
    called('runProteomicsAnalysis')[0].resolve(task(30,'succeeded'));await flush(h);
    assert.equal(find(h,node=>node.type?.name==='ProteomicsResultView').props.task.id,30);
    assert.deepEqual(navigations,[{search:'proteomicsTask=30&keep=1',replace:true}]);
    assert.equal(called('restore').length,1,'Adopting the accepted task must not start a competing read');
    const refreshed=proteomics('proteomicsTask=30');
    try{assert.deepEqual(refreshed.called('restore')[0].args,[30]);}finally{refreshed.h.cleanup();}
  }finally{h.cleanup();}
});
check('Fixed proteomics links keep their task ID on read retries and clear a previous result on access failure',async()=>{
  const {h,called,ready,navigate}=proteomics('proteomicsTask=10');
  try{
    assert.deepEqual(called('restore')[0].args,[10]);await ready(task(10,'succeeded'));
    assert.ok(text(h.value).includes('任务 #10'));
    navigate('proteomicsTask=20');assert.deepEqual(called('restore')[1].args,[20]);
    assert.ok(!text(h.value).includes('任务 #10'),'Changing the fixed ID immediately clears the earlier result');
    called('restore')[1].reject(new ApiError('没有访问权限','FORBIDDEN',null,null,403));await flush(h);
    assert.ok(!nodes(h.value).some(n=>n.type?.name==='ProteomicsResultView'));
    assert.ok(text(h.value).includes('没有访问权限'));
    find(h,n=>n.type==='button'&&text(n)==='重新读取历史任务').props.onClick();h.render();
    assert.deepEqual(called('restore')[2].args,[20],'Retry must preserve the inaccessible fixed ID');
    assert.equal(called('runProteomicsAnalysis').length,0);
  }finally{h.cleanup();}
});
check('Changing a proteomics fixed link suppresses late restoration from the previous URL',async()=>{
  const {h,called,navigate}=proteomics('proteomicsTask=10');
  try{
    called('getDatasets')[0].resolve(page([dataset(10)]));navigate('proteomicsTask=20');
    called('restore')[1].resolve({task:task(20,'succeeded'),visualizationTask:null,volcanoVisualizationTask:null});await flush(h);
    called('restore')[0].resolve({task:task(10,'succeeded'),visualizationTask:null,volcanoVisualizationTask:task(11,'succeeded','visualization',10)});await flush(h);
    assert.equal(find(h,n=>n.type?.name==='ProteomicsResultView').props.task.id,20);
    assert.equal(find(h,n=>n.type?.name==='ProteomicsResultView').props.volcanoVisualizationTask,null);
    assert.deepEqual(called('restore').map(call=>call.args),[[10],[20]]);
  }finally{h.cleanup();}
});
check('Changing a proteomics fixed link suppresses late progress from the previous task',async()=>{
  const {h,called,ready,navigate}=proteomics('proteomicsTask=10');
  try{
    await ready(task(10));tick();assert.equal(called('getAnalysisTask')[0].args[0],10);
    navigate('proteomicsTask=20');called('restore')[1].resolve({task:task(20,'succeeded'),visualizationTask:null,volcanoVisualizationTask:null});await flush(h);
    called('getAnalysisTask')[0].resolve(task(10,'succeeded'));await flush(h);
    assert.equal(find(h,n=>n.type?.name==='ProteomicsResultView').props.task.id,20);
  }finally{h.cleanup();}
});
check('Invalid proteomics URL IDs do not restore any recent task',async()=>{
  for(const value of ['', '0','-1','1.5','abc','9007199254740992']) {
    const {h,called}=proteomics('proteomicsTask='+value);
    try{assert.equal(called('restore').length,0);assert.ok(text(h.value).includes('蛋白组学任务编号无效'));assert.ok(!nodes(h.value).some(n=>n.type?.name==='ProteomicsResultView'));}finally{h.cleanup();}
  }
});
check('Proteomics progress recovers from one transient read failure without creating a job',async()=>{
  const {h,called,ready}=proteomics();try{await ready(task(20));tick();called('getAnalysisTask')[0].reject(new ApiError('暂时断开','NETWORK_ERROR',null,null,0));await flush(h);assert.ok(timers.size,'Read failures must schedule another read');tick();assert.equal(called('getAnalysisTask').length,2);assert.equal(called('runProteomicsAnalysis').length,0);called('getAnalysisTask')[1].resolve(task(20,'succeeded'));await flush(h);assert.ok(text(h.value).includes('任务 #20'));}finally{h.cleanup();}
});
check('Dataset selector can reach page two',async()=>{
  const {h,called,ready}=proteomics();try{await ready(null,'next');find(h,n=>n.type==='button'&&n.props['aria-label']==='下一页数据集').props.onClick();h.render();assert.equal(called('getDatasets').at(-1).args[0],2);called('getDatasets').at(-1).resolve(page([dataset(9)]));await flush(h);assert.ok(text(h.value).includes('SYNTHETIC 9'));}finally{h.cleanup();}
});
check('Saved analysis stays available when the dataset list read fails',async()=>{
  const {h,called}=proteomics();try{called('getDatasets')[0].reject(new ApiError('资料列表暂时不可用','NETWORK_ERROR',null,null,0));called('restore')[0].resolve({task:task(20),visualizationTask:null,volcanoVisualizationTask:null});await flush(h);assert.ok(text(h.value).includes('任务 #20'),'Independent history must not be discarded with a failed dataset list');}finally{h.cleanup();}
});
check('QC pagination clears previous rows while another page is loading',async()=>{
  const {h,called,ready}=proteomics();try{await ready(task(20,'succeeded'));let view=find(h,n=>n.type?.name==='ProteomicsResultView');view.props.onToggleRows();h.render();called('getProteomicsRows')[0].resolve(page([{row_index:0,original_label:'OLD_PRIVATE_ROW'}],'next'));await flush(h);view=find(h,n=>n.type?.name==='ProteomicsResultView');view.props.onRowPageChange(2);h.render();view=find(h,n=>n.type?.name==='ProteomicsResultView');assert.equal(view.props.rowPage,null,'Page two must not display page-one data under its new label');}finally{h.cleanup();}
});
function analysis(){
  const calls=[];const h=harness('src/pages/AnalysisPage.tsx',{'../api/datasets':{getAnalysisTask:deferred('getAnalysisTask',calls)},'../api/analysis':Object.fromEntries(['getTextAnalysisWorkspace','createTextAnalysis','exportTextAnalysis'].map(name=>[name,deferred(name,calls)])),'../components/KnowledgeNetworkGraph':{KnowledgeNetworkGraph:'KnowledgeNetworkGraph'}});
  h.render('AnalysisPage');return {h,called:name=>calls.filter(call=>call.name===name)};
}
check('Text analysis prevents duplicate saved tasks',async()=>{
  const {h,called}=analysis();const Original=global.FormData;global.FormData=class{get(name){return {name:'SYNTHETIC TASK',query:'乏力',caseId:''}[name];}};
  try{called('getTextAnalysisWorkspace')[0].resolve({tasks:[],cases:[]});await flush(h);const submit=find(h,n=>n.type==='form').props.onSubmit;submit({preventDefault(){},currentTarget:{}});submit({preventDefault(){},currentTarget:{}});assert.equal(called('createTextAnalysis').length,1);}finally{global.FormData=Original;h.cleanup();}
});
check('Text history read failure offers a read retry instead of an empty-history claim',async()=>{
  const {h,called}=analysis();try{called('getTextAnalysisWorkspace')[0].reject(new ApiError('暂时断开','NETWORK_ERROR',null,null,0));await flush(h);assert.ok(!text(h.value).includes('暂无保存结果'));find(h,n=>n.type==='button'&&text(n).includes('重新读取')).props.onClick();h.render();assert.equal(called('getTextAnalysisWorkspace').length,2);assert.equal(called('createTextAnalysis').length,0);}finally{h.cleanup();}
});
check('Saved text evidence keeps the original chain order after database JSON key reordering',async()=>{
  const {h,called}=analysis();
  const levels=['syndrome','formula','herbs','compounds','targets','genes','pathways'];
  const saved={...task(71,'succeeded','text_analysis'),input_parameters:{name:'ORDER_FIXTURE'},result:{summary:'SYNTHETIC_ORDER',evidence:Object.fromEntries([...levels].sort().map(level=>[level,level==='syndrome'?'SYNTHETIC':['SYNTHETIC']])),matchStatus:'matched',warnings:[],ruleScores:[],sources:[],evidenceRecords:[],network:{nodes:[],links:[]},limits:{relationsTruncated:false}}};
  try{called('getTextAnalysisWorkspace')[0].resolve({tasks:[saved],cases:[]});await flush(h);find(h,node=>node.type==='button'&&node.props['aria-label']==='查看结果：ORDER_FIXTURE').props.onClick();h.render();assert.deepEqual(nodes(h.value).filter(node=>node.type==='p'&&node.props.className==='text-xs font-bold uppercase text-pine').map(text),levels);}finally{h.cleanup();}
});
check('R gallery retries reads and blocks duplicate chart creation',async()=>{
  clock();const calls=[],called=name=>calls.filter(call=>call.name===name);
  const h=harness('src/components/RAnalysisGallery.tsx',{'../api/datasets':{getAnalysisTask:deferred('detail',calls),getAnalysisTaskSummaries:deferred('summary',calls)},'../api/task-restoration':{restoreGalleryJobs:deferred('restore',calls)},'../api/network':{createVisualization:deferred('create',calls)},'./RDemoGallery':{RDemoGallery:'RDemoGallery'}});
  h.props={taskId:1};h.render('RAnalysisGallery');
  try{called('detail')[0].resolve({...task(1,'succeeded','network'),result:{analysisKind:'catalog_evidence',network:{links:[{}]}}});called('summary')[0].resolve(page([]));await flush(h);called('restore')[0].resolve({});await flush(h);const create=find(h,n=>n.type==='button'&&text(n)==='生成 R 图表').props.onClick;create();create();assert.equal(called('create').length,1);called('create')[0].resolve({...task(2,'queued','visualization',1),input_parameters:{analysisKind:'r_visualization',parentTaskId:1,chartKey:'evidence_network'}});await flush(h);tick();called('detail').at(-1).reject(new ApiError('暂时断开','NETWORK_ERROR',null,null,0));await flush(h);assert.ok(timers.size,'Gallery must retry status reads');}finally{h.cleanup();}
});
check('A new proteomics run cannot inherit a previous volcano figure',async()=>{
  const {h,called,ready}=proteomics();try{await ready(task(20,'succeeded'),null,{volcanoVisualizationTask:task(21,'succeeded','visualization',20)});assert.equal(find(h,n=>n.type?.name==='ProteomicsResultView').props.volcanoVisualizationTask.id,21);find(h,n=>n.type==='form').props.onSubmit({preventDefault(){}});called('runProteomicsAnalysis')[0].resolve(task(30,'succeeded'));await flush(h);assert.equal(find(h,n=>n.type?.name==='ProteomicsResultView').props.volcanoVisualizationTask,null);}finally{h.cleanup();}
});
check('Proteomics rejects a chart response associated with another parent',async()=>{
  const {h,called,ready}=proteomics();try{await ready(task(20,'succeeded'));const create=find(h,n=>n.type?.name==='ProteomicsResultView').props.onCreateVolcanoVisualization;create();create();assert.equal(called('chart').length,1);called('chart')[0].resolve({...task(50,'queued','visualization',999),input_parameters:{analysisKind:'r_visualization',chartKey:'proteomics_volcano'}});await flush(h);assert.equal(find(h,n=>n.type?.name==='ProteomicsResultView').props.volcanoVisualizationTask,null);}finally{h.cleanup();}
});
check('Navigating away suppresses a late private proteomics response',async()=>{
  const {h,called,ready}=proteomics();await ready();find(h,n=>n.type==='form').props.onSubmit({preventDefault(){}});h.cleanup();const writes=h.writes;called('runProteomicsAnalysis')[0].resolve(task(40));await flush(h);assert.equal(h.writes,writes);
});
check('Transient figure restoration failure does not discard the verified analysis',async()=>{
  const file=path.join(root,'src/api/task-restoration.ts'),subject=new Module(file);
  subject.require=()=>({getAnalysisTaskSummaries:async(number,parent,type)=>{if(parent)throw new Error('PRIVATE_DATABASE_DETAIL');return page([{id:1,task_type:'proteomics',parent_task:null}]);},getAnalysisTask:async()=>task(1,'succeeded')});subject._compile(compile(file),file);
  const restored=await subject.exports.restoreProteomicsTasks();assert.equal(restored.task.id,1);assert.equal(restored.visualizationTask,null);assert.ok(restored.figureError);assert.ok(!restored.figureError.includes('PRIVATE_DATABASE_DETAIL'));
});
check('A saved text result survives a failed history refresh; retry only reads',async()=>{
  const {h,called}=analysis(),Original=global.FormData;global.FormData=class{get(name){return {name:'SYNTHETIC TASK',query:'乏力',caseId:''}[name];}};
  const saved={...task(70,'succeeded','text_analysis'),result:{summary:'SAVED_SYNTHETIC_RESULT',evidence:{},matchStatus:'no_rule_match',warnings:[],ruleScores:[],sources:[],evidenceRecords:[],network:{nodes:[],links:[]},limits:{relationsTruncated:false}}};
  try{called('getTextAnalysisWorkspace')[0].resolve({tasks:[],cases:[]});await flush(h);find(h,n=>n.type==='form').props.onSubmit({preventDefault(){},currentTarget:{}});called('createTextAnalysis')[0].resolve(saved);await flush(h);called('getTextAnalysisWorkspace')[1].reject(new ApiError('暂时断开','NETWORK_ERROR',null,null,0));await flush(h);assert.ok(text(h.value).includes('SAVED_SYNTHETIC_RESULT'));find(h,n=>n.type==='button'&&text(n).includes('重新读取')).props.onClick();h.render();assert.equal(called('createTextAnalysis').length,1);assert.equal(called('getTextAnalysisWorkspace').length,3);}finally{global.FormData=Original;h.cleanup();}
});
check('R chart history failure preserves its parent and offers a read-only retry',async()=>{
  clock();const calls=[],called=name=>calls.filter(call=>call.name===name);const h=harness('src/components/RAnalysisGallery.tsx',{'../api/datasets':{getAnalysisTask:deferred('detail',calls),getAnalysisTaskSummaries:deferred('summary',calls)},'../api/task-restoration':{restoreGalleryJobs:deferred('restore',calls)},'../api/network':{createVisualization:deferred('create',calls)},'./RDemoGallery':{RDemoGallery:'RDemoGallery'}});h.props={taskId:1};h.render('RAnalysisGallery');
  try{called('detail')[0].resolve({...task(1,'succeeded','network'),result:{analysisKind:'catalog_evidence',network:{links:[{}]}}});called('summary')[0].reject(new ApiError('暂时断开','NETWORK_ERROR',null,null,0));await flush(h);assert.ok(text(h.value).includes('中药—成分—靶点目录关系图'));find(h,n=>n.type==='button'&&text(n)==='重新读取图表记录').props.onClick();h.render();assert.equal(called('detail').length,2);assert.equal(called('create').length,0);}finally{h.cleanup();}
});

const savedRender=(id,parentId,key,status='succeeded',previousRenderTaskId=null)=>({
  ...task(id,status,'visualization',parentId),
  input_parameters:{analysisKind:'r_visualization',parentTaskId:parentId,chartKey:key,previousRenderTaskId},
  result:status==='succeeded'?{taskId:id,parentTaskId:parentId,chartKey:key,previousRenderTaskId,rendererVersion:'r-viz-0.3.0',
    artifacts:[{id,format:'svg',downloadUrl:`/private/saved-${id}.svg`}]}:{},
});
async function restoredGallery(saved){
  clock();const calls=[],called=name=>calls.filter(call=>call.name===name);
  const h=harness('src/components/RAnalysisGallery.tsx',{
    '../api/datasets':{getAnalysisTask:deferred('detail',calls),getAnalysisTaskSummaries:deferred('summary',calls)},
    '../api/task-restoration':{restoreGalleryJobs:deferred('restore',calls)},
    '../api/network':{createVisualization:deferred('create',calls)},
  });
  h.props={taskId:1};h.render('RAnalysisGallery');
  called('detail')[0].resolve({...task(1,'succeeded','network'),result:{analysisKind:'catalog_evidence',network:{links:[{}]}}});
  called('summary')[0].resolve(page([]));await flush(h);called('restore')[0].resolve({evidence_network:saved});await flush(h);
  return {h,called};
}
check('A saved R 0.3 graph can run again; failed submission preserves the old artifact and retry intent',async()=>{
  const {h,called}=await restoredGallery(savedRender(61,1,'evidence_network'));
  try{
    const run=find(h,n=>n.type==='button'&&text(n)==='重新运行 R 绘图');
    assert.equal(run.props.disabled,false);run.props.onClick();run.props.onClick();
    assert.deepEqual(called('create').map(call=>call.args),[[1,'evidence_network',{regenerate:true}]]);
    assert.ok(nodes(h.value).some(n=>n.type==='a'&&n.props.href==='/tasks/61'));
    called('create')[0].reject(new ApiError('SYNTHETIC_R_SUBMIT_FAILURE'));await flush(h);
    assert.ok(text(h.value).includes('SYNTHETIC_R_SUBMIT_FAILURE'));
    assert.equal(find(h,n=>n.type==='RChartViewer').props.svgUrl,'/private/saved-61.svg?inline=1');
    find(h,n=>n.type==='button'&&text(n)==='重新运行 R 绘图').props.onClick();
    assert.deepEqual(called('create')[1].args,[1,'evidence_network',{regenerate:true}]);
    called('create')[1].resolve(savedRender(62,1,'evidence_network','queued',61));await flush(h);
    assert.ok(nodes(h.value).some(n=>n.type==='a'&&n.props.href==='/tasks/61'&&text(n).includes('上一版')));
    const pending=find(h,n=>n.type==='button'&&text(n).startsWith('后台绘图'));
    assert.equal(pending.props.disabled,true);pending.props.onClick();assert.equal(called('create').length,2);
    assert.ok(!nodes(h.value).some(n=>n.type==='RChartViewer'),'The queued task cannot masquerade as its old artifact or a demo');
  }finally{h.cleanup();}
});
check('Retrying a failed or cancelled redraw preserves regeneration and the previous successful graph link',async()=>{
  for(const status of ['failed','cancelled']){
    const {h,called}=await restoredGallery(savedRender(62,1,'evidence_network',status,61));
    try{
      assert.ok(nodes(h.value).some(n=>n.type==='a'&&n.props.href==='/tasks/61'));
      find(h,n=>n.type==='button'&&text(n)===(status==='failed'?'重试绘图':'生成 R 图表')).props.onClick();
      assert.deepEqual(called('create')[0].args,[1,'evidence_network',{regenerate:true}]);
    }finally{h.cleanup();}
  }
});
check('Proteomics successful volcano and enrichment figures can rerun without losing parent binding or pending protection',async()=>{
  for(const [key,property,callback] of [['proteomics_volcano','volcanoVisualizationTask','onCreateVolcanoVisualization'],['proteomics_go_kegg_enrichment','visualizationTask','onCreateGoKeggVisualization']]){
    const {h,called,ready}=proteomics();
    try{
      await ready(task(20,'succeeded'),null,{[property]:savedRender(21,20,key)});
      const view=()=>find(h,n=>n.type?.name==='ProteomicsResultView');
      view().props[callback]();view().props[callback]();
      assert.deepEqual(called('chart').map(call=>call.args),[[20,key,{regenerate:true}]]);
      called('chart')[0].reject(new ApiError('SYNTHETIC_REDRAW_FAILURE'));await flush(h);
      assert.ok(text(h.value).includes('SYNTHETIC_REDRAW_FAILURE'));assert.equal(view().props[property].id,21);
      view().props[callback]();called('chart')[1].resolve(savedRender(22,20,key,'queued',21));await flush(h);
      assert.equal(view().props[property].input_parameters.previousRenderTaskId,21);
      view().props[callback]();assert.equal(called('chart').length,2);
    }finally{h.cleanup();}
  }
});
check('Failed and cancelled proteomics redraws always request a fresh R run',async()=>{
  for(const status of ['failed','cancelled'])for(const [key,property,callback] of [['proteomics_volcano','volcanoVisualizationTask','onCreateVolcanoVisualization'],['proteomics_go_kegg_enrichment','visualizationTask','onCreateGoKeggVisualization']]){
    const {h,called,ready}=proteomics();
    try{
      await ready(task(20,'succeeded'),null,{[property]:savedRender(22,20,key,status,21)});
      find(h,n=>n.type?.name==='ProteomicsResultView').props[callback]();
      assert.deepEqual(called('chart')[0].args,[20,key,{regenerate:true}]);
    }finally{h.cleanup();}
  }
});
check('A late proteomics redraw cannot replace figures belonging to a newly selected parent',async()=>{
  for(const [key,property,callback] of [['proteomics_volcano','volcanoVisualizationTask','onCreateVolcanoVisualization'],['proteomics_go_kegg_enrichment','visualizationTask','onCreateGoKeggVisualization']]){
    const {h,called,ready,navigate}=proteomics('proteomicsTask=20');
    try{
      await ready(task(20,'succeeded'),null,{[property]:savedRender(21,20,key)});
      find(h,n=>n.type?.name==='ProteomicsResultView').props[callback]();
      navigate('proteomicsTask=30');
      called('restore')[1].resolve({task:task(30,'succeeded'),visualizationTask:null,volcanoVisualizationTask:null,[property]:savedRender(31,30,key)});await flush(h);
      called('chart')[0].resolve(savedRender(22,20,key,'queued',21));await flush(h);
      const view=find(h,n=>n.type?.name==='ProteomicsResultView');
      assert.equal(view.props.task.id,30);assert.equal(view.props[property].id,31);
      view.props[callback]();assert.deepEqual(called('chart')[1].args,[30,key,{regenerate:true}]);
    }finally{h.cleanup();}
  }
});
check('Gallery redraws remount the viewer for a new job and ignore late results after a parent change',async()=>{
  const {h,called}=await restoredGallery(savedRender(61,1,'evidence_network'));
  try{
    assert.equal(find(h,n=>n.type==='RChartViewer').key,61);
    find(h,n=>n.type==='button'&&text(n)==='重新运行 R 绘图').props.onClick();
    const completed=savedRender(62,1,'evidence_network','succeeded',61);completed.result.rendererVersion='r-viz-0.4.2';
    called('create')[0].resolve(completed);await flush(h);
    assert.equal(find(h,n=>n.type==='RChartViewer').key,62);
    assert.equal(find(h,n=>n.type==='RChartViewer').props.svgUrl,'/private/saved-62.svg?inline=1');
    find(h,n=>n.type==='button'&&text(n)==='重新运行 R 绘图').props.onClick();
    h.props={taskId:2};h.render();
    called('detail')[1].resolve({...task(2,'succeeded','network'),result:{analysisKind:'catalog_evidence',network:{links:[{}]}}});
    called('summary')[1].resolve(page([]));await flush(h);called('restore')[1].resolve({evidence_network:savedRender(71,2,'evidence_network')});await flush(h);
    called('create')[1].resolve(savedRender(63,1,'evidence_network','queued',62));await flush(h);
    assert.equal(find(h,n=>n.type==='RChartViewer').key,71);
    assert.equal(find(h,n=>n.type==='RChartViewer').props.svgUrl,'/private/saved-71.svg?inline=1');
    find(h,n=>n.type==='button'&&text(n)==='重新运行 R 绘图').props.onClick();
    assert.deepEqual(called('create')[2].args,[2,'evidence_network',{regenerate:true}]);
  }finally{h.cleanup();}
});

(async()=>{let failures=0;for(const {name,run} of checks){try{await run();console.log('PASS: '+name);}catch(error){failures++;console.error('FAIL: '+name+'\n'+error.stack);}}console.log(`${checks.length-failures}/${checks.length} feature audit regressions passed`);if(failures)process.exitCode=1;})().catch(error=>{console.error(error.stack);process.exitCode=1;});
