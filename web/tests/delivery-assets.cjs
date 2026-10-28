// Read-only delivery gate: generated demonstrations must be complete before packaging.
const fs = require('fs'), path = require('path'), assert = require('node:assert/strict'), crypto = require('crypto');
const root = path.resolve(__dirname, '..');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText, filename);
const { R_CHARTS } = require('../src/demo/catalog.ts');
const directory = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(root,'../public/r-demo');
try {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory,'manifest.json'),'utf8'));
  assert.equal(manifest.synthetic, true); assert.equal(manifest.charts.length,R_CHARTS.length);
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
      if(format==='html') {
        assert.ok(data.toString().includes('echarts4r html-widget'));
        assert.ok(data.toString().includes('chart-find'));
        assert.ok(!/<script[^>]+src=/.test(data.toString()));
      }
      const checksum = manifest.charts.find(item=>item.key===key).artifacts?.[format];
      assert.equal(typeof checksum,'string','Regenerate demos to include artifact checksums');
      assert.equal(crypto.createHash('sha256').update(data).digest('hex'),checksum);
    }
  }
  console.log(`PASS: all ${R_CHARTS.length} keys, synthetic labels, hashes and ${R_CHARTS.length*4} R artifacts are ready for delivery.`);
  const publicDirectory = path.resolve(directory,'../r-public-demo');
  const publicManifest = JSON.parse(fs.readFileSync(path.join(publicDirectory,'manifest.json'),'utf8'));
  assert.equal(publicManifest.synthetic,false); assert.equal(publicManifest.publicExample,true);
  assert.equal(publicManifest.provenance.source,'STRING'); assert.equal(publicManifest.provenance.license,'CC BY 4.0');
  assert.equal(publicManifest.charts.length,7);
  for(const chart of publicManifest.charts) {
    assert.ok(R_CHARTS.some(([key])=>key===chart.key));
    const fixture = JSON.parse(fs.readFileSync(path.join(publicDirectory,chart.key+'.json'),'utf8'));
    assert.equal(fixture.synthetic,false); assert.equal(fixture.publicExample,true);
    assert.equal(fixture.payload.inputSha256,chart.inputSha256);
    assert.ok(fixture.payload.subtitle.includes('非用户实验结果'));
    for(const format of ['svg','pdf','png','html']) {
      const data = fs.readFileSync(path.join(publicDirectory,chart.key+'.'+format));
      assert.equal(crypto.createHash('sha256').update(data).digest('hex'),chart.artifacts[format]);
      if(format==='html') assert.ok(data.toString().includes('echarts4r html-widget'));
    }
  }
  console.log('PASS: 7 separately labelled STRING public example keys, provenance, offline widgets and 28 artifact checksums.');
} catch(error) { console.error('DELIVERY BLOCKED: 演示资源缺失或无效。先运行 r_viz/prepare_demo_gallery.py，再构建交付包。',error.message); process.exitCode=1; }
