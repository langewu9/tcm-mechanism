const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const postcss = require('postcss');
const root = path.resolve(__dirname, '..');
const typography = fs.readFileSync(path.join(root, 'src/styles/typography.css'), 'utf8');
const main = fs.readFileSync(path.join(root, 'src/main.tsx'), 'utf8');
const renderer = fs.readFileSync(path.join(root, '../r_viz/plumber.R'), 'utf8');
const widget = fs.readFileSync(path.join(root, '../r_viz/interactive.R'), 'utf8');
const css = postcss.parse(typography);
const declarations = [];
css.walkDecls(declaration => declarations.push(declaration));
const font = declarations.find(item => item.prop === '--font-ui').value;
assert.ok(font.startsWith('"Microsoft YaHei"'));
assert.ok(font.endsWith('system-ui, sans-serif'));
for (const role of ['body', 'heading', 'display', 'handwriting', 'ancient']) {
  assert.equal(declarations.find(item => item.prop === '--font-' + role).value, 'var(--font-ui)');
}
assert.ok(declarations.some(item => item.prop === '--font-mono' && item.value.includes('monospace')));
assert.ok(main.indexOf('typography.css') > main.indexOf('legacy-product.css'));
assert.equal(renderer.match(/BROWSER_FONT_FAMILY <- '([^']+)'/)[1], font);
assert.ok(widget.includes('fontFamily = BROWSER_FONT_FAMILY'));
assert.ok(widget.includes('BROWSER_FONT_FAMILY, \';font-synthesis:none'));
assert.ok(declarations.some(item => item.prop === 'font-variant-numeric' && item.value.includes('tabular-nums')));
assert.ok(declarations.every(item => item.prop !== 'font-weight' || ['400', '500', '600'].includes(item.value)));
for (const file of ['legacy-global.css', 'legacy-product.css', 'typography.css']) {
  const text = fs.readFileSync(path.join(root, 'src/styles', file), 'utf8');
  assert.ok(!/fonts\.googleapis|SimSun|STSong|Songti|KaiTi|STKaiti|Ma Shan Zheng|Zhi Mang Xing|Long Cang|cursive/.test(text), file);
}
assert.ok(fs.readFileSync(path.join(root, 'src/styles/app.css'), 'utf8').includes('min-height: 1100px'));
console.log('PASS: unified offline UI/R font stack, semantic weights, monospaced technical text, numeric alignment, no calligraphy/CDN and unchanged chart height.');
