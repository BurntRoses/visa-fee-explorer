import {useId,useMemo} from 'react';
import {sankey,sankeyLinkHorizontal} from 'd3-sankey';
import {AnimatedPath,EmptyPlot,FlowMotion,Mark,PlotFrame,type PlotProps} from './common';
import {countryColor,distributeLabels,fitLabel,money,OTHER,shortMoney,shortName} from './helpers';
import {bilateralMembers,globalSankeyGraph} from './bilateral';

export function SankeyPlot(p:PlotProps){
 const {analysis,state,width:w,height:h,events,reducedMotion}=p,mobile=w<600,gradientId=useId().replace(/:/g,'');
 const data=useMemo(()=>{
  const graph=globalSankeyGraph(analysis,state,w,h),positive=graph.edges.filter(e=>e.amount>0);
  const padding=mobile?91:184,left=padding,right=w-padding,top=mobile?66:51,bottom=h-65;
  if(!positive.length)return null;
  const sourceNodes=graph.sources.filter(n=>n.amount>0),targetNodes=graph.targets.filter(n=>n.amount>0);
  const input={nodes:[...sourceNodes.map((n,rank)=>({...n,id:'s:'+n.code,side:'source',rank})),...targetNodes.map((n,rank)=>({...n,id:'t:'+n.code,side:'target',rank}))],links:positive.map(e=>({source:'s:'+e.origin,target:'t:'+e.destination,value:e.amount,edge:e}))};
  const maxRows=Math.max(sourceNodes.length,targetNodes.length),gap=Math.min(mobile?16:18,Math.max(7,(bottom-top)/Math.max(1,maxRows)*.43));
  const layout=sankey<any,any>().nodeId(d=>d.id).nodeWidth(mobile?9:11).nodePadding(gap).nodeSort((a,b)=>a.rank-b.rank).extent([[left,top],[right,bottom]])(input as any);
  const sourceLabels=distributeLabels(layout.nodes.filter(n=>n.side==='source').map(node=>({node,y:(node.y0!+node.y1!)/2})),top+8,bottom-8,mobile?28:29);
  const targetLabels=distributeLabels(layout.nodes.filter(n=>n.side==='target').map(node=>({node,y:(node.y0!+node.y1!)/2})),top+8,bottom-8,mobile?28:29);
  const name=(code:string,side:'source'|'target')=>(side==='source'?sourceNodes:targetNodes).find(n=>n.code===code)!;
  return {graph,layout,labels:[...sourceLabels,...targetLabels],total:positive.reduce((sum,e)=>sum+e.amount,0),padding,left,right,name};
 },[analysis,state,w,h,mobile]);
 if(!data)return <EmptyPlot detail="所选范围暂无正金额费用流。已知免费方向可在热图中查看。"/>;
 const linkGen=sankeyLinkHorizontal(),highlight=events.highlight,links=[...data.layout.links].sort((a:any,b:any)=>{
  const aa=!highlight||a.source.code===highlight||a.target.code===highlight,bb=!highlight||b.source.code===highlight||b.target.code===highlight;
  return aa!==bb?(aa?1:-1):b.value-a.value;
 });
 return <PlotFrame width={w} height={h} view="sankey" title="签证费从申请人流向收款政府" description={`两侧分别按付款和收款金额排列，左侧为申请人来源，右侧为政府。其余国家保留在聚合中，未知国籍单列。线宽按金额，每条费用流计一次，合计${money(data.total)}。`}>
  <defs>{links.map((link:any,i:number)=><linearGradient key={link.edge.id} id={`${gradientId}-flow-${i}`} gradientUnits="userSpaceOnUse" x1={data.left} y1="0" x2={data.right} y2="0"><stop offset="0" stopColor={countryColor(link.source.code)}/><stop offset="1" stopColor={countryColor(link.target.code)}/></linearGradient>)}</defs>
  <text x="12" y={mobile?45:23} className="viz-chart-title">申请人付出</text><text x={w-12} y={mobile?45:23} textAnchor="end" className="viz-chart-title">政府收到</text>
  {links.map((link:any,i:number)=>{
   const e=link.edge,source=link.source.code,destination=link.target.code,dim=!!highlight&&source!==highlight&&destination!==highlight,d=linkGen(link)||'',color=countryColor(source),half=Math.max(.7,link.width)/2,sx=link.source.x1,tx=link.target.x0,sy=link.y0,ty=link.y1,mx=(sx+tx)/2,clipD=`M${sx} ${sy-half} C${mx} ${sy-half} ${mx} ${ty-half} ${tx} ${ty-half} L${tx} ${ty+half} C${mx} ${ty+half} ${mx} ${sy+half} ${sx} ${sy+half} Z`;
   return <Mark key={e.id} events={events} origin={source} destination={destination} data-origin={source} data-destination={destination} data-amount={e.amount} data-flow-width={link.width} members={bilateralMembers(data.name(source,'source'),data.name(destination,'target'))} title={`${link.source.name}申请人 → ${link.target.name}政府`} amount={e.amount} detail="点击查看费用与来源" color={color} opacity={dim?.09:1}>
    <path d={d} fill="none" stroke="transparent" strokeWidth={Math.max(12,link.width)}/><AnimatedPath d={d} reduced={reducedMotion} fill="none" stroke={`url(#${gradientId}-flow-${i})`} strokeOpacity={highlight?.76:.47} strokeWidth={Math.max(.7,link.width)}/><FlowMotion d={d} clipD={clipD} origin={source} destination={destination} color={color} active={!!highlight&&!dim} reduced={reducedMotion} enabled={state.flowLight}/>
   </Mark>;
  })}
  {data.layout.nodes.map((n:any)=>{
   const dim=!!highlight&&highlight!==n.code&&!links.some((l:any)=>(l.source.code===highlight&&l.target.code===n.code)||(l.target.code===highlight&&l.source.code===n.code));
   return <Mark key={n.id} events={events} code={n.code} data-node-code={n.code} data-side={n.side} data-node-amount={n.value} data-members={n.members.join(',')} members={n.members} title={`${n.name} · ${n.side==='source'?'申请人付出':'政府收到'}`} amount={n.value} detail={n.code===OTHER?'查看这一侧的聚合成员':'点击锁定高亮'} color={countryColor(n.code)} opacity={dim?.2:1}>
    <rect x={n.x0-4} y={n.y0-3} width={n.x1-n.x0+8} height={Math.max(8,n.y1-n.y0+6)} rx="4" fill="transparent" className="viz-node-surface"/><rect x={n.x0} y={n.y0} width={n.x1-n.x0} height={Math.max(2,n.y1-n.y0)} rx="2" fill={countryColor(n.code)}/>
   </Mark>;
  })}
  {data.labels.map(({node:n,y}:any)=>{
   const left=n.side==='source',x=left?data.padding-16:w-data.padding+16,anchor=left?'end':'start',cy=(n.y0+n.y1)/2,available=data.padding-26,name=fitLabel(n.code===OTHER?`其余${n.members.length}国`:shortName(n.code,n.name),available,mobile?12:13),dim=!!highlight&&highlight!==n.code&&!links.some((l:any)=>(l.source.code===highlight&&l.target.code===n.code)||(l.target.code===highlight&&l.source.code===n.code));
   return <Mark key={n.id+'label'} events={events} code={n.code} members={n.members} title={`${n.name} · ${left?'申请人付出':'政府收到'}`} amount={n.value} detail={n.code===OTHER?'查看这一侧的聚合成员':'点击锁定高亮'} color={countryColor(n.code)} opacity={dim?.3:1}>
    {Math.abs(y-cy)>5&&<path d={`M${left?n.x0-3:n.x1+3} ${cy} L${left?x+5:x-5} ${y}`} fill="none" stroke="#bccdca" strokeWidth=".8" pointerEvents="none"/>}
    <rect x={left?7:x-3} y={y-14} width={available+6} height="28" rx="5" fill="transparent" className="viz-label-surface"/>
    <text x={x} y={y+(mobile?1:-2)} textAnchor={anchor} className="viz-node-label" fontSize={mobile?12:13}>{name}</text>
    {!mobile&&<text x={x} y={y+12} textAnchor={anchor} fill="#6a827d" fontSize="10.5" fontVariant="tabular-nums">{shortMoney(n.value)}</text>}
   </Mark>;
  })}
 </PlotFrame>;
}
