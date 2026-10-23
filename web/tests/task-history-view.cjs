// Execute the actual historical-task page, parser, and figure renderer with
// synthetic deferred reads only. No browser, external service, model, or DB.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),load=Module.createRequire(path.join(root,'package.json')),ts=load('typescript');
const jsx=(type,props)=>({type,props});
function compile(relative,imports){
  const filename=path.join(root,relative),subject=new Module(filename);
  subject.require=name=>name==='react/jsx-runtime'?{jsx,jsxs:jsx,Fragment:'Fragment'}:imports[name]??(()=>{throw Error('Unexpected runtime import '+name);})();
  subject._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,filename);
  return subject.exports;
}
const history=compile('src/api/task-history.ts',{});
const figures=compile('src/components/SavedVisualizationResult.tsx',{'../api/task-history':history,'./ArtifactPreview':{ArtifactPreview:props=>jsx('img',props)}});
const {parseSavedTaskId,verifySavedTask,savedTaskDestination}=history;
const {savedFigure,SavedVisualizationResult}=figures;
class ApiError extends Error {}
const artifact=(id=7,format='svg')=>({id,format,downloadUrl:`/api/v1/research/analysis-artifacts/${id}/download/`});
const task=(id=50,status='succeeded',overrides={})=>({id,task_type:'visualization',status,parent_task:10,dataset:null,medical_case:null,
  progress:status==='succeeded'?100:25,error_summary:'SYNTHETIC_TASK_FAILURE',source_releases:[],
  input_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:10},
  result:status==='succeeded'?{taskId:id,parentTaskId:10,chartKey:'overlap',rendererVersion:'SYNTHETIC_RENDERER',artifacts:[artifact()]}:{},
  created_at:'2026-10-23T00:00:00Z',started_at:null,finished_at:null,...overrides});
const nodes=value=>!value||typeof value!=='object'?[]:Array.isArray(value)?value.flatMap(nodes):[value,...nodes(typeof value.type==='function'?value.type(value.props):value.props?.children)];
const text=value=>value==null||typeof value==='boolean'?'':typeof value==='string'||typeof value==='number'?String(value):Array.isArray(value)?value.map(text).join(''):text(typeof value.type==='function'?value.type(value.props):value.props?.children);

function harness(initialId='50'){
  const hooks=[],reads=[],timers=new Map();let taskId=initialId,cursor=0,effects=[],dirty=false,tree,writes=0,timerId=0;
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:typeof initial==='function'?initial():initial};return [hooks[i].value,next=>{writes++;const value=typeof next==='function'?next(hooks[i].value):next;if(!Object.is(value,hooks[i].value)){hooks[i].value=value;dirty=true;}}];},
    useEffect(fn,deps){const i=cursor++,previous=hooks[i];if(!previous||deps.some((value,index)=>!Object.is(value,previous.deps[index]))){hooks[i]={deps};effects.push(()=>{previous?.cleanup?.();hooks[i].cleanup=fn();});}},
  };
  global.window={setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
  const subject=compile('src/pages/TaskHistoryPage.tsx',{
    react,'react-router-dom':{Link:'Link',Navigate:'Navigate',useParams:()=>({taskId})},'../api/client':{ApiError},
    '../api/datasets':{getAnalysisTask:(...args)=>new Promise((resolve,reject)=>reads.push({args,resolve,reject}))},
    '../api/task-history':history,'../components/SavedVisualizationResult':figures,
    '../components/ReactomeEnrichmentResult':{ReactomeEnrichmentResult:'ReactomeSavedResult'},
    '../components/StringNetworkResult':{StringTaskResult:'StringSavedResult'},
  });
  function render(){let guard=0;do{assert.ok(guard++<25,'Hooks must settle');dirty=false;cursor=0;effects=[];tree=subject.TaskHistoryPage();effects.forEach(run=>run());}while(dirty);}
  async function flush(){for(let round=0;round<3;round++){for(let i=0;i<10;i++)await Promise.resolve();render();}}
  const find=predicate=>{const item=nodes(tree).find(predicate);assert.ok(item,'Expected rendered element');return item;};
  const button=label=>find(node=>node.type==='button'&&text(node)===label);
  const navigate=id=>{taskId=id;render();};
  const tick=()=>{const pending=[...timers.values()];timers.clear();pending.forEach(run=>run());};
  const unmount=()=>hooks.forEach(hook=>hook?.cleanup?.());
  render();
  return {reads,timers,render,flush,find,button,navigate,tick,unmount,writes:()=>writes,nodes:()=>nodes(tree),text:()=>text(tree)};
}
const tests=[];const check=(name,run)=>tests.push({name,run});

check('Task ID parser accepts safe positive decimal IDs and rejects invalid or ambiguous links',()=>{
  assert.equal(parseSavedTaskId('50'),50);assert.equal(parseSavedTaskId('9007199254740991'),Number.MAX_SAFE_INTEGER);
  for(const value of [undefined,'','0','-1','01','1.1','1e3','+1',' 1','1 ','abc','9007199254740992'])assert.throws(()=>parseSavedTaskId(value));
});
check('Saved task validation rejects broken identity, state, source references, and result metadata',()=>{
  assert.doesNotThrow(()=>verifySavedTask(task(),50));
  const changes=[{id:51},{task_type:'unknown'},{status:'complete'},{input_parameters:null},{input_parameters:[]},{result:null},{result:[]},
    {parent_task:50},{parent_task:0},{parent_task:-1},{parent_task:'10'},{dataset:undefined},{dataset:0},{medical_case:1.5},
    {progress:-1},{progress:101},{progress:1.5},{progress:NaN},{progress:'25'}];
  for(const change of changes)assert.throws(()=>verifySavedTask(task(50,'succeeded',change),50),JSON.stringify(change));
});
check('Polling keeps the original kind, chart, durable or legacy parent, input hash, dataset, and case identity',()=>{
  const before=task(50,'running',{input_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:10,inputSha256:'a'.repeat(64)}});
  assert.doesNotThrow(()=>verifySavedTask({...before,status:'succeeded',progress:100},50,before));
  for(const patch of [{task_type:'network'},{parent_task:11},{dataset:12},{medical_case:13},
    ...[{analysisKind:'string_ppi'},{chartKey:'ppi_network'},{parentTaskId:11},{inputSha256:'b'.repeat(64)}].map(value=>({input_parameters:{...before.input_parameters,...value}}))]){
    assert.throws(()=>verifySavedTask({...before,...patch},50,before));
  }
  const legacy={...before,parent_task:null};
  assert.throws(()=>verifySavedTask({...legacy,input_parameters:{...legacy.input_parameters,parentTaskId:11}},50,legacy));
});
check('Every known main task returns to its existing workbench with the exact saved ID',()=>{
  const expected=[['proteomics',undefined,'/proteomics?proteomicsTask=50'],['text_analysis',undefined,'/analysis?textTask=50'],
    ['case_link',undefined,'/cases?caseTask=50'],['research_assistant',undefined,'/assistant?assistantTask=50'],
    ['network','network_pharmacology','/network-pharmacology?networkTask=50'],['network','catalog_evidence','/research?catalogTask=50'],
    ['network','disease_evidence','/research?diseaseTask=50']];
  for(const [type,kind,url] of expected)assert.equal(savedTaskDestination(task(50,'succeeded',{task_type:type,input_parameters:{analysisKind:kind}})),url);
  for(const kind of ['reactome_enrichment','string_ppi',undefined])assert.equal(savedTaskDestination(task(50,'succeeded',{task_type:'network',input_parameters:{analysisKind:kind}})),null);
  assert.equal(savedTaskDestination(task()),null);
});
check('Exact historical figure uses its own saved artifact and only reads the requested ID',async()=>{
  const h=harness();try{assert.deepEqual(h.reads[0].args,[50]);h.reads[0].resolve(task());await h.flush();assert.ok(h.text().includes('历史任务 #50'));assert.equal(h.find(node=>node.type==='img').props.src,'/api/v1/research/analysis-artifacts/7/download/?inline=1');assert.equal(h.reads.length,1);assert.equal(h.timers.size,0);assert.equal(h.find(node=>node.type==='Link'&&node.props.to==='/tasks/10').props.children.join(''),'查看来源任务 #10');}finally{h.unmount();}
});
check('Reactome and STRING children render the correct saved-result component without calling external APIs',async()=>{
  for(const [kind,component] of [['reactome_enrichment','ReactomeSavedResult'],['string_ppi','StringSavedResult']]){
    const h=harness('60');try{const saved=task(60,'succeeded',{task_type:'network',input_parameters:{analysisKind:kind},result:{marker:'SYNTHETIC_SAVED_EXTERNAL_RESULT'}});h.reads[0].resolve(saved);await h.flush();assert.equal(h.find(node=>node.type===component).props.task,saved);assert.equal(h.reads.length,1);assert.equal(h.timers.size,0);assert.ok(!h.nodes().some(node=>node.type==='Navigate'));}finally{h.unmount();}
  }
});
check('Main-task history redirects to the existing exact-ID view without querying other tasks',async()=>{
  for(const [type,kind,to] of [['text_analysis',null,'/analysis?textTask=12'],['case_link',null,'/cases?caseTask=12'],['network','catalog_evidence','/research?catalogTask=12']]){
    const h=harness('12');try{h.reads[0].resolve(task(12,'running',{task_type:type,parent_task:null,input_parameters:{analysisKind:kind}}));await h.flush();assert.equal(h.find(node=>node.type==='Navigate').props.to,to);assert.equal(h.timers.size,0);assert.equal(h.reads.length,1);}finally{h.unmount();}
  }
});
check('Invalid URL IDs are rejected without reading any recent task',async()=>{
  for(const id of [undefined,'','0','-1','01','1.5','abc','9007199254740992']){
    const h=harness(id===undefined?null:id);try{await h.flush();assert.equal(h.reads.length,0);assert.ok(h.text().includes('任务编号无效'));assert.ok(!h.nodes().some(node=>node.type==='img'||node.type==='Navigate'));}finally{h.unmount();}
  }
});
check('Access errors and wrong identities remain on the requested ID and offer a read-only retry',async()=>{
  for(const failure of ['access','missing','identity','type']){
    const h=harness();try{if(failure==='access'||failure==='missing')h.reads[0].reject(new ApiError(failure==='access'?'没有访问权限':'任务不存在'));else h.reads[0].resolve(task(failure==='identity'?51:50,'succeeded',failure==='type'?{task_type:'unknown'}:{}));await h.flush();assert.ok(h.nodes().some(node=>node.props?.role==='alert'));assert.ok(!h.nodes().some(node=>node.type==='img'||node.type==='Navigate'));h.button('重新读取此任务').props.onClick();h.render();assert.deepEqual(h.reads.map(read=>read.args),[[50],[50]]);h.reads[1].resolve(task());await h.flush();assert.equal(h.find(node=>node.type==='img').props.src,'/api/v1/research/analysis-artifacts/7/download/?inline=1');}finally{h.unmount();}
  }
});
check('Pending child jobs poll the exact ID and finish from the saved result without resubmission',async()=>{
  const h=harness();try{h.reads[0].resolve(task(50,'queued'));await h.flush();assert.ok(h.text().includes('不会重新提交分析'));h.tick();assert.deepEqual(h.reads[1].args,[50]);h.reads[1].resolve(task(50,'running'));await h.flush();h.tick();h.reads[2].resolve(task());await h.flush();assert.equal(h.reads.length,3);assert.equal(h.timers.size,0);assert.ok(h.find(node=>node.type==='img'));}finally{h.unmount();}
});
check('A failed progress read preserves the pending task and retries only after a read retry',async()=>{
  const h=harness();try{h.reads[0].resolve(task(50,'running'));await h.flush();h.tick();h.reads[1].reject(new ApiError('进度暂不可用'));await h.flush();assert.ok(h.text().includes('进度暂不可用'));assert.ok(h.text().includes('任务 #50'));assert.equal(h.timers.size,0);h.button('重新读取此任务').props.onClick();h.render();assert.deepEqual(h.reads[2].args,[50]);}finally{h.unmount();}
});
check('Changed provenance during polling is rejected and never displays another saved result',async()=>{
  for(const patch of [{parent_task:11},{input_parameters:{analysisKind:'r_visualization',chartKey:'overlap',parentTaskId:11}}, {input_parameters:{analysisKind:'r_visualization',chartKey:'ppi_network',parentTaskId:10}}]){
    const h=harness();try{h.reads[0].resolve(task(50,'running'));await h.flush();h.tick();h.reads[1].resolve(task(50,'succeeded',patch));await h.flush();assert.ok(h.text().includes('任务来源发生变化'));assert.ok(!h.nodes().some(node=>node.type==='img'));assert.equal(h.timers.size,0);}finally{h.unmount();}
  }
});
check('Changing the route ignores late restoration and progress from the previous ID',async()=>{
  for(const pending of ['restore','progress']){
    const h=harness();try{if(pending==='progress'){h.reads[0].resolve(task(50,'running'));await h.flush();h.tick();}const older=h.reads.at(-1);h.navigate('70');h.reads.at(-1).resolve(task(70,'succeeded',{result:{...task(70).result,artifacts:[artifact(9)]}}));await h.flush();older.resolve(task());await h.flush();assert.ok(h.text().includes('历史任务 #70'));assert.equal(h.find(node=>node.type==='img').props.src,'/api/v1/research/analysis-artifacts/9/download/?inline=1');assert.equal(h.timers.size,0);}finally{h.unmount();}
  }
});
check('Unmount cancels timers and suppresses delayed private result writes',async()=>{
  for(const pending of ['restore','progress','timer']){
    const h=harness();if(pending!=='restore'){h.reads[0].resolve(task(50,'running'));await h.flush();if(pending==='progress')h.tick();}h.unmount();assert.equal(h.timers.size,0);const before=h.writes();if(pending!=='timer')h.reads.at(-1).resolve(task());for(let i=0;i<30;i++)await Promise.resolve();assert.equal(h.writes(),before);
  }
});
check('Failed and cancelled tasks show honest state without rendering results or scheduling new work',async()=>{
  for(const status of ['failed','cancelled']){
    const h=harness();try{h.reads[0].resolve(task(50,status));await h.flush();assert.ok(h.text().includes(status==='failed'?'SYNTHETIC_TASK_FAILURE':'任务已取消'));assert.ok(!h.nodes().some(node=>node.type==='img'));assert.equal(h.timers.size,0);assert.equal(h.reads.length,1);}finally{h.unmount();}
  }
});
check('Saved figure identity requires matching task, chart, input parent, durable parent, and optional input hash',()=>{
  assert.ok(savedFigure(task()));
  const invalid=[value=>({...value,task_type:'network'}),value=>({...value,parent_task:11}),value=>({...value,parent_task:0}),
    value=>({...value,input_parameters:{...value.input_parameters,analysisKind:'string_ppi'}}),
    ...[{taskId:51},{taskId:'50'},{chartKey:'ppi_network'},{parentTaskId:11},{parentTaskId:null},{parentTaskId:0},{parentTaskId:'01'}].map(patch=>value=>({...value,result:{...value.result,...patch}})),
    value=>({...value,input_parameters:{...value.input_parameters,parentTaskId:11}}),value=>({...value,input_parameters:{...value.input_parameters,parentTaskId:undefined}}),
    value=>({...value,result:null}),value=>({...value,result:[]}),value=>({...value,input_parameters:null})];
  for(const invalidate of invalid)assert.equal(savedFigure(invalidate(task())),null);
  const hash='a'.repeat(64),hashed=task(50,'succeeded',{input_parameters:{...task().input_parameters,inputSha256:hash},result:{...task().result,inputSha256:hash}});
  assert.ok(savedFigure(hashed));
  for(const patch of [{inputSha256:'b'.repeat(64)},{inputSha256:hash.toUpperCase()},{inputSha256:null},{inputSha256:undefined}])assert.equal(savedFigure({...hashed,result:{...hashed.result,...patch}}),null);
  assert.equal(savedFigure({...hashed,input_parameters:{...hashed.input_parameters,inputSha256:undefined}}),null);
});
check('Legacy figures without a durable parent do not invent a source-task link',async()=>{
  const legacy=task(50,'succeeded',{parent_task:null,input_parameters:{...task().input_parameters,parentTaskId:'10'}});
  assert.ok(savedFigure(legacy),'Matching positive legacy parent metadata may preserve its saved chart');
  const h=harness();try{h.reads[0].resolve(legacy);await h.flush();assert.ok(h.text().includes('不推断来源任务'));assert.ok(!h.nodes().some(node=>node.type==='Link'&&String(node.props.to).startsWith('/tasks/')));assert.equal(h.reads.length,1);}finally{h.unmount();}
  for(const parent of [undefined,null,0,-1,'01','abc',50]){
    assert.equal(savedFigure({...legacy,input_parameters:{...legacy.input_parameters,parentTaskId:parent},result:{...legacy.result,parentTaskId:parent}}),null);
  }
});
check('Figure artifact previews and downloads must use exact local authenticated artifact paths',()=>{
  for(const url of ['https://example.invalid/chart.svg','//example.invalid/chart.svg','javascript:alert(1)','data:image/svg+xml;base64,AA',
    'http://127.0.0.1:5174/api/v1/research/analysis-artifacts/7/download/','/api/v1/research/analysis-artifacts/8/download/',
    '/api/v1/research/analysis-artifacts/7/download/?token=secret','/api/v1/research/analysis-artifacts/7/download/#x',
    '/api/v1/research/analysis-artifacts/../7/download/','/private/old.svg']){
    const unsafe=task(50,'succeeded',{result:{...task().result,artifacts:[{...artifact(),downloadUrl:url}]}});
    assert.equal(savedFigure(unsafe),null,url);const rendered=SavedVisualizationResult({task:unsafe});assert.ok(!nodes(rendered).some(node=>node.type==='img'||node.type==='a'));assert.ok(text(rendered).includes('暂不能展示或下载'));
  }
  for(const artifacts of [[],[null],[{...artifact(),id:0}],[{...artifact(),format:'exe'}],[artifact(),artifact()],Array.from({length:17},(_,i)=>artifact(i+1))]){
    assert.equal(savedFigure(task(50,'succeeded',{result:{...task().result,artifacts}})),null);
  }
});
check('Image selection prefers SVG, falls back to PNG, and never embeds HTML or PDF as a preview',()=>{
  const render=artifacts=>SavedVisualizationResult({task:task(50,'succeeded',{result:{...task().result,artifacts}})});
  let view=render([artifact(8,'png'),artifact(7,'svg'),artifact(9,'pdf'),artifact(10,'html')]);
  assert.equal(nodes(view).find(node=>node.type==='img').props.src,'/api/v1/research/analysis-artifacts/7/download/?inline=1');
  assert.equal(nodes(view).filter(node=>node.type==='a').length,4);
  view=render([artifact(8,'png')]);assert.equal(nodes(view).find(node=>node.type==='img').props.src,'/api/v1/research/analysis-artifacts/8/download/?inline=1');
  view=render([artifact(9,'pdf'),artifact(10,'html')]);assert.ok(!nodes(view).some(node=>['img','iframe','object','embed'].includes(node.type)));assert.equal(nodes(view).filter(node=>node.type==='a').length,2);
});

(async()=>{let failures=0;for(const {name,run} of tests){try{await run();console.log('PASS: '+name);}catch(error){failures++;console.error('FAIL: '+name+'\n'+error.stack);}}console.log(`${tests.length-failures}/${tests.length} task-history regressions passed`);if(failures)process.exitCode=1;})().catch(error=>{console.error(error.stack);process.exitCode=1;});
