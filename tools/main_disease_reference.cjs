// Execute only the pinned main disease aliases and pure result merge functions.
// Never starts Next.js, reads credentials, or calls a provider.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const ts = require(path.join(root, 'web/node_modules/typescript'));
const ref = '078d374852d82ad398e98ff8e97d11f7eb2e3a62';
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (input.mainRef !== ref) throw new Error('Unexpected main reference.');
const source = name => {
  const record = input.referenceFiles[name];
  const bytes = fs.readFileSync(record.path);
  if (crypto.createHash('sha256').update(bytes).digest('hex') !== record.sha256) throw new Error('Reference source changed.');
  return bytes.toString('utf8');
};
const aliases = {exports:{}};
vm.runInNewContext(ts.transpileModule(source('src/lib/disease-query.ts'), {
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}
}).outputText, aliases, {timeout:1000});
const route = source('src/app/api/research/route.ts');
const ast = ts.createSourceFile('main-route.ts', route, ts.ScriptTarget.Latest, true);
const wanted = new Set(['uniqueValues','mergeDiseaseResults']);
const selected = ast.statements.filter(item => ts.isFunctionDeclaration(item) && wanted.has(item.name?.text));
if (selected.length !== wanted.size) throw new Error('Pinned main reference functions unavailable.');
const mergeScope = {};
vm.runInNewContext(ts.transpileModule(selected.map(item => item.getText(ast)).join('\n'), {
  compilerOptions:{target:ts.ScriptTarget.ES2022}
}).outputText, mergeScope, {timeout:1000});
const result = input.cases.map(item => {
  const expanded = aliases.exports.expandDiseaseQueries(item.query);
  if (!item.results) return {query:item.query,expandedQueries:expanded};
  if (JSON.stringify(expanded) !== JSON.stringify(item.expandedQueries)) throw new Error('Alias reference differs.');
  return {query:item.query, expandedQueries:expanded,
    data:mergeScope.mergeDiseaseResults(item.query,expanded,item.results)};
});
process.stdout.write(JSON.stringify({ref,cases:result}));
