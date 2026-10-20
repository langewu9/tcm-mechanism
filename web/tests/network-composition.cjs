// main Prep B regression: overlapping direct/strict evidence is counted once.
const fs = require('node:fs'), path = require('node:path'), {createRequire} = require('node:module'), assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), load = createRequire(path.join(root, 'package.json')), ts = load('typescript');
for (const ext of ['.ts','.tsx']) require.extensions[ext] = (module,file) => module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText,file);
const React = load('react'), {renderToStaticMarkup} = load('react-dom/server');
const {candidateComposition,NetworkPharmacologyCharts} = load('./src/components/NetworkPharmacologyCharts.tsx');
const result = {summary:{strictIntersectionCount:2,directAssociationTargetCount:2,candidateTargetCount:3},limits:{targetsTruncated:false},charts:{overlap:[],components:[],pathways:[]}};
assert.deepEqual(candidateComposition(result),{strict:2,directOnly:1,overlap:1,total:3});
const render = value => renderToStaticMarkup(React.createElement(NetworkPharmacologyCharts,{result:value}));
const html = render(result);
assert.ok(html.includes('Prep B') && html.includes('严格交集 2 个，仅直接关联 1 个') && html.includes('合计 3 个去重候选'));
for (const summary of [{strictIntersectionCount:4,directAssociationTargetCount:2,candidateTargetCount:3},{strictIntersectionCount:1,directAssociationTargetCount:1,candidateTargetCount:3},{strictIntersectionCount:1.5,directAssociationTargetCount:2,candidateTargetCount:3}]) {
  assert.equal(candidateComposition({...result,summary}),null);
}
const truncated = {...result,limits:{targetsTruncated:true}};
assert.equal(candidateComposition(truncated),null);
assert.ok(render(truncated).includes('暂不绘制构成比例'));
const empty = {...result,summary:{strictIntersectionCount:0,directAssociationTargetCount:0,candidateTargetCount:0}};
assert.ok(render(empty).includes('没有候选靶点') && !render(empty).includes('去重候选靶点</text>'));
assert.deepEqual(candidateComposition({...result,summary:{strictIntersectionCount:2,directAssociationTargetCount:1,candidateTargetCount:3}}),{strict:2,directOnly:1,overlap:0,total:3});
console.log('PASS: main Prep B union composition, overlapping evidence counted once; empty, truncated and inconsistent counts; accessible SVG labels.');
