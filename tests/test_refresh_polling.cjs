const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/build_site.py'), 'utf8');
const snippet = source.slice(source.indexOf('let checkingForUpdates = false;'),
  source.indexOf('// Simulate one best-of-N series'));
let reloads = 0, requests = 0;
let metadata = {last_updated: 'original'};
let httpOk = true;
const intervals = [], events = {};
const context = vm.createContext({
  D: {refresh: {last_updated: 'original'}},
  document: {hidden: false, addEventListener: (name, fn) => {events[name] = fn;}},
  window: {location: {reload: () => reloads++}, addEventListener: (name, fn) => {events[name] = fn;}},
  fetch: async (url, options) => {
    requests++;
    assert.equal(url, 'refresh_meta.json');
    assert.equal(options.cache, 'no-store');
    return {ok: httpOk, json: async () => metadata};
  },
  setInterval: (fn, delay) => intervals.push({fn, delay}),
});

(async () => {
  vm.runInContext(snippet, context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(reloads, 0, 'unchanged data should not reload');
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
