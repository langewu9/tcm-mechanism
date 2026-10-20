// Run the maintenance script against a tiny DOM and mocked fetch: never contact services.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

function output() {
  const node = {textContent: ''};
  Object.defineProperty(node, 'innerHTML', {set() {throw new Error('Do not render service data as HTML');}});
  return node;
}
const refresh = {dataset: {}, listeners: {}, addEventListener(name, callback) {this.listeners[name] = callback;}};
const local = {...refresh, listeners: {}};
const status = output(), error = output();
const forms = ['qwen','disease','herb','component','chembl','intersection','compare','scientist'].map(target => {
  const checkbox = ['qwen','chembl'].includes(target) ? {checked:false} : null;
  const button = {dataset: target === 'scientist' ? {unavailable:'true'} : {}};
  const result = output();
  return {
    dataset: {check:target, localCheck:['disease','herb','component','intersection','compare'].includes(target) ? 'true' : 'false'},
    listeners: {}, checkbox, button, result,
    addEventListener(name, callback) {this.listeners[name] = callback;},
    querySelector(selector) {
      if (selector === '[name="consent"]') return checkbox;
      if (selector === '[name="csrfmiddlewaretoken"]') return {value:'synthetic-admin-csrf'};
      if (selector === '[data-result]') return result;
      if (selector === '[data-unavailable="true"]') return target === 'scientist' ? button : null;
      throw new Error(`Unexpected selector ${selector}`);
    },
  };
});
const root = {
  dataset: {statusUrl:'/api/v1/admin/integrations/status/', testUrl:'/api/v1/admin/integrations/test/'},
  querySelectorAll(selector) {
    if (selector === 'form[data-check]') return forms;
    if (selector === 'button') return [refresh,local,...forms.map(form=>form.button)];
    throw new Error(`Unexpected selector ${selector}`);
  },
};
const nodes = {'maintenance-monitor':root,'monitor-refresh':refresh,'monitor-local':local,'monitor-status':status,'monitor-error':error};
let calls = [], failure = false;
const fetch = async (url, options) => {
  calls.push({url,options});
  if (failure) throw new Error('synthetic offline');
  return {ok:true,json:async()=>options.method === 'POST' ? {result:{ok:true,data:'<script>synthetic text only</script>'}} : {services:{health:{ok:true}}}};
};
const script = fs.readFileSync(path.resolve(__dirname,'../../python_app/apps/core/static/core/integration_monitor.js'),'utf8');
vm.runInNewContext(script, {document:{getElementById:id=>nodes[id]},fetch});
const submit = form => form.listeners.submit({preventDefault(){}});

(async () => {
  await new Promise(setImmediate);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,root.dataset.statusUrl);
  assert.equal(calls[0].options.method,undefined,'Opening the page does not run any test');
  calls = [];
  await local.listeners.click();
  assert.deepEqual(calls.map(call=>JSON.parse(call.options.body).target),['disease','herb','component','intersection','compare']);
  for (const call of calls) {
    assert.equal(call.options.credentials,'same-origin');
    assert.equal(call.options.headers['X-CSRFToken'],'synthetic-admin-csrf');
    assert.equal(JSON.parse(call.options.body).consent,false);
  }
  for (const target of ['qwen','chembl']) {
    const form = forms.find(item=>item.dataset.check === target);
    calls = [];
    await submit(form);
    assert.equal(calls.length,0,'A connection test needs fresh consent');
    form.checkbox.checked = true;
    await submit(form);
    assert.deepEqual(JSON.parse(calls[0].options.body),{target,consent:true});
    assert.equal(form.checkbox.checked,false,'Consent is consumed after success');
    assert.ok(form.result.textContent.includes('<script>synthetic text only</script>'));
    calls = [];
    failure = true;
    form.checkbox.checked = true;
    await submit(form);
    assert.equal(form.checkbox.checked,false,'Consent is consumed after failure');
    failure = false;
  }
  calls = [];
  await submit(forms.find(item=>item.dataset.check === 'scientist'));
  assert.equal(calls.length,0);
  assert.equal(forms.find(item=>item.dataset.check === 'scientist').button.disabled,true);
  console.log('PASS: admin monitor auto-load is read-only; local batch excludes model/external checks; session/CSRF; one-shot consent; plain-text results; unavailable checks.');
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
