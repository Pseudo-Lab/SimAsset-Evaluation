import test from 'node:test';
import assert from 'node:assert/strict';
import {filterRuns,seriesSegments,keyMetrics,format} from '../src/simasset_review/static/view-model.mjs';

test('execution success never implies human approval and skipped is not an error',()=>{
  const runs=[
    {run_id:'a',asset:'cup',test_type:'probe',condition:'decomposed',execution_status:'completed',judgments:0},
    {run_id:'b',asset:'cylinder',test_type:'probe',execution_status:'skipped',judgments:0},
    {run_id:'c',asset:'invalid',test_type:'incline',execution_status:'error',judgments:1},
  ];
  assert.deepEqual(filterRuns(runs,{queue:'unreviewed'}).map(r=>r.run_id),['a','b']);
  assert.deepEqual(filterRuns(runs,{queue:'error'}).map(r=>r.run_id),['c']);
  assert.deepEqual(filterRuns(runs,{search:'볼록 분해',test:'probe'}).map(r=>r.run_id),['a']);
  assert.deepEqual(filterRuns(runs,{search:'missing'}),[]);
});
test('missing hash and real versions stay distinct across combined filters',()=>{
  const runs=[{asset:'cup',asset_version:null,origin:'fixture'},{asset:'cup',asset_version:'abc',origin:'local_reproduction'}];
  assert.equal(filterRuns(runs,{asset:'cup',version:'__missing__',origin:'fixture'}).length,1);
  assert.equal(filterRuns(runs,{version:'abc',origin:'fixture'}).length,0);
});
test('chart gaps are neither zero-filled nor joined by an invented line',()=>{
  const points=[{t:0,depth:null},{t:1,depth:0},{t:2,depth:3},{t:3,depth:null},{t:4,depth:5},{t:5,depth:NaN},{t:6,depth:Infinity}];
  assert.deepEqual(seriesSegments(points,'depth'),[[points[1],points[2]],[points[4]]]);
  assert.deepEqual(seriesSegments([{t:NaN,depth:3}],'depth'),[]);
});
test('headline values keep SI conversion, true zero and unmeasured distinct',()=>{
  const result=keyMetrics({test_type:'probe',metrics:[
    {metric_name:'probe_depth',metric_value:0.087,valid:true},
    {metric_name:'peak_pen',metric_value:0,valid:true},
    {metric_name:'ball_settle_time',metric_value:0,valid:false,invalid_reason:'not settled'},
    {metric_name:'probe_pass',metric_value:1,valid:true},
  ]});
  assert.deepEqual(result.map(m=>[m.value,m.unit]),[[87,'mm'],[0,'mm'],[null,'']]);
  assert.equal(result[2].reason,'not settled');
  assert.equal(format(null),'—');assert.equal(format(0),'0');
  assert.notEqual(format(.00000006),'0');
  assert.equal(result.some(m=>m.key==='probe_pass'),false);
});
