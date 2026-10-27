const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const root=path.join(__dirname,'..');
const result=JSON.parse(fs.readFileSync(path.join(root,'outputs/availability_backtest/results.json'),'utf8'));
const source=fs.readFileSync(path.join(root,'src/backtest_ui.py'),'utf8').split('JS = r"""')[1].split('"""')[0];
const elements={};
for(const id of ['sample','n','changed','picks','metrics','finding','acc-base','acc-adj','bar-base','bar-adj','context']) elements['backtest-'+id]={value:'',textContent:'',innerHTML:'',style:{},addEventListener:(name,fn)=>{elements['backtest-sample'].change=fn;}};
const context=vm.createContext({window:{__WNBA__:{backtest:result}},document:{getElementById:id=>elements[id]}});
vm.runInContext(source,context);
assert.equal(elements['backtest-sample'].value,'verified_report_games');
assert.equal(elements['backtest-n'].textContent,'202');
assert.equal(elements['backtest-acc-base'].textContent,'72.28%');
assert.equal(elements['backtest-acc-adj'].textContent,'72.28%');
assert(elements['backtest-metrics'].innerHTML.includes('0.556734'));
assert(elements['backtest-metrics'].innerHTML.includes('0.555921'));
assert(elements['backtest-finding'].textContent.includes('No clear improvement'));
for(const key of ['all_eligible_games','changed_games','regular_season','playoffs']){
  elements['backtest-sample'].value=key;elements['backtest-sample'].change();
  assert.equal(elements['backtest-n'].textContent,String(result.groups[key].n));
  assert.equal(elements['backtest-bar-base'].style.width,(result.groups[key].metrics.accuracy.baseline*100).toFixed(2)+'%');
}
assert(elements['backtest-finding'].textContent.includes('Small sample: 5 games'));
assert(elements['backtest-context'].textContent.includes('cannot establish'));
assert(!('applyAvailability' in context),'comparing backtest samples must not enable injury forecasts');
console.log('Backtest sample switching, metrics, and uncertainty checks passed.');
