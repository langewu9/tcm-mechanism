// Read-only delivery gate: generated demonstrations must be complete before packaging.
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict'), crypto = require('crypto');
const root = path.resolve(__dirname, '..');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText, filename);
const { R_CHARTS } = require('../src/demo/catalog.ts');
const directory = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(root,'../public/r-demo');
try {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory,'manifest.json'),'utf8'));
  assert.equal(manifest.synthetic, true); assert.equal(manifest.charts.length,14);
  assert.deepEqual(new Set(manifest.charts.map(item=>item.key)),new Set(R_CHARTS.map(([key])=>key)));
  for (const [key] of R_CHARTS) {
    const fixture = JSON.parse(fs.readFileSync(path.join(directory,key+'.json'),'utf8'));
    assert.equal(fixture.synthetic,true); assert.equal(fixture.key,key);
    assert.ok(fixture.payload.title.includes('合成演示'));
    assert.ok(fixture.payload.subtitle.includes('非真实实验'));
    assert.equal(fixture.payload.inputSha256,manifest.charts.find(item=>item.key===key).inputSha256);
    for (const format of ['svg','pdf','png','html']) {
      const data = fs.readFileSync(path.join(directory,key+'.'+format)); assert.ok(data.length>100);
      if(format==='png') assert.equal(data.subarray(0,8).toString('hex'),'89504e470d0a1a0a');
      if(format==='pdf') assert.equal(data.subarray(0,4).toString(),'%PDF');
      if(format==='svg') assert.ok(data.toString().includes('<svg'));
      if(format==='html') assert.ok(data.toString().includes('合成演示'));
      const checksum = manifest.charts.find(item=>item.key===key).artifacts?.[format];
      assert.equal(typeof checksum,'string','Regenerate demos to include artifact checksums');
      assert.equal(crypto.createHash('sha256').update(data).digest('hex'),checksum);
    }
  }
  console.log('PASS: all 14 keys, synthetic labels, hashes and 56 R artifacts are ready for delivery.');
} catch(error) { console.error('DELIVERY BLOCKED: 演示资源缺失或无效。先运行 r_viz/prepare_demo_gallery.py，再构建交付包。',error.message); process.exitCode=1; }
