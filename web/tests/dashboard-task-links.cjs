// Exercise the actual dashboard routing declarations without mounting React.
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('typescript');
const filename = path.resolve(__dirname, '../src/pages/DashboardPage.tsx');
const source = fs.readFileSync(filename, 'utf8');
const tree = ts.createSourceFile(filename, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declarations = tree.statements.filter(node =>
  ts.isVariableStatement(node) && node.declarationList.declarations.some(item => item.name.getText(tree) === 'taskRoutes')
  || ts.isFunctionDeclaration(node) && node.name?.text === 'taskRoute');
assert.equal(declarations.length, 2, 'Expected the real dashboard route declarations');
const code = ts.transpileModule(declarations.map(node => node.getText(tree)).join('\n'),
  {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS}}).outputText;
const context = {}; vm.createContext(context); vm.runInContext(code + '\nthis.route = taskRoute;', context);
assert.equal(context.route({id: 33, task_type: 'proteomics'}), '/proteomics?proteomicsTask=33',
  'An older saved task must carry its own ID rather than open the latest result');
assert.equal(context.route({id: 38, task_type: 'proteomics'}), '/proteomics?proteomicsTask=38');
assert.equal(context.route({id: 39, task_type: 'research_assistant'}), '/assistant?assistantTask=39');
assert.equal(context.route({id: 28, task_type: 'network', analysis_kind: 'catalog_evidence'}), '/research?catalogTask=28');
assert.equal(context.route({id: 24, task_type: 'network', analysis_kind: 'disease_evidence'}), '/research?diseaseTask=24');
assert.equal(context.route({id: 29, task_type: 'network', analysis_kind: 'network_pharmacology'}), '/network-pharmacology?networkTask=29');
console.log('PASS: dashboard links carry the selected proteomics task and preserve existing explicit task routes.');
