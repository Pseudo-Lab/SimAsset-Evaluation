const $=s=>document.querySelector(s);
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const originLabel={team_shared:'팀 공유 결과',local_reproduction:'로컬 재현 결과',fixture:'기능 시험 데이터'};
const outcomes={pass:'통과',fail:'실패',inconclusive:'보류'};
const versionKey=r=>r.asset_version||'__missing__';
const versionText=(v,n=12)=>!v||v==='__missing__'?'해시 미기록':v.slice(0,n);
// Keep each run's form context when saving or returning from another run.
const judgmentDrafts=new Map();
let allRuns=[],active=/^#[0-9a-f-]{36}$/.test(location.hash)?location.hash.slice(1):null,detail=null,loading=0;
async function request(path,options={}){const r=await fetch(path,options);let d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'입력값을 확인해주세요.');return d;}
function notice(text){$('#notice').textContent=text;$('#notice').classList.add('show');setTimeout(()=>$('#notice').classList.remove('show'),6000);}
function optionFilter(id,values,label){const s=$(id),old=s.value;s.replaceChildren(new Option(label,''));[...new Set(values)].sort().forEach(v=>s.add(new Option(id==='#version'?versionText(v):v,v)));s.value=old;}
async function refresh(){try{allRuns=[];for(let offset=0;;offset+=1000){const page=await request('/api/runs?offset='+offset);allRuns.push(...page);if(page.length<1000)break;}optionFilter('#asset',allRuns.map(r=>r.asset),'전체 에셋');optionFilter('#test',allRuns.map(r=>r.test_type),'전체 검사');optionFilter('#version',allRuns.map(versionKey),'전체 버전');$('#stats').replaceChildren();for(const [v,l]of [[allRuns.length,'저장된 실행'],[new Set(allRuns.map(r=>r.asset)).size,'에셋 이름'],[allRuns.filter(r=>r.judgments>0).length,'판정이 있는 실행']]){let e=node('div');e.append(node('b',String(v)),node('span',l));$('#stats').append(e);}renderList();await renderImports();if(active)await showRun(active);}catch(e){notice(e.message);}}
function renderList(){const rows=allRuns.filter(r=>(!$('#asset').value||r.asset===$('#asset').value)&&(!$('#test').value||r.test_type===$('#test').value)&&(!$('#version').value||versionKey(r)===$('#version').value)&&(!$('#origin').value||r.origin===$('#origin').value));$('#run-list').replaceChildren();for(const r of rows){let b=node('button',undefined,'run'+(r.run_id===active?' active':''));b.append(node('strong',r.asset),node('small',`${r.test_type} · ${r.condition||"조건 미기록"} · seed ${r.seed} · ${versionText(r.asset_version,8)}`),node('small',`${originLabel[r.origin]||r.origin} · ${r.videos?'영상 있음':'수치 결과'}`),node('small',new Date(r.imported_at).toLocaleString('ko-KR')),node('span',r.source_status,'badge'+(r.execution_status==='error'?' error':'')));b.dataset.runId=r.run_id;b.onclick=()=>showRun(r.run_id);$('#run-list').append(b);}if(!rows.length)$('#run-list').append(node('p','조건에 맞는 실행이 없습니다.','hint'));}
function format(v){if(v===null)return '—';if(typeof v!=='number')return v;if(v!==0&&Math.abs(v)<.0001)return v.toExponential(3);return Number(v.toPrecision(6)).toLocaleString('ko-KR',{maximumSignificantDigits:6});}
function chart(points,key,label){const totalPoints=points.length;points=points.filter(p=>Number.isFinite(p[key]));const wrap=node('div',undefined,'chart');wrap.append(node('h3',label));if(!points.length){wrap.append(node('p','시계열이 없습니다.','hint'));return wrap;}const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 440 155');svg.setAttribute('role','img');svg.setAttribute('aria-label',label+' 시계열');const lo=points.reduce((a,p)=>Math.min(a,p[key]),Infinity),hi=points.reduce((a,p)=>Math.max(a,p[key]),-Infinity),tmax=points.at(-1).t||1,span=hi-lo||1;const poly=document.createElementNS(ns,'polyline');poly.setAttribute('points',points.map(p=>`${45+p.t/tmax*380},${118-(p[key]-lo)/span*100}`).join(' '));poly.setAttribute('fill','none');poly.setAttribute('stroke','#247a5f');poly.setAttribute('stroke-width','1.6');svg.append(poly);for(const [x,y,t]of [[2,20,format(hi)+' mm'],[2,121,format(lo)+' mm'],[44,146,'0 s'],[390,146,format(tmax)+' s']]){let te=document.createElementNS(ns,'text');te.setAttribute('x',x);te.setAttribute('y',y);te.textContent=t;svg.append(te);}wrap.append(svg,node('small',`최대 ${format(hi)} mm · 유효 ${points.length.toLocaleString()} / 전체 ${totalPoints.toLocaleString()}개 관측값`));return wrap;}
async function showRun(id){const ticket=++loading;try{const [d,series]=await Promise.all([request('/api/runs/'+id),request('/api/runs/'+id+'/series')]);const probeSeries=d.test_type==='probe'?await request('/api/runs/'+id+'/series?channel=probe'):null;if(ticket!==loading)return;active=id;detail=d;history.replaceState(null,'','#'+id);renderList();const root=$('#detail');root.replaceChildren();const head=node('div',undefined,'detail-head'),identity=node('div',undefined,'identity');identity.append(node('h2',d.asset),node('small',`${d.test_type} · ${d.config.condition||"조건 미기록"} · seed ${d.seed} · MuJoCo ${d.engine_version} · ${d.source_namespace}`));head.append(identity,node('span',originLabel[d.origin],'badge'));root.append(head);if(d.execution_status==='skipped')root.append(node('p','이 실행은 검사 대상이 아닙니다. 누락이나 실패와 구분해 보관합니다.','warning'));let columns=node('div',undefined,'columns'),left=node('section');const videos=d.artifacts.filter(a=>a.artifact_type==='video'),media=node('div');if(videos.length){const tabs=node('div',undefined,'media-switch'),video=document.createElement('video');video.controls=true;video.preload='metadata';video.setAttribute('aria-label','검사 영상');videos.forEach((v,i)=>{let b=node('button',v.filename);b.onclick=()=>{video.src='/api/artifacts/'+v.artifact_id;tabs.querySelectorAll('button').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');};tabs.append(b);if(i===0){video.src='/api/artifacts/'+v.artifact_id;b.classList.add('selected');}});media.append(tabs,video);}else media.append(node('div',d.execution_status==='skipped'?'적용 불가 결과에는 영상과 시계열을 생성하지 않습니다.':'이 실행에는 영상이 없습니다. 수치만으로 확인할 수 없는 내용은 보류할 수 있습니다.','warning'));left.append(media);if(series.points.length)left.append(chart(series.points,'max_pen','접촉 관통 깊이'),chart(series.points,'z','질량중심 높이'));else if(d.execution_status!=='skipped')left.append(node('p','이 실행에는 시계열이 없습니다.','hint'));if(probeSeries?.points.length){left.append(chart(probeSeries.points,'depth_mm','공의 진입 깊이'),node('p','공을 놓기 전의 빈 관측값은 그래프에서 제외합니다. probe_pass는 코드의 측정 결과이며 사람 판정과 별도로 보존합니다.','hint'));}columns.append(left,judgmentForm(d));root.append(columns);
 const table=node('table',undefined,'metric-table'),tr=node('tr');['측정 항목','저장값 · SI','원본 값'].forEach(t=>tr.append(node('th',t)));table.append(tr);d.metrics.forEach(m=>{let r=node('tr');r.append(node('td',m.metric_name),node('td',m.valid?`${format(m.metric_value??m.metric_text)} ${m.metric_value===null?'':m.unit}`:'측정 불가'),node('td',`${m.raw_value} ${m.raw_unit}`));table.append(r);});const tw=node('div',undefined,'table-wrap');tw.append(node('h3','측정값'),table);root.append(tw);
 const hist=node('section');hist.append(node('h3','판정 이력'));if(!d.judgments.length)hist.append(node('p','아직 판정이 없습니다.','hint'));d.judgments.forEach(j=>{let h=node('article',undefined,'history');h.append(node('b',`${outcomes[j.outcome]} · ${j.reviewer}${j.current?'':' · 이전 판정'}`),node('p',j.rationale),node('small',`${j.criterion_key} · ${j.protocol_version} · ${new Date(j.reviewed_at).toLocaleString('ko-KR')}`));if(j.current){const edit=node('button','이 판정 수정');edit.type='button';edit.onclick=async()=>{judgmentDrafts.set(d.run_id,{reviewer:j.reviewer,outcome:j.outcome,rationale:j.rationale,criterion_key:j.criterion_key,protocol_version:j.protocol_version,evidence_ids:j.evidence_ids||[]});await showRun(d.run_id);$('#detail [name=rationale]')?.focus();};h.append(edit);}hist.append(h);});root.append(hist);
 const meta=node('details');meta.append(node('summary','검사 조건과 자료 정보'),node('p',`원본 상태: ${d.source_status} / 처리 상태: ${d.execution_status}`,'hint'));d.warnings.forEach(t=>meta.append(node('p',t,'hint')));meta.append(node('pre',JSON.stringify(d.raw_meta,null,2)));d.artifacts.forEach(a=>{let p=node('p'),link=node('a',a.filename);link.href='/api/artifacts/'+a.artifact_id;link.target='_blank';link.rel='noopener';p.append(link,node('small',` · ${(a.size_bytes/1024).toFixed(1)} KiB`));meta.append(p);});root.append(meta);
 }catch(e){notice(e.message);}}
function judgmentForm(d){
 const draft=judgmentDrafts.get(d.run_id)||{};
 const f=node('form',undefined,'verdict-card');
 f.append(node('h3','사람 판정'),node('p','자동 실행 상태와 별도로 기록합니다.','hint'));
 const name=node('label','평가자'),input=node('input');
 input.name='reviewer';input.required=true;input.maxLength=100;
 input.value=draft.reviewer??localStorage.getItem('simasset-reviewer')??'';
 input.placeholder='이름';name.append(input);
 const radios=node('div',undefined,'verdicts');
 Object.entries(outcomes).forEach(([v,t])=>{let l=node('label'),r=node('input');r.type='radio';r.name='outcome';r.value=v;r.checked=v===(draft.outcome||'inconclusive');l.append(r,node('span',t));radios.append(l);});
 const reason=node('label','판정 이유와 추가 확인 사항'),ta=node('textarea');
 ta.name='rationale';ta.required=true;ta.maxLength=5000;ta.value=draft.rationale||'';
 ta.placeholder='어떤 장면이나 측정값을 근거로 판단했나요?';reason.append(ta);
 const itemLabel=node('label','검토 항목'),item=node('select');item.setAttribute('aria-label','검토 항목');
 [['physical_behavior','전체 물리 거동'],['penetration','관통'],['stability','안정성'],['motion','운동 모드'],['cavity','홈·구멍 보존']].forEach(([v,t])=>item.add(new Option(t,v)));
 item.value=draft.criterion_key||'physical_behavior';itemLabel.append(item);
 const criterion=node('label','판정 기준 버전'),ci=node('input');
 ci.value=draft.protocol_version??'review-draft-1';ci.required=true;ci.maxLength=100;criterion.append(ci);
 const evidence=node('details',undefined,'evidence');evidence.append(node('summary','판정에 사용한 파일 선택'));
 d.artifacts.filter(a=>['video','screenshot','trajectory'].includes(a.artifact_type)).forEach(a=>{let l=node('label'),c=node('input');c.type='checkbox';c.name='evidence';c.value=a.artifact_id;c.checked=(draft.evidence_ids||[]).includes(a.artifact_id);l.append(c,node('span',a.filename));evidence.append(l);});
 const submit=node('button','판정 저장','primary'),context=node('p',undefined,'hint');submit.type='submit';
 const currentJudgment=()=>d.judgments.find(j=>j.current&&j.reviewer===input.value.trim()&&j.protocol_version===ci.value.trim()&&j.criterion_key===item.value);
 const remember=()=>{
   const value={reviewer:input.value,outcome:new FormData(f).get('outcome'),rationale:ta.value,criterion_key:item.value,protocol_version:ci.value,evidence_ids:[...f.querySelectorAll('[name=evidence]:checked')].map(x=>x.value)};
   judgmentDrafts.set(d.run_id,value);
   context.textContent=currentJudgment()?'이 평가자·항목·기준의 현재 판정을 수정합니다. 이전 판정도 보존합니다.':'새 판정을 기록합니다. 이전 판정을 수정하려면 이력의 “이 판정 수정”을 선택하세요.';
   return value;
 };
 f.append(name,itemLabel,radios,reason,criterion,evidence,submit,context);
 f.addEventListener('input',remember);f.addEventListener('change',remember);remember();
 f.onsubmit=async e=>{
   e.preventDefault();submit.disabled=true;
   const value=remember(),reviewer=value.reviewer.trim(),version=value.protocol_version.trim(),current=currentJudgment();
   try{
     await request('/api/runs/'+d.run_id+'/judgments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...value,reviewer,protocol_version:version,supersedes_judgment_id:current?.judgment_id||null})});
     judgmentDrafts.set(d.run_id,{...value,reviewer,protocol_version:version});
     localStorage.setItem('simasset-reviewer',reviewer);notice('판정과 근거를 저장했습니다.');await refresh();
   }catch(err){notice(err.message);submit.disabled=false;}
 };
 return f;
}
async function renderImports(){const rows=await request('/api/imports');$('#import-count').textContent=`· 최근 ${rows.length}건`;$('#imports').replaceChildren();rows.forEach(r=>{let e=node('article');e.append(node('b',`${r.status} · ${r.source_namespace}`),node('p',r.diagnostics.message||r.diagnostics.code||'파일 검증 완료'),node('small',new Date(r.created_at).toLocaleString('ko-KR')));$('#imports').append(e);});}
['#asset','#test','#version','#origin'].forEach(id=>$(id).onchange=renderList);$('#refresh').onclick=refresh;refresh();
