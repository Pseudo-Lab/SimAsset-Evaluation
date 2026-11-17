// Comparisons share axes, never synthesize observations or convert missing values to zero.
export function chartChoices(series, probe) {
  const choices=[];
  if(probe?.points.length)choices.push({points:probe.points,key:'depth_mm',title:'공의 진입 깊이',short:'진입 깊이'});
  if(series.points.length)choices.push(
    {points:series.points,key:'max_pen',title:'접촉 관통 깊이',short:'관통 깊이'},
    {points:series.points,key:'z',title:'질량중심 높이',short:'질량중심'});
  return choices;
}
export function chartDomain(collections, key) {
  let start=Infinity,end=-Infinity,low=Infinity,high=-Infinity;
  for(const points of collections)for(const point of points){
    if(!Number.isFinite(point.t))continue;
    start=Math.min(start,point.t);end=Math.max(end,point.t);
    if(Number.isFinite(point[key])){low=Math.min(low,point[key]);high=Math.max(high,point[key]);}
  }
  const hasValues=Number.isFinite(low);
  if(!Number.isFinite(start)){start=0;end=1;}
  if(!hasValues){low=0;high=0;}
  const span=high-low,padding=span?span*.08:Math.max(Math.abs(high)*.1,1)/2;
  return {start,end,min:low-padding,max:high+padding,hasValues};
}
export function observationAt(points, key, time) {
  const timeline=points.filter(p=>Number.isFinite(p.t));
  if(!timeline.length || !Number.isFinite(time) || time<timeline[0].t || time>timeline.at(-1).t)return null;
  let nearest=timeline[0];
  for(const point of timeline)if(Math.abs(point.t-time)<Math.abs(nearest.t-time))nearest=point;
  return {t:nearest.t,value:Number.isFinite(nearest[key])?nearest[key]:null};
}
export function comparisonOptions(runs, current) {
  return runs.filter(r=>r.run_id!==current.run_id && r.test_type===current.test_type)
    .sort((a,b)=>Number(b.asset===current.asset)-Number(a.asset===current.asset)
      || Number(b.condition!==current.config.condition)-Number(a.condition!==current.config.condition)
      || Number(b.videos>0)-Number(a.videos>0));
}
export function clipTime(time,duration) {
  return Number.isFinite(time)&&Number.isFinite(duration)&&duration>0?Math.max(0,Math.min(time,duration)):null;
}
