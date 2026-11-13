// Exercise persisted-result eligibility and the real gallery's handlers offline.
// No database, R service, browser, external API or generated fixture is used.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), load = Module.createRequire(path.join(root, 'package.json'));
const ts = load('typescript'), file = path.join(root, 'src/components/RAnalysisGallery.tsx');
const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions:{
  module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022, jsx:ts.JsxEmit.ReactJSX,
}}).outputText;
class ApiError extends Error {}
const page = {results:[],next:null,previous:null,count:0};
const protein = (result = {}, flags = {}, id = 50) => ({id,task_type:'proteomics',status:'succeeded',
  input_parameters:{externalString:false,externalReactome:false,externalGProfiler:false,...flags},result});
const zeroSummary = {selectedRowCount:306,normalizedCount:306,databaseMappedCount:0,unmappedCount:0,candidateOverlapCount:0,pathwayCount:0};
const syntheticResult = () => ({summary:{...zeroSummary},topNodes:[{symbol:'DEMO_PROTEIN_001',degree:0,mappingStatus:'unverified'}],
  network:{nodes:[{id:'target:demo',type:'target',label:'DEMO_PROTEIN_001'}],links:[]}});
const renderTask = (id,status='succeeded',parent=50,previous=null) => ({id,task_type:'visualization',status,parent_task:parent,progress:0,
  input_parameters:{analysisKind:'r_visualization',parentTaskId:parent,chartKey:'proteomics_top_nodes',previousRenderTaskId:previous},
  result:status==='succeeded'?{taskId:id,parentTaskId:parent,chartKey:'proteomics_top_nodes',rendererVersion:'r-viz-0.4.2',
    artifacts:[{id,format:'svg',downloadUrl:`/private/${id}.svg`}]}:{},error_summary:'SYNTHETIC_RENDER_FAILURE'});
const nodes = node => node == null || typeof node !== 'object' ? [] : Array.isArray(node) ? node.flatMap(nodes) : [node,...nodes(node.props?.children)];
const text = node => node == null || typeof node === 'boolean' ? '' : typeof node === 'string' || typeof node === 'number' ? String(node) : Array.isArray(node) ? node.map(text).join('') : text(node.props?.children);
function harness(restored = {}) {
  const hooks=[],calls={detail:[],summary:[],restore:[],create:[]},timers=new Map();
  let cursor=0,dirty=false,effects=[],tree,props={taskId:50},timerId=0;
  const react={
    useState(initial){const i=cursor++;hooks[i]??={value:typeof initial==='function'?initial():initial};return[hooks[i].value,next=>{const value=typeof next==='function'?next(hooks[i].value):next;if(!Object.is(value,hooks[i].value)){hooks[i].value=value;dirty=true;}}];},
    useRef(initial){const i=cursor++;hooks[i]??={value:{current:initial}};return hooks[i].value;},
    useEffect(callback,deps){const i=cursor++,old=hooks[i];if(!old||deps.some((item,index)=>!Object.is(item,old.deps[index]))){hooks[i]={deps};effects.push(()=>{old?.cleanup?.();hooks[i].cleanup=callback();});}},
  };
  const jsx=(type,props,key)=>type==='SubviewTabs'
    ? {type,key,props:{...props,children:props.views.find(view=>view.key===props.value)?.content??props.views[0]?.content}}
    : {type,props,key};
  const deferred = name => (...args) => new Promise((resolve,reject)=>calls[name].push({args,resolve,reject}));
  const subject=new Module(file);
  subject.require=name=>{
    if(name==='react')return react;
    if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'Fragment'};
    if(name==='../api/client')return {ApiError};
    if(name==='../api/datasets')return {getAnalysisTask:deferred('detail'),getAnalysisTaskSummaries:async(...args)=>{calls.summary.push(args);return page;}};
    if(name==='../api/task-restoration')return {restoreGalleryJobs:async(...args)=>{calls.restore.push(args);return restored;}};
    if(name==='../api/network')return {createVisualization:deferred('create')};
    if(name==='./RChartSource')return {RChartSource:'RChartSource',RChartSourceProvider:'RChartSourceProvider'};
    if(name==='./SubviewTabs')return {SubviewTabs:'SubviewTabs'};
    if(name==='./RChartViewer')return {RChartViewer:'RChartViewer',hasInteractiveRenderer:version=>version==='r-viz-0.4.2'};
    throw Error('Unexpected import: '+name);
  };
  subject._compile(code,file);
  global.window={setTimeout(fn){timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);}};
  function render(next=props){props=next;let guard=0;do{assert.ok(guard++<30,'Bounded render');dirty=false;cursor=0;effects=[];tree=subject.exports.RAnalysisGallery(props);effects.forEach(run=>run());}while(dirty);}
  async function flush(){for(let i=0;i<18;i++)await Promise.resolve();render();}
  function find(predicate){const node=nodes(tree).find(predicate);assert.ok(node,'Expected gallery element');return node;}
  function select(key){find(node=>node.type==='SubviewTabs').props.onChange(key);render();}
  function button(label){return find(node=>node.type==='button'&&text(node)===label);}
  function tick(){const pending=[...timers.values()];timers.clear();pending.forEach(fn=>fn());}
  function cleanup(){hooks.forEach(hook=>hook.cleanup?.());}
  return {catalog:subject.exports.rChartCatalog,calls,render,flush,select,find,button,tick,cleanup,get tree(){return tree;}};
}
const pure=harness(),catalog=pure.catalog;pure.cleanup();
const findChart=(task,key)=>{const value=catalog(task).find(chart=>chart.key===key);assert.ok(value,`Missing business chart ${key}`);return value;};
const checks=[];
const check=(name,run)=>checks.push({name,run});
check('Saved format candidates with degree zero expose the real top-nodes chart without inventing validation',()=>{
  const saved=protein(syntheticResult()),before=JSON.stringify(saved),value=findChart(saved,'proteomics_top_nodes');
  assert.equal(value.available,true);assert.match(value.note,/degree 为 0 仍可绘制/);assert.match(value.note,/仅格式识别项/);assert.match(value.note,/不等于已验证靶点/);
  assert.equal(findChart(saved,'proteomics_summary').available,true);assert.equal(JSON.stringify(saved),before);
  for(const degree of [false,'0',null,NaN,Infinity])assert.equal(findChart(protein({topNodes:[{symbol:'DEMO',degree}]}),'proteomics_top_nodes').available,false);
  for(const topNodes of [[],[{symbol:'',degree:0}],[{degree:0}]]){
    const missing=findChart(protein({topNodes}),'proteomics_top_nodes');assert.equal(missing.available,false);assert.ok(missing.unavailableReason&&missing.nextStep);
  }
});
check('Zero statistics are plot data, while absent statistics have a specific next step',()=>{
  const zeros=Object.fromEntries(Object.keys(zeroSummary).map(key=>[key,0]));
  assert.equal(findChart(protein({summary:zeros}),'proteomics_summary').available,true);
  assert.equal(findChart(protein(),'proteomics_summary').available,false);
  for(const queryType of ['comparison','herb','pathway']){
    const saved={...protein(),task_type:'network',result:{analysisKind:'catalog_evidence',queryType,
      catalogSummary:[{label:'count',value:0}],catalogCoverage:[{label:'pathway',value:0}],network:{nodes:[],links:[]}}};
    assert.equal(findChart(saved,'catalog_summary').available,true);
    if(queryType==='pathway')assert.equal(findChart(saved,'catalog_degree').available,true);
  }
  const network={...protein(),task_type:'network',result:{summary:{herbTargetCount:10,diseaseTargetCount:5},charts:{
    overlap:[{name:'strict intersection',value:0}],components:[{name:'component',targets:0}],pathways:[{name:'pathway',targets:0}]}}};
  for(const key of ['overlap','components','pathways'])assert.equal(findChart(network,key).available,true);
});
check('Legacy complete catalogue summaries use frozen tables, while incomplete history stays unavailable',()=>{
  const snapshot={complete:true,tables:{entities:{count:378,sha256:'a'.repeat(64)},evidenceRecords:{count:894,sha256:'b'.repeat(64)}}};
  const saved={...protein(),task_type:'network',result:{analysisKind:'catalog_evidence',queryType:'herb',snapshot}};
  const before=JSON.stringify(saved);
  assert.equal(findChart(saved,'catalog_summary').available,true);
  assert.match(findChart(saved,'catalog_summary').note,/不读取当前目录/);
  assert.equal(JSON.stringify(saved),before);
  for(const broken of [undefined,{...snapshot,complete:false},{...snapshot,tables:{}},
    {...snapshot,tables:{...snapshot.tables,entities:{count:378,sha256:'invalid'}}}]){
    assert.equal(findChart({...saved,result:{...saved.result,snapshot:broken}},'catalog_summary').available,false);
  }
});
check('External results explain disabled, unavailable, identifier and empty-result states instead of claiming an empty workspace',()=>{
  const empty=protein(syntheticResult());
  for(const [key,provider] of [['ppi_network','STRING'],['ppi_degree','STRING'],['reactome_enrichment','Reactome'],['proteomics_go_kegg_bar','g:Profiler']]){
    const value=findChart(empty,key);assert.equal(value.available,false);assert.ok(value.unavailableReason.includes('未启用 '+provider));assert.match(value.nextStep,/单独同意/);assert.match(value.nextStep,/新任务/);
  }
  for(const [status,reason] of [['unavailable','服务不可用'],['insufficient_identifiers','标识不足'],['no_interactions','物理互作边']]){
    const value=findChart(protein({externalString:{status}}),'ppi_network');assert.equal(value.available,false);assert.ok(value.unavailableReason.includes(reason));
  }
  const nonphysical=findChart(protein({externalString:{source:'STRING',networkType:'functional',status:'succeeded',edges:[{}]}}),'ppi_network');
  assert.equal(nonphysical.available,false);assert.match(nonphysical.unavailableReason,/不能替代 PPI/);
  const noTerms=findChart(protein({externalGProfiler:{status:'no_significant_terms',terms:[]}}),'proteomics_go_kegg_bar');
  assert.match(noTerms.unavailableReason,/没有显著/);
  const noMapping=findChart(protein({externalReactome:{status:'no_mapped_identifiers',pathways:[]}}),'reactome_enrichment');
  assert.match(noMapping.unavailableReason,/没有映射到/);
});
check('Enrichment eligibility requires actual saved significant fields, while gene-pathway graphs require the matching edge',()=>{
  const go={status:'succeeded',terms:[{name:'term',source:'GO:BP',adjustedPValue:.01}]};
  assert.equal(findChart(protein({externalGProfiler:go}),'proteomics_go_kegg_bar').available,true);
  for(const adjustedPValue of [0,.1,'0.01',false])assert.equal(findChart(protein({externalGProfiler:{...go,terms:[{...go.terms[0],adjustedPValue}]}}),'proteomics_go_kegg_bar').available,false);
  const reactome={status:'succeeded',pathways:[{name:'pathway',fdr:.01,matchedEntities:2,totalEntities:10}]};
  assert.equal(findChart(protein({externalReactome:reactome}),'reactome_enrichment').available,true);
  assert.equal(findChart(protein({externalReactome:{...reactome,pathways:[{...reactome.pathways[0],totalEntities:null}]}}),'reactome_enrichment').available,false);
  const network={nodes:[{id:'gene',type:'gene',label:'gene'},{id:'path',type:'pathway',label:'path'},{id:'compound',type:'compound',label:'compound'}],links:[{source:'gene',target:'compound'}]};
  for(const key of ['gene_pathway_network','gene_pathway_distribution'])assert.equal(findChart(protein({network}),key).available,false);
  network.links.push({source:'path',target:'gene'});
  for(const key of ['gene_pathway_network','gene_pathway_distribution'])assert.equal(findChart(protein({network}),key).available,true);
});
check('Every unavailable business chart supplies both a reason and an action without changing source selection',()=>{
  const samples=[protein(),{...protein(),task_type:'network',result:{}},...['herb','pathway','comparison'].map(queryType=>({...protein(),task_type:'network',result:{analysisKind:'catalog_evidence',queryType}}))];
  for(const saved of samples)for(const value of catalog(saved))if(!value.available){assert.ok(value.unavailableReason,value.key);assert.ok(value.nextStep,value.key);}
});
check('Top-nodes real POST, polling, redraw history and retries retain task ownership and duplicate protection',async()=>{
  const h=harness();try{
    h.render();h.calls.detail[0].resolve(protein(syntheticResult()));await h.flush();h.select('ppi_network');
    assert.ok(text(h.tree).includes('本次任务未启用 STRING'));assert.ok(text(h.tree).includes('下一步：'));
    assert.equal(h.button('缺少所需分析数据').props.disabled,true);h.button('缺少所需分析数据').props.onClick();assert.equal(h.calls.create.length,0);
    h.select('proteomics_top_nodes');assert.equal(h.button('生成 R 图表').props.disabled,false);
    assert.ok(h.calls.restore[0][2].has('proteomics_top_nodes'));
    const create=h.button('生成 R 图表').props.onClick;create();create();assert.deepEqual(h.calls.create.map(call=>call.args),[[50,'proteomics_top_nodes']]);
    h.calls.create[0].resolve(renderTask(60,'queued'));await h.flush();assert.equal(h.button('后台绘图 0%').props.disabled,true);
    h.button('后台绘图 0%').props.onClick();assert.equal(h.calls.create.length,1);
    h.tick();assert.deepEqual(h.calls.detail[1].args,[60]);h.calls.detail[1].resolve(renderTask(60));await h.flush();
    assert.equal(h.find(node=>node.type==='RChartViewer').key,60);
    h.button('重新运行 R 绘图').props.onClick();assert.deepEqual(h.calls.create[1].args,[50,'proteomics_top_nodes',{regenerate:true}]);
    h.calls.create[1].reject(new ApiError('SYNTHETIC_POST_FAILURE'));await h.flush();assert.ok(text(h.tree).includes('SYNTHETIC_POST_FAILURE'));
    assert.equal(h.find(node=>node.type==='RChartViewer').props.svgUrl,'/private/60.svg?inline=1');
    h.button('重新运行 R 绘图').props.onClick();h.calls.create[2].resolve(renderTask(61,'failed',50,60));await h.flush();
    assert.ok(nodes(h.tree).some(node=>node.type==='a'&&node.props.href==='/tasks/60'&&text(node).includes('上一版')));
    h.button('重试绘图').props.onClick();assert.deepEqual(h.calls.create[3].args,[50,'proteomics_top_nodes',{regenerate:true}]);
  }finally{h.cleanup();}
});
check('A late top-nodes POST cannot attach to a different parent or replace its saved graph',async()=>{
  const h=harness();try{
    h.render();h.calls.detail[0].resolve(protein(syntheticResult()));await h.flush();h.select('proteomics_top_nodes');h.button('生成 R 图表').props.onClick();
    h.render({taskId:70});h.calls.detail[1].resolve(protein(syntheticResult(),{},70));await h.flush();
    h.calls.create[0].resolve(renderTask(60,'queued'));await h.flush();
    assert.equal(nodes(h.tree).some(node=>node.type==='a'&&node.props.href==='/tasks/60'),false);
    h.button('生成 R 图表').props.onClick();assert.deepEqual(h.calls.create[1].args,[70,'proteomics_top_nodes']);
    h.calls.create[1].resolve(renderTask(71,'queued',999));await h.flush();
    assert.ok(text(h.tree).includes('图表任务创建失败'));assert.equal(nodes(h.tree).some(node=>node.type==='a'&&node.props.href==='/tasks/71'),false);
  }finally{h.cleanup();}
});
(async()=>{let failures=0;for(const {name,run} of checks){try{await run();console.log('PASS: '+name);}catch(error){failures++;console.error('FAIL: '+name+'\n'+error.stack);}}console.log(`${checks.length-failures}/${checks.length} R gallery availability checks passed`);if(failures)process.exitCode=1;})().catch(error=>{console.error(error.stack);process.exitCode=1;});
