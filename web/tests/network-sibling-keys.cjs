const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const filename = path.join(__dirname, '../src/pages/NetworkPharmacologyPage.tsx');
const source = ts.createSourceFile(filename, fs.readFileSync(filename, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const elements = [];
let resultPanel;
function visit(node) {
  if (ts.isJsxElement(node) && node.openingElement.attributes.properties.some(attribute =>
    ts.isJsxAttribute(attribute) && attribute.name.text === 'className'
      && attribute.initializer && ts.isStringLiteral(attribute.initializer)
      && attribute.initializer.text === 'panel proteomics-result-panel')) resultPanel = node;
  ts.forEachChild(node, visit);
}
visit(source);
assert.ok(resultPanel, 'The real saved-result panel must be checked');

// JSX expressions do not create a reconciliation boundary. Their rendered
// elements remain siblings of the panel's other direct children.
function directElements(node) {
  if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) return [node];
  if (ts.isJsxExpression(node)) return node.expression ? directElements(node.expression) : [];
  if (ts.isParenthesizedExpression(node)) return directElements(node.expression);
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken)
    return directElements(node.right);
  return [];
}
for (const child of resultPanel.children) elements.push(...directElements(child));
const keyed = elements.flatMap(element => {
  const opening = ts.isJsxElement(element) ? element.openingElement : element;
  const attribute = opening.attributes.properties.find(item => ts.isJsxAttribute(item) && item.name.text === 'key');
  if (!attribute) return [];
  assert.ok(attribute.initializer && ts.isJsxExpression(attribute.initializer) && attribute.initializer.expression);
  return [{ name: opening.tagName.getText(source), expression: attribute.initializer.expression.getText(source) }];
});
assert.ok(keyed.some(item => item.name === 'NetworkPharmacologyCharts'));
assert.ok(keyed.some(item => item.name === 'RAnalysisGallery'));
function keys(resultId, pathwayId) {
  const context = { result: { taskId: resultId }, pathwayTask: { id: pathwayId } };
  return keyed.map(item => ({ ...item, key: String(vm.runInNewContext(item.expression, context)) }));
}
for (const [resultId, pathwayId] of [[29, 30], [32, 41]]) {
  const values = keys(resultId, pathwayId);
  assert.equal(new Set(values.map(item => item.key)).size, values.length,
    `Saved-result siblings must have unique keys: ${values.map(item => `${item.name}=${item.key}`).join(', ')}`);
  const changed = keys(resultId + 1000, pathwayId + 1000);
  values.forEach((item, index) => assert.notEqual(item.key, changed[index].key,
    `${item.name} must remount when its saved task changes`));
}
console.log('PASS: actual saved network result siblings have unique keys and remount when their task IDs change.');
