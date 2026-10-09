// Test real source-page polling against deferred replies, without a browser/API.
const fs=require('node:fs'), path=require('node:path'), Module=require('node:module'), assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'), load=Module.createRequire(path.join(root,'package.json')), ts=load('typescript');
const React=load('react'), slots=[]; let cursor=0, tree, effects=[], timer, writes=0;
const hooks={
  useState(initial){const i=cursor++; slots[i] ??= {value:initial}; return [slots[i].value,value=>{slots[i].value=typeof value==='function'?value(slots[i].value):value; writes++;}];},
  useRef(initial){const i=cursor++; slots[i] ??= {value:{current:initial}}; return slots[i].value;},
  useMemo(fn){return fn();},
  useCallback(fn,deps){const i=cursor++, prior=slots[i]; if(!prior || deps.some((value,index)=>!Object.is(value,prior.deps[index])))slots[i]={deps,value:fn}; return slots[i].value;},
  useEffect(callback,deps){const i=cursor++, prior=slots[i]; if(!prior || !deps || deps.some((value,index)=>!Object.is(value,prior.deps[index]))){slots[i]={deps}; effects.push(()=>{prior?.cleanup?.(); slots[i].cleanup=callback();});}},
};
const calls=[];
const deferred=name=>(...args)=>new Promise((resolve,reject)=>calls.push({name,args,resolve,reject}));
const api=Object.fromEntries(['getAdminDataSources','getSyncRuns','previewDataSourceSync','applySyncPreview','createSQLiteDataSource','testSQLiteDataSource','deleteDataSource'].map(name=>[name,deferred(name)]));
const SourceSettingsForm=()=>null;
const filename=path.join(root,'src/pages/SourcesPage.tsx'), module_=new Module(filename);
module_.paths=Module._nodeModulePaths(path.dirname(filename));
module_.require=name=>name==='react'?hooks:name==='react-router-dom'?{Link:'a',Navigate:'navigate',useOutletContext:()=>({isSuperuser:true})}:name==='../api/sources'?api:name==='../api/client'?{ApiError:class ApiError extends Error{}}:name==='../components/SourceSettingsForm'?{SourceSettingsForm}:load(name);
module_._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,filename);
global.window={setInterval(callback){timer=callback; return 1;},clearInterval(){timer=null;}};
function render(){cursor=0; tree=module_.exports.SourcesPage(); const queue=effects; effects=[]; queue.forEach(callback=>callback()); return tree;}
function nodes(node){if(!node || typeof node!=='object')return []; return [node,...React.Children.toArray(node.props?.children).flatMap(nodes)];}
const source={id:42,slug:'reactome',name:'Reactome',description:'',enabled:true,access_mode:'api',last_success_at:null,scheduled_previews_enabled:false};
const run={id:7,source:42,source_name:'Reactome',created_at:null,status:'running',preview_summary:{mode:'preview'},trigger:'scheduled'};
const page=results=>({results,count:results.length,next:null,previous:null});
async function settle(){await Promise.resolve(); await Promise.resolve(); await Promise.resolve();}
(async()=>{
  render(); assert.equal(calls.length,2);
  calls[0].resolve(page([source])); calls[1].resolve(page([run])); await settle(); render();
  assert.equal(typeof timer,'function');
  timer(); assert.equal(calls.length,4);
  const form=nodes(tree).find(node=>node.type===SourceSettingsForm);
  form.props.onSaved({...source,enabled:false,refresh_interval_hours:48}); render();
  calls[2].resolve(page([source])); calls[3].resolve(page([run])); await settle(); render();
  assert.equal(nodes(tree).find(node=>node.type===SourceSettingsForm).props.source.enabled,false,'Old polling response cannot overwrite freshly saved settings');
  timer(); const first= calls.length-2;
  timer(); const second=calls.length-2;
  calls[second].resolve(page([{...source,enabled:false,refresh_interval_hours:72}])); calls[second+1].resolve(page([run])); await settle(); render();
  calls[first].resolve(page([source])); calls[first+1].resolve(page([run])); await settle(); render();
  assert.equal(nodes(tree).find(node=>node.type===SourceSettingsForm).props.source.refresh_interval_hours,72,'Newest read wins despite out-of-order completion');
  timer(); const pending=calls.length-2;
  slots.forEach(slot=>slot?.cleanup?.()); const before=writes;
  calls[pending].resolve(page([source])); calls[pending+1].resolve(page([run])); await settle();
  assert.equal(writes,before,'Unmounted source page cannot accept late reads');
  console.log('PASS: saved settings protected from stale polls; newest read wins; unmount suppresses late responses.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
