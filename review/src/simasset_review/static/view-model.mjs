// Pure presentation rules shared by the browser and regression tests.
import {searchText} from './unicode.mjs';
export const originLabel = {team_shared:'팀 공유 결과',local_reproduction:'로컬 재현 결과',fixture:'기능 시험 데이터'};
export const outcomes = {pass:'통과',fail:'불통과',inconclusive:'보류'};
export const executionLabel = {completed:'실행 완료',error:'실행 오류',skipped:'대상 아님'};
export const testLabel = value => ({probe:'홈 검사',incline:'빗면 검사',settle:'가만히 두기',drop:'떨어뜨리기',spin:'스핀 검사'}[value] || value);
export const conditionLabel = value => ({decomposed:'볼록 분해',single_hull:'단일 볼록체',ramp45deg:'45° 빗면',
  base:'기본 자세',yaw90:'90° 돌려 놓기',tilt30:'30° 기울여 놓기',
  geom_axis_min:'최소 관성축 회전',geom_axis_mid:'중간 관성축 회전',geom_axis_max:'최대 관성축 회전'}[value] || value || '조건 미기록');
export const versionKey = run => run.asset_version || '__missing__';
export const versionText = (value,n=8) => !value || value==='__missing__' ? '해시 미기록' : value.slice(0,n);
export function format(value,precision=5) {
  if(value===null || value===undefined || (typeof value==='number' && !Number.isFinite(value))) return '—';
  if(typeof value!=='number') return String(value);
  if(value!==0 && Math.abs(value)<.0001) return value.toExponential(2);
  return value.toLocaleString('ko-KR',{maximumSignificantDigits:precision});
}
export function filterRuns(runs,{asset='',test='',version='',origin='',search='',queue='all'}={}) {
  const query=searchText(search.trim());
  const aliases={probe:'cavity test',incline:'incline test',settle:'settle test',drop:'drop test',spin:'spin test',
    decomposed:'convex decomposition',single_hull:'single convex hull',ramp45deg:'45° incline',
    base:'base pose',yaw90:'rotated 90°',tilt30:'tilted 30°',geom_axis_min:'minimum inertia axis',
    geom_axis_mid:'intermediate inertia axis',geom_axis_max:'maximum inertia axis'};
  return runs.filter(r=>(!asset || r.asset===asset) && (!test || r.test_type===test)
    && (!version || versionKey(r)===version) && (!origin || r.origin===origin)
    && (queue!=='unreviewed' || r.judgments===0) && (queue!=='error' || r.execution_status==='error')
    && (!query || searchText([r.asset,r.test_type,testLabel(r.test_type),aliases[r.test_type],r.condition,conditionLabel(r.condition),aliases[r.condition],r.source_run_id,r.run_id].join(' ')).includes(query)));
}
export function seriesSegments(points,key) {
  const segments=[]; let current=[];
  for(const p of points) {
    if(Number.isFinite(p.t) && Number.isFinite(p[key])) current.push(p);
    else if(current.length) {segments.push(current);current=[];}
  }
  if(current.length) segments.push(current);
  return segments;
}
export function keyMetrics(run) {
  const keys={
    probe:[['probe_depth','안착 진입 깊이','mm',1000],['peak_pen','최대 관통 깊이','mm',1000],['ball_settle_time','공 안착 시간','s',1]],
    settle:[['settle_class','안착 분류','',1],['jitter','떨림','mm/s',1000],['peak_pen','최대 관통 깊이','mm',1000]],
    drop:[['peak_pen','최대 관통 깊이','mm',1000],['bounce_height_mm','튀어 오른 높이','mm',1000],['slide_mm','미끄러진 거리','mm',1000]],
    spin:[['axis_dev_max_deg','최대 축 이탈','deg',180/Math.PI],['expected_stable','안정 예상','',1],['energy_increase_pct','에너지 증가','%',100]],
  }[run.test_type] || [['peak_pen','최대 관통 깊이','mm',1000],['mass_kg','질량','kg',1],['motion_mode','운동 모드','',1]];
  return keys.map(([key,label,unit,scale])=>{
    const m=run.metrics.find(m=>m.metric_name===key);
    const value=m?.valid ? (m.metric_value===null ? m.metric_text : m.metric_value*scale) : null;
    return {key,label,unit:value===null?'':unit,value,reason:m?.invalid_reason||'미측정'};
  });
}
