import {originLabel,outcomes,executionLabel,testLabel,conditionLabel,versionKey,versionText,format,filterRuns,seriesSegments,keyMetrics} from './view-model.mjs';
import {m,t,join,dateText,setText,attribute,initializeLanguage} from './i18n.mjs';
import {codePointLength,invalidUnicode} from './unicode.mjs';
initializeLanguage();
const $=selector=>document.querySelector(selector);
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)setText(e,text);if(cls)e.className=cls;return e;};
const ui=(tag,key,cls)=>node(tag,typeof key==='function'?key:m(key),cls);
const button=(text,action,cls)=>{const b=ui('button',text,cls);b.type='button';b.onclick=action;return b;};
const badge=(text,status='')=>ui('span',text,'badge '+status);
const date=dateText;
const option=(label,value)=>{const o=new Option('',value);setText(o,label);return o;};
const judgmentDrafts=new Map(), dirtyRuns=new Set();
let allRuns=[],active=/^#[0-9a-f-]{36}$/.test(location.hash)?location.hash.slice(1):null;
let loading=0,refreshTicket=0,queue='all',detailSection='metrics',noticeTimer;
function userText(tag,value){const e=node(tag,value);e.dir='auto';e.classList.add('authored-text');return e;}
function validateText(input){
  if(input.dataset.composing==='true')return;
  const value=input.value,limit=Number(input.dataset.codepointLimit);
  input.setCustomValidity(!value.trim()?t('빈 값은 저장할 수 없습니다.'):invalidUnicode(value)?t('지원하지 않는 제어 문자나 잘못된 유니코드가 있습니다.'):codePointLength(value)>limit?t('최대 {count}자까지 입력할 수 있습니다.',{count:limit}):'');
}
function multilingual(input,limit){
  input.dir='auto';input.dataset.codepointLimit=limit;
  input.addEventListener('compositionstart',()=>{input.dataset.composing='true';});
  input.addEventListener('compositionend',()=>{delete input.dataset.composing;validateText(input);});
  input.addEventListener('input',()=>validateText(input));
}
window.addEventListener('simasset-language-change',()=>document.querySelectorAll('[data-codepoint-limit]').forEach(validateText));
function savedReviewer(){try{return localStorage.getItem('simasset-reviewer')||'';}catch{return '';}}
async function request(path,options={}){
  const response=await fetch(path,options);
  const data=await response.json().catch(()=>null);
  if(!response.ok)throw Error(typeof data?.detail==='string'?data.detail:response.status===422?'입력 내용을 확인해주세요. 길이 제한이나 지원하지 않는 제어 문자가 있는지 확인해주세요.':'요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.');
  return data;
}
function notice(text,error=false){
  clearTimeout(noticeTimer);setText($('#notice span'),typeof text==='function'?text:m(text));
  $('#notice').className='notice show'+(error?' error':'');
  noticeTimer=setTimeout(()=>$('#notice').classList.remove('show'),8000);
}
$('#notice button').onclick=()=>$('#notice').classList.remove('show');
function optionFilter(id,values,label,display=v=>v){
  const select=$(id),old=select.value;select.replaceChildren(option(m(label),''));
  [...new Set(values)].sort().forEach(v=>select.add(option(display(v),v)));
  select.value=[...select.options].some(o=>o.value===old)?old:'';
}
async function refresh(){
  const ticket=++refreshTicket;$('#refresh').disabled=true;$('#refresh').setAttribute('aria-busy','true');
  try{
    const runs=[];
    for(let offset=0;;offset+=1000){const page=await request('/api/runs?offset='+offset);runs.push(...page);if(page.length<1000)break;}
    if(ticket!==refreshTicket)return;
    allRuns=runs;
    optionFilter('#asset',runs.map(r=>r.asset),'전체 에셋');optionFilter('#test',runs.map(r=>r.test_type),'전체 검사',v=>m(testLabel(v)));
    optionFilter('#version',runs.map(versionKey),'전체 버전',v=>v==='__missing__'?m('해시 미기록'):versionText(v));
    $('#stats').replaceChildren();
    for(const [value,label]of [[runs.length,'저장된 실행'],[new Set(runs.map(r=>r.asset)).size,'에셋 이름'],[runs.filter(r=>r.judgments>0).length,'판정된 실행']]){
      const stat=node('div',undefined,'stat');stat.append(node('b',String(value)),ui('span',label));$('#stats').append(stat);
    }
    renderList();
    if(active)await showRun(active);
    else if(runs.length)await showRun((runs.find(r=>r.videos>0)||runs[0]).run_id);
    else showEmpty('아직 가져온 실행이 없습니다.','결과 폴더를 가져오면 영상과 측정값이 여기에 표시됩니다.');
    await renderImports();
  }catch(error){notice(error.message,true);if(!allRuns.length)showEmpty('결과를 불러오지 못했습니다.','서버 연결을 확인한 뒤 다시 시도해주세요.',true);}
  finally{if(ticket===refreshTicket){$('#refresh').disabled=false;$('#refresh').setAttribute('aria-busy','false');}}
}
function showEmpty(title,text,retry=false){const e=node('div',undefined,'empty');e.append(node('div','◇','empty-symbol'),ui('h2',title),ui('p',text));if(retry)e.append(button('다시 불러오기',refresh));$('#detail').replaceChildren(e);}
function renderList(){
  const rows=filterRuns(allRuns,{asset:$('#asset').value,test:$('#test').value,version:$('#version').value,origin:$('#origin').value,search:$('#search').value,queue});
  $('#run-count').textContent=`${rows.length} / ${allRuns.length}`;
  const extras=Number(Boolean($('#version').value))+Number(Boolean($('#origin').value));$('#filter-count').textContent=extras?`· ${extras}`:'';
  $('#run-list').replaceChildren();
  for(const r of rows){
    const b=button('',()=>{detailSection='metrics';showRun(r.run_id);},'run'+(r.run_id===active?' active':''));
    b.dataset.runId=r.run_id;b.setAttribute('aria-current',String(r.run_id===active));
    attribute(b,'title',m('{source}\n실행 {id}\n{origin} · {date}\n{version}',{source:r.source_run_id,id:r.run_id,origin:m(originLabel[r.origin]),date:date(r.imported_at),version:r.asset_version||m('해시 미기록')}));
    const top=node('div',undefined,'run-top');top.append(node('strong',r.asset),ui('span',r.videos?'▷ 영상':'수치','run-media'));
    const bottom=node('div',undefined,'run-bottom');bottom.append(badge(executionLabel[r.execution_status]||r.source_status,r.execution_status),ui('span',r.judgments?m('판정 {count}',{count:r.judgments}):'판정 없음','review-mark'));
    b.append(top,node('small',join(m(testLabel(r.test_type)),' · ',m(conditionLabel(r.condition)))),ui('small',m('seed {seed} · 실행 {id}',{seed:r.seed,id:r.run_id.slice(0,8)})),bottom);
    $('#run-list').append(b);
  }
  if(!rows.length)$('#run-list').append(ui('p','조건에 맞는 실행이 없습니다. 필터를 초기화해보세요.','list-empty'));
}
function setQueue(value){queue=value;document.querySelectorAll('[data-queue]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.queue===value)));renderList();}
function clearFilters(){['#asset','#test','#version','#origin','#search'].forEach(id=>$(id).value='');setQueue('all');}
function metricStrip(d){
  const strip=node('dl',undefined,'key-metrics');
  keyMetrics(d).forEach(m=>{const cell=node('div',undefined,'key-metric'),value=node('dd',format(m.value,4));value.append(node('span',m.unit));cell.append(ui('dt',m.label),value);attribute(cell,'title',m.value===null?()=>t(m.reason):m.key);strip.append(cell);});
  return strip;
}
function mediaPanel(d){
  const panel=node('section',undefined,'panel'),head=node('div',undefined,'panel-heading');
  const duration=ui('small','저장된 실행');
  head.append(ui('h3','시뮬레이션 영상'),duration);panel.append(head);
  const videos=d.artifacts.filter(a=>a.artifact_type==='video').sort((a,b)=>Number(b.filename==='clip_visual.mp4')-Number(a.filename==='clip_visual.mp4'));
  if(!videos.length){
    const empty=node('div',undefined,'no-media');empty.append(node('div','◇','empty-symbol'),ui('h3',d.execution_status==='skipped'?'검사 대상이 아닙니다.':'영상이 없는 실행입니다.'),ui('p',d.execution_status==='skipped'?'이 결과에는 영상과 시계열을 생성하지 않습니다.':'수치와 원본 상태를 확인해주세요.'));
    panel.append(empty);return panel;
  }
  const tabs=node('div',undefined,'media-switch'),video=node('video'),caption=node('div',undefined,'media-caption'),filename=node('span'),link=ui('a','영상 열기 ↗');
  tabs.setAttribute('role','group');attribute(tabs,'aria-label',m('영상 표현'));
  video.controls=true;video.preload='metadata';attribute(video,'aria-label',m('검사 영상'));
  link.target='_blank';link.rel='noopener';
  const slow=button('1×',()=>{video.playbackRate=video.playbackRate===1?.25:1;slow.textContent=video.playbackRate===1?'1×':'0.25×';slow.setAttribute('aria-pressed',String(video.playbackRate!==1));},'text-button');
  attribute(slow,'aria-label',m('느리게 재생'));slow.setAttribute('aria-pressed','false');attribute(slow,'title',m('1배속 / 0.25배속'));
  const play=button('▷ 재생',()=>{if(video.paused)video.play().catch(()=>notice('영상을 재생하지 못했습니다. 원본 영상을 확인해주세요.',true));else video.pause();},'text-button');
  attribute(play,'aria-label',m('영상 재생'));
  video.addEventListener('play',()=>{setText(play,m('Ⅱ 일시정지'));attribute(play,'aria-label',m('영상 일시정지'));});
  video.addEventListener('pause',()=>{setText(play,m('▷ 재생'));attribute(play,'aria-label',m('영상 재생'));});
  const controls=node('div',undefined,'media-tools');controls.append(duration,slow,play);head.append(controls);
  caption.append(filename,link);
  const mediaError=ui('p','영상을 불러오지 못했습니다. “영상 열기”에서 원본을 확인해주세요.','warning');mediaError.hidden=true;
  video.addEventListener('error',()=>{mediaError.hidden=false;});
  const labels={'clip_visual.mp4':'외형 보기','clip_collision.mp4':'충돌 형상'};
  function select(v,b){
    const at=Number.isFinite(video.currentTime)?video.currentTime:0;
    video.pause();mediaError.hidden=true;video.src='/api/artifacts/'+v.artifact_id;
    video.onloadedmetadata=()=>{setText(duration,Number.isFinite(video.duration)?m('영상 {seconds}초',{seconds:format(video.duration,3)}):m('저장된 실행'));if(at>0&&Number.isFinite(video.duration))video.currentTime=Math.min(at,video.duration);};
    tabs.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
    filename.textContent=v.filename;link.href=video.src;
  }
  videos.forEach((v,i)=>{const b=button(labels[v.filename]||v.filename,()=>select(v,b));b.setAttribute('aria-pressed','false');tabs.append(b);if(i===0)select(v,b);});
  panel.append(tabs,video,caption,mediaError);return panel;
}
function svgNode(tag,attrs={},text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>attribute(e,k,v));if(text!==undefined)setText(e,text);return e;}
function chart(points,key,label){
  const segments=seriesSegments(points,key),valid=segments.flat(),wrap=node('div',undefined,'chart');
  const head=node('div',undefined,'chart-head');head.append(ui('h3',label));wrap.append(head);
  if(!valid.length){wrap.append(ui('p','유효한 관측값이 없습니다.','hint'));return wrap;}
  const low=valid.reduce((v,p)=>Math.min(v,p[key]),Infinity),high=valid.reduce((v,p)=>Math.max(v,p[key]),-Infinity);
  const times=points.filter(p=>Number.isFinite(p.t)).map(p=>p.t),start=times.reduce((a,b)=>Math.min(a,b),Infinity),end=times.reduce((a,b)=>Math.max(a,b),-Infinity);
  const span=high-low||Math.max(Math.abs(high)*.1,1),min=low-(high-low?span*.08:span/2),max=high+(high-low?span*.08:span/2);
  const x=t=>55+(t-start)/(end-start||1)*560,y=v=>174-(v-min)/(max-min)*150;
  head.append(ui('span',m('최대 {value} mm',{value:format(high)})));
  const svg=svgNode('svg',{viewBox:'0 0 640 210',role:'img','aria-label':m('{label} 시계열. 좌우 방향키로 관측값 탐색',{label:m(label)}),tabindex:0});
  for(let i=0;i<=4;i++){
    const value=min+(max-min)*i/4,Y=y(value),time=start+(end-start)*i/4,X=x(time);
    svg.append(svgNode('line',{x1:55,y1:Y,x2:615,y2:Y,class:'grid-line'}),svgNode('text',{x:47,y:Y+3,'text-anchor':'end'},format(value,3)));
    svg.append(svgNode('line',{x1:X,y1:24,x2:X,y2:174,class:'grid-line'}),svgNode('text',{x:X,y:194,'text-anchor':'middle'},format(time,3)));
  }
  svg.append(svgNode('text',{x:8,y:12},'mm'),svgNode('text',{x:630,y:194},'s'));
  segments.forEach(segment=>{
    if(segment.length===1)svg.append(svgNode('circle',{cx:x(segment[0].t),cy:y(segment[0][key]),r:2,fill:'var(--accent)'}));
    else svg.append(svgNode('polyline',{points:segment.map(p=>`${x(p.t)},${y(p[key])}`).join(' '),class:'plot-line'}));
  });
  const marker=svgNode('g',{visibility:'hidden'}),line=svgNode('line',{y1:24,y2:174,stroke:'var(--muted)','stroke-dasharray':'3 4'}),dot=svgNode('circle',{r:3,fill:'var(--accent)',stroke:'var(--bg)','stroke-width':2});marker.append(line,dot);svg.append(marker);
  const readout=ui('div','그래프 위에서 시각과 측정값을 확인합니다.','chart-readout');let pointIndex=0;
  function inspect(index){pointIndex=Math.max(0,Math.min(index,valid.length-1));const p=valid[pointIndex],X=x(p.t);line.setAttribute('x1',X);line.setAttribute('x2',X);dot.setAttribute('cx',X);dot.setAttribute('cy',y(p[key]));marker.setAttribute('visibility','visible');setText(readout,`${format(p.t)} s · ${format(p[key])} mm`);}
  svg.onpointermove=e=>{const rect=svg.getBoundingClientRect(),t=start+(((e.clientX-rect.left)/rect.width*640-55)/560)*(end-start);let idx=0;for(let i=1;i<valid.length;i++)if(Math.abs(valid[i].t-t)<Math.abs(valid[idx].t-t))idx=i;inspect(idx);};
  svg.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();inspect(e.key==='Home'?0:e.key==='End'?valid.length-1:pointIndex+(e.key==='ArrowRight'?1:-1));}};
  const foot=node('div',undefined,'chart-foot');foot.append(ui('span',m('{valid} / {total}개 유효 관측',{valid:valid.length.toLocaleString(),total:points.length.toLocaleString()})),ui('span','빈 관측은 연결하지 않습니다.'));
  wrap.append(svg,readout,foot);return wrap;
}
function chartPanel(series,probe){
  const choices=[];if(probe?.points.length)choices.push({points:probe.points,key:'depth_mm',title:'공의 진입 깊이',short:'진입 깊이'});
  if(series.points.length)choices.push({points:series.points,key:'max_pen',title:'접촉 관통 깊이',short:'관통 깊이'},{points:series.points,key:'z',title:'질량중심 높이',short:'질량중심'});
  if(!choices.length)return ui('p','시계열이 기록되지 않았습니다.','hint');
  const panel=node('section',undefined,'panel chart-panel'),tabs=node('div',undefined,'chart-select'),body=node('div');tabs.setAttribute('role','group');attribute(tabs,'aria-label',m('그래프 항목'));
  choices.forEach((c,i)=>{const b=button(c.short,()=>select(c,b));b.setAttribute('aria-pressed','false');tabs.append(b);if(i===0)select(c,b);});
  function select(c,b){tabs.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));body.replaceChildren(chart(c.points,c.key,c.title));}
  panel.append(tabs,body);return panel;
}
async function showRun(id){
  const ticket=++loading;$('#detail').setAttribute('aria-busy','true');
  try{
    const [d,series]=await Promise.all([request('/api/runs/'+id),request('/api/runs/'+id+'/series')]);
    const probe=d.test_type==='probe'?await request('/api/runs/'+id+'/series?channel=probe'):null;
    if(ticket!==loading)return;
    active=id;history.replaceState(null,'','#'+id);renderList();const root=$('#detail');root.replaceChildren();
    const head=node('div',undefined,'detail-head'),identity=node('div',undefined,'identity'),title=node('div',undefined,'identity-title'),meta=node('div',undefined,'identity-meta');
    title.append(node('h2',d.asset),ui('span',testLabel(d.test_type),'type-tag'),badge(executionLabel[d.execution_status]||d.source_status,d.execution_status));
    [m(conditionLabel(d.config.condition)),`MuJoCo ${d.engine_version}`,`seed ${d.seed}`].forEach(t=>meta.append(node('span',t)));
    identity.append(title,meta);head.append(identity);root.append(head);
    if(d.execution_status==='error')root.append(ui('p',m('실행 오류 · {reason}',{reason:d.status_reason||d.source_status}),'warning'));
    if(d.execution_status==='skipped')root.append(ui('p','대상 아님으로 기록된 결과입니다. 누락이나 불통과로 집계하지 않습니다.','warning neutral'));
    const columns=node('div',undefined,'columns'),left=node('section',undefined,'evidence-column');left.append(mediaPanel(d));
    if(d.execution_status!=='skipped')left.append(metricStrip(d),chartPanel(series,probe));
    columns.append(left,judgmentForm(d));root.append(columns,detailTabs(d));
  }catch(error){if(ticket===loading){notice(error.message,true);if(!$('#detail .detail-head'))showEmpty('실행을 불러오지 못했습니다.',error.message,true);}}
  finally{if(ticket===loading)$('#detail').setAttribute('aria-busy','false');}
}
function metricsTable(d){
  const wrap=node('div',undefined,'table-wrap'),table=node('table',undefined,'metric-table');attribute(table,'aria-label',m('전체 측정값'));
  const thead=node('thead'),tr=node('tr');['측정 항목','저장값 · SI','원본 값','상태'].forEach(t=>{const th=ui('th',t);th.scope='col';tr.append(th);});thead.append(tr);table.append(thead);const body=node('tbody');
  d.metrics.forEach(m=>{const row=node('tr'),value=node('td'),raw=node('td');
    value.append(node('span',m.valid?format(m.metric_value??m.metric_text):'—'),node('span',m.valid&&m.metric_value!==null?' '+m.unit:'','unit'));
    raw.append(node('span',m.raw_value),node('span',m.raw_unit?' '+m.raw_unit:'','unit'));
    row.append(node('td',m.metric_name,'metric-name'),value,raw,ui('td',m.valid?'유효':m.invalid_reason||'미측정'));body.append(row);
  });table.append(body);wrap.append(table);return wrap;
}
function judgmentHistory(d){
  const section=node('section');
  if(!d.judgments.length){section.append(ui('div','아직 판정이 없습니다. 영상과 측정값을 검토한 뒤 기록해주세요.','history-empty'));return section;}
  d.judgments.forEach(j=>{
    const h=node('article',undefined,'history'),top=node('div',undefined,'history-top');top.append(badge(outcomes[j.outcome],j.outcome),userText('strong',j.reviewer));if(!j.current)top.append(ui('small','이전 판정'));
    const context=node('small');context.append(userText('bdi',j.criterion_key),document.createTextNode(' · '),userText('bdi',j.protocol_version),document.createTextNode(' · '),node('span',date(j.reviewed_at)));
    h.append(top,userText('p',j.rationale),context);
    if(j.current)h.append(button('이 판정 수정',async()=>{
      judgmentDrafts.set(d.run_id,{reviewer:j.reviewer,outcome:j.outcome,rationale:j.rationale,criterion_key:j.criterion_key,protocol_version:j.protocol_version,evidence_ids:j.evidence_ids||[]});dirtyRuns.delete(d.run_id);
      await showRun(d.run_id);$('#detail [name=rationale]')?.focus();
    },'edit-judgment'));section.append(h);
  });return section;
}
function metadata(d){
  const section=node('section'),list=node('dl',undefined,'metadata-list');
  for(const [key,value]of [['자료 구분',m(originLabel[d.origin])],['실행 묶음',d.source_namespace],['실행 ID',d.run_id],['원본 실행',d.source_run_id],['에셋 해시',d.asset_version||m('미기록')],['원본 상태',d.source_status],['처리 상태',d.execution_status],['가져온 시각',date(d.imported_at)]])list.append(ui('dt',key),node('dd',value));
  section.append(list);
  if(d.warnings.length){const warnings=node('details');warnings.append(ui('summary',m('자료 확인 사항 · {count}',{count:d.warnings.length})));d.warnings.forEach(t=>warnings.append(ui('p',t,'hint')));section.append(warnings);}
  const raw=node('details');raw.append(ui('summary','전체 실행 설정 · JSON'),node('pre',JSON.stringify(d.raw_meta,null,2)));section.append(raw);
  const files=node('div',undefined,'artifact-list');d.artifacts.forEach(a=>{const link=node('a');link.append(node('span',a.filename),node('small',`${format(a.size_bytes/1024,3)} KiB ↗`));link.href='/api/artifacts/'+a.artifact_id;link.target='_blank';link.rel='noopener';files.append(link);});section.append(files);return section;
}
function detailTabs(d){
  const section=node('section',undefined,'detail-tabs'),tabs=node('div',undefined,'tab-list');tabs.setAttribute('role','tablist');attribute(tabs,'aria-label',m('상세 자료'));section.append(tabs);
  const entries=[['metrics',m('전체 측정값 {count}',{count:d.metrics.length}),metricsTable(d)],['history',m('판정 이력 {count}',{count:d.judgments.length}),judgmentHistory(d)],['metadata','검사 조건·파일',metadata(d)]];
  const buttons=[],panels=[];
  entries.forEach(([key,label,content])=>{
    const tab=button(label,()=>select(key)),panel=node('div',undefined,'tab-panel');tab.id='tab-'+key;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','panel-'+key);panel.id='panel-'+key;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',tab.id);panel.tabIndex=0;panel.append(content);buttons.push(tab);panels.push(panel);tabs.append(tab);section.append(panel);
    tab.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const i=buttons.indexOf(tab),next=e.key==='Home'?0:e.key==='End'?entries.length-1:(i+(e.key==='ArrowRight'?1:-1)+entries.length)%entries.length;select(entries[next][0]);buttons[next].focus();}};
  });
  function select(key){detailSection=key;entries.forEach(([id],i)=>{buttons[i].setAttribute('aria-selected',String(id===key));buttons[i].tabIndex=id===key?0:-1;panels[i].hidden=id!==key;});}
  select(detailSection);return section;
}
function judgmentForm(d){
  const draft=judgmentDrafts.get(d.run_id)||{},form=node('form',undefined,'verdict-card');
  const heading=node('div',undefined,'form-heading'),state=ui('span',dirtyRuns.has(d.run_id)?'미저장':'','draft-state'+(dirtyRuns.has(d.run_id)?' dirty':''));heading.append(ui('h3','판정 기록'),state);
  form.append(heading);
  const reviewerLabel=ui('label','평가자'),reviewer=node('input');reviewer.name='reviewer';reviewer.required=true;multilingual(reviewer,100);reviewer.value=draft.reviewer??savedReviewer();attribute(reviewer,'placeholder',m('이름'));reviewerLabel.append(reviewer);
  const itemLabel=ui('label','검토 항목'),item=node('select');item.name='criterion_key';attribute(item,'aria-label',m('검토 항목'));
  [['physical_behavior','전체 물리 거동'],['penetration','관통'],['stability','안정성'],['motion','운동 모드'],['cavity','홈·구멍 보존']].forEach(([v,t])=>item.add(option(m(t),v)));if(draft.criterion_key&&![...item.options].some(o=>o.value===draft.criterion_key))item.add(option(draft.criterion_key,draft.criterion_key));item.value=draft.criterion_key||'physical_behavior';itemLabel.append(item);
  const radios=node('fieldset',undefined,'verdicts');radios.append(ui('legend','사람 판정'));
  Object.entries(outcomes).forEach(([value,text])=>{const label=node('label'),radio=node('input');radio.type='radio';radio.name='outcome';radio.value=value;radio.checked=value===(draft.outcome||'inconclusive');label.append(radio,ui('span',text));radios.append(label);});
  const reasonLabel=ui('label','판정 이유','reason-label'),reason=node('textarea');reason.name='rationale';reason.required=true;multilingual(reason,5000);reason.value=draft.rationale||'';attribute(reason,'placeholder',m('어떤 장면이나 측정값을 근거로 판단했나요?'));reasonLabel.append(reason);const counter=node('div',undefined,'reason-counter');
  const criterion=ui('label','판정 기준 버전'),version=node('input');version.name='protocol_version';version.value=draft.protocol_version??'review-draft-1';version.required=true;multilingual(version,100);criterion.append(version);
  const evidence=node('details',undefined,'evidence'),evidenceTitle=ui('summary','근거 파일 선택');evidence.append(evidenceTitle);
  d.artifacts.filter(a=>['video','screenshot','trajectory'].includes(a.artifact_type)).forEach(a=>{const label=node('label'),check=node('input');check.type='checkbox';check.name='evidence';check.value=a.artifact_id;check.checked=(draft.evidence_ids||[]).includes(a.artifact_id);label.append(check,node('span',a.filename));evidence.append(label);});
  const submit=ui('button','판정 저장','primary'),context=node('p',undefined,'save-context');submit.type='submit';
  const current=()=>d.judgments.find(j=>j.current&&j.reviewer===reviewer.value.trim()&&j.protocol_version===version.value.trim()&&j.criterion_key===item.value);
  const remember=(dirty=false)=>{
    const value={reviewer:reviewer.value,outcome:new FormData(form).get('outcome'),rationale:reason.value,criterion_key:item.value,protocol_version:version.value,evidence_ids:[...form.querySelectorAll('[name=evidence]:checked')].map(x=>x.value)};
    judgmentDrafts.set(d.run_id,value);if(dirty){dirtyRuns.add(d.run_id);setText(state,m('미저장'));state.classList.add('dirty');}
    setText(context,m(current()?'현재 판정을 수정하며, 이전 기록은 보존합니다.':'새 판정으로 기록합니다.'));
    setText(counter,`${codePointLength(reason.value).toLocaleString()} / 5,000`);setText(evidenceTitle,m('근거 파일 · {count}개 선택',{count:value.evidence_ids.length}));return value;
  };
  form.append(reviewerLabel,itemLabel,radios,reasonLabel,counter,criterion,evidence,submit,context);
  form.addEventListener('input',()=>remember(true));form.addEventListener('change',()=>remember(true));remember();
  form.onsubmit=async e=>{
    e.preventDefault();form.querySelectorAll('[data-codepoint-limit]').forEach(validateText);if(!form.reportValidity())return;submit.disabled=true;setText(submit,m('저장 중…'));
    const value=remember(),name=value.reviewer.trim(),protocol=value.protocol_version.trim(),previous=current();
    try{
      await request('/api/runs/'+d.run_id+'/judgments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...value,reviewer:name,protocol_version:protocol,supersedes_judgment_id:previous?.judgment_id||null})});
      judgmentDrafts.set(d.run_id,{...value,reviewer:name,protocol_version:protocol});dirtyRuns.delete(d.run_id);
      try{localStorage.setItem('simasset-reviewer',name);}catch{/* The judgment is already saved; browser preferences are optional. */}
      notice('판정과 근거를 저장했습니다.');await refresh();
    }catch(error){notice(error.message,true);submit.disabled=false;setText(submit,m('판정 저장'));}
  };
  return form;
}
async function renderImports(){
  const rows=await request('/api/imports');setText($('#import-count'),m('최근 {count}건',{count:rows.length}));$('#imports').replaceChildren();
  const labels={imported:'가져옴',duplicate:'중복',conflict:'충돌',invalid:'형식 오류'};
  rows.forEach(r=>{const article=node('article'),body=node('div');body.append(node('strong',r.source_namespace),ui('p',r.diagnostics.message||r.diagnostics.code||'파일 검증 완료'));article.append(badge(labels[r.status]||r.status,['conflict','invalid'].includes(r.status)?'error':''),body,node('small',date(r.created_at)));$('#imports').append(article);});
}
['#asset','#test','#version','#origin'].forEach(id=>$(id).onchange=renderList);
$('#search').oninput=renderList;$('#clear-filters').onclick=clearFilters;$('#refresh').onclick=refresh;
$('.queue-filter').addEventListener('click',e=>{const b=e.target.closest('[data-queue]');if(b)setQueue(b.dataset.queue);});
window.addEventListener('beforeunload',e=>{if(dirtyRuns.size){e.preventDefault();e.returnValue='';}});
refresh();
