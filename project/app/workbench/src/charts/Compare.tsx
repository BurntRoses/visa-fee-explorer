import {useMemo,useState} from 'react';
import {Mark,PlotFrame,type PlotProps,EmptyPlot} from './common';
import {fitLabel,fmt,IN,money,OTHER,OUT,shortMoney,shortName} from './helpers';
export function ComparePlot(p:PlotProps){
 const {analysis,state,width:w,height:h,events}=p,mobile=w<600,[order,setOrder]=useState<'total'|'in'|'out'|'net'>('total');
 const data=useMemo(()=>{
  const selected=analysis.nodes.filter(n=>state.countries.includes(n.code)).map(n=>({...n,members:analysis.entities.find(e=>e.code===n.code)?.members||[n.code]})).sort((a,b)=>order==='in'?b.incoming-a.incoming:order==='out'?b.outgoing-a.outgoing:order==='net'?(b.net??-Infinity)-(a.net??-Infinity):(b.incoming+b.outgoing)-(a.incoming+a.outgoing)),cap=Math.max(3,Math.min(state.maxNodes,Math.floor((h-93)/53)));
  if(selected.length<=cap)return selected;const shown=selected.slice(0,cap-1),rest=selected.slice(cap-1);shown.push({code:OTHER,name:`其余 ${rest.length} 国`,members:rest.map(n=>n.code),incoming:rest.reduce((s,n)=>s+n.incoming,0),outgoing:rest.reduce((s,n)=>s+n.outgoing,0),incomingKnown:rest.some(n=>n.incomingKnown),outgoingKnown:rest.some(n=>n.outgoingKnown),net:rest.every(n=>n.net!==null)?rest.reduce((s,n)=>s+n.net!,0):null,unallocated:rest.reduce((s,n)=>s+n.unallocated,0),selected:false});return shown;
 },[analysis,state.countries,state.maxNodes,order,h]);
 if(!data.length)return <EmptyPlot title="选择国家后比较收到与付出"/>;
 const previous=analysis.previousNodes,comparisonYear=(analysis as typeof analysis&{comparisonYear?:number}).comparisonYear,previousMap=new Map((previous||[]).map(n=>[n.code,n]));
 for(const n of data.filter(n=>n.code===OTHER)){const rest=(previous||[]).filter(x=>n.members.includes(x.code));if(rest.length)previousMap.set(OTHER,{...rest[0],code:OTHER,incoming:rest.reduce((s,n)=>s+n.incoming,0),outgoing:rest.reduce((s,n)=>s+n.outgoing,0)});}
 const labelWidth=mobile?81:185,rightWidth=mobile?68:140,plotWidth=w-labelWidth-rightWidth-24,half=plotWidth/2,zero=labelWidth+half,max=Math.max(...data.flatMap(n=>[n.incoming,n.outgoing,previousMap.get(n.code)?.incoming||0,previousMap.get(n.code)?.outgoing||0]),1),scale=half/max,rowH=Math.min(61,(h-95)/data.length),top=79;
 const barChange=(v:number,old:number|undefined)=>old===undefined?'':`，${comparisonYear?`${comparisonYear}年`:'对照年'}${money(old)}，${old>0?`${v>=old?'增长':'减少'}${fmt(Math.abs(v-old)/old*100,1)}%`:'对照值为零'}`;
 return <div className="viz-compare-layout"><div className="viz-mini-controls" role="group" aria-label="国家对照排序">{[['total','往来额'],['in','收到'],['out','付出'],['net','差额']].map(([id,name])=><button key={id} className={order===id?'active':''} aria-pressed={order===id} onClick={()=>setOrder(id as typeof order)}>{name}</button>)}</div>
 <PlotFrame width={w} height={h} view="compare" title="各国签证费用收到与付出比较" description="绿色向左为政府收到，橙色向右为申请人付出。右侧为收到减付出。细条表示对照年，年份随当前数据提供。">
  <line x1={zero} x2={zero} y1="54" y2={top+rowH*data.length-12} stroke="#c4d1d6"/>
  <text x={zero-12} y="49" textAnchor="end" className="viz-legend-text" style={{fill:IN}}>政府收到</text><text x={zero+12} y="49" className="viz-legend-text" style={{fill:OUT}}>申请人付出</text><text x={w-8} y="49" textAnchor="end" className="viz-legend-text">收付差额</text>
  {data.map((n,i)=>{const y=top+i*rowH,old=previousMap.get(n.code),inWidth=n.incoming*scale,outWidth=n.outgoing*scale,barHeight=16,dim=!!events.highlight&&events.highlight!==n.code,name=fitLabel(shortName(n.code,n.name),labelWidth-15,14);return <g key={n.code} opacity={dim?.25:1}>
   <Mark events={events} code={n.code} members={n.members} title={n.name} amount={n.incoming+n.outgoing} detail={n.code===OTHER?'查看聚合成员':'点击锁定高亮'}><rect x="4" y={y-18} width={labelWidth-9} height={rowH-5} rx="5" fill="transparent" className="viz-label-surface"/><text x="8" y={y+4} className="viz-node-label" fontSize="14">{name}</text></Mark>
   <Mark events={events} code={n.code} members={n.members} title={`${n.name}政府收到`} amount={n.incomingKnown?n.incoming:undefined} detail={(n.incomingKnown?'当前范围内流入':'未识别金额')+barChange(n.incoming,old?.incoming)} color={IN}>
    <rect x={zero-Math.max(inWidth,2)} y={y-11} width={Math.max(inWidth,n.incomingKnown?1:0)} height={barHeight} rx="2" fill={IN} style={{transition:p.reducedMotion?'none':'x .3s,width .3s'}}/><rect x={labelWidth} y={y-18} width={half} height={rowH-5} fill="transparent"/>{old&&<rect x={zero-old.incoming*scale} y={y+9} width={old.incoming*scale} height="3" rx="1" fill={IN} fillOpacity=".46"/>}
   </Mark>
   <Mark events={events} code={n.code} members={n.members} title={`${n.name}申请人付出`} amount={n.outgoingKnown?n.outgoing:undefined} detail={(n.outgoingKnown?'当前范围内流出':'未识别金额')+barChange(n.outgoing,old?.outgoing)} color={OUT}>
    <rect x={zero+1} y={y-11} width={Math.max(outWidth,n.outgoingKnown?1:0)} height={barHeight} rx="2" fill={OUT} style={{transition:p.reducedMotion?'none':'width .3s'}}/><rect x={zero} y={y-18} width={half} height={rowH-5} fill="transparent"/>{old&&<rect x={zero+1} y={y+9} width={old.outgoing*scale} height="3" rx="1" fill={OUT} fillOpacity=".46"/>}
   </Mark>
   <text x={zero-7} y={y+29} textAnchor="end" className="viz-bar-value" style={{fill:IN}}>{n.incomingKnown?shortMoney(n.incoming):'—'}</text><text x={zero+8} y={y+29} className="viz-bar-value" style={{fill:OUT}}>{n.outgoingKnown?shortMoney(n.outgoing):'—'}</text>
   <text x={w-8} y={y+5} textAnchor="end" className="viz-net-value" fontSize={mobile?12:14} fill={(n.net||0)>=0?IN:OUT}>{n.net===null?'未识别':`${n.net>0?'+':''}${shortMoney(n.net)}`}</text>
  </g>;})}
 </PlotFrame></div>;
}
