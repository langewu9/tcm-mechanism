const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..');
const read = name => fs.readFileSync(path.join(root,'src',name),'utf8');
assert.ok(read('app/App.tsx').includes('<Route path="/" element={<HomePage />} />'));
assert.ok(read('pages/LoginPage.tsx').includes('navigate("/", { replace: true })'));
assert.ok(!read('pages/HomePage.tsx').includes('R 交互图仍待接入'));
assert.ok(read('components/AppNavigation.tsx').includes('href: "/", label: "平台首页"'));
assert.ok(read('components/AppShell.tsx').includes('to="/" className="brand-lockup"'));
for(const file of ['components/ResearchToolTabs.tsx','components/DiseaseEvidenceResults.tsx','components/ComponentComparisonResults.tsx']) assert.ok(read(file).includes('CatalogRVisualization'));
const network = read('pages/NetworkPharmacologyPage.tsx');
const ts = require('typescript');
const networkTree = ts.createSourceFile('NetworkPharmacologyPage.tsx',network,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const galleries = [], statistics = [];
function visitNetwork(node) {
  if (ts.isJsxSelfClosingElement(node)) {
    if (node.tagName.getText(networkTree) === 'RAnalysisGallery') galleries.push(node);
    if (node.tagName.getText(networkTree) === 'NetworkPharmacologyCharts') statistics.push(node);
  }
  ts.forEachChild(node, visitNetwork);
}
visitNetwork(networkTree);
const expression = (node,name) => node.attributes.properties.find(attribute=>ts.isJsxAttribute(attribute) && attribute.name.text===name)?.initializer?.expression;
const currentGalleries = galleries.filter(node=>expression(node,'taskId')?.getText(networkTree)==='result.taskId');
assert.equal(currentGalleries.length,1,'The current network analysis has one R gallery');
assert.ok(expression(currentGalleries[0],'key'),'The gallery remounts when its saved task changes');
assert.equal(statistics.length,1,'Saved evidence statistics have one implementation in the page');
assert.ok(expression(currentGalleries[0],'additionalCharts')?.getText(networkTree).includes('<NetworkPharmacologyCharts'),
  'Saved evidence statistics render as a gallery subpage alongside the new R interface');
const view = read('components/CatalogRVisualization.tsx');
assert.ok(view.includes('expectedSha256') && view.includes('generation.current === current') && view.includes('lock.current'));
assert.ok(!view.includes('network:') && !view.includes('nodes:'));
assert.ok(read('api/catalog.ts').includes('/api/v1/catalog/visualization-snapshots/'));
console.log('PASS: home entry and login destination, homepage navigation, R catalogue/name-comparison integration, immutable-source submission and stale-response guard.');
