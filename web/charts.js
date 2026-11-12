(function () {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const colors = {blue:'var(--blue)',orange:'var(--orange)',green:'var(--green)',gray:'var(--gray)',purple:'var(--purple)'};
  const number = fact => fact && fact.valueDecimal !== null && Number.isFinite(Number(fact.valueDecimal)) ? Number(fact.valueDecimal) : null;
  function node(tag, parent, attrs, text) {
    const value = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([key,item]) => value.setAttribute(key, String(item)));
    if (text !== undefined) value.textContent = String(text);
    parent.appendChild(value);
    return value;
  }
  function svg(parent, className, title) {
    const result=node('svg',parent,{class:'chart '+className,role:'img',viewBox:'0 0 1000 400'});
    node('title',result,{},title);
    result.cache=new Map();
    return result;
  }
  function item(root, tag, key, attrs, text) {
    let value=root.cache.get(key);
    if(!value){value=node(tag,root,{});root.cache.set(key,value);}
    value._seen=true;
    Object.entries(attrs||{}).forEach(([name,entry])=>value.setAttribute(name,String(entry)));
    value.setAttribute('visibility','visible');
    if(text!==undefined)value.textContent=String(text);
    return value;
  }
  function start(root, width, height){root.setAttribute('viewBox',`0 0 ${width} ${height}`);root.cache.forEach(value=>value._seen=false);}
  function finish(root){root.cache.forEach(value=>{if(!value._seen)value.setAttribute('visibility','hidden');});}
  function animate(value, next, reduced) {
    if(value._frame)cancelAnimationFrame(value._frame);
    const previous={};Object.keys(next).forEach(key=>previous[key]=Number(value.getAttribute(key)));
    const instant=reduced||!value._painted||Object.values(previous).some(v=>!Number.isFinite(v));
    if(instant){Object.entries(next).forEach(([key,v])=>value.setAttribute(key,v));value._painted=true;return;}
    const started=performance.now();
    function tick(time){const progress=Math.max(0,Math.min(1,(time-started)/480)),t=1-Math.pow(1-progress,3);Object.entries(next).forEach(([key,v])=>value.setAttribute(key,previous[key]+(v-previous[key])*t));if(progress<1)value._frame=requestAnimationFrame(tick);}
    value._frame=requestAnimationFrame(tick);
  }
  function ribbonPath(g){const [x0,x1,y0,y1,h]=g,mid=(x0+x1)/2;return `M ${x0} ${y0} C ${mid} ${y0} ${mid} ${y1} ${x1} ${y1} L ${x1} ${y1+h} C ${mid} ${y1+h} ${mid} ${y0+h} ${x0} ${y0+h} Z`;}
  function ribbon(root,key,geometry,color,reduced){
    const value=item(root,'path',key,{fill:color,opacity:.2});
    if(value._frame)cancelAnimationFrame(value._frame);
    const previous=value._geometry||geometry;value._geometry=geometry;
    if(reduced){value.setAttribute('d',ribbonPath(geometry));return;}
    const started=performance.now();function tick(time){const p=Math.max(0,Math.min(1,(time-started)/480)),t=1-Math.pow(1-p,3);value.setAttribute('d',ribbonPath(geometry.map((v,i)=>previous[i]+(v-previous[i])*t)));if(p<1)value._frame=requestAnimationFrame(tick);}value._frame=requestAnimationFrame(tick);
  }
  function focusAttrs(fact,label){return fact?{'data-fact':fact.factId,'data-label':label,tabindex:0,role:'button','aria-label':label+' '+fact.displayValue,class:'chart-node'}:{class:'chart-node'};}
  function titleFor(group, value){let title=group.querySelector('title');if(!title)title=node('title',group,{});title.textContent=value;}
  function factBox(root,key,fact,label,x,y,width,height,color,reduced,maxValue){
    if(!fact)return;
    const group=item(root,'g',key,focusAttrs(fact,label));
    if(!group._rect){group._rect=node('rect',group,{rx:3,class:'node-outline plot-shape'});group._label=node('text',group,{class:'chart-label'});group._value=node('text',group,{class:'chart-value'});}
    group._rect.setAttribute('fill',color);group._rect.setAttribute('fill-opacity','.16');
    animate(group._rect,{x,y,width,height},reduced);
    group._label.setAttribute('x',x+13);group._label.setAttribute('y',y+22);group._label.textContent=label;
    group._value.setAttribute('x',x+13);group._value.setAttribute('y',y+47);group._value.textContent=fact.shortValue;
    if(maxValue){if(!group._bar)group._bar=node('rect',group,{rx:1,fill:color,'fill-opacity':'.75'});animate(group._bar,{x:x+13,y:y+height-7,width:Math.max(1,(width-26)*Math.min(1,Math.abs(number(fact)||0)/maxValue)),height:3},reduced);}
    titleFor(group,label+' · '+fact.displayValue);
  }
  function maxMetric(report,key){return Math.max(1,...report.periods.map(p=>Math.abs(number(p.metrics[key])||0)));}
  function stableBusiness(period){return period.business.status==='conflict'?[]:(period.business.items||[]).slice().sort((a,b)=>a.id.localeCompare(b.id));}
  function businessColor(fact){const key=(fact.presentation||{}).color;return Object.prototype.hasOwnProperty.call(colors,key)?colors[key]:colors.blue;}
  function businessLabel(fact,L){const key=(fact.presentation||{}).labelKey;return key&&typeof L[key]==='string'?L[key]:fact.name;}
  function profit(root,p,report,basis,L,reduced){
    start(root,1000,360);const m=p.metrics,rev=number(m.revenue),scale=190/(basis==='share'?Math.max(1,rev||1):maxMetric(report,'revenue'));
    const right=[['cost_of_revenue',colors.gray],['operating_expenses',colors.gray],['operating_income',colors.blue]];
    if(!rev||rev<0||right.some(([key])=>number(m[key])===null||number(m[key])<0)){
      finish(root);bars(root,['revenue','gross_profit','operating_income','net_income'].map(key=>({fact:m[key],label:L[key]})),1000,300,L,reduced);return;
    }
    const sources=stableBusiness(p);const totalHeight=rev*scale;const revY=(295-totalHeight)/2+5;
    const centerX=470,rightX=975;
    const revNode=item(root,'g','revenue',focusAttrs(m.revenue,L.revenue));if(!revNode._rect)revNode._rect=node('rect',revNode,{fill:colors.blue,rx:1});animate(revNode._rect,{x:centerX,y:revY,width:11,height:totalHeight},reduced);
    item(root,'text','revenue-label',{x:centerX-9,y:revY-16,'text-anchor':'end',class:'chart-label'},L.revenue);
    item(root,'text','revenue-value',{x:centerX-9,y:revY+5,'text-anchor':'end',class:'chart-value','data-fact':m.revenue.factId,tabindex:0,role:'button'},basis==='share'?m.revenue.shareDisplay:m.revenue.shortValue);
    let offset=0;const sourcesHeight=totalHeight+Math.max(0,sources.length-1)*32;let sy=(295-sourcesHeight)/2+5;
    sources.forEach(fact=>{const h=Math.max(0,number(fact))*scale,color=businessColor(fact);ribbon(root,'in-'+fact.id,[24,centerX,sy,revY+offset,h],color,reduced);const g=item(root,'g','source-'+fact.id,focusAttrs(fact,fact.name));if(!g._rect)g._rect=node('rect',g,{fill:color,rx:1});animate(g._rect,{x:13,y:sy,width:11,height:h},reduced);item(root,'text','source-name-'+fact.id,{x:36,y:sy+Math.max(15,h/2-4),class:'chart-label'},fact.name);item(root,'text','source-value-'+fact.id,{x:36,y:sy+Math.max(35,h/2+18),class:'chart-value','data-fact':fact.factId,tabindex:0,role:'button'},basis==='share'?fact.shareDisplay:fact.shortValue);offset+=h;sy+=h+32;});
    offset=0;let ry=(295-totalHeight-64)/2+5;
    right.forEach(([key,color])=>{const fact=m[key],h=number(fact)*scale;ribbon(root,'out-'+key,[centerX+11,rightX,revY+offset,ry,h],color,reduced);const g=item(root,'g','target-'+key,focusAttrs(fact,L[key]));if(!g._rect)g._rect=node('rect',g,{fill:color,rx:1});animate(g._rect,{x:rightX,y:ry,width:11,height:h},reduced);item(root,'text','target-name-'+key,{x:rightX-14,y:ry+Math.max(15,h/2-3),'text-anchor':'end',class:'chart-label'},L[key]);item(root,'text','target-value-'+key,{x:rightX-14,y:ry+Math.max(34,h/2+19),'text-anchor':'end',class:'chart-value','data-fact':fact.factId,tabindex:0,role:'button'},basis==='share'?fact.shareDisplay:fact.shortValue);offset+=h;ry+=h+32;});
    finish(root);
  }
  function bars(root, entries,width,height,L,reduced){
    root.style.minWidth='';root.removeAttribute('data-waterfall-width');
    start(root,width,height);const valid=entries.filter(x=>x.fact&&number(x.fact)!==null);const max=Math.max(1,...valid.map(x=>Math.abs(number(x.fact))));const hasNegative=valid.some(x=>number(x.fact)<0),left=hasNegative?width*.51:width*.28,right=width-20,space=(height-40)/Math.max(1,valid.length),usable=hasNegative?width*.36:width*.63;
    item(root,'line','zero',{x1:left,x2:left,y1:12,y2:height-18,stroke:'var(--line)'});
    valid.forEach((entry,i)=>{const value=number(entry.fact),w=Math.abs(value)/max*usable,y=15+i*space;const rect=item(root,'rect','bar-'+entry.fact.factId,{fill:value<0?colors.orange:colors.blue,opacity:.65,rx:1,'data-fact':entry.fact.factId,tabindex:0,role:'button','aria-label':entry.label+' '+entry.fact.displayValue});animate(rect,{x:value<0?left-w:left,y,width:w,height:Math.min(32,space-24)},reduced);item(root,'text','bar-label-'+entry.fact.factId,{x:12,y:y+12,class:'chart-label'},entry.label);item(root,'text','bar-value-'+entry.fact.factId,{x:right,y:y+15,'text-anchor':'end',class:'chart-number-small','data-fact':entry.fact.factId,tabindex:0,role:'button'},entry.fact.shortValue);});finish(root);
  }
  function waterfall(root,steps,facts,width,height,L,reduced,shortLabels){
    root.style.minWidth=width+'px';root.setAttribute('data-waterfall-width',String(width));
    start(root,width,height);const max=Math.max(1,...steps.flatMap(s=>[Math.abs(Number(s.startDecimal)),Math.abs(Number(s.endDecimal))]));const min=Math.min(0,...steps.flatMap(s=>[Number(s.startDecimal),Number(s.endDecimal)]));const top=20,plotH=height-105,range=max-min||1,py=value=>top+(max-value)/range*plotH;const slot=(width-40)/steps.length,bw=Math.min(64,slot*.65);const zeroY=py(0);
    item(root,'line','zero',{x1:20,x2:width-15,y1:zeroY,y2:zeroY,stroke:'var(--line)'});
    steps.forEach((step,i)=>{const startV=Number(step.startDecimal),endV=Number(step.endDecimal),fact=facts[step.factId],x=20+i*slot+(slot-bw)/2,y=Math.min(py(startV),py(endV)),h=Math.max(1,Math.abs(py(startV)-py(endV))),color=step.kind==='total'?colors.blue:(endV>=startV?colors.green:colors.orange),fullLabel=L[step.key]||step.key;const g=item(root,'g','step-'+i,focusAttrs(fact,fullLabel));if(!g._rect)g._rect=node('rect',g,{rx:1});g._rect.setAttribute('fill',color);g._rect.setAttribute('opacity','.65');animate(g._rect,{x,y,width:bw,height:h},reduced);const label=shortLabels&&shortLabels[step.key]||fullLabel,chunk=shortLabels?6:8,fullAttrs=shortLabels?{'data-fact':step.factId,'data-label':fullLabel,tabindex:0,role:'button','aria-label':fullLabel+' '+(fact?fact.displayValue:step.displayValue)}:{};const labelNode=item(root,'text','step-label-'+i,{x:x+bw/2,y:height-50,'text-anchor':'middle',class:'chart-small',...fullAttrs});labelNode.replaceChildren();const characters=Array.from(label);for(let offset=0;offset<characters.length;offset+=chunk)node('tspan',labelNode,{x:x+bw/2,dy:offset?13:0},characters.slice(offset,offset+chunk).join(''));const valueNode=item(root,'text','step-value-'+i,{x:x+bw/2,y:Math.max(13,y-8),'text-anchor':'middle',class:'chart-small','data-fact':step.factId,tabindex:0,role:'button',...(shortLabels?{'data-label':fullLabel,'aria-label':fullLabel+' '+(fact?fact.displayValue:step.displayValue)}:{})},fact?fact.shortValue:step.displayValue);if(shortLabels){titleFor(g,fullLabel+' · '+(fact?fact.displayValue:step.displayValue));titleFor(labelNode,fullLabel);titleFor(valueNode,fullLabel+' · '+(fact?fact.displayValue:step.displayValue));}if(i<steps.length-1)item(root,'line','connector-'+i,{x1:x+bw,x2:20+(i+1)*slot+(slot-bw)/2,y1:py(endV),y2:py(endV),stroke:'var(--gray)','stroke-dasharray':'3 3',opacity:.45});});finish(root);
  }
  function cash(root,p,report,L,reduced,view){
    const recon=view==='reconciliation',source=recon?p.reconciliation:p.cash;
    if(source.steps&&source.steps.length){waterfall(root,source.steps,report.facts,Math.max(1000,source.steps.length*130),330,L,reduced);return;}
    const keys=recon?['net_income','cfo']:['cfo','cfi','cff'];bars(root,keys.map(key=>({fact:p.metrics[key],label:L[key]})),1000,270,L,reduced);
  }
  function balance(root,p,report,basis,L,reduced){
    start(root,490,285);const m=p.metrics,assets=number(m.assets),liabilities=number(m.liabilities),equity=number(m.equity);
    if(assets===null||assets<=0||[liabilities,equity].some(v=>v===null||v<0)){finish(root);bars(root,['assets','liabilities','equity'].map(key=>({fact:m[key],label:L[key]})),490,270,L,reduced);return;}
    const w=195,h=182,y=55,lx=5,rx=280;
    [['assets',lx,y,w,h,colors.blue],['liabilities',rx,y,w,h*(liabilities/assets),colors.gray],['equity',rx,y+h*(liabilities/assets),w,h*(equity/assets),colors.green]].forEach(([key,x,ny,nw,nh,color])=>{const fact=m[key],g=item(root,'g','balance-'+key,focusAttrs(fact,L[key]));if(!g._rect){g._rect=node('rect',g,{rx:1,class:'node-outline'});g._label=node('text',g,{class:'chart-label','text-anchor':'middle'});g._value=node('text',g,{class:'chart-number-small','text-anchor':'middle'});}g._rect.setAttribute('fill',color);g._rect.setAttribute('fill-opacity','.24');animate(g._rect,{x,y:ny,width:nw,height:nh},reduced);g._label.setAttribute('x',x+nw/2);g._label.setAttribute('y',ny+nh/2-4);g._label.textContent=L[key];g._value.setAttribute('x',x+nw/2);g._value.setAttribute('y',ny+nh/2+17);g._value.textContent=basis==='share'?fact.assetShareDisplay:fact.shortValue;});
    item(root,'text','equal',{x:245,y:150,'text-anchor':'middle',class:'chart-value'},'=');finish(root);
  }
  function business(root,p,report,basis,L,reduced){
    start(root,490,285);const items=stableBusiness(p),revenue=number(p.metrics.revenue);if(!items.length||!revenue){item(root,'text','empty',{x:245,y:145,'text-anchor':'middle',class:'chart-small'},L.businessMissing);finish(root);return;}
    const w=480,h=182,x=5,y=55;let offset=0;
    items.forEach(fact=>{const share=Number(fact.shareDecimal)/100,nw=w*share,g=item(root,'g','business-'+fact.id,focusAttrs(fact,fact.name));if(!g._rect){g._rect=node('rect',g,{class:'node-outline'});g._label=node('text',g,{class:'chart-small','text-anchor':'middle'});g._value=node('text',g,{class:'chart-number-small','text-anchor':'middle'});}g._rect.setAttribute('fill',businessColor(fact));g._rect.setAttribute('fill-opacity','.24');animate(g._rect,{x:x+offset,y,width:nw,height:h},reduced);const label=businessLabel(fact,L);g._label.setAttribute('x',x+offset+nw/2);g._label.setAttribute('y',y+h/2-5);g._label.textContent=label;g._value.setAttribute('x',x+offset+nw/2);g._value.setAttribute('y',y+h/2+17);g._value.textContent=basis==='share'?fact.shareDisplay:fact.shortValue;offset+=nw;});finish(root);
  }
  function scene(root,p,report,L,reduced){
    start(root,1000,385);const m=p.metrics;
    item(root,'text','left-head',{x:8,y:22,class:'chart-label'},L.beginning_balance);
    item(root,'text','center-head',{x:374,y:22,class:'chart-label'},L.current_activity);
    item(root,'text','right-head',{x:760,y:22,class:'chart-label'},L.ending_balance);
    const drawLink=(key,x0,y0,x1,y1,color,kind)=>item(root,'path',key,{d:`M ${x0} ${y0} C ${(x0+x1)/2} ${y0} ${(x0+x1)/2} ${y1} ${x1} ${y1}`,fill:'none',stroke:color,'stroke-width':kind==='cash'?2:1.3,'stroke-dasharray':kind==='cash'?'':'5 5',opacity:.55});
    item(root,'path','assets-link',{d:'M 236 84 C 282 84 282 37 331 37 L 665 37 C 714 37 714 84 760 84',fill:'none',stroke:colors.gray,'stroke-width':1.3,'stroke-dasharray':'5 5',opacity:.55});
    item(root,'path','cash-balance',{d:'M 236 315 C 320 375 676 375 760 315',fill:'none',stroke:colors.blue,'stroke-width':1.3,'stroke-dasharray':'5 5',opacity:.45});
    drawLink('cash-out',613,191,760,291,colors.blue,'cash');
    drawLink('profit-cfo',487,114,487,157,colors.purple,'reference');
    drawLink('profit-equity',613,80,760,210,colors.gray,'reference');
    factBox(root,'begin-assets',m.begin_assets,L.assets,8,51,228,66,colors.blue,reduced,Math.max(maxMetric(report,'assets'),maxMetric(report,'begin_assets')));
    factBox(root,'begin-liabilities',m.begin_liabilities,L.liabilities,8,132,228,59,colors.gray,reduced,Math.max(maxMetric(report,'liabilities'),maxMetric(report,'begin_liabilities')));
    factBox(root,'begin-equity',m.begin_equity,L.equity,8,206,228,59,colors.green,reduced,Math.max(maxMetric(report,'equity'),maxMetric(report,'begin_equity')));
    factBox(root,'begin-cash',m.cash_begin,L.cash_begin,8,280,228,66,colors.blue,reduced,Math.max(maxMetric(report,'cash_begin'),maxMetric(report,'cash_end')));
    factBox(root,'period-profit',m.net_income,L.net_income,362,51,251,66,colors.green,reduced,maxMetric(report,'net_income'));
    factBox(root,'period-cfo',m.cfo,L.cfo,362,157,251,66,colors.blue,reduced,maxMetric(report,'cfo'));
    factBox(root,'ending-assets',m.assets,L.assets,760,51,228,66,colors.blue,reduced,Math.max(maxMetric(report,'assets'),maxMetric(report,'begin_assets')));
    factBox(root,'ending-liabilities',m.liabilities,L.liabilities,760,132,228,59,colors.gray,reduced,Math.max(maxMetric(report,'liabilities'),maxMetric(report,'begin_liabilities')));
    factBox(root,'ending-equity',m.equity,L.equity,760,206,228,59,colors.green,reduced,Math.max(maxMetric(report,'equity'),maxMetric(report,'begin_equity')));
    factBox(root,'ending-cash',m.cash_end,L.cash_end,760,280,228,66,colors.blue,reduced,Math.max(maxMetric(report,'cash_begin'),maxMetric(report,'cash_end')));
    item(root,'text','profit-cfo-label',{x:501,y:140,class:'chart-small'},L.noncash_adjustments);
    item(root,'text','balance-reference',{x:636,y:111,class:'chart-small'},L.balance_reference);
    item(root,'text','cash-balance-label',{x:487,y:378,'text-anchor':'middle',class:'chart-small'},L.cash_balance_reference);
    const extras=[['cfi',L.cfi],['cff',L.cff],['fx',L.fx]];
    extras.forEach(([key,label],i)=>{const y=258+i*32,fact=m[key];item(root,'text','cash-extra-label-'+key,{x:365,y,class:'chart-small'},label);const text=item(root,'text','cash-extra-value-'+key,{x:613,y,'text-anchor':'end',class:'chart-number-small',...(fact?{'data-fact':fact.factId,tabindex:0,role:'button'}:{})},fact?fact.shortValue:L.unknown);text.setAttribute('opacity',fact?1:.55);});
    finish(root);
  }
  function trend(root,points,L){
    root.replaceChildren();root.setAttribute('viewBox','0 0 550 125');const known=points.filter(x=>x.fact&&number(x.fact)!==null);if(!known.length)return;
    const values=known.map(x=>number(x.fact)),max=Math.max(...values),min=Math.min(0,...values),range=max-min||1;
    const coords=points.map((p,i)=>p.fact&&number(p.fact)!==null?[20+i*510/Math.max(1,points.length-1),10+(max-number(p.fact))/range*72,p]:null);
    node('line',root,{x1:20,x2:530,y1:90,y2:90,stroke:'var(--line)'});
    node('path',root,{d:coords.map((c,i)=>c?(i&&coords[i-1]?'L':'M')+c[0]+' '+c[1]:'').join(' '),stroke:colors.blue,'stroke-width':2,fill:'none'});
    points.forEach((p,i)=>{const x=20+i*510/Math.max(1,points.length-1),c=coords[i];if(c)node('circle',root,{cx:x,cy:c[1],r:4,fill:colors.blue,'data-fact':p.fact.factId,'data-series-key':p.seriesKey||'',tabindex:0,role:'button','aria-label':p.year+' '+p.fact.displayValue});node('text',root,{x,y:112,'text-anchor':'middle',class:'chart-small'},'FY'+p.year);});
  }
  function analysisStart(root,width,height,label){root.replaceChildren();root.cache=new Map();root.setAttribute('viewBox',`0 0 ${width} ${height}`);root.style.minWidth=width+'px';node('title',root,{},label);}
  function analysisWidth(root){return Math.max(220,Math.min(700,root.parentElement.clientWidth||700));}
  function wrappedLabel(parent,label,x,y,maxLength,className){const value=node('text',parent,{x,y,class:className||'chart-label'});const characters=Array.from(label);for(let i=0;i<characters.length;i+=maxLength)node('tspan',value,{x,dy:i?15:0},characters.slice(i,i+maxLength).join(''));return value;}
  function analyticalBars(root,groups,L,options){
    const settings=options||{},all=groups.flatMap(group=>group.entries).filter(entry=>entry.fact&&number(entry.fact)!==null),width=analysisWidth(root),compact=width<560,rowHeight=compact?97:49;
    const hasNegative=settings.diverging||all.some(entry=>number(entry.fact)<0),max=Math.max(1,...all.map(entry=>Math.abs(number(entry.fact)))),axis=compact?(hasNegative?width/2:12):(hasNegative?width*.58:230),usable=compact?(hasNegative?width/2-18:width-24):(hasNegative?width*.22:width-360);
    const height=Math.max(125,groups.reduce((h,group)=>h+(group.label?34:0)+group.entries.length*rowHeight,35));analysisStart(root,width,height,settings.title||'');
    if(!compact)node('line',root,{x1:axis,x2:axis,y1:14,y2:height-12,stroke:'var(--line)'});let y=28;
    groups.forEach(group=>{
      if(group.label){node('text',root,{x:10,y,class:'analysis-group-label'},group.label);y+=25;}
      group.entries.filter(entry=>entry.fact&&number(entry.fact)!==null).forEach(entry=>{
        const fact=entry.fact,value=number(fact),barWidth=Math.abs(value)/max*usable,color=entry.color||(value<0?colors.orange:colors.blue),g=node('g',root,focusAttrs(fact,entry.label));g.setAttribute('data-series-key',entry.key||'');
        wrappedLabel(g,entry.label,10,y+8,compact?Math.max(16,Math.floor((width-20)/12)):15,'chart-label');if(compact)node('line',g,{x1:axis,x2:axis,y1:y+51,y2:y+78,stroke:'var(--line)'});node('rect',g,{x:value<0?axis-barWidth:axis,y:compact?y+56:y-4,width:Math.max(1,barWidth),height:compact?17:19,fill:color,opacity:.62,rx:1});node('text',g,{x:width-10,y:compact?y+45:y+11,'text-anchor':'end',class:'chart-number-small'},fact.shortValue||fact.displayValue);titleFor(g,entry.label+' · '+fact.displayValue);y+=rowHeight;
      });
    });
    if(!all.length)node('text',root,{x:12,y:58,class:'chart-label'},L.analysisChartUnavailable);
  }
  function balancePairs(root,entries,L,label){
    const groups=entries.filter(group=>group.begin||group.end),all=groups.flatMap(group=>[group.begin,group.end]).filter(Boolean),max=Math.max(1,...all.map(fact=>Math.abs(number(fact)||0))),width=analysisWidth(root),compact=width<560,height=Math.max(130,groups.length*104+35),left=compact?10:155,space=compact?width-140:width-335,negative=all.some(fact=>number(fact)<0),axis=negative?left+space/2:left,usable=negative?space/2:space;
    analysisStart(root,width,height,label);
    let y=32;groups.forEach(group=>{node('text',root,{x:10,y:compact?y:y+16,class:'chart-label'},group.label);[['begin',colors.gray],['end',colors.blue]].forEach(([phase,color],i)=>{const fact=group[phase],rowY=y+i*30+(compact?16:0);if(!fact){node('text',root,{x:width-10,y:rowY+17,'text-anchor':'end',class:'chart-small'},L.unknown);return;}const value=number(fact),barWidth=Math.abs(value)/max*usable,g=node('g',root,focusAttrs(fact,(phase==='begin'?L.beginning_balance:L.ending_balance)+' · '+group.label));g.setAttribute('data-series-key',group[phase+'SeriesKey']||fact.key||phase+'_'+group.key);if(negative)node('line',g,{x1:axis,x2:axis,y1:rowY-3,y2:rowY+25,stroke:'var(--line)'});node('rect',g,{x:value<0?axis-barWidth:axis,y:rowY+1,width:Math.max(1,barWidth),height:20,fill:color,opacity:.62,rx:1});node('text',g,{x:width-10,y:rowY+17,'text-anchor':'end',class:'chart-number-small'},fact.shortValue);titleFor(g,fact.displayValue);});y+=104;});
    if(!groups.length)node('text',root,{x:12,y:60,class:'chart-label'},L.analysisChartUnavailable);
  }
  function pairedBalances(root,p,report,L){
    const lookup=p.analysis&&p.analysis.facts||{},groups=[['receivables',L.receivablesBalanceLabel],['inventory',L.inventoryBalanceLabel],['payables',L.payablesBalanceLabel]].map(([key,label])=>({key,label,begin:report.facts[lookup['begin_'+key]],end:report.facts[lookup['end_'+key]]}));
    balancePairs(root,groups,L,L.analysisBalanceChart);
  }
  function balancePair(root,begin,end,L){balancePairs(root,[{key:'equity',label:L.equity,begin,end}],L,L.equityBalanceChart);}
  function analysisProfit(root,p,report,L,view){
    if(p.analysis&&p.analysis.sections){const section=p.analysis.sections.find(value=>value.id==='profit'),chart=section&&(view==='formation'?section.formationChart:section.chart);if(chart&&['profit_bridge','income_formation'].includes(chart.type)&&chart.steps&&chart.steps.length){const formation=chart.type==='income_formation',shortLabels=formation?Object.fromEntries(chart.steps.map(step=>[step.key,L['formationShort_'+step.key]||L[step.key]||step.key])):null;waterfall(root,chart.steps,report.facts,formation?700:Math.max(700,chart.steps.length*130),335,L,true,shortLabels);return true;}}
    return false;
  }
  function cashResearchBridge(root,metadata,report,L){
    const steps=metadata.groupedSteps||metadata.steps||[];
    if(!steps.length)return false;
    const labels=Object.fromEntries(steps.map(step=>[step.key,L['cashShort_'+step.key]||L[step.key]||step.key]));
    waterfall(root,steps,report.facts,700,335,L,true,labels);
    const groups=metadata.groups||[];
    root.querySelectorAll('[data-fact]').forEach(value=>{const group=groups.find(entry=>entry.factId===value.getAttribute('data-fact'));if(group&&group.rows&&group.rows.length){value.setAttribute('data-cash-group',group.key);value.setAttribute('aria-label',(L[group.labelKey]||L[group.key]||group.key)+' · '+L.cashGroupOpen);}});
    return true;
  }
  function cashScope(root,metadata,facts,L,basis){
    const width=analysisWidth(root),compact=width<560,height=compact?338:284,barX=12,barWidth=width-24,rowHeight=compact?154:126;
    analysisStart(root,width,height,L.cashScopeChart);
    [['begin',L.beginning_balance],['end',L.ending_balance]].forEach(([phase,label],index)=>{
      const values=metadata[phase]||{},cashFact=facts[values.cashFactId],restrictedFact=facts[values.restrictedFactId],totalFact=facts[values.totalFactId],cashValue=number(cashFact),restrictedValue=number(restrictedFact),totalValue=number(totalFact),shares=metadata.shares&&metadata.shares[phase]||{},cashShare=facts[shares.cashFactId],restrictedShare=facts[shares.restrictedFactId],y=24+index*rowHeight;
      node('text',root,{x:barX,y,class:'chart-label'},label);
      if(totalFact){const total=node('g',root,focusAttrs(totalFact,L.cashScopeTotal));total.setAttribute('data-series-key','cash_scope_'+phase+'_total');node('text',total,{x:width-12,y,'text-anchor':'end',class:'chart-number-small'},totalFact.shortValue);titleFor(total,L.cashScopeTotal+' · '+totalFact.displayValue);}
      if(!totalFact||totalValue===null||totalValue<=0||cashValue===null||restrictedValue===null||cashValue<0||restrictedValue<0||!values.check||values.check.status!=='match'){
        node('text',root,{x:barX,y:y+40,class:'chart-small'},L.cashScopeIncomplete);return;
      }
      const entries=[{key:'cash',label:L.cashScopeCash,fact:cashFact,share:cashShare,value:cashValue,color:colors.blue},{key:'restricted',label:L.cashScopeRestricted,fact:restrictedFact,share:restrictedShare,value:restrictedValue,color:colors.orange}];
      let offset=0;entries.forEach(entry=>{const partWidth=barWidth*entry.value/totalValue,g=node('g',root,focusAttrs(entry.fact,entry.label)),x=barX+offset;g.setAttribute('data-series-key','cash_scope_'+phase+'_'+entry.key);node('rect',g,{x,y:y+18,width:Math.max(0,partWidth),height:22,fill:entry.color,opacity:.62,rx:1});titleFor(g,entry.label+' · '+entry.fact.displayValue);offset+=partWidth;});
      entries.forEach((entry,i)=>{const rowY=y+61+i*25,g=node('g',root,focusAttrs(basis==='share'&&entry.share?entry.share:entry.fact,entry.label)),display=basis==='share'?(entry.share?entry.share.displayValue:L.unknown):entry.fact.shortValue;g.setAttribute('data-series-key','cash_scope_'+phase+'_'+entry.key+(basis==='share'&&entry.share?'_share':''));node('rect',g,{x:barX,y:rowY-8,width:7,height:7,fill:entry.color,opacity:.75});node('text',g,{x:barX+14,y:rowY,class:'chart-small'},entry.label);node('text',g,{x:width-12,y:rowY,'text-anchor':'end',class:'chart-number-small'},display);titleFor(g,entry.label+' · '+entry.fact.displayValue+(entry.share?' · '+entry.share.displayValue:''));});
    });
  }
  function metricTrend(root,points,label,currentYear,L){
    const known=points.filter(point=>point.fact&&number(point.fact)!==null),width=analysisWidth(root),compact=width<560,height=155,margin=compact?28:55;analysisStart(root,width,height,label);if(!known.length)return;
    const values=known.map(point=>number(point.fact)),max=Math.max(...values),min=Math.min(0,...values),range=max-min||1;
    const coords=points.map((point,i)=>point.fact&&number(point.fact)!==null?[margin+i*(width-margin*2)/Math.max(1,points.length-1),28+(max-number(point.fact))/range*72,point]:null);
    node('path',root,{d:coords.map((coord,i)=>coord?(i&&coords[i-1]?'L':'M')+coord[0]+' '+coord[1]:'').join(' '),stroke:colors.blue,'stroke-width':2,fill:'none'});
    points.forEach((point,i)=>{const x=margin+i*(width-margin*2)/Math.max(1,points.length-1),coord=coords[i];node('text',root,{x,y:140,'text-anchor':'middle',class:'chart-small'},'FY'+point.year);if(!coord)return;const g=node('g',root,focusAttrs(point.fact,label+' FY'+point.year));g.setAttribute('data-series-key',point.seriesKey||'');node('circle',g,{cx:x,cy:coord[1],r:point.year===currentYear?5:3.5,fill:colors.blue});if(!compact||point.year===currentYear)node('text',g,{x,y:coord[1]-12,'text-anchor':compact&&i===0?'start':compact&&i===points.length-1?'end':'middle',class:'chart-number-small'},point.fact.shortValue||point.fact.displayValue);titleFor(g,point.fact.displayValue);});
  }
  window.FVCharts={svg,profit,cash,balance,business,scene,trend,analyticalBars,pairedBalances,balancePairs,balancePair,analysisProfit,cashResearchBridge,cashScope,metricTrend};
}());
