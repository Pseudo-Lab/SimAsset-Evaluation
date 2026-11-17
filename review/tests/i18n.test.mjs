import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {english,t} from '../src/simasset_review/static/i18n.mjs';
import {codePointLength,invalidUnicode,searchText} from '../src/simasset_review/static/unicode.mjs';
import {filterRuns} from '../src/simasset_review/static/view-model.mjs';

test('Unicode limits count code points rather than UTF-16 units',()=>{
  assert.equal(codePointLength('🧪'.repeat(5000)),5000);
  assert.equal(codePointLength('가éع中🧪'),5);
  assert.equal(codePointLength('👩‍💻'),3);
  assert.equal(invalidUnicode('👩‍💻 한글 العربية'),false);
  for(const text of ['\0','\ud800','\udfff'])assert.equal(invalidUnicode(text),true);
});
test('English and Korean labels preserve interpolation values',()=>{
  assert.equal(t('판정 {count}',{count:3},'en'),'3 assessments');
  assert.equal(t('판정 {count}',{count:3},'ko'),'판정 3');
  assert.equal(t('실행 오류 · {reason}',{reason:'原文 오류'},'en'),'Execution error · 原文 오류');
  assert.equal(t('source_{original}',{},'en'),'source_{original}');
});
test('all literal Korean UI messages have an English entry',async()=>{
  const source=await readFile(new URL('../src/simasset_review/static/app.js',import.meta.url),'utf8');
  const keys=[...source.matchAll(/'([^'\n]*[가-힣][^'\n]*)'/g)].map(m=>m[1].replace(/\\n/g,'\n'));
  assert.deepEqual([...new Set(keys)].filter(key=>!(key in english)),[]);
});
test('search accepts either UI language and canonically equivalent Korean',()=>{
  const row={asset:'한글',test_type:'probe',condition:'decomposed',judgments:0};
  for(const search of ['한글'.normalize('NFD'),'cavity','convex','홈 검사'])assert.equal(filterRuns([row],{search}).length,1);
  assert.equal(searchText('Cafe\u0301'),searchText('CAFÉ'));
});
