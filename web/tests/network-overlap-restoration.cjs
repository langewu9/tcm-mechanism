// Execute the actual page effects and callbacks with deferred, synthetic API reads.
// No browser, model, R renderer, external service, or business database is used.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), load = Module.createRequire(path.join(root, 'package.json'));
const ts = load('typescript'), filename = path.join(root, 'src/pages/NetworkPharmacologyPage.tsx');
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX},
}).outputText;
const source = id => ({taskId:id, summary:{herb:'SYNTHETIC_HERB_'+id,disease:'SYNTHETIC_DISEASE_'+id,
  herbTargetCount:2,diseaseTargetCount:2,strictIntersectionCount:1,directAssociationTargetCount:0,
  candidateTargetCount:1,componentCount:1,unmatchedHerbs:[],unmatchedDiseases:[]},
  targets:[], charts:{overlap:[],components:[],pathways:[]}, network:{nodes:[],links:[]},
  limits:{linksTruncated:false,targetsTruncated:false}});
const parent = id => ({id,task_type:'network',status:'succeeded',parent_task:null,
  input_parameters:{analysisKind:'network_pharmacology'},progress:100,result:source(id)});
const summary = (id, parentId=10, overrides={}) => ({id,task_type:'visualization',parent_task:parentId,status:'succeeded',
  display_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:String(parentId)},...overrides});
const figure = (id, parentId=10, status='succeeded') => ({id,task_type:'visualization',parent_task:parentId,status,progress:status==='succeeded'?100:25,
  input_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:parentId},error_summary:'SYNTHETIC_RENDER_FAILED',
  result:status==='succeeded'?{taskId:id,parentTaskId:parentId,chartKey:'overlap',rendererVersion:'synthetic-renderer',
    artifacts:[{id:1,format:'svg',downloadUrl:'/private/synthetic-'+id+'.svg'}, {id:2,format:'pdf',downloadUrl:'/private/synthetic-'+id+'.pdf'}]}:{}});
const page = (results=[], next=null) => ({count:results.length,next,previous:null,results});

function harness(savedId='10') {
  const hooks=[], reads=[], summaries=[], local=[], creates=[], timers=new Map();
  let cursor=0, dirty=false, effects=[], tree, writes=0, timerId=0, params=new URLSearchParams('networkTask='+savedId);
  const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:initial};return [hooks[i].value,value=>{const next=typeof value==='function'?value(hooks[i].value):value;if(!Object.is(next,hooks[i].value)){hooks[i].value=next;dirty=true;writes++;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,previous=hooks[i];if(!previous||!same(previous.deps,deps)){hooks[i]={deps};effects.push(()=>{previous?.cleanup?.();hooks[i].cleanup=callback();});}},
  };
  const enqueue=list=>(...args)=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});list.push({args,resolve,reject});return promise;};
  const jsx=(type,props)=>({type,props}), subject=new Module(filename);
  global.window={setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
  subject.require=name=>{
    if(name==='../components/ArtifactPreview')return {ArtifactPreview:props=>jsx('img',props)};
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(name==='react-router-dom')return {Link:'Link',useLocation:()=>({key:'synthetic',state:null}),useSearchParams:()=>[params,()=>{}]};
    if(name==='lucide-react')return {Activity:'Activity',ArrowLeft:'ArrowLeft',Network:'Network',RefreshCw:'RefreshCw'};
    if(name==='../api/client')return {ApiError:class extends Error {}};
    if(name==='../api/datasets')return {getAnalysisTask:enqueue(reads),getAnalysisTaskSummaries:enqueue(summaries)};
    if(name==='../api/network')return {runNetworkPharmacology:enqueue(local),createVisualization:enqueue(creates),runReactomeEnrichment(){throw Error('External request forbidden');},runStringNetwork(){throw Error('External request forbidden');}};
    if(name==='../api/complete-evidence')return {waitForCompleteTask:async task=>task};
    if(name==='../components/KnowledgeNetworkGraph')return {KnowledgeNetworkGraph:'Graph'};
    if(name==='../components/NetworkPharmacologyCharts')return {NetworkPharmacologyCharts:'Charts'};
    if(name==='../components/NetworkResultDownloads')return {NetworkResultDownloads:'Downloads'};
    if(name==='../components/ReactomeEnrichmentResult')return {ReactomeEnrichmentResult:'Reactome',readReactomeEnrichment:()=>null};
    if(name==='../components/StringNetworkResult')return {StringTaskResult:'StringResult'};
    if(name==='../components/RAnalysisGallery')return {RAnalysisGallery:'RGallery'};
    if(name==='../components/RDemoGallery')return {RDemoGallery:'DemoGallery'};
    throw Error('Unexpected import: '+name);
  };
  subject._compile(code,filename);
  function render(){let guard=0;do{assert.ok(guard++<30,'Hooks settle');dirty=false;cursor=0;effects=[];tree=subject.exports.NetworkPharmacologyPage();effects.forEach(run=>run());}while(dirty);}
  function nodes(value){if(!value||typeof value!=='object')return [];if(Array.isArray(value))return value.flatMap(nodes);return [value,...nodes(typeof value.type==='function'?value.type(value.props):value.props?.children)];}
  function text(value){return typeof value==='string'?value:Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';}
  function find(predicate){const node=nodes(tree).find(predicate);assert.ok(node,'Expected rendered control');return node;}
  function button(label){return find(node=>node.type==='button'&&text(node).includes(label));}
  async function flush(){for(let round=0;round<3;round++){for(let i=0;i<10;i++)await Promise.resolve();render();}}
  function tick(){const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn());}
  function submit(){find(node=>node.type==='form').props.onSubmit({preventDefault(){}});render();}
  function mainId(){return find(node=>node.type==='Charts').props.result.taskId;}
  function historyError(){return nodes(tree).some(node=>node.props?.role==='alert'&&text(node).includes('历史 R 图表读取失败'));}
  function figureUrls(){return nodes(tree).filter(node=>node.type==='img').map(node=>node.props.src);}
  function unmount(){hooks.forEach(hook=>hook?.cleanup?.());}
  function navigate(id){params=new URLSearchParams('networkTask='+id);render();}
  async function restore(){render();assert.deepEqual(reads[0].args,[Number(savedId)]);reads[0].resolve(parent(Number(savedId)));await flush();assert.equal(mainId(),Number(savedId));assert.deepEqual(summaries[0].args,[1,Number(savedId)]);}
  return {reads,summaries,local,creates,render,flush,tick,submit,mainId,historyError,figureUrls,unmount,navigate,restore,button,nodes:()=>nodes(tree),text,writes:()=>writes};
}

(async()=>{
  // Page one may contain newer unrelated charts and legacy rows without a durable FK.
  let h=harness();await h.restore();
  const drawing=h.button('生成 R 图表');assert.equal(drawing.props.disabled,true);drawing.props.onClick();assert.equal(h.creates.length,0,'Reading history cannot submit R work');
  h.summaries[0].resolve(page([summary(100,10,{display_parameters:{analysisKind:'r_visualization',chartKey:'evidence_network',parentTaskId:'10'}}),summary(99,null,{display_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:'10'}})],'https://untrusted.invalid/arbitrary-next'));
  await h.flush();assert.deepEqual(h.summaries[1].args,[2,10],'Pagination constructs the local endpoint and never follows next URL');
  h.summaries[1].resolve(page([summary(98)]));await h.flush();assert.deepEqual(h.reads[1].args,[98],'Only the matching overlap needs a full detail read');
  h.reads[1].resolve(figure(98));await h.flush();assert.equal(h.mainId(),10);
  assert.deepEqual(h.figureUrls(),['/private/synthetic-98.svg?inline=1']);
  assert.ok(h.nodes().some(node=>node.type==='a'&&node.props.href==='/private/synthetic-98.pdf'));
  assert.equal(h.creates.length,0);assert.equal(h.historyError(),false);h.unmount();

  h=harness();await h.restore();h.summaries[0].resolve(page());await h.flush();
  assert.equal(h.historyError(),false,'An empty history is normal');assert.equal(h.mainId(),10);assert.equal(h.reads.length,1);h.unmount();

  h=harness();await h.restore();h.summaries[0].resolve(page([
    summary(50,999),summary(49,10,{task_type:'network'}),summary(48,10,{display_parameters:{analysisKind:'string_ppi',chartKey:'overlap',parentTaskId:'10'}}),
    summary(47,10,{display_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:'999'}}),
  ]));await h.flush();assert.equal(h.reads.length,1,'Unbound, wrong-kind, and other-parent summaries never hydrate');assert.equal(h.historyError(),false);h.unmount();

  const invalidDetails=[
    value=>({...value,id:999}),value=>({...value,task_type:'network'}),value=>({...value,parent_task:999}),value=>({...value,parent_task:null}),
    value=>({...value,input_parameters:{...value.input_parameters,parentTaskId:999}}),value=>({...value,input_parameters:{...value.input_parameters,chartKey:'evidence_network'}}),
    value=>({...value,input_parameters:{...value.input_parameters,analysisKind:'reactome_enrichment'}}),
    value=>({...value,result:{...value.result,taskId:999}}),value=>({...value,result:{...value.result,parentTaskId:999}}),value=>({...value,result:{...value.result,chartKey:'ppi_network'}}),
  ];
  for(const invalidate of invalidDetails){
    h=harness();await h.restore();h.summaries[0].resolve(page([summary(50)]));await h.flush();h.reads[1].resolve(invalidate(figure(50)));await h.flush();
    assert.equal(h.historyError(),true);assert.equal(h.mainId(),10,'A rejected figure never removes the saved analysis');assert.deepEqual(h.figureUrls(),[]);assert.equal(h.creates.length,0);h.unmount();
  }

  // Failed/cancelled historical jobs stay truthful and never trigger an automatic retry.
  for(const status of ['failed','cancelled']){
    h=harness();await h.restore();h.summaries[0].resolve(page([summary(45,10,{status})]));await h.flush();h.reads[1].resolve(figure(45,10,status));await h.flush();
    assert.ok(h.nodes().some(node=>h.text(node).includes(status==='failed'?'SYNTHETIC_RENDER_FAILED':'已取消')));assert.equal(h.historyError(),false);assert.equal(h.creates.length,0);h.unmount();
  }

  for(const failure of ['list','detail']){
    h=harness();await h.restore();
    if(failure==='list')h.summaries[0].reject(Error('SYNTHETIC_LIST_FAILURE'));
    else{h.summaries[0].resolve(page([summary(44)]));await h.flush();h.reads[1].reject(Error('SYNTHETIC_DETAIL_FAILURE'));}
    await h.flush();assert.equal(h.historyError(),true);assert.equal(h.mainId(),10);assert.equal(h.creates.length,0);
    h.button('重新读取历史 R 图表').props.onClick();h.render();assert.deepEqual(h.summaries[1].args,[1,10]);
    h.summaries[1].resolve(page([summary(43)]));await h.flush();h.reads.at(-1).resolve(figure(43));await h.flush();
    assert.equal(h.historyError(),false);assert.deepEqual(h.figureUrls(),['/private/synthetic-43.svg?inline=1']);assert.equal(h.creates.length,0);h.unmount();
  }

  // Poll the restored existing job, retaining it if a detail response changes identity.
  h=harness();await h.restore();h.summaries[0].resolve(page([summary(42,10,{status:'running'})]));await h.flush();h.reads[1].resolve(figure(42,10,'running'));await h.flush();
  h.tick();assert.deepEqual(h.reads[2].args,[42]);h.reads[2].resolve(figure(42,999));await h.flush();assert.deepEqual(h.figureUrls(),[]);
  assert.ok(h.nodes().some(node=>node.props?.role==='status'&&h.text(node).includes('正在重试读取已有任务')));
  h.tick();assert.deepEqual(h.reads[3].args,[42]);h.reads[3].resolve(figure(42));await h.flush();assert.deepEqual(h.figureUrls(),['/private/synthetic-42.svg?inline=1']);assert.equal(h.creates.length,0);h.unmount();

  for(const pending of ['list','detail']){
    h=harness();await h.restore();if(pending==='detail'){h.summaries[0].resolve(page([summary(41)]));await h.flush();}
    h.submit();h.local[0].resolve(source(20));await h.flush();assert.equal(h.mainId(),20);
    if(pending==='list')h.summaries[0].resolve(page([summary(41)]));else h.reads[1].resolve(figure(41));
    await h.flush();assert.equal(h.mainId(),20);assert.deepEqual(h.figureUrls(),[]);assert.equal(h.reads.length,pending==='list'?1:2);h.unmount();
  }

  h=harness();await h.restore();h.summaries[0].resolve(page([summary(40)]));await h.flush();
  h.navigate(20);h.reads[2].resolve(parent(20));await h.flush();h.summaries[1].resolve(page());h.reads[1].resolve(figure(40));await h.flush();
  assert.equal(h.mainId(),20);assert.deepEqual(h.figureUrls(),[]);h.unmount();

  for(const pending of ['list','detail']){
    h=harness();await h.restore();if(pending==='detail'){h.summaries[0].resolve(page([summary(39)]));await h.flush();}
    h.unmount();const previous=h.writes();if(pending==='list')h.summaries[0].resolve(page([summary(39)]));else h.reads[1].resolve(figure(39));
    for(let i=0;i<20;i++)await Promise.resolve();assert.equal(h.writes(),previous,'Unmount suppresses all delayed figure state writes');
    assert.equal(h.reads.length,pending==='list'?1:2,'Unmounted summary reads cannot start a detail request');
  }

  for(const analysisKind of ['catalog_evidence','disease_evidence','reactome_enrichment','string_ppi',undefined]){
    h=harness();h.render();h.reads[0].resolve({...parent(10),input_parameters:{analysisKind}});await h.flush();
    assert.equal(h.summaries.length,0,'This route only restores local network pharmacology parents');assert.equal(h.creates.length,0);h.unmount();
  }
  console.log('PASS: saved overlap restoration, later-page selection, durable parent/type/input/result identity, empty/failed/cancelled history, read-only retry, resumed polling, new-query/navigation/unmount isolation; no automatic R or external request.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
