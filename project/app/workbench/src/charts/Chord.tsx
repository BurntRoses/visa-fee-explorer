import {useId,useMemo} from 'react';
import {arc,chordDirected,ribbon as d3Ribbon} from 'd3';
import {AnimatedPath,EmptyPlot,FlowMotion,Mark,PlotFrame,type ChartEvents,type PlotProps} from './common';
import {countryColor,distributeLabels,graphData,labelLines,money,OTHER,shortName,singleCountryGraph,viewNodeCap,type GraphData} from './helpers';

const ROUTE_HIGHLIGHT='flow:';
export function ChordPlot(p:PlotProps&{graph?:GraphData;focus?:string}){
 const {analysis,state,width:w,height:h,events,reducedMotion}=p,mobile=w<600,gradientId=useId().replace(/:/g,'');
 const graph=useMemo(()=>p.graph||(p.focus?singleCountryGraph(analysis,state,w,h):graphData(analysis,{...state,maxNodes:viewNodeCap('chord',w,h,state.maxNodes)},w)),[p.graph,p.focus,analysis,state,w,h]);
 const {nodes,edges}=graph,total=edges.reduce((sum,e)=>sum+e.amount,0),active=events.highlight;
 const activeRoute=active?.startsWith(ROUTE_HIGHLIGHT)?active.slice(ROUTE_HIGHLIGHT.length).split('|'):null;
 const geometry=useMemo(()=>{
  const codes=nodes.map(n=>n.code),matrix=codes.map(()=>codes.map(()=>0));for(const e of edges)matrix[codes.indexOf(e.origin)][codes.indexOf(e.destination)]+=e.amount||Math.max(total*.0005,1);
  const ribbonPad=(c:any)=>Math.min(.003,(c.source.endAngle-c.source.startAngle)*.15,(c.target.endAngle-c.target.startAngle)*.15);
  const chords=chordDirected().padAngle(mobile?.04:.026).sortSubgroups((a,b)=>b-a)(matrix);
  const labelWidth=mobile?w/2-38:Math.min(178,Math.max(112,w*.135)),cx=w/2,r=Math.max(44,Math.min((w-(mobile?28:2*labelWidth+68))/2,(h-(mobile?218:p.focus?138:112))/2)),cy=mobile?r+18:p.focus?r+66:(h-34)/2;
  const focusGroup=chords.groups.find(g=>codes[g.index]===p.focus),largest=focusGroup||[...chords.groups].sort((a,b)=>b.value-a.value)[0],preferred=largest?-(largest.startAngle+largest.endAngle)/2:0;
  // Keep the dominant country above the ring. Partners spread over both sides,
  // rather than piling every label along one semicircle in a single-country view.
  let rotation=preferred;
  if(!focusGroup&&chords.groups.length>3){
   let best=Infinity;
   for(let step=-12;step<=12;step++){
    const candidate=preferred+step*Math.PI/72,angles=chords.groups.map(g=>(g.startAngle+g.endAngle)/2+candidate),left=angles.filter(a=>Math.sin(a)<0).length;
    const crowd=(side:boolean)=>{const yy=angles.filter(a=>(Math.sin(a)<0)===side).map(a=>-Math.cos(a)*(r+20)).sort((a,b)=>a-b);return yy.slice(1).reduce((v,y,i)=>v+Math.pow(Math.max(0,30-(y-yy[i])),2),0);};
    const cost=Math.pow(left-(angles.length-left),2)*65+crowd(true)+crowd(false)+step*step*.3;
    if(cost<best){best=cost;rotation=candidate;}
   }
  }
  const ring=arc<any>().innerRadius(r).outerRadius(r+8),ribbonPath=d3Ribbon<any,any>().radius(r-3).padAngle(ribbonPad),labelSize=mobile?12:13.5;
  const labels=chords.groups.filter(g=>!p.focus||codes[g.index]!==p.focus).map(g=>{const angle=(g.startAngle+g.endAngle)/2+rotation;return {code:codes[g.index],angle,y:cy-Math.cos(angle)*(r+22),left:Math.sin(angle)<0,lines:labelLines(shortName(codes[g.index],nodes[g.index].name),labelWidth,labelSize)};});
  const labelGap=Math.max(29,...labels.map(n=>n.lines.length*16+10)),labelTop=p.focus?72:29,labelBottom=h-61;
  return {chords,cx,cy,r,ring,ribbon:ribbonPath,ribbonPad,rotation,labelWidth,labelSize,labels:[...distributeLabels(labels.filter(n=>n.left),labelTop,labelBottom,labelGap),...distributeLabels(labels.filter(n=>!n.left),labelTop,labelBottom,labelGap)]};
 },[nodes,edges,total,w,h,mobile,p.focus]);
 if(!nodes.length||!edges.length)return <EmptyPlot title={p.focus?`当前${state.singleMode==='origins'?'流入':state.singleMode==='destinations'?'流出':'范围'}没有已识别的费用流`:undefined} detail="所选国家之间尚无已识别金额，可切换与全球往来或加入对手方。"/>;
 const {chords,cx,cy,r,ring,ribbon,ribbonPad,rotation,labelWidth,labelSize,labels}=geometry,nodeMap=new Map(nodes.map(n=>[n.code,n])),edgeMap=new Map(edges.map(e=>[e.origin+'|'+e.destination,e]));
 const related=(c:any)=>!active||(activeRoute?nodes[c.source.index].code===activeRoute[0]&&nodes[c.target.index].code===activeRoute[1]:nodes[c.source.index].code===active||nodes[c.target.index].code===active);
 const nodeRelated=(code:string)=>!active||(activeRoute?activeRoute.includes(code):code===active||edges.some(e=>(e.origin===active&&e.destination===code)||(e.destination===active&&e.origin===code)));
 const nodeActive=(code:string)=>activeRoute?activeRoute.includes(code):active===code;
 // A ribbon represents one directed pair. Highlight that pair, not every ribbon
 // sharing the focus country as its payer in the single-country chart.
 const routeEvents=(origin:string,destination:string):ChartEvents=>({...events,setHighlight:code=>events.setHighlight(code?ROUTE_HIGHLIGHT+origin+'|'+destination:null)});
 const ordered=[...chords].sort((a,b)=>{const aa=related(a),bb=related(b);if(active&&aa!==bb)return aa?1:-1;return b.source.value-a.source.value;});
 const focusNode=nodes.find(n=>n.code===p.focus),focusName=focusNode?.name,modeName=state.singleMode==='origins'?'付款来源':state.singleMode==='destinations'?'支出去向':'双向费用';
 const nodeDetail=(node:typeof nodes[number])=>`收到${node.incomingKnown?money(node.incoming):'未识别'} · 付出${node.outgoingKnown?money(node.outgoing):'未识别'}`;
 return <PlotFrame width={w} height={h} view={p.focus?'single-chord':'chord'} resetKey={p.focus?`${p.focus}-${state.singleMode}`:undefined} title={p.focus?`${focusName}签证费${modeName}环形流向`:'国家／地区之间的签证费环形流向'} description="半透明色带连接申请人来源与收款方，颜色从付款端渐变到收款端；圆弧按收到与付出合计分配，色带宽度按金额。流光持续从付款端移向收款端。悬停色带高亮单条路线，点击国家／地区锁定相关往来。">
  <defs>{ordered.map(c=>{const source=nodes[c.source.index],destination=nodes[c.target.index],sa=(c.source.startAngle+c.source.endAngle)/2,ta=(c.target.startAngle+c.target.endAngle)/2;return <linearGradient key={source.code+'-'+destination.code} id={`${gradientId}-${c.source.index}-${c.target.index}`} gradientUnits="userSpaceOnUse" x1={Math.sin(sa)*r} y1={-Math.cos(sa)*r} x2={Math.sin(ta)*r} y2={-Math.cos(ta)*r}><stop offset="0%" stopColor={countryColor(source.code)}/><stop offset="100%" stopColor={countryColor(destination.code)} stopOpacity=".86"/></linearGradient>;})}</defs>
  <g transform={`translate(${cx} ${cy}) rotate(${rotation*180/Math.PI})`}>
   {ordered.map(c=>{const source=nodes[c.source.index],destination=nodes[c.target.index],e=edgeMap.get(source.code+'|'+destination.code)!;if(!e.amount)return null;const d=(ribbon as unknown as (datum:any)=>string|null)(c)||'',visible=related(c),pad=ribbonPad(c),sa=(c.source.startAngle+c.source.endAngle)/2,ta=(c.target.startAngle+c.target.endAngle)/2,sr=(r-3)*Math.cos((c.source.endAngle-c.source.startAngle-pad)/2),tr=(r-3)*Math.cos((c.target.endAngle-c.target.startAngle-pad)/2),centerline=`M${Math.sin(sa)*sr} ${-Math.cos(sa)*sr} Q0 0 ${Math.sin(ta)*tr} ${-Math.cos(ta)*tr}`;return <Mark key={e.id} events={routeEvents(source.code,destination.code)} origin={source.code} destination={destination.code} data-origin={source.code} data-destination={destination.code} data-amount={e.amount} data-highlighted={active?visible:'none'} members={[...(source.code===OTHER||source.code.startsWith('REG_')?source.members:[]),...(destination.code===OTHER||destination.code.startsWith('REG_')?destination.members:[])]} title={`${source.name}申请人 → ${destination.name}收款方`} amount={e.amount} detail="点击查看费用与来源" color={countryColor(source.code)} className="viz-chord-link" opacity={active&&!visible?.045:1}>
    <AnimatedPath className="viz-chord-band" d={d} reduced={reducedMotion} fill={`url(#${gradientId}-${c.source.index}-${c.target.index})`} fillOpacity={active&&visible?.93:.46}/>
    <FlowMotion d={centerline} clipD={d} origin={source.code} destination={destination.code} color={countryColor(source.code)} active={!!active&&visible} reduced={reducedMotion} enabled={state.flowLight}/>
   </Mark>;})}
   {state.showFree&&edges.filter(e=>e.amount===0&&e.origin!==e.destination).map(e=>{const source=chords.groups[nodes.findIndex(n=>n.code===e.origin)],target=chords.groups[nodes.findIndex(n=>n.code===e.destination)];if(!source||!target)return null;const sa=(source.startAngle+source.endAngle)/2,ta=(target.startAngle+target.endAngle)/2,d=`M${Math.sin(sa)*(r-5)} ${-Math.cos(sa)*(r-5)} Q0 0 ${Math.sin(ta)*(r-5)} ${-Math.cos(ta)*(r-5)}`,visible=!active||(activeRoute?e.origin===activeRoute[0]&&e.destination===activeRoute[1]:e.origin===active||e.destination===active);return <Mark key={'free'+e.id} title={`${nodeMap.get(e.origin)?.name} → ${nodeMap.get(e.destination)?.name}`} amount={0} detail="已知免费路线" events={routeEvents(e.origin,e.destination)} origin={e.origin} destination={e.destination} opacity={visible?1:.12}><path d={d} fill="none" stroke="#729889" strokeWidth="1.5" strokeDasharray="3 5"/></Mark>;})}
   {chords.groups.map(g=>{const n=nodes[g.index];return <Mark key={n.code} events={events} code={n.code} data-node-code={n.code} data-node-weight={n.amount} data-arc-start={g.startAngle} data-arc-end={g.endAngle} data-related={nodeRelated(n.code)} data-active={nodeActive(n.code)} members={n.members} title={n.name} amount={n.amount} detail={nodeDetail(n)} color={countryColor(n.code)} className="viz-chord-node" opacity={nodeRelated(n.code)?1:.22}><AnimatedPath d={ring(g)||''} reduced={reducedMotion} fill={countryColor(n.code)}/></Mark>;})}
  </g>
  {mobile?nodes.map((node,i)=>{const x=14+(i%2)*(w/2),y=cy+r+32+Math.floor(i/2)*27;return <Mark key={'legend'+node.code} events={events} code={node.code} members={node.members} title={node.name} amount={node.amount} detail={nodeDetail(node)} color={countryColor(node.code)} data-active={nodeActive(node.code)} className="viz-chord-label" opacity={nodeRelated(node.code)?1:.3}><rect x={x-6} y={y-15} width={w/2-12} height={25} rx={5} fill="transparent" className="viz-label-surface"/><circle cx={x} cy={y-3} r={3} fill={countryColor(node.code)}/><text x={x+10} y={y+1} className="viz-node-label" fontSize={12}>{shortName(node.code,node.name).length>Math.floor((w/2-35)/12)?labelLines(shortName(node.code,node.name),w/2-35,12)[0]+'…':shortName(node.code,node.name)}</text></Mark>;}):<>
   {focusNode&&<Mark events={events} code={focusNode.code} members={focusNode.members} title={focusNode.name} amount={focusNode.amount} detail={nodeDetail(focusNode)} color={countryColor(focusNode.code)} data-active={nodeActive(focusNode.code)} className="viz-chord-label viz-focus-label" opacity={nodeRelated(focusNode.code)?1:.3}><rect x={cx-75} y={cy-r-37} width={150} height={26} rx={6} fill="transparent" className="viz-label-surface"/><text x={cx} y={cy-r-18} textAnchor="middle" className="viz-node-label" fontSize={14}>{shortName(focusNode.code,focusNode.name)}</text></Mark>}
   {labels.map(n=>{const node=nodeMap.get(n.code)!,tx=n.left?cx-r-29:cx+r+29,anchor=n.left?'end':'start',textHeight=n.lines.length*16,textTop=n.y-(textHeight-16)/2;return <Mark key={'label'+n.code} events={events} code={n.code} members={node.members} title={node.name} amount={node.amount} detail={nodeDetail(node)} color={countryColor(n.code)} data-active={nodeActive(n.code)} className="viz-chord-label" opacity={nodeRelated(node.code)?1:.3}>
    <path d={`M${cx+Math.sin(n.angle)*(r+10)} ${cy-Math.cos(n.angle)*(r+10)} L${cx+Math.sin(n.angle)*(r+19)} ${cy-Math.cos(n.angle)*(r+19)} L${n.left?tx+8:tx-8} ${n.y}`} fill="none" stroke={nodeActive(node.code)?countryColor(node.code):'#b6c7c8'} strokeWidth={nodeActive(node.code)?1.4:.85} pointerEvents="none"/>
    <rect x={n.left?tx-labelWidth-6:tx-6} y={textTop-13} width={labelWidth+12} height={textHeight+10} rx={6} fill="transparent" className="viz-label-surface"/>
    <text x={tx} y={textTop+4} textAnchor={anchor} className="viz-node-label" fontSize={labelSize}>{n.lines.map((line,i)=><tspan key={i} x={tx} dy={i?16:0}>{line}</tspan>)}</text>
   </Mark>;})}
  </>}
 </PlotFrame>;
}
