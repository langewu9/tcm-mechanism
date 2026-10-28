const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {createRequire,Module}=require('node:module');
const root=path.resolve(__dirname,'..'),load=createRequire(path.join(root,'package.json'));
const ts=load('typescript'),React=load('react'),{renderToStaticMarkup}=load('react-dom/server');
const file=path.join(root,'src/components/DiseaseEvidenceResults.tsx'),subject=new Module(file);
subject.require=name=>name==='./CatalogRVisualization'?{CatalogRVisualization:()=>React.createElement('aside',{'data-chart-preparation':'true'})}:
  name==='./PaginatedTable'?{PaginatedTable:()=>null}:name==='../utils/downloads'?{downloadText(){},encodeCsv(){return '';}}:load(name);
subject._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,file);
const data={query:'NOT_A_DISEASE',matches:[],herbs:[],targets:[],relations:[],links:[],expandedQueries:[],ambiguous:false,
  truncated:false,counts:{diseases:0,herbs:0,targets:0,links:0,relations:0},limits:{maxMatches:20,maxRelations:1200}};
const render=value=>renderToStaticMarkup(React.createElement(subject.exports.DiseaseEvidenceResults,{data:value}));
const empty=render(data);assert.ok(empty.includes('没有匹配的疾病实体'));assert.ok(!empty.includes('data-chart-preparation'));
const found=render({...data,matches:[{id:1,label:'Synthetic disease',stableId:'fixture:disease'}],counts:{...data.counts,diseases:1}});
assert.ok(found.includes('data-chart-preparation'));assert.ok(found.includes('没有返回关联证据'));
console.log('PASS: unmatched disease has no chart preparation; matched entity without links has an explicit evidence-empty state.');
