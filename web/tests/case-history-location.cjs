// Exercise the actual case page with synthetic API responses. No model, database,
// private clinical values, browser service, or external endpoint is used.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), load = Module.createRequire(path.join(root, 'package.json'));
const ts = load('typescript'), filename = path.join(root, 'src/pages/CasesPage.tsx');
const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
class ApiError extends Error {}
const sampleCase = (id = 1, archived = false) => ({id, title:'SYNTHETIC_CASE_'+id, owner_id:1, owner_username:'synthetic',
  archived_at:archived?'2026-10-01':null, archived_by:null, deidentified_text:'SYNTHETIC_TEXT_'+id, structured_data:{},
  source_reference:'synthetic fixture', research_notes:'', review_status:'draft', reviewed_at:null,
  reviewed_by_username:null, created_at:'2026-10-01', updated_at:'2026-10-01'});
const task = (id = 10, caseId = 1, status = 'succeeded') => ({id, medical_case:caseId, task_type:'case_link', status,
  dataset:null, parent_task:null, progress:status==='succeeded'?100:25, input_parameters:{analysisKind:'case_analysis'},
  error_summary:'SYNTHETIC_FAILURE', result:{observations:[]}, created_at:'2026-10-01'});
const candidate = (id=100, taskId=10, caseId=1) => ({id, task_id:taskId, medical_case_id:caseId, candidate_type:'syndrome',
  label:'SYNTHETIC_CANDIDATE_'+id, entity_id:1, entity_label:'synthetic entity', match_status:'exact', confidence:'0.5',
  rank:1, evidence:[], knowledge_evidence:[], review_status:'pending'});
const analysis = (saved=task(), candidates=[candidate()]) => ({task:saved, candidates, stale:false,
  modelConfiguration:{configured:true, name:'SYNTHETIC', version:'fixture'}});
const page = (items=[]) => ({count:items.length, results:items, next:null, previous:null});
function harness(search='caseTask=10') {
  const hooks=[], calls=[], timers=new Map(), navigations=[];
  let cursor=0, dirty=false, effects=[], tree, writes=0, timerId=0, params=new URLSearchParams(search);
  const same=(a,b)=>a&&b&&a.length===b.length&&a.every((value,index)=>Object.is(value,b[index]));
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:typeof initial==='function'?initial():initial};return[hooks[i].value,value=>{writes++;const next=typeof value==='function'?value(hooks[i].value):value;if(!Object.is(next,hooks[i].value)){hooks[i].value=next;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||!same(old.deps,deps)){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
    useCallback(callback,deps){const i=cursor++,old=hooks[i];if(!old||!same(old.deps,deps))hooks[i]={deps,value:callback};return hooks[i].value;},
  };
  const enqueue=name=>(...args)=>new Promise((resolve,reject)=>calls.push({name,args,resolve,reject}));
  const jsx=(type,props)=>({type,props}), subject=new Module(filename);
  global.window={setTimeout(callback){const id=++timerId;timers.set(id,callback);return id;},clearTimeout(id){timers.delete(id);}};
  subject.require=name=>{
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(name==='react-router-dom')return {Link:'Link', useOutletContext:()=>({isSuperuser:false}), useSearchParams:()=>[params,(value,options)=>{params=typeof value==='function'?value(params):new URLSearchParams(value);navigations.push({search:params.toString(),replace:options?.replace});}]};
    if(name==='lucide-react')return new Proxy({},{get:(_,key)=>key});
    if(name==='../api/client')return {ApiError};
    if(name==='../components/ConfirmationDialog')return {useConfirmation:()=>({confirm:async()=>false,confirmation:null})};
    if(name==='../api/datasets')return {getAnalysisTask:enqueue('getAnalysisTask')};
    if(name==='../api/cases')return Object.fromEntries(['approveMedicalCase','createMedicalCase','deleteMedicalCase','getMedicalCase','getMedicalCaseAnalysis','getMedicalCaseAudit','getMedicalCases','restoreMedicalCase','reviewMedicalCaseCandidate','startMedicalCaseAnalysis'].map(method=>[method,enqueue(method)]));
    throw Error('Unexpected import '+name);
  };
  subject._compile(code,filename);
  function render(capture){let guard=0;do{assert.ok(guard++<30,'Hooks must settle');dirty=false;cursor=0;effects=[];tree=subject.exports.CasesPage();if(capture){capture(tree);capture=null;}effects.forEach(run=>run());}while(dirty);}
  function nodes(value){if(!value||typeof value!=='object')return [];if(Array.isArray(value))return value.flatMap(nodes);return[value,...nodes(typeof value.type==='function'?value.type(value.props):value.props?.children)];}
  function text(value){if(typeof value==='string'||typeof value==='number')return String(value);if(Array.isArray(value))return value.map(text).join('');return value?.props?text(typeof value.type==='function'?value.type(value.props):value.props.children):'';}
  function find(predicate){const value=nodes(tree).find(predicate);assert.ok(value,'Expected rendered element');return value;}
  const called=name=>calls.filter(call=>call.name===name);
  const panel=()=>find(node=>node.type?.name==='CaseAnalysisPanel');
  async function flush(){for(let round=0;round<3;round++){for(let i=0;i<12;i++)await Promise.resolve();render();}}
  function navigate(search){params=new URLSearchParams(search);let firstFrame;render(value=>{firstFrame=value;});return{nodes:()=>nodes(firstFrame),text:()=>text(firstFrame)};}
  function tick(){const pending=[...timers.values()];timers.clear();pending.forEach(run=>run());}
  function unmount(){hooks.forEach(hook=>hook?.cleanup?.());}
  async function restore(saved=task(), item=sampleCase(), result=analysis(saved)){
    called('getAnalysisTask').at(-1).resolve(saved);await flush();
    called('getMedicalCase').at(-1).resolve(item);called('getMedicalCaseAnalysis').at(-1).resolve(result);await flush();
  }
  render();return{called,calls,panel,nodes:()=>nodes(tree),text:(...args)=>text(args.length?args[0]:tree),find,flush,navigate,tick,unmount,restore,navigations,writes:()=>writes};
}
const checks=[];const check=(name,run)=>checks.push({name,run});
check('Explicit case task restores its own case and candidates even outside the visible list page',async()=>{
  const h=harness();try{
    h.called('getMedicalCases')[0].resolve(page([sampleCase(99)]));await h.restore();
    assert.deepEqual(h.called('getAnalysisTask')[0].args,[10]);
    assert.deepEqual(h.called('getMedicalCase')[0].args,[1]);assert.deepEqual(h.called('getMedicalCaseAnalysis')[0].args,[1,10]);
    assert.equal(h.panel().props.task.id,10);assert.equal(h.panel().props.candidates[0].task_id,10);assert.ok(h.text().includes('任务 #10'));
    assert.ok(h.text().includes('SYNTHETIC_CASE_1'));assert.ok(!h.text().includes('SYNTHETIC_CASE_99'));
    assert.equal(h.find(node=>node.type==='details'&&node.props.className==='case-notes').props.open,true);
    assert.equal(h.called('startMedicalCaseAnalysis').length,0);
  }finally{h.unmount();}
});
check('Archived case detail remains visible for a specific historical task',async()=>{
  const h=harness();try{await h.restore(task(),sampleCase(1,true));assert.equal(h.panel().props.task.id,10);assert.equal(h.find(node=>node.type==='fieldset').props.disabled,true);}finally{h.unmount();}
});
check('Invalid IDs never fetch a recent task or candidates',async()=>{
  for(const id of ['', '0','01','-1','+1','1.5','abc','9007199254740992']){const h=harness('caseTask='+encodeURIComponent(id));try{
    assert.equal(h.called('getAnalysisTask').length,0);assert.equal(h.called('getMedicalCaseAnalysis').length,0);assert.ok(h.text().includes('任务编号无效'));
  }finally{h.unmount();}}
});
check('Wrong task identity, type, or missing case association is rejected before case reads',async()=>{
  for(const invalid of [value=>({...value,id:20}),value=>({...value,task_type:'proteomics'}),value=>({...value,medical_case:null}),value=>({...value,medical_case:0})]){
    const h=harness();try{h.called('getAnalysisTask')[0].resolve(invalid(task()));await h.flush();assert.equal(h.called('getMedicalCase').length,0);assert.equal(h.called('getMedicalCaseAnalysis').length,0);assert.ok(h.text().includes('不一致'));}finally{h.unmount();}
  }
});
check('Mismatched case detail, task response, and candidates fail without falling back to the latest',async()=>{
  const variations=[
    [sampleCase(2),analysis()],
    [sampleCase(),analysis(null,[])],
    [sampleCase(),analysis(task(99),[candidate(100,99)])],
    [sampleCase(),analysis({...task(),task_type:'network'})],
    [sampleCase(),analysis(task(10,2),[candidate(100,10,2)])],
    [sampleCase(),analysis(task(),[candidate(100,99)])],
    [sampleCase(),analysis(task(),[candidate(100,10,2)])],
  ];
  for(const[item,result]of variations){const h=harness();try{await h.restore(task(),item,result);assert.ok(!h.nodes().some(node=>node.type?.name==='CaseAnalysisPanel'));assert.deepEqual(h.called('getMedicalCaseAnalysis').map(call=>call.args),[[1,10]]);assert.ok(h.nodes().some(node=>node.props?.role==='alert'));}finally{h.unmount();}}
});
check('Access failure offers a read-only retry of the same fixed ID',async()=>{
  const h=harness();try{
    h.called('getAnalysisTask')[0].reject(new ApiError('SYNTHETIC_ACCESS_DENIED'));await h.flush();assert.ok(h.text().includes('SYNTHETIC_ACCESS_DENIED'));
    h.find(node=>node.type==='button'&&h.text(node)==='重新读取').props.onClick();await h.flush();
    assert.deepEqual(h.called('getAnalysisTask').map(call=>call.args),[[10],[10]]);assert.equal(h.called('startMedicalCaseAnalysis').length,0);
  }finally{h.unmount();}
});
check('The first render under a changed URL cannot show the previously loaded task or case',async()=>{
  const h=harness();try{
    await h.restore();h.panel().props.onAnalyze();h.called('startMedicalCaseAnalysis')[0].reject(new ApiError('SYNTHETIC_OLD_ACTION_FAILURE'));await h.flush();assert.ok(h.text().includes('SYNTHETIC_OLD_ACTION_FAILURE'));const first=h.navigate('caseTask=20');
    assert.ok(!first.nodes().some(node=>node.type?.name==='CaseAnalysisPanel'));
    assert.ok(!first.text().includes('SYNTHETIC_CASE_1'));assert.ok(!first.text().includes('任务 #10'));assert.ok(!first.text().includes('SYNTHETIC_OLD_ACTION_FAILURE'));
    assert.ok(first.text().includes('正在读取医案'));
    await h.restore(task(20,2),sampleCase(2),analysis(task(20,2),[]));assert.equal(h.panel().props.task.id,20);
  }finally{h.unmount();}
});
check('URL changes ignore late old detail and candidate reads',async()=>{
  const h=harness();try{
    h.called('getAnalysisTask')[0].resolve(task());await h.flush();h.navigate('caseTask=20');
    await h.restore(task(20,2),sampleCase(2),analysis(task(20,2),[candidate(200,20,2)]));
    h.called('getMedicalCase')[0].resolve(sampleCase());h.called('getMedicalCaseAnalysis')[0].resolve(analysis());await h.flush();
    assert.equal(h.panel().props.task.id,20);assert.equal(h.panel().props.caseId,2);assert.equal(h.panel().props.candidates[0].id,200);
  }finally{h.unmount();}
});
check('URL changes ignore late old initial task reads',async()=>{
  const h=harness();try{h.navigate('caseTask=20');await h.restore(task(20,2),sampleCase(2),analysis(task(20,2),[]));h.called('getAnalysisTask')[0].resolve(task());await h.flush();assert.equal(h.panel().props.task.id,20);assert.equal(h.called('getMedicalCase').length,1);}finally{h.unmount();}
});
check('Running historical task polls its exact ID and fetches its own completed candidates',async()=>{
  const h=harness();try{
    await h.restore(task(10,1,'running'),sampleCase(),analysis(task(10,1,'running'),[]));h.tick();assert.deepEqual(h.called('getAnalysisTask')[1].args,[10]);
    h.called('getAnalysisTask')[1].resolve(task());await h.flush();assert.deepEqual(h.called('getMedicalCaseAnalysis')[1].args,[1,10]);
    h.called('getMedicalCaseAnalysis')[1].resolve(analysis());await h.flush();assert.equal(h.panel().props.candidates[0].task_id,10);
  }finally{h.unmount();}
});
check('Late progress cannot replace a newly selected case task',async()=>{
  const h=harness();try{
    await h.restore(task(10,1,'running'),sampleCase(),analysis(task(10,1,'running'),[]));h.tick();h.navigate('caseTask=20');
    await h.restore(task(20,2),sampleCase(2),analysis(task(20,2),[]));h.called('getAnalysisTask')[1].resolve(task());await h.flush();
    assert.equal(h.panel().props.task.id,20);assert.deepEqual(h.called('getMedicalCaseAnalysis').map(call=>call.args),[[1,10],[2,20]]);
  }finally{h.unmount();}
});
check('Failed completed-candidate read keeps a running task recoverable and retries the exact ID',async()=>{
  const h=harness();try{
    await h.restore(task(10,1,'running'),sampleCase(),analysis(task(10,1,'running'),[]));h.tick();
    h.called('getAnalysisTask')[1].resolve(task());await h.flush();h.called('getMedicalCaseAnalysis')[1].reject(new ApiError('SYNTHETIC_READ_FAILURE'));await h.flush();
    assert.equal(h.panel().props.task.status,'running');assert.ok(h.text().includes('SYNTHETIC_READ_FAILURE'));
    h.tick();assert.deepEqual(h.called('getAnalysisTask')[2].args,[10]);h.called('getAnalysisTask')[2].resolve(task());await h.flush();
    assert.deepEqual(h.called('getMedicalCaseAnalysis')[2].args,[1,10]);h.called('getMedicalCaseAnalysis')[2].resolve(analysis());await h.flush();
    assert.equal(h.panel().props.task.status,'succeeded');assert.equal(h.panel().props.candidates[0].task_id,10);assert.ok(!h.text().includes('SYNTHETIC_READ_FAILURE'));
  }finally{h.unmount();}
});
check('Wrong identity from polling is rejected and no latest candidates are read',async()=>{
  const h=harness();try{
    await h.restore(task(10,1,'running'),sampleCase(),analysis(task(10,1,'running'),[]));h.tick();h.called('getAnalysisTask')[1].resolve(task(99));await h.flush();
    assert.equal(h.panel().props.task.id,10);assert.equal(h.called('getMedicalCaseAnalysis').length,1);assert.ok(h.text().includes('不一致'));
  }finally{h.unmount();}
});
check('Candidate review refresh remains scoped to the selected historical task',async()=>{
  const h=harness();try{await h.restore();h.panel().props.onDecision(candidate(),'reject');h.called('reviewMedicalCaseCandidate')[0].resolve(candidate());await h.flush();assert.deepEqual(h.called('getMedicalCaseAnalysis')[1].args,[1,10]);h.called('getMedicalCaseAnalysis')[1].resolve(analysis());await h.flush();assert.equal(h.panel().props.task.id,10);}finally{h.unmount();}
});
check('Starting a new task from history updates its URL and does not re-read old results',async()=>{
  const h=harness('caseTask=10&keep=1');try{
    await h.restore();h.panel().props.onAnalyze();h.panel().props.onAnalyze();assert.equal(h.called('startMedicalCaseAnalysis').length,1);
    h.called('startMedicalCaseAnalysis')[0].resolve(task(30,1,'queued'));await h.flush();
    assert.equal(h.panel().props.task.id,30);assert.deepEqual(h.navigations,[{search:'caseTask=30&keep=1',replace:true}]);assert.equal(h.called('getAnalysisTask').length,1);
    const refreshed=harness('caseTask=30');try{assert.deepEqual(refreshed.called('getAnalysisTask')[0].args,[30]);}finally{refreshed.unmount();}
  }finally{h.unmount();}
});
check('A pending submit keeps its lock across navigation until that exact request ends',async()=>{
  const h=harness();try{
    await h.restore();h.panel().props.onAnalyze();assert.equal(h.called('startMedicalCaseAnalysis').length,1);
    h.navigate('caseTask=20');await h.restore(task(20,2),sampleCase(2),analysis(task(20,2),[]));
    h.panel().props.onAnalyze();assert.equal(h.called('startMedicalCaseAnalysis').length,1,'Navigation must not reset the pending-submit lock');
    h.called('startMedicalCaseAnalysis')[0].resolve(task(30,1,'queued'));await h.flush();
    assert.equal(h.panel().props.task.id,20);assert.equal(h.navigations.length,0,'Late accepted work must not change the new selection');
    h.panel().props.onAnalyze();h.panel().props.onAnalyze();assert.equal(h.called('startMedicalCaseAnalysis').length,2);
    h.called('startMedicalCaseAnalysis')[1].resolve(task(40,2,'queued'));await h.flush();
    assert.equal(h.panel().props.task.id,40);assert.deepEqual(h.navigations,[{search:'caseTask=40',replace:true}]);
  }finally{h.unmount();}
});
check('Ordinary entry still reads latest analysis only after the researcher opens a case',async()=>{
  const h=harness('');try{
    assert.equal(h.called('getAnalysisTask').length,0);assert.equal(h.called('getMedicalCaseAnalysis').length,0);
    h.called('getMedicalCases')[0].resolve(page([sampleCase()]));await h.flush();
    h.find(node=>node.type==='button'&&h.text(node)==='证候与方剂分析').props.onClick();await h.flush();assert.deepEqual(h.called('getMedicalCaseAnalysis')[0].args,[1]);
    h.called('getMedicalCaseAnalysis')[0].resolve(analysis());await h.flush();assert.equal(h.panel().props.task.id,10);
  }finally{h.unmount();}
});
check('An unmounted page ignores late responses and never creates work',async()=>{
  const h=harness();h.unmount();const writes=h.writes();h.called('getAnalysisTask')[0].resolve(task());await Promise.resolve();await Promise.resolve();assert.equal(h.writes(),writes);assert.equal(h.called('getMedicalCase').length,0);assert.equal(h.called('startMedicalCaseAnalysis').length,0);
});
(async()=>{for(const{name,run}of checks){await run();console.log('PASS '+name);}console.log(`${checks.length} case history location checks passed`);})().catch(error=>{console.error(error);process.exitCode=1;});
