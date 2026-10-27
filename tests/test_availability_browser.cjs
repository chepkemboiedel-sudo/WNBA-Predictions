const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/build_site.py'),'utf8');
const snippet=source.slice(source.indexOf('let applyAvailability ='),source.indexOf('// ---- aggregate Monte Carlo'));
const probabilities={'A|B|0':1,'A|B|1':1};
const context=vm.createContext({
  D:{availability:{apply_adjustments:true},prob_base:probabilities,prob_availability:probabilities,prob_next:{'A|B|0':0},observed:{'A|B':{hw:3,lw:2}}},
  PROB:probabilities,
  FMT:{FINALS:[1,1,0,0,1,0,1]},seedIdx:team=>team==='A'?0:1,
  Math:Object.assign(Object.create(Math),{random:()=>.5}),
});
vm.runInContext(snippet,context);
assert.equal(vm.runInContext('applyAvailability',context),false,'fresh player data must not enable the optional model by default');
const defaultResult=vm.runInContext('simSeries("A","B","FINALS")',context);
assert.equal(defaultResult.lw,2,'first simulation must use score-only probabilities');
vm.runInContext('applyAvailability=true',context);
const adjusted=vm.runInContext('simSeries("A","B","FINALS")',context);
assert.equal(adjusted.winner,'A');assert.equal(adjusted.lw,3,'one-game absence must affect game six only');
vm.runInContext('applyAvailability=false',context);
const baseline=vm.runInContext('simSeries("A","B","FINALS")',context);
assert.equal(baseline.hw,4);assert.equal(baseline.lw,2,'score-only toggle must use baseline probabilities');
assert.equal(context.D.observed['A|B'].hw,3,'simulations must not rewrite completed results');
const handlers={};
const toggle={checked:true,addEventListener:(name,fn)=>{handlers[name]=fn;}};
const board={textContent:''}, status={textContent:''};
context.document={getElementById:id=>({'use-availability':toggle,'board-model':board,'manystatus':status}[id])};
context.reset=()=>{};
context.D.published_baseline={reach:{A:100},champ:{A:70}};
context.updateLeaderboard=agg=>{context.lastBoard=agg;};
const handler=source.slice(source.indexOf('const availabilityToggle='),source.indexOf('\n"""',source.indexOf('const availabilityToggle=')));
vm.runInContext(handler,context);
assert.equal(toggle.checked,false,'browser-restored checkbox state must reset to off');
toggle.checked=true;handlers.change({target:toggle});
assert.equal(vm.runInContext('applyAvailability',context),true,'explicit opt-in must work');
assert.equal(context.lastBoard,context.D.published_baseline,'model changes must restore published odds');
toggle.checked=false;handlers.change({target:toggle});
assert.equal(vm.runInContext('applyAvailability',context),false);
assert.equal(board.textContent,'Published score-only forecast');
context.D.availability.apply_adjustments=false;
toggle.checked=true;handlers.change({target:toggle});
assert.equal(vm.runInContext('applyAvailability',context),false,'unverified player data must not be enabled');
const input=source.match(/<input id="use-availability"[^>]+>/)[0];
assert(!input.includes('checked'),'rendered optional toggle must start unchecked');
console.log('Browser availability and baseline-toggle checks passed.');
