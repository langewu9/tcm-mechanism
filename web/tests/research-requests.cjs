// Execute the real workbench handlers with deferred API responses. This checks
// request ordering and export content; browser rendering is verified separately.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const webRoot = path.resolve(__dirname, '..');
const load = Module.createRequire(path.join(webRoot, 'package.json'));
const ts = load('typescript');
const hooks = [];
let cursor = 0, dirty = false, writes = 0, tree, effects = [];
const fakeReact = {
  useState(initial) { const i = cursor++; hooks[i] ??= {value: initial}; return [hooks[i].value, value => { const next = typeof value === 'function' ? value(hooks[i].value) : value; if (!Object.is(next, hooks[i].value)) { hooks[i].value = next; dirty = true; writes++; } }]; },
  useRef(initial) { const i = cursor++; hooks[i] ??= {value: {current: initial}}; return hooks[i].value; },
  useEffect(callback) { const i = cursor++; if (!hooks[i]) { hooks[i] = {callback}; effects.push(() => { hooks[i].cleanup = callback(); }); } },
};
const jsx = (type, props, key) => ({type, props, key});
const calls = [], downloads = [];
const api = name => (...args) => { let resolve, reject; const promise = new Promise((yes,no) => {resolve=yes;reject=no;}); calls.push({name,args,resolve,reject}); return promise; };
const catalogue = Object.fromEntries(['searchHerbComponentEvidence','searchDiseaseEvidence','searchReactomeCatalog','searchCatalogEntities','getEntityNeighborhood'].map(name=>[name,api(name)]));
const chemblApi = Object.fromEntries(['compareComponents','searchChemblMolecules','searchChemblActivities'].map(name=>[name,api(name)]));
const helpersFile = path.join(webRoot,'src/utils/downloads.ts');
const helpers = new Module(helpersFile);
const compile = (filename) => ts.transpileModule(fs.readFileSync(filename,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
helpers._compile(compile(helpersFile), helpersFile);
const filename = path.join(webRoot,'src/components/ResearchToolTabs.tsx');
const subject = new Module(filename);
subject.require = name => {
  if (name === 'react') return fakeReact;
  if (name === 'react/jsx-runtime') return {jsx,jsxs:jsx,Fragment:'Fragment'};
  if (name === 'react-router-dom') return {Link:'Link',useSearchParams:()=>[new URLSearchParams(),()=>{}]};
  if (name === 'lucide-react') return new Proxy({}, {get:(_,key)=>String(key)});
  if (name === '../api/client') return {ApiError:class extends Error {}};
  if (name === '../api/catalog') return catalogue;
  if (name === '../api/chembl') return chemblApi;
  if (name === '../api/network') return {runNetworkPharmacology:api('runNetworkPharmacology')};
  if (name === '../utils/downloads') return {...helpers.exports,downloadText:(...args)=>downloads.push(args)};
  if (name === './ReactomePathwayLookup') return {reactomeCatalogueCsv:()=>''};
  if (name === './CatalogEvidenceFigures') return {CatalogEvidenceFigures:'CatalogEvidenceFigures'};
  const child = {'./ComponentComparisonResults':'ComponentComparisonResults','./DiseaseEvidenceResults':'DiseaseEvidenceResults','./NetworkPharmacologyCharts':'NetworkPharmacologyCharts','./NetworkResultDownloads':'NetworkResultDownloads','./PaginatedTable':'PaginatedTable'}[name];
  if (child) return {[child]:child};
  throw new Error('Unexpected import '+name);
};
subject._compile(compile(filename), filename);
const Page = subject.exports.ResearchToolTabs;
function expand(value) { if (Array.isArray(value)) return value.map(expand); if (!value || typeof value !== 'object') return value; if (typeof value.type === 'function') return expand(value.type(value.props)); return {...value,props:{...value.props,children:expand(value.props?.children)}}; }
function render() { do { dirty=false;cursor=0;effects=[];tree=expand(Page());effects.forEach(fn=>fn()); } while(dirty); }
function nodes(value) { if (!value || typeof value !== 'object') return []; if (Array.isArray(value)) return value.flatMap(nodes); return [value,...nodes(value.props?.children)]; }
const text = value => typeof value==='string' || typeof value==='number' ? String(value) : Array.isArray(value) ? value.map(text).join('') : value?.props ? text(value.props.children) : '';
function find(predicate) { const found=nodes(tree).find(predicate);assert.ok(found,'Expected rendered control');return found; }
const button = label => find(n=>n.type==='button' && text(n).includes(label));
const tab = id => {find(n=>n.props?.id===`research-tab-${id}`).props.onClick();render();};
const form = () => find(n=>n.type==='form').props.onSubmit;
const event = () => ({preventDefault(){}});
const submit = () => {form()(event());render();};
const input = (id,value) => {find(n=>n.props?.id===id).props.onChange({target:{value}});render();};
const consent = () => {find(n=>n.type==='input' && n.props.type==='checkbox').props.onChange({target:{checked:true}});render();};
const checked = () => find(n=>n.type==='input' && n.props.type==='checkbox').props.checked;
const named = name => calls.filter(c=>c.name===name);
const flush = async () => {for(let i=0;i<8;i++) await Promise.resolve();render();};
const entity = (id,label='同名实体') => ({id,label,stable_id:`entity:${id}`,entity_type:'protein',organism:'Homo sapiens',source_slug:'fixture',source_version:'v1'});
const page = (results,next=null,previous=null) => ({results,count:results.length,next,previous});
const molecules = () => ({results:[{chemblId:'CHEMBL1',preferredName:'分子一'},{chemblId:'CHEMBL2',preferredName:'分子二'}],totalCount:2,source:'ChEMBL',sourceVersion:'fixture',retrievedAt:'2026-10-04',nameMatches:[],resolvedQueries:['fixture'],failedQueries:[]});
const activity = chemblId => ({chemblId,results:[],totalCount:0,sourceVersion:'fixture',retrievedAt:'2026-10-04',resultLimit:50});
const evidenceEntity = (id,label) => ({id,label,stableId:`fixture:${id}`,sourceSlug:'fixture',sourceVersion:'v1'});
const targetA=evidenceEntity(21,'同名靶点'), targetB=evidenceEntity(22,'同名靶点'), compound=evidenceEntity(11,'=合成成分');
const evidence = {queryType:'herb',results:['黄芩','黄芩别名'].map((query,i)=>({query,matches:[evidenceEntity(1,'黄芩')],herbs:[evidenceEntity(1,'黄芩')],compounds:[compound],targets:i?[targetA,targetB]:[targetA],relations:[],truncated:Boolean(i)}))};
evidence.results.push({query:'未导入中药',matches:[],herbs:[],compounds:[],targets:[],relations:[],truncated:false});
(async()=>{
  render();
  // React development setup/cleanup/setup must leave usable event handlers.
  for(const hook of hooks) if(hook?.callback) {hook.cleanup();hook.cleanup=hook.callback();}
  const oldSubmit=form();oldSubmit(event());oldSubmit(event());render();
  assert.equal(named('searchHerbComponentEvidence').length,1,'Duplicate local POST blocked synchronously');
  tab('disease');submit();
  named('searchHerbComponentEvidence')[0].resolve(evidence);await flush();
  assert.equal(button('正在检索').props.disabled,true,'Old response cannot unlock new query');
  oldSubmit(event());assert.equal(named('searchHerbComponentEvidence').length,1,'Old tab callback cannot issue a request');
  named('searchDiseaseEvidence')[0].reject(new Error('fixture failure'));await flush();
  assert.ok(nodes(tree).some(n=>n.props?.role==='alert'));
  submit();assert.equal(named('searchDiseaseEvidence').length,2,'Failure releases the request lock');
  named('searchDiseaseEvidence')[1].resolve({query:'肺纤维化'});await flush();
  tab('intersection');const intersectionSubmit=form();intersectionSubmit(event());intersectionSubmit(event());render();
  assert.equal(named('runNetworkPharmacology').length,1,'Intersection task cannot be created twice');
  named('runNetworkPharmacology')[0].reject(new Error('fixture failure'));await flush();

  tab('chembl');submit();assert.equal(named('searchChemblMolecules').length,0);
  consent();const moleculeSubmit=form();moleculeSubmit(event());moleculeSubmit(event());render();
  assert.equal(named('searchChemblMolecules').length,1);assert.equal(checked(),false);
  named('searchChemblMolecules')[0].resolve(molecules());await flush();
  moleculeSubmit(event());assert.equal(named('searchChemblMolecules').length,1,'A cached handler cannot reuse consumed consent');
  assert.equal(button('查看活性').props.disabled,true,'Activities need a fresh consent');
  consent();input('research-query','改过的检索词');assert.equal(checked(),false,'Editing the query clears previous consent');
  consent();const oldActivity=button('查看活性').props.onClick;oldActivity();oldActivity();render();
  assert.equal(named('searchChemblActivities').length,1);assert.equal(checked(),false);
  consent();assert.ok(nodes(tree).filter(n=>n.type==='button' && (text(n).includes('查看活性') || text(n).includes('正在查询'))).every(n=>n.props.disabled));
  named('searchChemblActivities')[0].resolve(activity('CHEMBL999'));await flush();
  assert.ok(text(tree).includes('活性数据与所选'));
  assert.ok(!text(tree).includes('实验活性与靶点'),'Wrong compound response is not displayed');
  oldActivity();assert.equal(named('searchChemblActivities').length,2,'The pending lock released after invalid response');
  render();tab('herb');tab('chembl');assert.equal(checked(),false,'Tab switch clears consent');
  consent();submit();named('searchChemblMolecules')[1].resolve(molecules());await flush();
  consent();button('查看活性').props.onClick();render();
  named('searchChemblActivities')[1].resolve(activity('CHEMBL1'));await flush();
  assert.ok(!text(tree).includes('实验活性与靶点'),'Old activity cannot replace a new request');
  consent();button('正在查询').props.onClick();assert.equal(named('searchChemblActivities').length,3,'Old completion cannot release new detail lock');
  named('searchChemblActivities')[2].resolve(activity('CHEMBL1'));await flush();
  assert.ok(text(tree).includes('实验活性与靶点'));
  const activityRetry=button('查看活性').props.onClick;activityRetry();render();
  named('searchChemblActivities')[3].resolve(activity('CHEMBL1'));await flush();
  assert.equal(checked(),false);activityRetry();
  assert.equal(named('searchChemblActivities').length,4,'Cached activity callback cannot reuse consumed consent');

  tab('catalogue');input('research-query','fixture');submit();
  named('searchCatalogEntities')[0].resolve(page([entity(1,'实体一'),entity(2,'实体二')],'next'));await flush();
  const select = label => find(n=>n.type==='button' && n.props.className==='knowledge-entity-option' && text(n).includes(label)).props.onClick;
  select('实体一')();render();select('实体二')();render();
  named('getEntityNeighborhood')[1].resolve({entity:entity(2,'实体二'),relations:[],truncated:false});await flush();
  named('getEntityNeighborhood')[0].reject(new Error('old failure'));await flush();
  assert.ok(text(tree).includes('实体二'));assert.ok(!nodes(tree).some(n=>n.props?.role==='alert'),'Old detail failure is suppressed');
  const oldEntitySelect=select('实体一');oldEntitySelect();render();
  const next=button('下一页').props.onClick;next();next();render();
  assert.equal(named('searchCatalogEntities').length,2,'Synchronous duplicate pagination blocked');
  named('getEntityNeighborhood')[2].resolve({entity:entity(1,'实体一'),relations:[],truncated:false});await flush();
  named('searchCatalogEntities')[1].resolve(page([entity(3,'实体三')],null,'previous'));await flush();
  oldEntitySelect();assert.equal(named('getEntityNeighborhood').length,3,'Cached entity from another result page cannot load evidence');
  assert.ok(!text(tree).includes('实体一'),'Page change discards old entity detail');
  select('实体三')();render();named('getEntityNeighborhood')[3].resolve({entity:entity(999),relations:[],truncated:false});await flush();
  assert.ok(text(tree).includes('来源证据与所选实体不一致'));
  assert.ok(!nodes(tree).some(n=>n.props?.className==='knowledge-entity-detail'));

  tab('herb');submit();named('searchHerbComponentEvidence')[1].resolve(evidence);await flush();
  const summary=find(n=>n.type==='table' && n.props['aria-label']==='逐项中药检索汇总');
  assert.equal(nodes(summary).filter(n=>n.type==='tbody')[0].props.children.length,3);
  assert.ok(text(summary).includes('未匹配'),'Unimported query is shown separately');assert.ok(text(summary).includes('0+'),'Truncated per-query relation count remains marked');
  button('导出成分清单').props.onClick();button('导出靶点清单').props.onClick();button('导出完整 JSON').props.onClick();
  assert.equal(downloads[0][1].trim().split('\r\n').length,2,'Shared component exported once');
  assert.ok(downloads[0][1].includes("'=合成成分"),'CSV formula protection retained');
  assert.equal(downloads[1][1].trim().split('\r\n').length,3,'Same label with distinct IDs remains separate');
  assert.ok(downloads[1][1].includes('fixture:21') && downloads[1][1].includes('fixture:22'));
  assert.deepEqual(JSON.parse(downloads[2][1]),evidence,'JSON retains per-query evidence and truncation');
  submit();for(const hook of hooks) hook?.cleanup?.();const previousWrites=writes;
  named('searchHerbComponentEvidence')[2].resolve(evidence);for(let i=0;i<8;i++) await Promise.resolve();
  assert.equal(writes,previousWrites,'Unmounted workbench receives no state writes');
  console.log('PASS: duplicate search/task/pagination guards; stale tab and detail responses; invalid evidence identity; per-call consent; cleanup; main herb summary; entity-ID export deduplication.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
