// Exercise private pagination through the actual React component callbacks.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),load=Module.createRequire(path.join(root,'package.json')),ts=load('typescript');
const hooks=[],calls=[];let cursor=0,dirty=false,effects=[],tree,taskId=1;
const snapshot={sha256:'snapshot-a',tables:{evidenceRecords:{count:21,sha256:'table-a'},entities:{count:2,sha256:'table-b'}}};
const react={useState(initial){const i=cursor++;hooks[i]??={value:initial};return[hooks[i].value,next=>{const value=typeof next==='function'?next(hooks[i].value):next;if(!Object.is(value,hooks[i].value)){hooks[i].value=value;dirty=true;}}];},useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},useEffect(fn,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=fn();});}}};
const jsx=(type,props)=>({type,props});
const file=path.join(root,'src/components/SnapshotEvidence.tsx'),subject=new Module(file);
subject.require=name=>{
  if(name==='react')return react;
  if(name==='react/jsx-runtime')return{jsx,jsxs:jsx};
  if(name==='../api/complete-evidence')return{
    getSnapshotPage:(...args)=>new Promise((resolve,reject)=>calls.push({args,resolve,reject})),
    snapshotDownloadUrl:(id,table,format)=>`/private/${id}/${table??'all'}/${format??'jsonl'}`,
  };
  throw new Error('Unexpected import '+name);
};
subject._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,file);
function render(){let guard=0;do{assert.ok(guard++<20,'render loop');dirty=false;cursor=0;effects=[];tree=subject.exports.SnapshotEvidence({taskId,snapshot});effects.forEach(fn=>fn());}while(dirty);}
const nodes=value=>!value||typeof value!=='object'?[]:Array.isArray(value)?value.flatMap(nodes):[value,...nodes(value.props?.children)];
const text=value=>typeof value==='string'||typeof value==='number'?String(value):Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';
const button=label=>nodes(tree).find(node=>node.type==='button'&&text(node)===label);
const flush=async()=>{for(let i=0;i<10;i++)await Promise.resolve();render();};
const page=(id=1,table='evidenceRecords',ordinal=1,sha='snapshot-a')=>({taskId:id,table,count:snapshot.tables[table].count,snapshotSha256:sha,tableSha256:snapshot.tables[table].sha256,complete:true,next:'https://untrusted.invalid/never-follow',results:[{ordinal,payload:{label:`PRIVATE_${id}_${table}_${ordinal}`}}]});
(async()=>{
  render();assert.equal(calls.length,0,'Closed details does not prefetch private evidence');
  tree.props.onToggle({currentTarget:{open:true}});render();assert.deepEqual(calls[0].args,[1,'evidenceRecords',1]);
  calls[0].resolve(page());await flush();assert.ok(text(tree).includes('PRIVATE_1_evidenceRecords_1'));
  button('下一页').props.onClick();render();assert.deepEqual(calls[1].args,[1,'evidenceRecords',2]);
  assert.ok(!text(tree).includes('PRIVATE_1_evidenceRecords_1'),'Old page clears while next page loads');
  nodes(tree).find(node=>node.type==='select').props.onChange({target:{value:'entities'}});render();
  assert.deepEqual(calls.at(-1).args,[1,'entities',1]);
  calls[1].resolve(page(1,'evidenceRecords',21));await flush();assert.ok(!text(tree).includes('PRIVATE_1_evidenceRecords_21'),'Late page cannot replace another evidence table');
  calls.at(-1).resolve(page(1,'entities',1,'another-snapshot'));await flush();assert.ok(text(tree).includes('不一致'));assert.ok(!text(tree).includes('PRIVATE_'));
  button('重试读取').props.onClick();render();assert.deepEqual(calls.at(-1).args,[1,'entities',1]);
  const stale=calls.at(-1);taskId=2;render();stale.resolve(page(1,'entities'));await flush();assert.ok(!text(tree).includes('PRIVATE_1_'));
  assert.ok(nodes(tree).filter(node=>node.type==='a').every(node=>node.props.href.startsWith('/private/2/')),'Download follows current private task');
  const latest=calls.at(-1);assert.deepEqual(latest.args,[2,'evidenceRecords',1]);latest.resolve(page(2));await flush();assert.ok(text(tree).includes('PRIVATE_2_'));
  console.log('PASS: lazy private paging, local page numbers, stale page/table/task isolation, snapshot hash check, read-only retry and task-bound downloads.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
