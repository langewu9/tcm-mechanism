// Offline coverage for the actual settings API/form and page-load recovery.
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..'), load = Module.createRequire(path.join(root, 'package.json'));
const ts = load('typescript');
const compile = file => ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX},
}).outputText;
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (module, file) => module._compile(compile(file), file);
const {updateDataSourceSettings} = load('./src/api/sources.ts');
const {ApiError} = load('./src/api/client.ts');
const React = load('react'), {renderToStaticMarkup} = load('react-dom/server');
const {PageLoadBoundary, PageLoading} = load('./src/app/PageLoadBoundary.tsx');
const slots = []; let cursor = 0, writes = 0, cleanups = [], submitted = [];
const hooks = {
  useState(initial) {const i=cursor++; slots[i] ??= {value:initial}; return [slots[i].value, value => {slots[i].value=value; writes++;}];},
  useRef(initial) {const i=cursor++; slots[i] ??= {value:{current:initial}}; return slots[i].value;},
  useEffect(callback) {const i=cursor++; if (!slots[i]) {slots[i]={}; cleanups.push(callback());}},
};
const file = path.join(root, 'src/components/SourceSettingsForm.tsx'), module_ = new Module(file);
module_.paths = Module._nodeModulePaths(path.dirname(file));
module_.require = name => name === 'react' ? hooks : name === '../api/sources' ? {
  updateDataSourceSettings: (...args) => new Promise((resolve,reject) => submitted.push({args,resolve,reject})),
} : load(name === '../api/client' ? './src/api/client.ts' : name);
module_._compile(compile(file), file);
const {SourceSettingsForm} = module_.exports;
const source = {id:42, name:'Reactome', enabled:true, refresh_interval_hours:24};
const saved = [];
function render() {cursor=0; return SourceSettingsForm({source, onSaved:value=>saved.push(value)});}
function nodes(tree) {if (!tree || typeof tree !== 'object') return []; return [tree,...React.Children.toArray(tree.props?.children).flatMap(nodes)];}
function find(tree,type) {return nodes(tree).find(node=>node.type===type);}
async function settle() {await Promise.resolve(); await Promise.resolve();}

(async () => {
  const calls=[];
  global.fetch = async (url,options) => {
    calls.push({url,options});
    return new Response(JSON.stringify(url.endsWith('/csrf/') ? {csrfToken:'test-csrf'} : source), {status:200});
  };
  await updateDataSourceSettings(42,{enabled:false,refresh_interval_hours:null});
  assert.equal(calls[1].url,'/api/v1/admin/sources/42/');
  assert.equal(calls[1].options.method,'PATCH');
  assert.equal(calls[1].options.headers.get('X-CSRFToken'),'test-csrf');
  assert.equal(calls[1].options.credentials,'same-origin');
  assert.deepEqual(JSON.parse(calls[1].options.body),{enabled:false,refresh_interval_hours:null});

  let tree=render();
  const interval=nodes(tree).find(node=>node.type==='input' && node.props.type==='number');
  assert.equal(interval.props.min,1); assert.equal(interval.props.max,8760);
  interval.props.onChange({target:{value:''}}); tree=render();
  const form=find(tree,'form'), event={preventDefault(){}};
  form.props.onSubmit(event); form.props.onSubmit(event);
  assert.equal(submitted.length,1,'Synchronous repeated submissions must not duplicate PATCH');
  assert.deepEqual(submitted[0].args,[42,{enabled:true,refresh_interval_hours:null}]);
  assert.equal(find(render(),'button').props.disabled,true);
  submitted[0].resolve({...source,refresh_interval_hours:null}); await settle();
  assert.equal(saved.length,1); assert.equal(find(render(),'button').props.disabled,false);
  assert.ok(nodes(render()).some(node=>node.props.role==='status'));

  find(render(),'form').props.onSubmit(event);
  submitted[1].reject(new ApiError('权限不足','PERMISSION_DENIED',null,null,403)); await settle();
  assert.ok(nodes(render()).some(node=>node.props.role==='alert' && node.props.children==='权限不足'));

  find(render(),'form').props.onSubmit(event);
  cleanups.filter(Boolean).forEach(cleanup=>cleanup()); const before=writes;
  submitted[2].resolve(source); await settle();
  assert.equal(writes,before,'Late completion must not update unmounted form');
  assert.equal(saved.length,1);
  assert.ok(renderToStaticMarkup(React.createElement(PageLoading)).includes('role="status"'));
  const boundary=new PageLoadBoundary({children:null});
  boundary.state=PageLoadBoundary.getDerivedStateFromError(new Error('synthetic chunk failure'));
  const html=renderToStaticMarkup(boundary.render());
  assert.ok(html.includes('role="alert"') && html.includes('刷新页面') && html.includes('返回首页'));
  console.log('PASS: settings PATCH/CSRF, manual-only config, duplicate submit, errors/unmount, loading and chunk recovery.');
})().catch(error=>{console.error(error.stack); process.exitCode=1;});
