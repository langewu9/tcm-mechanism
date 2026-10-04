// Synthetic export contract checks; no browser or external service calls.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const assert = require('node:assert/strict');
const load = createRequire(path.join(__dirname, '..', 'package.json'));
const ts = load('typescript');
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => module._compile(ts.transpileModule(
    fs.readFileSync(filename, 'utf8'),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } },
  ).outputText, filename);
}
const React = load('react');
const { renderToStaticMarkup } = load('react-dom/server');
const { networkRawCsv, NetworkResultDownloads } = load('./src/components/NetworkResultDownloads.tsx');

function parseCsv(text) {
  const rows = [], row = [];
  let cell = '', quoted = false;
  const data = text.replace(/^\ufeff/, '');
  for (let i = 0; i < data.length; i++) {
    const char = data[i];
    if (char === '"') {
      if (quoted && data[i + 1] === '"') { cell += '"'; i++; }
      else quoted = !quoted;
    } else if (char === ',' && !quoted) { row.push(cell); cell = ''; }
    else if (char === '\r' && data[i + 1] === '\n' && !quoted) {
      row.push(cell); rows.push([...row]); row.length = 0; cell = ''; i++;
    } else cell += char;
  }
  assert.equal(quoted, false);
  return rows;
}
const result = {
  taskId: 61, summary: { herb: 'H', disease: 'D' }, targets: [],
  limits: { targetsTruncated: false, linksTruncated: false },
  raw: {
    herbLinks: [
      { herb: 'H', component: 'C', target: 'HERB_ONLY', targetStableId: 'target:1', sourceVersion: 'v2', sourceRecordId: 'ct:1', herbSourceVersion: 'v1', herbSourceRecordId: 'hc:1', score: null },
      { herb: '=formula', component: '含"引号\n换行', target: 'HERB_ONLY', targetStableId: 'target:2', sourceVersion: 'v3', sourceRecordId: 'ct:2', herbSourceVersion: 'v1', herbSourceRecordId: 'hc:2', score: 0.2 },
    ],
    diseaseTargets: [{ disease: 'D', target: 'DISEASE_ONLY', sourceRecordId: 'dt:1' }],
    diseaseHerbLinks: [],
    directDiseaseHerbLinks: [{ disease: 'D', herb: 'H', target: 'DIRECT_ONLY', herbStableId: 'herb:1', sourceRecordId: 'dht:1' }],
  },
  rawLimits: {
    formatVersion: 'network-raw-evidence-v1', rowLimit: 4000,
    tablesTruncated: { herbLinks: false, diseaseTargets: false, diseaseHerbLinks: false, directDiseaseHerbLinks: false },
    inputRelationsTruncated: {},
  },
};
const [headers, ...records] = parseCsv(networkRawCsv(result, 'herbLinks'));
const field = (row, name) => row[headers.indexOf(name)];
assert.equal(records.length, 2);
assert.equal(field(records[0], 'taskId'), '61');
assert.equal(field(records[0], 'target'), 'HERB_ONLY');
assert.equal(field(records[0], 'sourceVersion'), 'v2');
assert.equal(field(records[0], 'herbSourceVersion'), 'v1');
assert.equal(field(records[0], 'sourceRecordId'), 'ct:1');
assert.equal(field(records[0], 'herbSourceRecordId'), 'hc:1');
assert.equal(field(records[0], 'score'), '');
assert.equal(field(records[1], 'herb'), "'=formula");
assert.equal(field(records[1], 'component'), '含"引号\n换行');
assert.equal(field(records[1], 'targetStableId'), 'target:2');
const before = JSON.stringify(result);
const html = renderToStaticMarkup(React.createElement(NetworkResultDownloads, { result }));
for (const label of ['中药侧原始表', '疾病侧原始表', '直接关联表']) assert.ok(html.includes(label));
assert.equal((html.match(/<button[^>]*disabled=""/g) || []).length, 2); // Only candidate exports are empty.
assert.ok(networkRawCsv(result, 'diseaseTargets').includes('DISEASE_ONLY'));
assert.ok(networkRawCsv(result, 'directDiseaseHerbLinks').includes('DIRECT_ONLY'));
assert.equal(JSON.stringify(result), before);
result.rawLimits.inputRelationsTruncated.compoundTargets = true;
assert.equal(field(parseCsv(networkRawCsv(result, 'herbLinks'))[1], 'truncated'), 'true');
const diseaseCsv = parseCsv(networkRawCsv(result, 'diseaseTargets'));
assert.equal(diseaseCsv[1][diseaseCsv[0].indexOf('truncated')], 'false');
result.rawLimits.tablesTruncated.directDiseaseHerbLinks = true;
const directCsv = parseCsv(networkRawCsv(result, 'directDiseaseHerbLinks'));
assert.equal(directCsv[1][directCsv[0].indexOf('truncated')], 'true');
const historical = { ...result, raw: undefined, rawLimits: undefined };
assert.equal(networkRawCsv(historical, 'herbLinks'), null);
const historicalHtml = renderToStaticMarkup(React.createElement(NetworkResultDownloads, { result: historical }));
assert.ok(historicalHtml.includes('此任务未保存原始侧证据'));
assert.equal((historicalHtml.match(/<button[^>]*disabled=""/g) || []).length, 5);
console.log('PASS: side evidence independent of candidates; two edge sources; stable IDs; CSV quoting/formula protection; table/input truncation; unavailable historical exports.');
