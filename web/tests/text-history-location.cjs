// Actual AnalysisPage hooks with deferred synthetic reads. No service or database.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), load = Module.createRequire(path.join(root, 'package.json'));
const ts = load('typescript'), filename = path.join(root, 'src/pages/AnalysisPage.tsx');
const source = process.env.TEXT_HISTORY_TEST_SOURCE || filename;
const compiled = ts.transpileModule(fs.readFileSync(source, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
class ApiError extends Error {}
const result = id => ({summary:'SYNTHETIC_RESULT_'+id,evidence:{},matchStatus:'no_rule_match',warnings:[],
  ruleScores:[],sources:[],evidenceRecords:[],network:{nodes:[],links:[]},limits:{relationsTruncated:false}});
const task = (id, status='succeeded', overrides={}) => ({id,task_type:'text_analysis',status,progress:50,
  input_parameters:{name:'SYNTHETIC_TASK_'+id},created_at:'2026-10-23T00:00:00Z',
  error_summary:'SYNTHETIC_FAILURE',result:status==='succeeded'?result(id):{},...overrides});

function harness(search='textTask=10&keep=1') {
  const hooks=[], reads=[], workspaces=[], creates=[], exports=[], navigations=[], timers=new Map();
  let cursor=0,effects=[],dirty=false,tree,writes=0,timerId=0,params=new URLSearchParams(search),frames=[];
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:typeof initial==='function'?initial():initial};return [hooks[i].value,next=>{writes++;const value=typeof next==='function'?next(hooks[i].value):next;if(!Object.is(value,hooks[i].value)){hooks[i].value=value;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(fn,deps){const i=cursor++,previous=hooks[i];if(!previous||deps.some((value,index)=>!Object.is(value,previous.deps[index]))){hooks[i]={deps};effects.push(()=>{previous?.cleanup?.();hooks[i].cleanup=fn();});}},
  };
  const defer = list => (...args) => new Promise((resolve,reject)=>list.push({args,resolve,reject}));
  const jsx=(type,props)=>({type,props}),subject=new Module(filename);
  subject.require=name=>{
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(name==='react-router-dom')return {useSearchParams:()=>[params,(next,options)=>{params=typeof next==='function'?next(params):new URLSearchParams(next);navigations.push({search:params.toString(),replace:options?.replace});}]};
    if(name==='lucide-react')return new Proxy({},{get:(_,key)=>key});
    if(name==='../api/client')return {ApiError};
    if(name==='../api/analysis')return {getTextAnalysisWorkspace:defer(workspaces),createTextAnalysis:defer(creates),exportTextAnalysis:defer(exports)};
    if(name==='../api/datasets')return {getAnalysisTask:defer(reads)};
    if(name==='../components/KnowledgeNetworkGraph')return {KnowledgeNetworkGraph:'Graph'};
    throw Error('Unexpected import '+name);
  };
  global.window={setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);}};
  subject._compile(compiled,filename);
  function render(){let guard=0;do{assert.ok(guard++<30,'Hooks must settle');dirty=false;cursor=0;effects=[];tree=subject.exports.AnalysisPage();frames.push(tree);effects.forEach(run=>run());}while(dirty);}
  function nodes(value){return !value||typeof value!=='object'?[]:Array.isArray(value)?value.flatMap(nodes):[value,...nodes(value.props?.children)];}
  function text(value){return value==null||typeof value==='boolean'?'':typeof value==='string'||typeof value==='number'?String(value):Array.isArray(value)?value.map(text).join(''):text(value.props?.children);}
  function find(predicate){const item=nodes(tree).find(predicate);assert.ok(item,'Expected rendered control');return item;}
  const button=label=>find(node=>node.type==='button'&&text(node)===label);
  const main=()=>find(node=>node.type==='section'&&['分析结果','最新分析结果'].includes(node.props['aria-label']));
  async function flush(){for(let round=0;round<3;round++){for(let i=0;i<10;i++)await Promise.resolve();render();}}
  function submit(){find(node=>node.type==='form').props.onSubmit({preventDefault(){},currentTarget:{}});render();}
  function tick(){const pending=[...timers.values()];timers.clear();pending.forEach(run=>run());}
  function navigate(search){params=new URLSearchParams(search);frames=[];render();return frames[0];}
  function unmount(){hooks.forEach(hook=>hook?.cleanup?.());}
  async function ready(id=10,status='succeeded'){assert.deepEqual(reads[0]?.args,[id],'Fixed textTask must read that exact task');workspaces[0].resolve({tasks:[task(99)],cases:[]});reads[0].resolve(task(id,status));await flush();}
  render();
  return {reads,workspaces,creates,exports,navigations,render,flush,submit,tick,navigate,unmount,button,main,text,nodes,find,ready,writes:()=>writes,timers};
}

const tests=[];const check=(name,run)=>tests.push({name,run});
check('Exact old task is independent of newer workspace results and refresh preserves it',async()=>{
  const h=harness();try{await h.ready();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_10'));assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_99'));assert.equal(h.creates.length,0);const refreshed=harness('textTask=10');try{assert.deepEqual(refreshed.reads[0].args,[10]);}finally{refreshed.unmount();}}finally{h.unmount();}
});
check('Ordinary entry keeps its empty selection rather than silently opening the latest result',async()=>{
  const h=harness('');try{assert.equal(h.reads.length,0);h.workspaces[0].resolve({tasks:[task(99)],cases:[]});await h.flush();assert.ok(h.text(h.main()).includes('等待分析任务'));assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_99'));}finally{h.unmount();}
});
check('Invalid IDs never request a task or fall back to the newest result',async()=>{
  for(const id of ['', '0','-1','1.5','01','abc','9007199254740992']){const h=harness('textTask='+id);try{h.workspaces[0].resolve({tasks:[task(99)],cases:[]});await h.flush();assert.equal(h.reads.length,0);assert.ok(h.text(h.main()).includes('任务编号无效'));assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_99'));assert.equal(h.creates.length,0);}finally{h.unmount();}}
});
check('Inaccessible, mismatched, and wrong-type details clear the earlier result and retry only the specified ID',async()=>{
  for(const failure of ['access','missing','id','type']){const h=harness();try{await h.ready();h.navigate('textTask=20');assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_10'));if(failure==='access'||failure==='missing')h.reads[1].reject(new ApiError(failure==='access'?'没有访问权限':'任务不存在'));else h.reads[1].resolve(task(failure==='id'?999:20,'succeeded',failure==='type'?{task_type:'network'}:{}));await h.flush();assert.ok(h.text(h.main()).includes('读取失败'));assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_99'));h.button('重新读取分析任务').props.onClick();h.render();assert.deepEqual(h.reads[2].args,[20]);assert.equal(h.creates.length,0);}finally{h.unmount();}}
});
check('Workspace read failures do not discard the requested saved result',async()=>{
  const h=harness();try{h.workspaces[0].reject(new ApiError('历史列表暂不可用'));h.reads[0].resolve(task(10));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_10'));h.button('重新读取分析记录').props.onClick();h.render();assert.equal(h.workspaces.length,2);assert.equal(h.reads.length,1);}finally{h.unmount();}
});
check('Saved-list selection synchronizes the URL and cannot inherit an earlier pending restore',async()=>{
  const h=harness();try{h.workspaces[0].resolve({tasks:[task(99)],cases:[]});await h.flush();h.find(node=>node.type==='button'&&node.props['aria-label']==='查看结果：SYNTHETIC_TASK_99').props.onClick();h.render();assert.deepEqual(h.navigations,[{search:'textTask=99&keep=1',replace:true}]);assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_99'));h.reads[0].resolve(task(10));await h.flush();assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_10'));assert.equal(h.reads.length,1);}finally{h.unmount();}
});
check('Late restores and progress reads cannot replace a newly selected URL',async()=>{
  for(const pending of ['restore','poll']){const h=harness();try{if(pending==='poll'){await h.ready(10,'running');h.tick();assert.deepEqual(h.reads[1].args,[10]);}h.navigate('textTask=20');h.reads.at(-1).resolve(task(20));await h.flush();h.reads[pending==='restore'?0:1].resolve(task(10));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_20'));assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_10'));assert.equal(h.creates.length,0);}finally{h.unmount();}}
});
check('The first render of a changed URL hides the earlier result, task identity, and export controls before effects run',async()=>{
  for(const status of ['succeeded','running','failed','cancelled']){
    const h=harness();try{await h.ready(10,status);const first=h.navigate('textTask=20');const main=h.nodes(first).find(node=>node.type==='section'&&node.props['aria-label']==='分析结果');assert.ok(main);assert.ok(!h.text(main).includes('SYNTHETIC_RESULT_10'));assert.ok(!h.text(main).includes('SYNTHETIC_TASK_10'));assert.ok(!h.text(main).includes('任务 #10'));assert.ok(!h.nodes(main).some(node=>node.type==='button'&&['CSV','PDF'].includes(h.text(node))));}finally{h.unmount();}
  }
});
check('Pending tasks retry reads after errors or identity mismatch; no analysis is resubmitted',async()=>{
  const h=harness();try{await h.ready(10,'queued');h.tick();h.reads[1].reject(new ApiError('暂时断开'));await h.flush();assert.ok(h.text(h.main()).includes('不会重新提交'));h.tick();h.reads[2].resolve(task(999));await h.flush();assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_999'));h.tick();h.reads[3].resolve(task(10));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_10'));assert.equal(h.creates.length,0);}finally{h.unmount();}
});
check('Failed and cancelled histories are shown truthfully without exports or automatic retry',async()=>{
  for(const status of ['failed','cancelled']){const h=harness();try{await h.ready(10,status);assert.ok(h.text(h.main()).includes(status==='failed'?'SYNTHETIC_FAILURE':'已取消'));assert.ok(!h.text(h.main()).includes('SYNTHETIC_RESULT_10'));assert.equal(h.timers.size,0);assert.equal(h.creates.length,0);assert.equal(h.exports.length,0);}finally{h.unmount();}}
});
check('A new saved analysis adopts its URL, blocks duplicate submits, and survives history-refresh failure',async()=>{
  const h=harness();try{await h.ready();h.submit();h.submit();assert.equal(h.creates.length,1);h.creates[0].resolve(task(30));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_30'));assert.deepEqual(h.navigations,[{search:'textTask=30&keep=1',replace:true}]);assert.equal(h.reads.length,1);h.workspaces[1].reject(new ApiError('列表暂不可用'));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_30'));const refreshed=harness('textTask=30');try{assert.deepEqual(refreshed.reads[0].args,[30]);}finally{refreshed.unmount();}}finally{h.unmount();}
});
check('A late creation from another URL cannot replace the active result or release another submission',async()=>{
  const h=harness();try{await h.ready();h.submit();h.navigate('textTask=20');h.reads[1].resolve(task(20));await h.flush();h.submit();assert.equal(h.creates.length,2);h.creates[0].resolve(task(30));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_20'));assert.equal(h.navigations.length,0);h.submit();assert.equal(h.creates.length,2);h.creates[1].resolve(task(40));await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_40'));assert.deepEqual(h.navigations,[{search:'textTask=40',replace:true}]);}finally{h.unmount();}
});
check('Invalid creation identities are not adopted or inserted into history',async()=>{
  for(const invalid of [task(0),task(30,'succeeded',{task_type:'network'})]){const h=harness();try{await h.ready();h.submit();h.creates[0].resolve(invalid);await h.flush();assert.ok(h.text(h.main()).includes('SYNTHETIC_RESULT_10'));assert.equal(h.navigations.length,0);assert.equal(h.workspaces.length,1);}finally{h.unmount();}}
});
check('Exports use the selected task and late downloads cannot unlock or overwrite a newer download',async()=>{
  const h=harness();try{await h.ready();const first=h.button('CSV').props.onClick;first();first();assert.deepEqual(h.exports[0].args,[10,'csv']);assert.equal(h.exports.length,1);h.render();h.navigate('textTask=20');h.reads[1].resolve(task(20));await h.flush();const second=h.button('PDF').props.onClick;second();h.render();assert.deepEqual(h.exports[1].args,[20,'pdf']);h.exports[0].reject(new ApiError('OLD_PRIVATE_ERROR'));await h.flush();assert.ok(!h.text(h.main()).includes('OLD_PRIVATE_ERROR'));second();assert.equal(h.exports.length,2,'Older finally cannot release the current export guard');h.exports[1].reject(new ApiError('CURRENT_EXPORT_FAILURE'));await h.flush();assert.ok(h.find(node=>node.props?.role==='alert'&&h.text(node).includes('CURRENT_EXPORT_FAILURE')));}finally{h.unmount();}
});
check('Unmount suppresses delayed restore, progress, and creation writes',async()=>{
  for(const pending of ['restore','poll','create']){const h=harness();if(pending!=='restore')await h.ready(10,pending==='poll'?'running':'succeeded');if(pending==='poll')h.tick();if(pending==='create')h.submit();h.unmount();const before=h.writes();(pending==='create'?h.creates[0]:h.reads.at(-1)).resolve(task(30));for(let i=0;i<30;i++)await Promise.resolve();assert.equal(h.writes(),before);assert.equal(h.navigations.length,0);}
});

(async()=>{
  const original=global.FormData;global.FormData=class{get(name){return {name:'SYNTHETIC_NEW',query:'SYNTHETIC_QUERY',caseId:''}[name];}};
  let failures=0;
  try{for(const {name,run} of tests){try{await run();console.log('PASS: '+name);}catch(error){failures++;console.error('FAIL: '+name+'\n'+error.stack);}}}
  finally{global.FormData=original;}
  console.log(`${tests.length-failures}/${tests.length} text-history location regressions passed`);if(failures)process.exitCode=1;
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
