import test from 'node:test';
import assert from 'node:assert/strict';
import {chartDomain,observationAt,comparisonOptions,clipTime} from '../src/simasset_review/static/comparison.mjs';

test('compared charts use a shared range including negative values and true zero',()=>{
  const a=[{t:0,v:0},{t:1,v:2},{t:2,v:null}],b=[{t:.5,v:-5},{t:4,v:20}];
  const domain=chartDomain([a,b],'v');
  assert.equal(domain.start,0);assert.equal(domain.end,4);
  assert(domain.min<-5);assert(domain.max>20);
  assert.deepEqual(chartDomain([a,b],'v'),chartDomain([b,a],'v'));
  assert.equal(chartDomain([[{t:0,v:null},{t:1,v:NaN}]],'v').hasValues,false);
});
test('shared cursor keeps missing observations and out-of-range periods empty',()=>{
  const points=[{t:0,v:0},{t:1,v:null},{t:2,v:3}];
  assert.deepEqual(observationAt(points,'v',0),{t:0,value:0});
  assert.deepEqual(observationAt(points,'v',.9),{t:1,value:null});
  assert.equal(observationAt(points,'v',3),null);
  assert.equal(observationAt(points,'v',-1),null);
  assert.equal(observationAt([],'v',0),null);
});
test('comparison preserves run identity and only pairs the same test type',()=>{
  const current={run_id:'a',asset:'cup',test_type:'probe',config:{condition:'decomposed'}};
  const runs=[
    {...current,condition:'decomposed'},
    {run_id:'b',asset:'bowl',test_type:'probe',condition:'decomposed',videos:1},
    {run_id:'c',asset:'cup',test_type:'incline',condition:'ramp45deg',videos:1},
    {run_id:'d',asset:'cup',test_type:'probe',condition:'single_hull',videos:1},
  ];
  assert.deepEqual(comparisonOptions(runs,current).map(r=>r.run_id),['d','b']);
  assert.equal(runs.length,4);
});
test('shared video seek uses clip seconds and clamps at each clip end',()=>{
  assert.equal(clipTime(.9,.733),.733);assert.equal(clipTime(.9,1.2),.9);
  assert.equal(clipTime(-1,1.2),0);assert.equal(clipTime(0,1.2),0);
  for(const duration of [0,NaN,Infinity])assert.equal(clipTime(.5,duration),null);
});
