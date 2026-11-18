import {useId} from 'react';
import {EmptyPlot,Mark,PlotFrame,type PlotProps} from './common';
import {countryColor,fitLabel,fmt,money,OTHER,shortName} from './helpers';
import {bilateralMembers,heatmapLayout,type BilateralGraph} from './bilateral';
const cellValue=(value:number)=>value>=1e8?`${fmt(value/1e8,value>=1e10?0:1)}亿`:value>=1e4?`${fmt(value/1e4,value>=1e6?0:1)}万`:fmt(value,0);
function cellLabel(value:number,cell:number,font:number){
 if(value===0)return '0';
 if(cell<27)return '';
 const full=cellValue(value).replaceAll(',','');
 const width=(label:string)=>[...label].reduce((sum,char)=>sum+font*(char==='.'?.31:/[0-9]/.test(char)?.63:1),0);
 if(width(full)<=cell-4)return full;
 if(value>=1e7){
  const short=`${fmt(value/1e8,value<1e8?1:0)}亿`;
  if(width(short)<=cell-4)return short;
 }
 return '';
}
const intensity=(value:number,max:number)=>Math.pow(value/max,.32);
const cellColor=(t:number)=>{const a=[233,244,237],b=[22,100,84];return `rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*t)).join(',')})`;};

export function HeatmapPlot({graph,width:w,height:h,events}:PlotProps&{graph:BilateralGraph}){
 const mobile=w<600,gradientId=useId().replace(/:/g,''),{sources,targets}=graph;
 const edges=new Map(graph.edges.map(e=>[e.origin+'|'+e.destination,e]));
 if(!sources.length)return <EmptyPlot title="当前范围没有可绘制的双边费用" detail="收付双方均有归属的记录才进入矩阵。"/>;
 const {top,left,side,axis}=heatmapLayout(w,h),cell=side/sources.length,maxAmount=Math.max(...graph.edges.filter(e=>e.origin!==OTHER&&e.destination!==OTHER).map(e=>e.amount),0),max=Math.max(maxAmount,1),font=cell<35?9:11;
 const axisName=(code:string,name:string)=>code===OTHER?'其余':shortName(code,name);
 return <PlotFrame width={w} height={h} view="heatmap" title="签证费用双边矩阵" description={`行是付款国籍，列是收款政府。两轴共用同一份排序，按收到加付出总额排列；对角线两侧为反向往来，各自保留实际金额。国籍未分配另列，灰蓝色为其余地区汇总，这两类不参与绿色色阶。0 表示已知免费，横杠表示金额未识别。共 ${sources.length} 行、${targets.length} 列。`}>
  <defs><linearGradient id={`${gradientId}-scale`}><stop offset="0" stopColor={cellColor(0)}/><stop offset="1" stopColor={cellColor(1)}/></linearGradient></defs>
  <text x={left} y={mobile?22:24} className="viz-chart-title" fontSize={mobile?12:14}>付款国籍 ↓ · 收款政府 →</text>
  {targets.map((n,j)=>{
   const name=fitLabel(axisName(n.code,n.name),mobile?48:52,mobile?11:12),x=left+(j+.5)*cell,y=top-8,dim=!!events.highlight&&events.highlight!==n.code;
   return <Mark key={'col'+n.code} events={events} code={n.code} data-axis="destination" data-node-code={n.code} data-node-amount={n.amount} data-members={n.members.join(',')} members={n.members} title={`${n.name}政府收到`} amount={n.incomingKnown?n.amount:undefined} detail={n.code===OTHER?'查看聚合成员':'仅含国籍已分配的费用'} color={countryColor(n.code)} opacity={dim?.55:1}>
    <rect x={left+j*cell} y={34} width={cell} height={top-34} rx="5" fill="transparent" className="viz-label-surface"/>
    <text x={x} y={y} textAnchor="start" transform={`rotate(-55 ${x} ${y})`} className="viz-matrix-axis" fontSize={mobile?11:12}>{name}</text>
   </Mark>;
  })}
  {sources.map((origin,i)=>{
   const dimAxis=!!events.highlight&&events.highlight!==origin.code;
   return <g key={origin.code}>
    <Mark events={events} code={origin.code} data-axis="origin" data-node-code={origin.code} data-node-amount={origin.amount} data-members={origin.members.join(',')} members={origin.members} title={`${origin.name}申请人付出`} amount={origin.outgoingKnown?origin.amount:undefined} detail={origin.code===OTHER?'查看聚合成员':'点击锁定高亮'} color={countryColor(origin.code)} opacity={dimAxis?.55:1}>
     <rect x={left-axis+5} y={top+i*cell} width={axis-11} height={cell} rx="4" fill="transparent" className="viz-label-surface"/>
     <text x={left-9} y={top+(i+.5)*cell+4} textAnchor="end" className="viz-matrix-axis" fontSize={mobile?11:12}>{fitLabel(axisName(origin.code,origin.name),axis-17,mobile?11:12)}</text>
    </Mark>
    {targets.map((destination,j)=>{
     const x=left+j*cell,y=top+i*cell,e=edges.get(origin.code+'|'+destination.code),dim=!!events.highlight&&events.highlight!==origin.code&&events.highlight!==destination.code;
     if(!e)return <g key={destination.code} aria-hidden="true" opacity={dim?.35:1}><rect x={x+1} y={y+1} width={cell-2} height={cell-2} rx="2" fill={i===j?'#e6ece9':'#f2f5f3'}/><text x={x+cell/2} y={y+cell/2+4} textAnchor="middle" fill="#718980" fontSize={font}>{i===j?'／':'—'}</text></g>;
     const value=e.amount,aggregated=origin.code===OTHER||destination.code===OTHER,t=intensity(Math.min(value,max),max),free=value===0;
     const text=cellLabel(value,cell,font),color=aggregated?'#d8e5eb':cellColor(t);
     return <Mark key={destination.code} events={events} origin={origin.code} destination={destination.code} data-origin={origin.code} data-destination={destination.code} data-amount={value} data-free={free?'true':'false'} data-aggregate={aggregated?'true':undefined} members={bilateralMembers(origin,destination)} title={`${origin.name}申请人 → ${destination.name}政府`} amount={value} detail={free?'已知免费路线':aggregated?'汇总金额 · 点击查看成员':'点击查看费用与来源'} color={color} opacity={dim?.19:1}>
      <rect x={x+1} y={y+1} width={cell-2} height={cell-2} rx="2" fill={free?'white':color} stroke={free?'#5f9b83':'none'} strokeWidth={free?1:0} strokeDasharray={free?'3 2':undefined}/>
      <text x={x+cell/2} y={y+cell/2+4} textAnchor="middle" fontSize={font} fontWeight={free?600:500} fill={free?'#28775e':aggregated?'#355463':t>.54?'white':'#163e31'}>{text}</text>
     </Mark>;
    })}
   </g>;
  })}
  <g transform={`translate(${left} ${top+side+17})`} data-scale-max={maxAmount} aria-label={`色阶上限 ${money(maxAmount)}`}>
   {maxAmount>0&&<><rect width={mobile?54:94} height="7" rx="3.5" fill={`url(#${gradientId}-scale)`}/><text x={mobile?61:102} y="7" className="viz-legend-text">{cellValue(maxAmount)}</text></>}
   <text x={mobile||!maxAmount?0:157} y={mobile&&maxAmount?23:8} className="viz-legend-text" style={{fontSize:mobile?11:12}}>0 免费 · — 未识别{graph.others>0?' · 灰蓝 汇总':''}</text>
  </g>
 </PlotFrame>;
}
