const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/build_site.py'),'utf8');
const snippet=source.slice(source.indexOf('let applyAvailability ='),source.indexOf('// ---- aggregate Monte Carlo'));
const probabilities={'A|B|0':1,'A|B|1':1};
const context=vm.createContext({
  D:{availability:{apply_adjustments:true},prob_base:probabilities,prob_next:{'A|B|0':0},observed:{'A|B':{hw:3,lw:2}}},
  PROB:probabilities,
  FMT:{FINALS:[1,1,0,0,1,0,1]},seedIdx:team=>team==='A'?0:1,
  Math:Object.assign(Object.create(Math),{random:()=>.5}),
});
vm.runInContext(snippet,context);
const adjusted=vm.runInContext('simSeries("A","B","FINALS")',context);
assert.equal(adjusted.winner,'A');assert.equal(adjusted.lw,3,'one-game absence must affect game six only');
vm.runInContext('applyAvailability=false',context);
const baseline=vm.runInContext('simSeries("A","B","FINALS")',context);
assert.equal(baseline.hw,4);assert.equal(baseline.lw,2,'score-only toggle must use baseline probabilities');
assert.equal(context.D.observed['A|B'].hw,3,'simulations must not rewrite completed results');
console.log('Browser availability and baseline-toggle checks passed.');
