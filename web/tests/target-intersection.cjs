const fs = require('node:fs'), path = require('node:path'), {createRequire} = require('node:module'), assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..'), load = createRequire(path.join(root,'package.json')), ts = load('typescript');
for (const ext of ['.ts','.tsx']) require.extensions[ext] = (module,file) => module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,file);
const React = load('react'), {renderToStaticMarkup} = load('react-dom/server');
const {intersectionState,TargetIntersectionFigure,TargetIntersectionNotice} = load('./src/components/TargetIntersectionFigure.tsx');
const base = {taskId:1,summary:{herb:'麦冬、半夏、人参、大枣、甘草、粳米',disease:'肺纤维化',matchedHerbs:['麦冬'],matchedDiseases:['Pulmonary fibrosis'],unmatchedHerbs:[],unmatchedDiseases:[],herbTargetCount:1078,diseaseTargetCount:600,strictIntersectionCount:50},limits:{targetsTruncated:false,linksTruncated:false}};
const make = (summary={},other={}) => ({...base,...other,summary:{...base.summary,...summary}});
const render = result => renderToStaticMarkup(React.createElement(TargetIntersectionFigure,{result}));
const notice = (result,onDiseaseSelect) => renderToStaticMarkup(React.createElement(TargetIntersectionNotice,{result,onDiseaseSelect}));
const circles = html => [...html.matchAll(/<circle[^>]*cx="([\d.]+)"[^>]*r="([\d.]+)"/g)].map(match=>({x:Number(match[1]),r:Number(match[2])}));

for (const result of [make({matchedDiseases:[],unmatchedDiseases:['肺纤维化'],diseaseTargetCount:0,strictIntersectionCount:0}),make({matchedHerbs:[],herbTargetCount:0,strictIntersectionCount:0})]) {
  assert.equal(intersectionState(result).kind,'unmatched'); assert.equal(circles(render(result)).length,0);
  assert.ok(render(result).includes('未匹配不等于')); assert.ok(!render(result).includes('<svg'));
}
for (const counts of [{herbTargetCount:0,diseaseTargetCount:10},{herbTargetCount:10,diseaseTargetCount:0},{herbTargetCount:0,diseaseTargetCount:0}]) {
  const result=make({...counts,strictIntersectionCount:0});
  assert.equal(intersectionState(result).kind,'missing_evidence'); assert.equal(circles(render(result)).length,0);
  assert.ok(render(result).includes('未返回有效靶点证据'));
}
const zero=make({strictIntersectionCount:0});
assert.equal(intersectionState(zero).kind,'disjoint');
const disjoint=circles(render(zero)); assert.equal(disjoint.length,2);
assert.ok(Math.abs(disjoint[0].x-disjoint[1].x)>disjoint[0].r+disjoint[1].r,'Zero intersection has separated circles');
assert.ok(render(zero).includes('∩ = 0'));
assert.ok(notice(zero).includes('不能据此判断没有生物学关联'));
const overlapping=circles(render(base));
assert.ok(Math.abs(overlapping[0].x-overlapping[1].x)<overlapping[0].r+overlapping[1].r);
for (const counts of [{herbTargetCount:50,diseaseTargetCount:600},{herbTargetCount:600,diseaseTargetCount:50}]) {
  const nested=circles(render(make({...counts,strictIntersectionCount:50})));
  assert.ok(Math.abs(nested[0].x-nested[1].x)+nested[1].r<nested[0].r,'A true subset is contained');
}
assert.ok(render(make({herbTargetCount:50,diseaseTargetCount:50,strictIntersectionCount:50})).includes('两侧集合完全重合'));
for (const invalid of [NaN,-1,1.5,Number.MAX_SAFE_INTEGER+1]) assert.equal(intersectionState(make({strictIntersectionCount:invalid})).kind,'invalid');
assert.equal(intersectionState(make({strictIntersectionCount:800})).kind,'invalid');
const partial=make({}, {rawLimits:{inputRelationsTruncated:{diseaseTargets:true}}});
assert.equal(intersectionState(partial).partial,true);assert.equal(intersectionState(partial).badge,'部分结果');
assert.ok(notice(partial).includes('不是全库总量'));assert.ok(render(partial).includes('当前返回子集'));
assert.equal(intersectionState(make({}, {rawLimits:{inputRelationsTruncated:{pathways:true}}})).partial,false,'Pathway bounds do not invalidate target sets');
assert.equal(intersectionState(make({unmatchedHerbs:['未匹配药材']})).partial,true);
assert.equal(intersectionState(make({diseaseResolution:{entitiesTruncated:true}})).partial,true);
const long='中药名称'.repeat(60)+'<script>alert(1)</script>', longResult=make({herb:long});
const html=render(longResult), svg=html.match(/<svg[\s\S]*?<\/svg>/)[0];
assert.ok(!svg.includes('中药名称'),'Full query names are outside SVG');
assert.ok(html.includes('中药名称'.repeat(60)));assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
assert.ok(html.indexOf('target-intersection-caption')>html.indexOf('</svg>'),'Caption never overlays circles');
assert.ok(html.includes('圆面积不代表数量'));
const unresolved=make({unmatchedDiseases:['冠心病'],matchedDiseases:[],diseaseTargetCount:0,strictIntersectionCount:0,diseaseResolution:{status:'needs_selection',candidates:[{label:'Acute coronary syndromes',sourceSlugs:['source-a']}],entitiesTruncated:false}});
assert.ok(notice(unresolved,()=>{}).includes('使用名称：Acute coronary syndromes'));
assert.ok(notice(unresolved).includes('不一定与原疾病等价'));
const css=fs.readFileSync(path.join(root,'src/styles/app.css'),'utf8');
assert.ok(css.includes('min-width: 360px; height: auto'));assert.ok(css.includes('.target-intersection .target-intersection-legend { grid-template-columns: minmax(0, 1fr)'));
const before=JSON.stringify(base);render(base);notice(base);assert.equal(JSON.stringify(base),before);
console.log('PASS: unmatched/missing/invalid states, disjoint/overlap/subset/equal sets, partial-source limits, accessible counts, external full labels, safe escaping and caption separation.');
