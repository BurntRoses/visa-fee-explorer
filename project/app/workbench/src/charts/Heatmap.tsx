import {useId,useMemo} from 'react';
import {EmptyPlot,Mark,PlotFrame,type PlotProps} from './common';
import {countryColor,fitLabel,fmt,money,OTHER,shortName} from './helpers';
import {bilateralMembers,globalHeatmapGraph} from './bilateral';
const cellValue=(value:number)=>value>=1e8?`${fmt(value/1e8,value>=1e10?0:1)}亿`:value>=1e4?`${fmt(value/1e4,value>=1e6?0:1)}万`:fmt(value,0);
const intensity=(value:number,max:number)=>Math.pow(value/max,.32);
const cellColor=(t:number)=>{const a=[233,244,237],b=[22,100,84];return `rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*t)).join(',')})`;};

export function HeatmapPlot(p:PlotProps){
 const {analysis,state,width:w,height:h,events}=p,mobile=w<600,gradientId=useId().replace(/:/g,'');
 const graph=useMemo(()=>globalHeatmapGraph(analysis,state,w,h),[analysis,state,w,h]),sources=graph.sources,targets=graph.targets,edges=new Map(graph.edges.map(e=>[e.origin+'|'+e.destination,e]));
 if(!sources.length||!targets.length)return <EmptyPlot title="选择国家后查看交叉费用"/>;
 const top=mobile?126:104,bottom=53,left=mobile?83:139,right=mobile?39:51,cellW=(w-left-right)/targets.length,cellH=(h-top-bottom)/sources.length,gridW=cellW*targets.length,gridH=cellH*sources.length,maxAmount=Math.max(...graph.edges.map(e=>e.amount),0),max=Math.max(maxAmount,1),font=mobile?10:11;
 const axisName=(code:string,name:string)=>(code===OTHER?name:shortName(code,name)).replace(/\s/g,'');
 return <PlotFrame width={w} height={h} view="heatmap" title="付款来源与收款政府的签证费用热图" description={`行是付款申请人来源，列是收款政府，两轴独立按金额排列；其余国家费用保留聚合，未知国籍单列。深浅按金额，0表示已知免费，横杠表示未识别金额。共${sources.length}行、${targets.length}列，金额格可点击查看费用与来源。`}>
  <defs><linearGradient id={`${gradientId}-scale`}><stop offset="0" stopColor={cellColor(0)}/><stop offset="1" stopColor={cellColor(1)}/></linearGradient></defs>
  <text x={mobile?8:left} y={mobile?45:22} className="viz-chart-title" fontSize={mobile?12:14}>付款来源 ↓ · 收款政府 →</text>
  {targets.map((n,j)=>{
   const name=fitLabel(axisName(n.code,n.name),mobile?67:82,mobile?11:12),x=left+(j+.5)*cellW,y=top-12,dim=!!events.highlight&&events.highlight!==n.code;
   return <Mark key={'col'+n.code} events={events} code={n.code} data-axis="destination" data-node-code={n.code} data-node-amount={n.amount} data-members={n.members.join(',')} members={n.members} title={`${n.name}政府收到`} amount={n.amount} detail={n.code===OTHER?'查看收款政府聚合成员':'点击锁定高亮'} color={countryColor(n.code)} opacity={dim?.55:1}>
    <rect x={left+j*cellW} y={mobile?58:31} width={cellW} height={top-(mobile?58:31)} rx="5" fill="transparent" className="viz-label-surface"/>
    <text x={x} y={y} textAnchor="start" transform={`rotate(-55 ${x} ${y})`} className="viz-matrix-axis" fontSize={mobile?11:12}>{name}</text>
   </Mark>;
  })}
  {sources.map((origin,i)=>{
   const dimAxis=!!events.highlight&&events.highlight!==origin.code;
   return <g key={origin.code}>
    <Mark events={events} code={origin.code} data-axis="origin" data-node-code={origin.code} data-node-amount={origin.amount} data-members={origin.members.join(',')} members={origin.members} title={`${origin.name}申请人付出`} amount={origin.amount} detail={origin.code===OTHER?'查看付款来源聚合成员':'点击锁定高亮'} color={countryColor(origin.code)} opacity={dimAxis?.55:1}>
     <rect x="7" y={top+i*cellH} width={left-13} height={cellH} rx="4" fill="transparent" className="viz-label-surface"/>
     <text x={left-10} y={top+(i+.5)*cellH+4} textAnchor="end" className="viz-matrix-axis" fontSize={mobile?11:12}>{fitLabel(axisName(origin.code,origin.name),left-19,mobile?11:12)}</text>
    </Mark>
    {targets.map((destination,j)=>{
     const x=left+j*cellW,y=top+i*cellH,diagonal=origin.code===destination.code&&origin.code!==OTHER&&!edges.has(origin.code+'|'+destination.code),e=edges.get(origin.code+'|'+destination.code),missing=!e,free=e?.amount===0,below=!!e&&e.amount>0&&e.amount<state.minAmount,dim=!!events.highlight&&events.highlight!==origin.code&&events.highlight!==destination.code;
     const value=e?.amount||0,t=intensity(value,max),text=diagonal?'／':missing?'—':free?'0':cellW>=43&&cellH>=22?cellValue(value):'';
     if(diagonal)return <g key={destination.code}><rect x={x+1} y={y+1} width={Math.max(1,cellW-2)} height={Math.max(1,cellH-2)} rx="2" fill="#f4f6f5"/><text x={x+cellW/2} y={y+cellH/2+4} textAnchor="middle" fill="#acbcb7" fontSize={font}>／</text></g>;
     return <Mark key={destination.code} events={events} origin={origin.code} destination={destination.code} data-origin={origin.code} data-destination={destination.code} data-amount={e?.amount} data-missing={missing?'true':'false'} data-free={free?'true':'false'} members={bilateralMembers(origin,destination)} title={`${origin.name}申请人 → ${destination.name}政府`} amount={e?.amount} detail={missing?'这个方向的金额尚未识别':free?'已知免费路线':below?'已知金额，低于显示门槛':'点击查看费用与来源'} color={cellColor(t)} opacity={dim?.19:below?.5:1}>
      <rect x={x+1} y={y+1} width={Math.max(1,cellW-2)} height={Math.max(1,cellH-2)} rx="2" fill={missing?'#f2f5f3':free?'white':cellColor(t)} stroke={free?'#5f9b83':'none'} strokeWidth={free?1:0} strokeDasharray={free?'3 2':undefined}/>
      <text x={x+cellW/2} y={y+cellH/2+4} textAnchor="middle" fontSize={font} fontWeight={free?600:500} fill={missing?'#a4b6ae':free?'#28775e':t>.57?'white':'#245845'}>{text}</text>
     </Mark>;
    })}
   </g>;
  })}
  <g transform={`translate(${left} ${top+gridH+17})`} aria-label={`颜色深浅从0至${money(max)}`}>
   <rect width={mobile?54:94} height="7" rx="3.5" fill={`url(#${gradientId}-scale)`}/><text x={mobile?61:102} y="7" className="viz-legend-text" fontSize={mobile?10:11}>{maxAmount>0?cellValue(maxAmount):'全部免费'}</text>
   <text x={mobile?0:Math.min(gridW-140,245)} y={mobile?24:8} className="viz-legend-text" fontSize={mobile?10:11}>0 免费 · — 未识别</text>
  </g>
 </PlotFrame>;
}
