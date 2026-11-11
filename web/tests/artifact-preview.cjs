// Execute the real component hooks. No HTTP requests or chart creation.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const assert=require('node:assert/strict'),ts=require('typescript');
const filename=path.resolve(__dirname,'../src/components/ArtifactPreview.tsx');
const hooks=[];let cursor=0,effects=[],tree,writes=0,props={src:'/private/synthetic.svg?inline=1',alt:'合成图'};
const react={
  useState(initial){const i=cursor++;hooks[i]??={value:initial};return[hooks[i].value,next=>{writes++;hooks[i].value=typeof next==='function'?next(hooks[i].value):next;}];},
  useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
  useEffect(fn,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((value,index)=>!Object.is(value,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=fn();});}},
};
const jsx=(type,props)=>({type,props}),subject=new Module(filename);
subject.require=name=>name==='react'?react:name==='react/jsx-runtime'?{jsx,jsxs:jsx}:(()=>{throw Error('Unexpected side effect/import '+name);})();
subject._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
function render(){cursor=0;effects=[];tree=subject.exports.ArtifactPreview(props);effects.forEach(run=>run());return tree;}
const nodes=value=>!value||typeof value!=='object'?[]:Array.isArray(value)?value.flatMap(nodes):[value,...nodes(value.props?.children)];
const text=value=>typeof value==='string'?value:Array.isArray(value)?value.map(text).join(''):value?.props?text(value.props.children):'';
render();assert.equal(tree.type,'img');assert.equal(tree.props.alt,'合成图');
const firstError=tree.props.onError;firstError();render();assert.equal(tree.props.role,'alert');
assert.ok(text(tree).includes('分析记录仍保留'));assert.ok(!nodes(tree).some(n=>n.type==='img'));
nodes(tree).find(n=>n.type==='button').props.onClick();render();
assert.equal(tree.props.src,'/private/synthetic.svg?inline=1&readAttempt=1');
const writesBeforeOldError=writes;firstError();assert.equal(writes,writesBeforeOldError,'An earlier attempt cannot fail the new request');
const staleError=tree.props.onError;props={src:'/private/new.svg',alt:'另一任务图'};render();
staleError();assert.equal(writes,writesBeforeOldError,'Another task cannot inherit an old image failure');
assert.equal(tree.type,'img');assert.equal(tree.props.alt,'另一任务图');
tree.props.onError();render();assert.equal(tree.props.role,'alert');
nodes(tree).find(n=>n.type==='button').props.onClick();render();assert.equal(tree.props.src,'/private/new.svg?readAttempt=1');
const unmountedError=tree.props.onError;hooks.forEach(h=>h?.cleanup?.());const previous=writes;unmountedError();assert.equal(writes,previous);
console.log('PASS: artifact preview keeps healthy layout, explains unreadable files, retries reads only, isolates task/attempt changes and ignores unmounted errors.');
