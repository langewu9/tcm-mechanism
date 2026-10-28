const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const load = createRequire(path.resolve(__dirname, '../package.json'));
const ts = load('typescript');
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, filename) =>
  module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, filename);
const { createElement } = load('react');
const { renderToStaticMarkup } = load('react-dom/server');
const { EvidenceEntityTables, EvidenceEntityDirectory, filterEvidenceEntities, uniqueEvidenceEntities } =
  load('./src/components/EvidenceEntityTables.tsx');
const row = (id, label, source = 'herb') => Object.freeze({ id, label,
  stableId: `master:${id}`, sourceSlug: source,
  sourceVersion: 'local-workbooks-master-v1:' + 'a'.repeat(64),
});
const sameA = row(1, '同名靶点', 'herb'), sameB = row(2, '同名靶点', 'hit');
const original = Object.freeze([sameA, sameB, sameA]);
const saved = JSON.stringify(original);
assert.deepEqual(uniqueEvidenceEntities(original).map(item => item.id), [1, 2]);
assert.deepEqual(filterEvidenceEntities(original, 'MASTER:2').map(item => item.id), [2]);
assert.deepEqual(filterEvidenceEntities(original, 'hit').map(item => item.id), [2]);
assert.equal(filterEvidenceEntities(original, '未知名称').length, 0);
assert.strictEqual(filterEvidenceEntities(original, '   '), original);
const longName = '(1S,2S,4S,6R,8S,9S,12R,13R)-5,7,9,13-Tetramethylspiro[5-Oxapentacyclo[10.8.0.0]]-23,24-dihydroxy ruscogenin';
const compounds = Object.freeze([row(10, longName), ...Array.from({ length: 16 }, (_, i) => row(11 + i, `成分-${i + 1}`))]);
const item = Object.freeze({ query: '麦冬', matches: Object.freeze([row(50, 'MatchOnly')]),
  herbs: Object.freeze([row(60, 'HerbOnly')]), compounds,
  targets: Object.freeze([row(70, 'TargetOnly')]), relations: [], ambiguous: false, truncated: true });
const markup = renderToStaticMarkup(createElement(EvidenceEntityTables, { item }));
assert.equal((markup.match(/role="tabpanel"/g) || []).length, 1);
assert.equal((markup.match(/role="tab"/g) || []).length, 4);
assert.ok(markup.includes('成分（17）') && markup.includes('aria-selected="true"'));
assert.ok(markup.includes('aria-label="麦冬 · 成分目录"'));
assert.ok(markup.includes(longName));
assert.ok(!markup.includes('MatchOnly') && !markup.includes('HerbOnly') && !markup.includes('TargetOnly'));
assert.ok(markup.includes('1-8 / 17') && markup.includes('成分目录下一页'));
assert.ok(!markup.includes('成分-16'), 'Only a page of data is mounted');
assert.ok(markup.includes('type="search"') && markup.includes('筛选名称、ID 或来源'));
assert.ok(markup.includes('<details') && markup.includes('查看 ID / 版本'));
const twins = renderToStaticMarkup(createElement(EvidenceEntityDirectory, {
  label: '测试靶点目录', rows: [sameA, sameB],
}));
assert.ok(twins.includes('master:1') && twins.includes('master:2'));
assert.equal((twins.match(/同名靶点/g) || []).length, 2);
assert.ok(twins.includes('a'.repeat(64)), 'Full source version remains inspectable');
const empty = renderToStaticMarkup(createElement(EvidenceEntityDirectory, { label: '空目录', rows: [] }));
assert.ok(empty.includes('暂无空目录记录') && empty.includes('0 / 0 条'));
const hostile = renderToStaticMarkup(createElement(EvidenceEntityDirectory, {
  label: '安全测试', rows: [row(90, '<script>alert(1)</script>')],
}));
assert.ok(!hostile.includes('<script>') && hostile.includes('&lt;script&gt;'));
assert.equal(JSON.stringify(original), saved);
const css = fs.readFileSync(path.resolve(__dirname, '../src/styles/app.css'), 'utf8');
assert.ok(css.includes('.evidence-entity-directory .table-scroll { max-height: 27rem'));
assert.ok(css.includes('white-space: normal; overflow-wrap: anywhere; overflow: visible; text-overflow: clip'));
for (const file of ['ResearchToolTabs.tsx', 'BatchHerbEvidenceLookup.tsx']) {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/components', file), 'utf8');
  assert.ok(source.includes('<EvidenceEntityTables item={item} />'));
  assert.ok(!source.includes('匹配实体：') && !source.includes('sourceNames(item.') && !source.includes('showNames(item.'));
}
console.log('PASS: classified one-table subpages, bounded paging, name/ID/source filters, full wrapped names, expandable provenance, distinct same-name IDs, empty states, escaped text and unchanged input.');
