// Regression for browser findings: confirmations, safe field errors and task rereads.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),load=Module.createRequire(path.join(root,'package.json')),ts=load('typescript');
const compile=filename=>ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
require.extensions['.ts']=(module,filename)=>module._compile(compile(filename),filename);
const {ApiError}=load('./src/api/client.ts');
const {datasetUploadErrorMessage}=load('./src/utils/validation-errors.ts');
const failure=(details,status=400,code='VALIDATION_ERROR')=>new ApiError('提交的数据无效',code,details,'synthetic-request',status);
assert.equal(datasetUploadErrorMessage(failure({file:['XLSX 文件结构无效或已损坏。']})),'文件：XLSX 文件结构无效或已损坏。');
assert.equal(datasetUploadErrorMessage(failure({traceback:'PRIVATE_TRACE',file:{unexpected:'PRIVATE_FILE'}})),'提交的数据无效');
assert.equal(datasetUploadErrorMessage(failure({file:['PRIVATE_INTERNAL_EXCEPTION']},500,'INTERNAL_ERROR')),'提交的数据无效');
assert.equal(datasetUploadErrorMessage(failure({file:['PRIVATE_AUTH_EXCEPTION']},403,'PERMISSION_DENIED')),'提交的数据无效');
assert.equal(datasetUploadErrorMessage(failure({file:['重复','重复']})),'文件：重复');
assert.ok(datasetUploadErrorMessage(failure({file:Array(20).fill('长'.repeat(2000))})).length<=900);

const jsx=(type,props)=>({type,props});
function harness(relative,imports={}){
  const hooks=[];let cursor=0,effects=[],dirty=false,value,writes=0;
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:typeof initial==='function'?initial():initial};return [hooks[i].value,next=>{writes++;const current=typeof next==='function'?next(hooks[i].value):next;if(!Object.is(current,hooks[i].value)){hooks[i].value=current;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((item,index)=>!Object.is(item,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
    useCallback(fn){return fn;},useId(){return 'test-confirmation';},
  };
  const filename=path.join(root,relative),subject=new Module(filename);
  subject.require=name=>name==='react'?react:name==='react/jsx-runtime'?{jsx,jsxs:jsx}:name in imports?imports[name]:(()=>{throw new Error('Unexpected import '+name);})();
  subject._compile(compile(filename),filename);
  let renderFunction;
  function render(name){if(name)renderFunction=subject.exports[name];let guard=0;do{assert.ok(guard++<20,'render loop');dirty=false;cursor=0;effects=[];value=renderFunction();effects.forEach(run=>run());}while(dirty);return value;}
  return {render,get value(){return value;},get writes(){return writes;},cleanup(){hooks.forEach(hook=>hook?.cleanup?.());}};
}
const nodes=value=>!value||typeof value!=='object'?[]:Array.isArray(value)?value.flatMap(nodes):[value,...nodes(value.props?.children)];
const text=value=>typeof value==='string'||typeof value==='number'?String(value):Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';
const find=(h,predicate)=>{const result=nodes(h.value).find(predicate);assert.ok(result,'Expected rendered control');return result;};
const button=(h,label)=>find(h,node=>node.type==='button'&&text(node)===label);
const deferred=(name,calls)=>(...args)=>new Promise((resolve,reject)=>calls.push({name,args,resolve,reject}));
const flush=async h=>{for(let i=0;i<10;i++)await Promise.resolve();h.render();};

(async()=>{
  const confirm=harness('src/components/ConfirmationDialog.tsx');
  confirm.render('useConfirmation');
  let pending=confirm.value.confirm({title:'归档合成资料',description:'不会删除原件',confirmLabel:'确认归档'});
  confirm.render();
  assert.equal(await confirm.value.confirm({title:'重复请求'}),false,'A second prompt cannot replace pending intent');
  assert.equal(confirm.value.confirmation.props.prompt.title,'归档合成资料');
  confirm.value.confirmation.props.onDecision(false);assert.equal(await pending,false);confirm.render();assert.equal(confirm.value.confirmation,null);
  pending=confirm.value.confirm({title:'恢复',description:'保留所有者',confirmLabel:'确认恢复'});confirm.render();
  confirm.value.confirmation.props.onDecision(true);assert.equal(await pending,true);
  pending=confirm.value.confirm({title:'未提交',description:'取消导航',confirmLabel:'确认'});confirm.cleanup();
  assert.equal(await pending,false,'Navigating away cancels pending confirmation');

  const calls=[],timers=new Map();let timerId=0,locationSearch='';
  global.window={setTimeout(fn){timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);}};
  const assistant=()=>harness('src/pages/ResearchAssistantPage.tsx',{
    'react-router-dom':{Link:'Link',useLocation:()=>({state:null,search:locationSearch})},
    'lucide-react':new Proxy({}, {get:(_,key)=>key}),
    '../api/client':{ApiError},
    '../api/assistant':{createResearchAssistantTask:deferred('create',calls)},
    '../api/datasets':{getAnalysisTask:deferred('poll',calls)},
    '../api/task-restoration':{restoreLatestAssistantTask:deferred('restore',calls)},
    '../api/catalog':{searchCatalogEntities:deferred('search',calls)},
    '../components/ScientistReport':{ScientistReport:'ScientistReport'},
  });
  const task=(id,status='succeeded',answer='保存的回答')=>({id,task_type:'research_assistant',status,input_parameters:{question:'保存的问题',modelConsentRecorded:true},result:{answer,evidence:{entities:[],relations:[]}}});
  const called=name=>calls.filter(call=>call.name===name);
  const runTimer=()=>{const [id,fn]=timers.entries().next().value;timers.delete(id);fn();};
  let h=assistant();h.render('ResearchAssistantPage');called('restore')[0].resolve(task(40));await flush(h);
  assert.ok(text(h.value).includes('保存的回答'));
  assert.equal(find(h,node=>node.type==='input'&&node.props.type==='checkbox').props.checked,false,'Historical consent is never restored');
  assert.equal(called('create').length,0,'Restoring results is read-only');
  find(h,node=>node.type==='input'&&node.props.placeholder?.startsWith('例如：黄芪')).props.onChange({target:{value:'合成证据'}});h.render();
  find(h,node=>node.type==='form'&&nodes(node).some(child=>child.type==='button'&&text(child)==='搜索本地目录')).props.onSubmit({preventDefault(){}});h.render();
  called('search')[0].resolve({results:[{id:1,label:'合成证据',entity_type:'herb',stable_id:'synthetic:1',source_slug:'fixture',source_version:'v1'}]});await flush(h);
  find(h,node=>node.type==='button'&&node.props.className==='knowledge-entity-option').props.onClick();h.render();
  const questionForm=()=>find(h,node=>node.type==='form'&&nodes(node).some(child=>child.props?.id==='assistant-question'));
  const event={preventDefault(){}};
  const submit=questionForm().props.onSubmit;submit(event);submit(event);h.render();
  assert.equal(called('create').length,1,'Duplicate submit cannot create another task');
  assert.equal(called('create')[0].args[0].useModel,false);
  called('create')[0].resolve(task(41,'queued'));await flush(h);runTimer();
  called('poll')[0].reject(new ApiError('连接中断','NETWORK_ERROR',null,null,0));await flush(h);
  assert.ok(text(h.value).includes('任务未重新提交'));
  button(h,'重新读取任务').props.onClick();h.render();runTimer();
  assert.equal(called('create').length,1,'Retry rereads the original task, never resubmits or calls a model');
  called('poll')[1].resolve(task(41,'succeeded','重读后完成'));await flush(h);assert.ok(text(h.value).includes('重读后完成'));

  questionForm().props.onSubmit(event);h.render();called('create')[1].resolve(task(42,'queued'));await flush(h);runTimer();
  questionForm().props.onSubmit(event);h.render();called('create')[2].resolve(task(43));await flush(h);
  called('poll')[2].resolve(task(42,'succeeded','过期任务不能覆盖'));await flush(h);
  assert.ok(!text(h.value).includes('过期任务不能覆盖'),'Late old task response is discarded');h.cleanup();

  h=assistant();h.render('ResearchAssistantPage');const pendingRestore=called('restore').at(-1);h.cleanup();const writes=h.writes;
  pendingRestore.resolve(task(88,'succeeded','PRIVATE_OLD_RESULT'));for(let i=0;i<10;i++)await Promise.resolve();
  assert.equal(h.writes,writes,'Unmounted restoration cannot write private results');
  h=assistant();h.render('ResearchAssistantPage');called('restore').at(-1).reject(new Error('offline'));await flush(h);
  button(h,'重新读取历史任务').props.onClick();h.render();called('restore').at(-1).resolve(task(90));await flush(h);
  assert.ok(text(h.value).includes('保存的回答'));h.cleanup();

  h=assistant();h.render('ResearchAssistantPage');called('restore').at(-1).resolve(null);await flush(h);
  find(h,node=>node.type==='input'&&node.props.type==='checkbox').props.onChange({target:{checked:true}});h.render();
  find(h,node=>node.props?.id==='assistant-mode').props.onChange({target:{value:'scientist_hypothesis'}});h.render();
  assert.equal(nodes(h.value).filter(node=>node.type==='input'&&node.props.type==='checkbox').length,0,'Local report has no model consent control');
  for(const [id,value] of [['scientist-disease','合成疾病'],['scientist-formula','药甲、药乙'],['assistant-question','核对来源'],['scientist-focus','本地核对']]){
    find(h,node=>node.props?.id===id).props.onChange({target:{value}});h.render();
  }
  const beforeReports=called('create').length;
  const reportForm=find(h,node=>node.type==='form'&&nodes(node).some(child=>child.props?.id==='assistant-question'));
  reportForm.props.onSubmit(event);reportForm.props.onSubmit(event);h.render();
  assert.equal(called('create').length,beforeReports+1);
  assert.deepEqual(called('create').at(-1).args[0],{mode:'scientist_hypothesis',question:'核对来源',disease:'合成疾病',formula:'药甲、药乙',focus:'本地核对',useModel:false,confirmModelSharing:false});
  const reportTask={...task(101),input_parameters:{analysisKind:'scientist_hypothesis',question:'核对来源',disease:'合成疾病',formulaHerbs:['药甲','药乙'],focus:'本地核对'},result:{analysisKind:'scientist_hypothesis'}};
  called('create').at(-1).resolve(reportTask);await flush(h);
  assert.equal(find(h,node=>node.type==='ScientistReport').props.taskId,101);h.cleanup();
  h=assistant();h.render('ResearchAssistantPage');const createsBeforeRestore=called('create').length;
  called('restore').at(-1).resolve(reportTask);await flush(h);
  assert.equal(find(h,node=>node.props?.id==='assistant-mode').props.value,'scientist_hypothesis');
  assert.equal(find(h,node=>node.props?.id==='scientist-formula').props.value,'药甲、药乙');
  assert.equal(called('create').length,createsBeforeRestore,'Restoring a report never creates or recomputes a task');
  locationSearch='?assistantTask=40';h.render();
  assert.equal(called('restore').at(-1).args[0],40);
  called('restore').at(-1).resolve(task(40));await flush(h);
  assert.equal(find(h,node=>node.props?.id==='assistant-mode').props.value,'evidence','Fixed task navigation restores its own mode');
  assert.equal(find(h,node=>node.props?.id==='assistant-question').props.value,'保存的问题','Fixed task navigation cannot retain a different task question');
  assert.equal(called('create').length,createsBeforeRestore);h.cleanup();
  console.log('PASS: safe upload errors; confirmation cancel/accept/duplicate/unmount; assistant restoration, no restored model consent, duplicate submit, read-only retry, stale result and unmount isolation.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
