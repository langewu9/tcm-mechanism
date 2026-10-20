// Run main's pure parser, independently of the Django implementation.
const fs = require('node:fs');
const crypto = require('node:crypto');
const ts = require('../web/node_modules/typescript');
const ref = '078d374852d82ad398e98ff8e97d11f7eb2e3a62';
const source = fs.readFileSync(0, 'utf8');
const sourceSha256 = crypto.createHash('sha256').update(source).digest('hex');
if (sourceSha256 !== '1f7744336311855bbef91dd3066e6cd6643e921f0eeddab1977d6e4352dd2c35') throw new Error('Pipe the frozen main src/lib/proteomics.ts into this tool.');
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const module_ = {exports:{}};
new Function('exports', compiled)(module_.exports);
const thresholds = {log2FcMin:1, pValueMax:.05, fdrMax:.05};
const normal = (Gene, log2FC, PValue, FDR) => ({Gene, log2FC, PValue, FDR});
const cases = [
  {name:'valid-boundaries', policy:'equal', rows:[normal('A','1','.05','.05'),normal('B','-2','.9','.01'),normal('C','.99','.001','.001'),normal('D','2','.05',''),normal('E','2','.001','.051')]},
  {name:'percent-and-duplicates', policy:'equal', rows:[normal('A','2','1%','2%'),normal('A','-1','.05','.05'),normal('B','0','.01','.01')]},
  {name:'identifier-list', policy:'equal', rows:[{Gene:'A'},{Gene:'B'}]},
  {name:'invalid-or-missing-statistics', policy:'intentional_qc_exclusion', rows:[normal('BAD_FC','invalid','.01','.01'),normal('MISSING_FC','','.01','.01'),normal('BAD_P','2','-.1',''),normal('BAD_FDR','2','.01','-.2')]},
  {name:'missing-identifier', policy:'intentional_keep_qc_row', rows:[normal('','2','.01','.01')]},
];
for (const item of cases) {
  item.thresholds = thresholds;
  item.mapping = module_.exports.resolveProteomicsMapping(Object.keys(item.rows[0]), {});
  const result = module_.exports.parseProteomicsRows(item.rows, item.mapping, thresholds);
  item.mainSelectedIndices = result.selectedRows.map(row=>row.index);
  item.mainParsedRows = result.parsedRows;
}
process.stdout.write(JSON.stringify({referenceCommit:ref, sourcePath:'src/lib/proteomics.ts',
  sourceSha256, syntheticMeasurements:true, cases},null,2));
