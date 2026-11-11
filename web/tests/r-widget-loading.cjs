const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire,Module}=require('node:module');
const root=path.resolve(__dirname,'..'),load=createRequire(path.join(root,'package.json')),ts=load('typescript');
const compile=file=>ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const helperFile=path.join(root,'src/components/rWidgetDocument.ts'),helper=new Module(helperFile);
helper._compile(compile(helperFile),helperFile);
const html='<html><head><title>fixture</title></head><body><script>fixture()</script></body></html>';
let requests=[];
global.fetch=async(url,options)=>{requests.push({url,options});return new Response(html,{headers:{'Content-Type':'text/html; charset=utf-8'}});};
const hooks=[],effects=[];let cursor=0,dirty=false,tree,props,pending=[],writes=0;
const fakeReact={
 useState(initial){const i=cursor++;hooks[i]??={value:initial};return[hooks[i].value,value=>{hooks[i].value=typeof value==='function'?value(hooks[i].value):value;dirty=true;writes++;}];},
 useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
 useEffect(callback,deps){const i=cursor++;const old=hooks[i];if(!old||deps.some((d,j)=>!Object.is(d,old.deps[j]))){hooks[i]={deps,callback};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}}
};
const jsx=(type,props)=>({type,props});
const viewerFile=path.join(root,'src/components/RChartViewer.tsx'),viewer=new Module(viewerFile);
const previewFile=path.join(root,'src/components/ArtifactPreview.tsx'),preview=new Module(previewFile);
preview.require=name=>name==='react'?fakeReact:name==='react/jsx-runtime'?{jsx,jsxs:jsx,Fragment:'Fragment'}:load(name);
preview._compile(compile(previewFile),previewFile);
viewer.require=name=>name==='react'?fakeReact:name==='react/jsx-runtime'?{jsx,jsxs:jsx,Fragment:'Fragment'}:
 name==='./SubviewTabs'?{useSubviewVisible:()=>true,SubviewTabs:({views,value,onChange})=>jsx('tabs',{onChange,children:views.find(v=>v.key===value)?.content})}:
 name==='./ArtifactPreview'?preview.exports:
 name==='./rWidgetDocument'?{loadRWidgetDocument:(url,signal)=>new Promise((resolve,reject)=>pending.push({url,signal,resolve,reject}))}:load(name);
viewer._compile(compile(viewerFile),viewerFile);
const expand=v=>Array.isArray(v)?v.map(expand):v&&typeof v==='object'?typeof v.type==='function'?expand(v.type(v.props)):{...v,props:{...v.props,children:expand(v.props?.children)}}:v;
function render(next=props){props=next;do{dirty=false;cursor=0;effects.length=0;tree=expand(viewer.exports.RChartViewer(props));effects.splice(0).forEach(fn=>fn());}while(dirty);}
const nodes=v=>Array.isArray(v)?v.flatMap(nodes):v&&typeof v==='object'?[v,...nodes(v.props?.children)]:[];
const find=type=>nodes(tree).find(n=>n.type===type);
const flush=async()=>{for(let i=0;i<6;i++)await Promise.resolve();render();};
(async()=>{
 const signal=new AbortController().signal;
 const loaded=await helper.exports.loadRWidgetDocument('/api/v1/research/analysis-artifacts/64/download/?inline=1',signal);
 assert.equal(requests[0].options.credentials,'same-origin');assert.equal(requests[0].options.signal,signal);
 assert.ok(loaded.indexOf('Content-Security-Policy')<loaded.indexOf('<script>'));
 assert.ok(loaded.includes("connect-src 'none'")&&loaded.includes("default-src 'none'"));
 for(const url of ['https://outside.test/widget.html','//outside.test/x','/api/v1/auth/session/','/r-demo/../../x.html'])
  await assert.rejects(()=>helper.exports.loadRWidgetDocument(url,signal),/地址无效/);
 global.fetch=async()=>new Response('{}',{status:401,headers:{'Content-Type':'application/json'}});
 await assert.rejects(()=>helper.exports.loadRWidgetDocument('/r-demo/overlap.html',signal),/HTTP 401/);
 global.fetch=async()=>new Response('{}',{headers:{'Content-Type':'application/json'}});
 await assert.rejects(()=>helper.exports.loadRWidgetDocument('/r-demo/overlap.html',signal),/格式不正确/);
 render({title:'fixture',interactive:true,htmlUrl:'/r-demo/overlap.html'});
 assert.equal(find('iframe').props.sandbox,'allow-scripts allow-downloads');assert.equal(find('iframe').props.src,undefined);
 render({...props,htmlUrl:'/r-demo/components.html'});assert.equal(pending[0].signal.aborted,true);
 pending[1].resolve('NEW_PRIVATE_WIDGET');await flush();assert.equal(find('iframe').props.srcDoc,'NEW_PRIVATE_WIDGET');
 pending[0].resolve('STALE_WIDGET');await flush();assert.equal(find('iframe').props.srcDoc,'NEW_PRIVATE_WIDGET');
 render({...props,htmlUrl:'/r-demo/pathways.html'});pending[2].reject(new Error('fixture unavailable'));await flush();
 assert.ok(nodes(tree).some(n=>n.props?.role==='alert'));assert.ok(!find('iframe'));
 nodes(tree).find(n=>n.type==='button'&&n.props.children==='重新加载图表').props.onClick();render();
 assert.equal(pending.length,4,'Failed widget has a real retry action');
 for(const hook of hooks)hook.cleanup?.();const before=writes;
 pending[3].resolve('UNMOUNTED_WIDGET');await Promise.resolve();assert.equal(writes,before);
 // The merged viewer must retain the existing GET-only image recovery instead
 // of asking the researcher to generate a second analysis or chart.
 hooks.length=0;pending.length=0;
 render({title:'private saved chart',interactive:false,svgUrl:'/api/v1/research/analysis-artifacts/45/download/?inline=1'});
 const staleImageError=find('img').props.onError;
 staleImageError();render();assert.ok(nodes(tree).some(n=>n.props?.role==='alert'));
 nodes(tree).find(n=>n.type==='button'&&n.props.children==='重新读取图表文件').props.onClick();render();
 assert.equal(find('img').props.src,'/api/v1/research/analysis-artifacts/45/download/?inline=1&readAttempt=1');
 const beforeStale=writes;staleImageError();assert.equal(writes,beforeStale);
 assert.equal(pending.length,0,'Static image retries never load or generate an interactive widget');
 console.log('PASS: authenticated local widget loading; opaque CSP-protected srcdoc; URL/MIME/401 failures; stale response cancellation; retry and unmount guards.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
