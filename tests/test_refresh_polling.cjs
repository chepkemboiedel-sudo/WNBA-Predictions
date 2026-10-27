const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/app_features.py'), 'utf8');
const snippet = source.split('POLL_JS = r"""')[1].split('"""')[0];
let reloads = 0, requests = 0;
let metadata = {last_updated: 'original'};
let httpOk = true;
const intervals = [], events = {};
const context = vm.createContext({
  document: {hidden: false, addEventListener: (name, fn) => {events[name] = fn;}},
  window: {__WNBA__: {refresh: {last_updated:'original'}}, WNBAFeatures:{updateHealth: report=>{context.report=report;}}, location: {reload: () => reloads++}, addEventListener: (name, fn) => {events[name] = fn;}},
  fetch: async (url, options) => {
    requests++;
    assert.ok(['/refresh_meta.json','/refresh_health.json'].includes(url));
    assert.equal(options.cache, 'no-store');
    return {ok: httpOk, json: async () => url==='/refresh_meta.json'?metadata:{status:'failed',message:'Saved forecast retained'}};
  },
  setInterval: (fn, delay) => intervals.push({fn, delay}),
});

(async () => {
  vm.runInContext(snippet, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(reloads, 0, 'unchanged data should not reload');
  assert.equal(context.report.status,'failed','failed refreshes should update health even without a new forecast');
  assert.equal(intervals[0].delay, 60000, 'open tabs should check every minute');
  metadata = {last_updated: 'new successful run'};
  await intervals[0].fn();
  assert.equal(reloads, 1, 'newly published forecasts should reload');
  httpOk = false;
  await events.focus();
  assert.equal(reloads, 1, 'failed checks should keep the current forecast');
  context.document.hidden = true;
  const before = requests;
  await intervals[0].fn();
  assert.equal(requests, before, 'hidden tabs should wait until visible');
  assert.equal(typeof events.visibilitychange, 'function');
  console.log('Refresh polling checks passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
