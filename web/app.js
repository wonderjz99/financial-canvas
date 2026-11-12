(function () {
  'use strict';
  const L=window.__FV_LOCALE__||{};
  const registry=window.__FV_REPORTS__||(window.__FV_REPORT__?{[window.__FV_REPORT__.symbol]:window.__FV_REPORT__}:{});
  const app=document.getElementById('app');
  const C=window.FVCharts;
  const preferredReport=window.__FV_REPORT__,initialSymbol=preferredReport&&registry[preferredReport.symbol]?preferredReport.symbol:Object.keys(registry)[0];
  const state={symbol:initialSymbol,year:null,basis:'share',cashView:'cash',profitView:'formation',cashUseView:'cash',reduced:window.matchMedia('(prefers-reduced-motion: reduce)').matches,playing:false,detail:null};
  let timer=null,lastFocus=null,analysisContext=null,analysisResizeFrame=null,cashGroupReturn=null;
  function el(tag,attrs,...children){const value=document.createElement(tag);Object.entries(attrs||{}).forEach(([key,item])=>{if(item===null||item===undefined||item===false)return;if(key==='class')value.className=item;else if(key==='checked')value.checked=Boolean(item);else value.setAttribute(key,String(item));});children.flat().forEach(child=>{if(child===null||child===undefined)return;value.appendChild(child instanceof Node?child:document.createTextNode(String(child)));});return value;}
  function icon(name){const ns='http://www.w3.org/2000/svg',value=document.createElementNS(ns,'svg');value.setAttribute('viewBox','0 0 24 24');value.setAttribute('class','icon');value.setAttribute('aria-hidden','true');const paths={play:'M8 5 L19 12 L8 19 Z',pause:'M8 5 V19 M16 5 V19',close:'M6 6 L18 18 M18 6 L6 18'};const path=document.createElementNS(ns,'path');path.setAttribute('d',paths[name]||paths.close);value.appendChild(path);return value;}
  function text(key){return L[key]||key;}
  function message(key,params){return text(key).replace(/\{([^}]+)\}/g,(_,name)=>params&&params[name]!==undefined&&params[name]!==null?String(params[name]):text('unknown'));}
  function report(){return registry[state.symbol];}
  function presentationKey(field,fallback){const key=(report().presentation||{})[field];return typeof key==='string'&&typeof L[key]==='string'?key:fallback||null;}
  function presentationText(field,fallback){const key=presentationKey(field,fallback);return key?text(key):'';}
  function period(){return report().periods.find(row=>row.year===state.year)||report().periods[report().periods.length-1];}
  function factPeriod(fact){return report().periods.find(row=>row.end===fact.end&&(!fact.start||row.start===fact.start));}
  function analysisSections(p){return p&&p.analysis&&Array.isArray(p.analysis.sections)?p.analysis.sections:[];}
  function analysisTitle(section){return L['analysis_'+section.id]||text(section.titleKey);}
  function analysisFact(p,key){const id=p.analysis&&p.analysis.facts&&p.analysis.facts[key];return id?report().facts[id]:null;}
  function reconciliationNote(p){return p.reconciliation.status!=='eligible'?'reconPartialShort':(p.reconciliation.items||[]).some(fact=>fact.source==='IR_manual')?'reconciliationManual':'reconciliationComplete';}
  function safeUrl(value){try{const url=new URL(String(value));return ['https:','http:'].includes(url.protocol)?url.href:null;}catch(_){return null;}}
  function metricLabel(fact){const key=fact.nameKey||fact.key||fact.name||'value';return L[key]||(/_native$/.test(key)&&L[key.replace(/_native$/,'')]?L[key.replace(/_native$/,'')]+' · '+text('nativeSourceFact'):fact.name||text(key));}
  function factButton(fact,label,seriesKey){if(!fact)return el('span',{},text('unknown'));return el('button',{class:'readout-value number','data-fact':fact.factId,'data-label':label||metricLabel(fact),'data-series-key':seriesKey||null,title:fact.displayValue},fact.shortValue||fact.displayValue);}
  function readout(key,fact){return el('span',{},text(key)+' ',factButton(fact,text(key)));}
  function section(title,hint,control){const box=el('section',{class:'section'}),head=el('div',{class:'section-head'},el('div',{},el('h2',{},text(title)),hint?el('p',{class:'section-meta'},text(hint)):null));if(control)head.appendChild(control);box.appendChild(head);return box;}
  function scrollChart(parent,className,title){const wrapper=el('div',{class:'chart-container'});parent.appendChild(wrapper);return C.svg(wrapper,className,title);}
  if(!state.symbol||!C){app.appendChild(el('div',{class:'page'},el('p',{class:'error'},text('dataUnavailable'))));return;}
  const page=el('main',{class:'page'}),title=el('h1'),subtitle=el('p',{class:'lead'}),companyButtons=el('div',{class:'companies','aria-label':text('searchLabel')});
  Object.keys(registry).forEach(symbol=>companyButtons.appendChild(el('button',{class:'company-button','data-company':symbol},symbol)));
  page.appendChild(el('header',{class:'page-head'},el('div',{},title,subtitle),companyButtons));
  const yearOutput=el('output',{class:'number'}),slider=el('input',{type:'range',class:'year-slider',step:1,'aria-label':text('selectYear')}),yearsRow=el('div',{class:'year-labels'}),playButton=el('button',{class:'play-button','aria-label':text('play'),title:text('play')},icon('play'));
  const basis=el('div',{class:'segment basis-switch',role:'group','aria-label':text('displayMode')},el('button',{type:'button','data-basis':'amount','aria-pressed':'false'},text('amount')),el('button',{type:'button','data-basis':'share','aria-pressed':'true'},text('share')));
  const controls=el('div',{class:'controls'},el('label',{class:'year-control'},el('span',{class:'control-label'},text('year')+' ',yearOutput),slider,yearsRow),playButton,el('div',{class:'control-field basis-control'},el('span',{class:'control-label'},text('displayMode')),basis));page.appendChild(controls);
  const sceneSection=section('threeTitle','threeHint'),sceneChart=scrollChart(sceneSection,'scene-chart',text('threeTitle'));
  const legend=el('div',{class:'legend'},el('span',{},el('i',{}),text('cash_link')),el('span',{},el('i',{class:'reference'}),text('reference_link')));
  sceneSection.appendChild(legend);const sceneNote=el('p',{class:'relation-description'});sceneSection.appendChild(sceneNote);
  const analysisEntries=el('nav',{class:'analysis-entries','aria-label':text('analysisExplore')});
  [['profit','analysisProfitEntry'],['cash_conversion','analysisCashEntry'],['working_capital','analysisCapitalEntry']].forEach(([id,label])=>analysisEntries.appendChild(el('button',{type:'button','data-analysis':id},text(label),el('span',{'aria-hidden':'true'},' ↗'))));
  sceneSection.appendChild(analysisEntries);page.appendChild(sceneSection);
  const profitSection=section('profitHeading','notCashFlows'),profitChart=scrollChart(profitSection,'profit-chart',text('profitHeading')),profitReadout=el('div',{class:'mini-readout'}),profitBasisNote=el('p',{class:'section-meta basis-note'});profitSection.querySelector('.section-head > div').appendChild(profitBasisNote);profitSection.appendChild(profitReadout);profitSection.appendChild(el('p',{class:'status-note'},text('profitFoot')));page.appendChild(profitSection);
  const cashControl=el('div',{class:'segment'},el('button',{'data-cash-view':'cash'},text('cash')),el('button',{'data-cash-view':'reconciliation'},text('reconciliationTitle'))),cashSection=section('cashTitle',null,cashControl),cashReadout=el('div',{class:'mini-readout'}),cashChart=scrollChart(cashSection,'cash-chart',text('cashTitle')),cashNote=el('p',{class:'status-note'}),cashScrollHint=el('p',{class:'chart-scroll-hint',hidden:true},text('scrollChartHint'));cashSection.insertBefore(cashReadout,cashChart.parentElement);cashSection.append(cashScrollHint,cashNote);page.appendChild(cashSection);
  const lower=el('div',{class:'two-column'}),balanceSection=section('balanceTitle','fixedBalanceBasis'),balanceChart=scrollChart(balanceSection,'balance-chart',text('balanceTitle')),businessSection=section('businessLabel',null),businessChart=scrollChart(businessSection,'business-chart',text('businessLabel')),businessNote=el('p',{class:'status-note'});businessSection.appendChild(businessNote);lower.append(balanceSection,businessSection);page.appendChild(lower);
  const footerText=el('span'),reduceToggle=el('input',{type:'checkbox',checked:state.reduced}),footer=el('footer',{class:'footnote'},footerText,el('label',{class:'motion-toggle'},reduceToggle,text('motion')));page.appendChild(footer);app.appendChild(page);
  function updateControls(){const r=report(),p=period();title.textContent=text('pageTitle').replace('{company}',r.company.nameZh||r.company.name).replace('{periodCount}',L['yearCount_'+r.years.length]||String(r.years.length));subtitle.textContent=r.symbol+' · '+r.company.name+' · '+r.company.currency+' · '+text('consolidated')+' · '+p.start+'—'+p.end;companyButtons.querySelectorAll('button').forEach(button=>{const selected=button.getAttribute('data-company')===state.symbol;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));});slider.min=r.years[0];slider.max=r.years[r.years.length-1];slider.value=state.year;yearOutput.value='FY'+state.year;yearOutput.textContent='FY'+state.year;yearsRow.replaceChildren(...r.years.map(year=>el('button',{class:year===state.year?'active':'','data-year':year,'aria-label':'FY'+year},String(year))));basis.querySelectorAll('[data-basis]').forEach(button=>{const selected=button.getAttribute('data-basis')===state.basis;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));});cashControl.querySelectorAll('button').forEach(button=>{const selected=button.getAttribute('data-cash-view')===state.cashView;button.classList.toggle('active',selected);button.setAttribute('aria-pressed',String(selected));});playButton.replaceChildren(icon(state.playing?'pause':'play'));playButton.setAttribute('aria-label',text(state.playing?'pause':'play'));playButton.title=text(state.playing?'pause':'play');document.documentElement.classList.toggle('reduce-motion',state.reduced);document.title=(r.company.nameZh||r.symbol)+' · '+text('brand');footerText.textContent=text('snapshotShort')+' · '+text('asOf')+' '+r.snapshot.asOf+' · '+presentationText('sourceSummaryKey','sourceSummaryGeneric');}
  function update(){const r=report(),p=period();updateControls();C.scene(sceneChart,p,r,L,state.reduced);C.profit(profitChart,p,r,state.basis,L,state.reduced);C.cash(cashChart,p,r,L,state.reduced,state.cashView);C.balance(balanceChart,p,r,state.basis,L,state.reduced);C.business(businessChart,p,r,state.basis,L,state.reduced);profitReadout.replaceChildren(readout('gross_profit',p.metrics.gross_profit),readout('pretax_income',p.metrics.pretax_income),readout('income_tax',p.metrics.income_tax),readout('net_income',p.metrics.net_income));const margin=p.ratios.net_margin;profitReadout.appendChild(el('span',{},text('net_margin')+' ',el('button',{class:'readout-value','data-ratio':'net_margin'},margin&&margin.displayValue?margin.displayValue:text('unknown'))));const cashKeys=state.cashView==='cash'?['cash_begin','cash_end']:['net_income','cfo'];cashReadout.replaceChildren(...cashKeys.map(key=>readout(key,p.metrics[key])));if(state.cashView==='cash'){cashNote.textContent=text('cashAmountBasis')+' '+(p.cash.status==='partial'?text('cashPartialShort'):text('cashHint'));}else{cashNote.textContent=text('cashAmountBasis')+' '+(p.reconciliation.status==='eligible'?text('reconciliationManual'):text('reconPartialShort'));}profitBasisNote.textContent=text(state.basis==='share'?'profitRatioBasis':'profitAmountBasis');sceneNote.textContent=text('sceneAmountBasis')+' '+text('scaleNote')+' '+text('balancesNote')+(presentationText('cashScopeNoteKey')?' '+presentationText('cashScopeNoteKey'):'');businessNote.textContent=text('fixedBusinessBasis')+' '+presentationText('businessNoteKey','businessNoteGeneric');updateCashScrollHint();markSelection();}
  function pause(){if(timer)clearInterval(timer);timer=null;state.playing=false;}
  function chooseYear(year){state.year=Number(year);state.detail=null;analysisContext=null;closeDetail(false);update();}
  function chooseCompany(symbol){pause();closeDetail(false);state.symbol=symbol;state.year=report().years[report().years.length-1];state.detail=null;analysisContext=null;update();}
  slider.addEventListener('input',()=>{pause();chooseYear(slider.value);});
  basis.addEventListener('click',event=>{const button=event.target.closest('[data-basis]');if(!button)return;state.basis=button.getAttribute('data-basis');update();});
  function updateCashScrollHint(){const viewport=cashChart.parentElement;cashScrollHint.hidden=viewport.scrollWidth<=viewport.clientWidth+1;}
  window.addEventListener('resize',()=>{
    updateCashScrollHint();const detail=document.querySelector('.detail');
    if(!detail||detail.getAttribute('data-detail-section')==='fact'||!analysisContext)return;
    if(analysisResizeFrame)cancelAnimationFrame(analysisResizeFrame);
    analysisResizeFrame=requestAnimationFrame(()=>{
      const current=document.querySelector('.detail');if(!current||current.getAttribute('data-detail-section')==='fact'||!analysisContext)return;
      const scroll=current.scrollTop,dataOpen=Boolean(current.querySelector('.analysis-data[open]')),pendingOpen=Boolean(current.querySelector('.analysis-pending[open]')),adjustmentsOpen=Boolean(current.querySelector('.cash-adjustments[open]'));
      if(analysisContext.groupKey)openCashGroup(analysisContext.groupKey,analysisContext.year);else openAnalysis(analysisContext.id,analysisContext.year);const next=document.querySelector('.detail');
      if(dataOpen&&next.querySelector('.analysis-data'))next.querySelector('.analysis-data').open=true;
      if(pendingOpen&&next.querySelector('.analysis-pending'))next.querySelector('.analysis-pending').open=true;
      if(adjustmentsOpen&&next.querySelector('.cash-adjustments'))next.querySelector('.cash-adjustments').open=true;
      next.scrollTop=scroll;
    });
  });
  playButton.addEventListener('click',()=>{if(state.playing){pause();updateControls();return;}state.playing=true;updateControls();timer=setInterval(()=>{const years=report().years,index=years.indexOf(state.year);chooseYear(years[(index+1)%years.length]);},1400);});
  reduceToggle.addEventListener('change',()=>{state.reduced=reduceToggle.checked;if(state.reduced)pause();update();});
  function markSelection(){const r=report(),selectedFact=r.facts[state.detail],identity=selectedFact&&selectedFact.equivalentFactId||state.detail;page.querySelectorAll('[data-fact]').forEach(value=>{const id=value.getAttribute('data-fact'),fact=r.facts[id],selected=Boolean(identity&&(fact&&fact.equivalentFactId||id)===identity);value.classList.toggle('focused',selected);if(selected)value.setAttribute('data-selected','true');else value.removeAttribute('data-selected');});}
  function closeDetail(restore){const returnSection=analysisContext&&analysisContext.id;document.querySelectorAll('.detail,.detail-backdrop').forEach(node=>node.remove());document.body.style.overflow='';if(restore){state.detail=null;analysisContext=null;markSelection();if(lastFocus&&lastFocus.isConnected)lastFocus.focus();else (page.querySelector('[data-analysis="'+(returnSection||'profit')+'"]')||slider).focus();}}
  function field(dl,label,value){if(value===null||value===undefined||value==='')return;dl.appendChild(el('div',{},el('dt',{},label),el('dd',{},value)));}
  function factPoints(fact,seriesKey){
    const r=report();
    const analysisKey=r.periods.flatMap(p=>Object.entries(p.analysis&&p.analysis.facts||{})).find(([key,id])=>id===fact.factId&&key===fact.key)||r.periods.flatMap(p=>Object.entries(p.analysis&&p.analysis.facts||{})).find(([,id])=>id===fact.factId);
    return r.periods.map(p=>{
      let found=seriesKey?(analysisFact(p,seriesKey)||p.metrics[seriesKey]):p.metrics[fact.key]||(analysisKey&&analysisFact(p,analysisKey[0]));
      if(fact.key==='business_revenue')found=(p.business.items||[]).find(item=>item.id===fact.id||item.name===fact.name);
      if(!found&&!seriesKey)found=(p.reconciliation.items||[]).find(item=>item.key===fact.key&&(!fact.nameKey||item.nameKey===fact.nameKey));
      return {year:p.year,fact:found||null,seriesKey:seriesKey||analysisKey&&analysisKey[0]||null};
    });
  }
  function addTrend(panel,points){
    if(!points.some(point=>point.fact))return;
    panel.appendChild(el('h3',{class:'detail-subtitle'},text('detailTrend')));
    const chart=C.svg(panel,'trend-chart',text('yearlyTrend'));C.trend(chart,points,L);
    const table=el('table',{class:'detail-table trend-table'},el('thead',{},el('tr',{},el('th',{},text('year')),el('th',{},text('value'))))),tbody=el('tbody');
    points.forEach(point=>tbody.appendChild(el('tr',{},el('td',{},'FY'+point.year),el('td',{},factButton(point.fact,null,point.seriesKey)))));
    table.appendChild(tbody);panel.appendChild(table);
    if(points.some(point=>!point.fact))panel.appendChild(el('p',{class:'detail-note'},text('trendMissingNote')));
  }
  function factTable(panel,entries,className){
    const table=el('table',{class:'detail-table '+(className||'')}),tbody=el('tbody');
    entries.forEach(entry=>{
      const label=entry.label||text(entry.key),fact=entry.fact;
      tbody.appendChild(el('tr',{'data-metric-key':entry.key||fact&&fact.key||''},el('td',{},fact?el('button',{'data-fact':fact.factId,'data-label':label,'data-series-key':entry.key||null},label):label),el('td',{},factButton(fact,label,entry.key))));
    });table.appendChild(tbody);panel.appendChild(table);return table;
  }
  function analysisLinks(panel,p,activeId){
    const sections=analysisSections(p);if(!sections.length)return;
    const nav=el('nav',{class:'analysis-nav','aria-label':text('analysisSections')});
    sections.forEach(section=>nav.appendChild(el('button',{type:'button','data-analysis':section.id,'data-analysis-year':p.year,'aria-current':section.id===activeId?'page':null},analysisTitle(section))));
    panel.appendChild(nav);
  }
  function analysisYears(panel,p){
    const years=report().years,index=years.indexOf(p.year),select=el('select',{'data-analysis-year-select':'true','aria-label':text('selectAnalysisYear')});
    years.forEach(year=>select.appendChild(el('option',{value:year,selected:year===p.year?'selected':null},'FY'+year)));
    panel.appendChild(el('div',{class:'analysis-years'},el('label',{},el('span',{},text('year')),select),el('div',{class:'analysis-year-arrows'},el('button',{type:'button','data-analysis-step':'-1',disabled:index===0?'disabled':null,'aria-label':text('previousAnalysisYear')},'‹'),el('button',{type:'button','data-analysis-step':'1',disabled:index===years.length-1?'disabled':null,'aria-label':text('nextAnalysisYear')},'›'))));
  }
  function switchAnalysisYear(year,focusSelector){
    if(!analysisContext||!report().years.includes(Number(year)))return;
    const id=analysisContext.id;state.year=Number(year);state.detail=null;update();openAnalysis(id,state.year);
    const focus=document.querySelector('.detail '+focusSelector);if(focus&&!focus.disabled)focus.focus();else document.querySelector('.detail [data-analysis-year-select]').focus();
  }
  function observations(panel,section,calculations){
    const viewForMessage={operating_change_observed:'change',income_formation_observed:'formation'};
    const cashOnlyMessages=['investments_are_not_capex','cash_uses_may_overlap_do_not_sum','simplified_cash_not_company_fcf'];
    const items=(section.observations||[]).filter(item=>L[item.messageKey]&&(item.kind==='calculation')===Boolean(calculations)&&(!viewForMessage[item.messageKey]||section.id!=='profit'||viewForMessage[item.messageKey]===state.profitView)&&!(section.id==='profit'&&state.profitView==='formation'&&item.messageKey==='profit_change_is_arithmetic')&&!(section.id==='cash_uses'&&state.cashUseView==='equity'&&cashOnlyMessages.includes(item.messageKey)));
    if(!items.length)return;
    const list=el('div',{class:'analysis-observations'+(calculations?' analysis-calculations':'')});
    items.forEach(item=>{
      const note=el('div',{class:'analysis-observation '+(item.kind==='limitation'?'is-limitation':'')},el('p',{},message(item.messageKey,item.params)));
      const refs=Array.from(new Set(item.refs||[])).map(id=>report().facts[id]).filter(Boolean);
      if(refs.length){const links=el('div',{class:'observation-refs'});refs.forEach(fact=>links.appendChild(el('button',{type:'button','data-fact':fact.factId},metricLabel(fact))));note.appendChild(links);}
      list.appendChild(note);
    });panel.appendChild(list);
  }
  function analysisFigure(panel,titleKey,hintKey,draw){
    const figure=el('figure',{class:'analysis-figure'},el('figcaption',{},el('h3',{},text(titleKey)),hintKey?el('p',{},text(hintKey)):null)),wrapper=el('div',{class:'chart-container'});
    figure.appendChild(wrapper);panel.appendChild(figure);const chart=C.svg(wrapper,'analysis-chart',text(titleKey));draw(chart);if(chart.hasAttribute('data-waterfall-width')&&Number(chart.getAttribute('data-waterfall-width'))>wrapper.clientWidth+1)figure.appendChild(el('p',{class:'chart-scroll-hint'},text('scrollChartHint')));return figure;
  }
  function analysisSeries(key){return report().periods.map(p=>({year:p.year,seriesKey:key,fact:analysisFact(p,key)||p.metrics[key]||null}));}
  function analysisTrends(panel,keys,p){
    keys.filter(key=>analysisSeries(key).some(point=>point.fact)).slice(0,3).forEach(key=>{
      const points=analysisSeries(key),known=points.find(point=>point.fact),unit=known.fact.unit||'currency';
      const figure=analysisFigure(panel,key,null,chart=>C.metricTrend(chart,points,text(key),p.year,L));
      figure.querySelector('figcaption').appendChild(el('p',{},text('chartUnit')+'：'+(unit==='currency'?report().company.currency:text('unit_'+unit))+' · '+text('independentMetricAxis')));
    });
  }
  function equityCharts(panel,p,section){
    const r=report(),metadata=section.equityChart;
    if(!metadata){panel.appendChild(el('p',{class:'detail-note'},text('equityChartUnavailable')));return;}
    const begin=r.facts[metadata.beginFactId],end=r.facts[metadata.endFactId];
    const balanceFigure=analysisFigure(panel,'equityBalanceChart','equityBalanceCaption',chart=>C.balancePair(chart,begin,end,L));
    balanceFigure.querySelector('figcaption').appendChild(balanceLegend());
    const balanceRows=(metadata.rows||[]).filter(row=>row.relation==='balance'),pairs=['common_stock','apic','retained_earnings','aoci','treasury_stock'].map(key=>({key,label:text('equity_component_'+key),begin:r.facts[(balanceRows.find(row=>row.key==='begin_'+key)||{}).factId],end:r.facts[(balanceRows.find(row=>row.key==='end_'+key)||{}).factId]})).filter(pair=>pair.begin||pair.end);
    if(pairs.length){const components=analysisFigure(panel,'equityBalanceParts','equityBalancePartsCaption',chart=>C.balancePairs(chart,pairs,L,text('equityBalanceParts')));components.querySelector('figcaption').appendChild(balanceLegend());}
    const relations=[['profit','equityProfitParts'],['oci','equityOciParts'],['owner_cash','equityOwnerCashParts'],['expense','equityExpenseParts']];
    const groups=relations.map(([relation,label])=>({label:text(label),entries:(metadata.rows||[]).filter(row=>row.relation===relation&&row.factId&&![metadata.beginFactId,metadata.endFactId].includes(row.factId)).map(row=>({key:row.key,label:text(row.labelKey||row.key),fact:r.facts[row.factId],color:relation==='owner_cash'?'var(--orange)':relation==='expense'?'var(--purple)':undefined})).filter(row=>row.fact)})).filter(group=>group.entries.length);
    analysisFigure(panel,'equityComponentsChart','equityIndependentCaption',chart=>C.analyticalBars(chart,groups,L,{title:text('equityComponentsChart')}));
    if(metadata.status==='partial')panel.appendChild(el('p',{class:'detail-note'},text('equityPartialCaption')));
  }
  function cashGroupRows(group){return (group.rows||[]).map(row=>({key:row.key,label:text(row.labelKey||row.key),fact:report().facts[row.factId]})).filter(row=>row.fact);}
  function cashResearchCharts(panel,p,section){
    const metadata=section.cashResearch;if(!metadata)return false;
    const bridge=metadata.bridge||{},scope=metadata.cashScope||{},merchant=metadata.merchant||{},groups=bridge.groups||[];
    panel.setAttribute('data-cash-research',metadata.status||'partial');
    if(bridge.status==='eligible'&&(bridge.groupedSteps||bridge.steps||[]).length){
      analysisFigure(panel,'cashResearchBridge','cashResearchBridgeCaption',chart=>C.cashResearchBridge(chart,bridge,report(),L));
      const links=el('div',{class:'cash-group-links'});groups.filter(group=>(group.rows||[]).length).forEach(group=>links.appendChild(el('button',{type:'button','data-cash-group':group.key,'data-analysis-year':p.year},text(group.labelKey||group.key)+' ↗')));panel.appendChild(links);
      const adjustments=el('details',{class:'cash-adjustments'},el('summary',{},text('cashAdjustmentDetails')));panel.appendChild(adjustments);
      let drawn=false;adjustments.addEventListener('toggle',()=>{if(!adjustments.open||drawn)return;drawn=true;analysisFigure(adjustments,'cashAdjustmentDetailsTitle','partialCashBarsCaption',chart=>C.analyticalBars(chart,groups.map(group=>({label:text(group.labelKey||group.key),entries:cashGroupRows(group)})).filter(group=>group.entries.length),L,{diverging:true,title:text('cashAdjustmentDetailsTitle')}));});
    }else{
      const knownGroups=groups.map(group=>({label:text(group.labelKey||group.key),entries:cashGroupRows(group)})).filter(group=>group.entries.length);
      if(knownGroups.length)analysisFigure(panel,'knownCashAdjustments','partialCashBarsCaption',chart=>C.analyticalBars(chart,knownGroups,L,{diverging:true,title:text('knownCashAdjustments')}));
      else if(!scope.begin&&!scope.end&&!(merchant.rows||[]).length)return false;
    }
    if(scope.status==='eligible'&&(scope.parts||[]).some(part=>part.beginFactId||part.endFactId)){
      const figure=analysisFigure(panel,'cashScopeChart','cashScopeCaption',chart=>C.cashScope(chart,scope,report().facts,L,state.basis));
      const control=el('div',{class:'cash-scope-control'},el('span',{},text(state.basis==='share'?'cashScopeShareBasis':'cashScopeAmountBasis')),el('div',{class:'segment',role:'group','aria-label':text('cashScopeDisplayMode')},...['amount','share'].map(value=>el('button',{type:'button','data-cash-scope-basis':value,'aria-pressed':String(state.basis===value),class:state.basis===value?'active':''},text(value)))));
      figure.insertBefore(control,figure.querySelector('.chart-container'));
    }else if((scope.parts||[]).some(part=>part.beginFactId||part.endFactId)){
      panel.appendChild(el('p',{class:'detail-note'},text('cashScopeIncomplete')));
    }
    const pairs=(merchant.status==='conflict'?[]:merchant.rows||[]).map(row=>({key:row.key,label:text(row.labelKey||row.key),begin:report().facts[row.beginFactId],end:report().facts[row.endFactId],beginSeriesKey:'begin_'+row.key,endSeriesKey:'end_'+row.key})).filter(row=>row.begin||row.end);
    if(pairs.length){const figure=analysisFigure(panel,'settlementBalancesChart','settlementBalancesCaption',chart=>C.balancePairs(chart,pairs,L,text('settlementBalancesChart')));figure.querySelector('figcaption').appendChild(balanceLegend());}
    if(merchant.status==='conflict')panel.appendChild(el('p',{class:'detail-note'},text('settlementScopeConflict')));
    const effects=(merchant.status==='conflict'?[]:merchant.rows||[]).filter(row=>row.cashEffectFactId).map(row=>({key:report().facts[row.cashEffectFactId].key,label:text('cashEffectOf')+' · '+text(row.labelKey||row.key),fact:report().facts[row.cashEffectFactId]}));
    if(effects.length)analysisFigure(panel,'settlementEffectsChart','settlementEffectsCaption',chart=>C.analyticalBars(chart,[{entries:effects}],L,{diverging:true,title:text('settlementEffectsChart')}));
    if((metadata.noteKeys||[]).length){const notes=el('div',{class:'cash-research-notes'});metadata.noteKeys.filter(key=>L[key]).forEach(key=>notes.appendChild(el('p',{class:'detail-note'},text(key))));panel.appendChild(notes);}
    return true;
  }
  function openCashGroup(key,year){
    const p=report().periods.find(value=>value.year===Number(year))||period(),section=analysisSections(p).find(value=>value.id==='cash_conversion'),metadata=section&&section.cashResearch,group=metadata&&(metadata.bridge.groups||[]).find(value=>value.key===key);
    if(!group)return;
    const previous=document.querySelector('.detail');if(previous&&previous.getAttribute('data-detail-section')==='cash_conversion')cashGroupReturn={year:p.year,key,scroll:previous.scrollTop};
    analysisContext={id:'cash_conversion',year:p.year,groupKey:key};state.detail=null;markSelection();
    const label=text(group.labelKey||group.key),panel=createDetail(label,'cash_group');
    panel.insertBefore(el('button',{class:'detail-back','data-analysis':'cash_conversion','data-analysis-year':p.year,'data-cash-research-back':'true'},'← '+text('backToAnalysis')),panel.firstChild);
    panel.appendChild(el('p',{class:'detail-period analysis-period'},'FY'+p.year+' · '+p.start+' — '+p.end+' · '+report().company.currency));
    if(group.factId)panel.appendChild(el('div',{class:'cash-group-total'},el('span',{},text('cashGroupNetEffect')),factButton(report().facts[group.factId],label)));
    const rows=cashGroupRows(group);analysisFigure(panel,'cashGroupDetails','cashGroupDetailsCaption',chart=>C.analyticalBars(chart,[{entries:rows}],L,{diverging:true,title:label}));
    const data=el('details',{class:'analysis-data'},el('summary',{},text('analysisViewData')));factTable(data,rows,'analysis-table');panel.appendChild(data);panel.focus();
  }
  function balanceLegend(){return el('div',{class:'analysis-chart-legend'},el('span',{},el('i',{class:'begin-swatch'}),text('beginning_balance')),el('span',{},el('i',{}),text('ending_balance')));}
  function analysisCharts(panel,p,section){
    const r=report(),fact=key=>analysisFact(p,key)||p.metrics[key]||null,entry=key=>({key,label:text(key),fact:fact(key)});
    if(section.id==='profit'){
      const formation=state.profitView==='formation',metadata=formation?section.formationChart:section.chart;
      if(section.status!=='conflict'&&metadata&&metadata.steps&&metadata.steps.length&&(!formation||metadata.status==='eligible'))analysisFigure(panel,formation?'incomeFormationChart':'profitChangeChart',formation?'incomeFormationCaption':'profitBridgeCaption',chart=>C.analysisProfit(chart,p,r,L,state.profitView));
      else if(formation&&metadata&&metadata.steps&&metadata.steps.length){
        panel.appendChild(el('div',{class:'analysis-endpoints'},readout('operating_income',p.metrics.operating_income),readout('net_income',p.metrics.net_income)));
        const entries=metadata.steps.filter(step=>step.kind==='flow').map(step=>({key:step.key,label:text(step.key),fact:r.facts[step.factId]}));
        analysisFigure(panel,'incomeFormationKnown','incomeFormationPartial',chart=>C.analyticalBars(chart,[{entries}],L,{diverging:true,title:text('incomeFormationKnown')}));
      }
      else {panel.appendChild(el('p',{class:'detail-note'},text(formation?'incomeFormationUnavailable':'profitChangeUnavailable')));analysisTrends(panel,formation?['operating_income','net_income']:['revenue','operating_income'],p);}
    }else if(section.id==='cash_conversion'){
      panel.appendChild(el('div',{class:'analysis-endpoints'},readout('net_income',p.metrics.net_income),readout('cfo',p.metrics.cfo)));
      if(cashResearchCharts(panel,p,section))return;
      if(section.status==='eligible'&&p.reconciliation.steps&&p.reconciliation.steps.length){
        analysisFigure(panel,'fullCashBridge','analysisBridgeHint',chart=>C.cash(chart,p,r,L,true,'reconciliation'));
      }else{
        const rows=(section.rows||[]).filter(row=>row.factId&&!['net_income','cfo'].includes(row.key)).map(row=>{
          const value=r.facts[row.factId],item=(p.reconciliation.items||[]).find(candidate=>candidate.factId===row.factId);
          return {...row,label:text(row.labelKey||row.key),fact:value,kind:value&&value.cashEffectKind||item&&item.kind||'noncash'};
        });
        const groups=[{label:text('noncash'),entries:rows.filter(row=>row.kind!=='working_capital')},{label:text('working_capital'),entries:rows.filter(row=>row.kind==='working_capital')}].filter(group=>group.entries.length);
        analysisFigure(panel,'knownCashAdjustments','partialCashBarsCaption',chart=>C.analyticalBars(chart,groups,L,{diverging:true,title:text('knownCashAdjustments')}));
      }
    }else if(section.id==='working_capital'){
      const figure=analysisFigure(panel,'analysisBalanceChart','pairedBalanceCaption',chart=>C.pairedBalances(chart,p,r,L));
      figure.querySelector('figcaption').appendChild(balanceLegend());
      const unearnedBegin=fact('begin_unearned_revenue'),unearnedEnd=fact('unearned_revenue');
      if(unearnedBegin||unearnedEnd){const pairs=[{key:'unearned_revenue',label:text('unearned_revenue'),begin:unearnedBegin,end:unearnedEnd}];const unearned=analysisFigure(panel,'unearnedBalanceChart','unearnedBalanceCaption',chart=>C.balancePairs(chart,pairs,L,text('unearnedBalanceChart')));unearned.querySelector('figcaption').appendChild(balanceLegend());}
      const entries=['cf_receivables','cf_inventory','cf_payables','cf_prepaid_assets','cf_unearned_revenue'].map(entry).filter(row=>row.fact);
      analysisFigure(panel,'workingCashChart','workingCashCaption',chart=>C.analyticalBars(chart,[{entries}],L,{diverging:true,title:text('workingCashChart')}));
    }else if(section.id==='cash_uses'){
      if(state.cashUseView==='equity'){equityCharts(panel,p,section);return;}
      const groups=[
        {label:text('assetCashUses'),keys:['productive_asset_purchases','ppe_purchases','business_acquisitions']},
        {label:text('securityCashUses'),keys:['short_investment_purchases','short_investment_proceeds','long_investment_purchases','long_investment_proceeds','debt_security_purchases','debt_security_sales','debt_security_maturities','equity_security_purchases','equity_security_sales']},
        {label:text('financingCashUses'),keys:['debt_proceeds','debt_repayments','convertible_debt_repayments','finance_lease_principal_paid','dividends_paid','share_repurchases']}
      ].map(group=>({label:group.label,entries:group.keys.map(key=>({...entry(key),color:/proceeds|sales|maturities/.test(key)?'var(--blue)':'var(--orange)'})).filter(row=>row.fact)})).filter(group=>group.entries.length);
      const figure=analysisFigure(panel,'cashUseChart','cashUseCaption',chart=>C.analyticalBars(chart,groups,L,{title:text('cashUseChart')}));
      figure.querySelector('figcaption').appendChild(el('div',{class:'analysis-chart-legend'},el('span',{},el('i',{class:'out-swatch'}),text('cashOutflow')),el('span',{},el('i',{}),text('cashInflow'))));
      const noncash=['finance_lease_assets_obtained'].map(entry).filter(row=>row.fact);
      if(noncash.length)analysisFigure(panel,'noncashAssetChart','noncashAssetCaption',chart=>C.analyticalBars(chart,[{entries:noncash}],L,{title:text('noncashAssetChart')}));
    }else if(section.id==='efficiency'){
      analysisTrends(panel,['receivable_days','inventory_days','payable_days_cost_proxy','total_asset_turnover','effective_tax_rate','marketing_ratio'],p);
    }else if(section.id==='quality'){
      analysisTrends(panel,['cash_profit_conversion','sbc_revenue_ratio','effective_tax_rate'],p);
      panel.appendChild(el('button',{class:'equity-entry','data-open-equity':'true'},text('openEquityRelations')+' ↗'));
    }
  }
  function analysisContent(panel,p,section){
    if(!section){panel.appendChild(el('p',{class:'detail-note'},text('analysisUnavailable')));return;}
    if(section.status==='unavailable')panel.appendChild(el('p',{class:'detail-note'},text('analysisUnavailable')));
    if(section.status==='conflict')panel.appendChild(el('p',{class:'analysis-missing'},text('analysisConflict')));
    if(section.id==='profit')panel.appendChild(el('div',{class:'segment analysis-view-switch',role:'group','aria-label':text('profitViewLabel')},...['formation','change'].map(view=>el('button',{type:'button','data-profit-view':view,'aria-pressed':String(state.profitView===view),class:state.profitView===view?'active':''},text(view==='formation'?'profitFormationView':'profitChangeView')))));
    if(section.id==='cash_uses')panel.appendChild(el('div',{class:'segment analysis-view-switch',role:'group','aria-label':text('cashUseViewLabel')},...['cash','equity'].map(view=>el('button',{type:'button','data-cash-use-view':view,'aria-pressed':String(state.cashUseView===view),class:state.cashUseView===view?'active':''},text(view==='cash'?'cashUseCashView':'cashUseEquityView')))));
    observations(panel,section,true);
    analysisCharts(panel,p,section);
    const viewMetadata=section.id==='cash_uses'&&state.cashUseView==='equity'?section.equityChart:section.id==='profit'&&state.profitView==='formation'?section.formationChart:null;
    let rowDefinitions=section.id==='cash_uses'&&state.cashUseView==='equity'&&viewMetadata?viewMetadata.rows||[]:section.rows||[];
    if(section.id==='cash_conversion'&&section.cashResearch){
      const research=section.cashResearch,scope=research.cashScope||{},merchant=research.merchant||{},ids=new Set(rowDefinitions.map(row=>row.factId));
      const add=(id,key)=>{const fact=report().facts[id];if(fact&&!ids.has(id)){rowDefinitions=rowDefinitions.concat({key:key||fact.key,labelKey:key||fact.key,factId:id});ids.add(id);}};
      ['begin','end'].forEach(phase=>{const values=scope[phase]||{};['cash','restricted','total'].forEach(key=>add(values[key+'FactId'],'cash_scope_'+phase+'_'+key));});
      (merchant.rows||[]).forEach(row=>{add(row.beginFactId,'begin_'+row.key);add(row.endFactId,'end_'+row.key);[row.changeFactId,row.cashEffectFactId].forEach(id=>add(id));});
    }
    if(section.id==='profit'&&viewMetadata)rowDefinitions=rowDefinitions.concat((viewMetadata.steps||[]).filter(step=>!rowDefinitions.some(row=>row.key===step.key)).map(step=>({key:step.key,labelKey:step.key,factId:step.factId})));
    const rows=rowDefinitions.map(row=>({key:row.key,label:text(row.labelKey||row.key),fact:row.factId?report().facts[row.factId]:null}));
    if(section.id==='profit'){
      const priority=['net_income','operating_income','operating_profit_change','net_profit_change','revenue_change_effect','cost_change_effect','expense_change_effect'];
      rows.sort((a,b)=>{const ai=priority.indexOf(a.key),bi=priority.indexOf(b.key);return (ai<0?priority.length:ai)-(bi<0?priority.length:bi);});
    }
    const knownRows=rows.filter(row=>row.fact),unknownRows=rows.filter(row=>!row.fact);
    observations(panel,section,false);
    const data=el('details',{class:'analysis-data'},el('summary',{},text('analysisViewData')));panel.appendChild(data);
    if(knownRows.length)factTable(data,knownRows,'analysis-table');
    const visibleMissing=new Set(unknownRows.map(row=>row.key));
    let missingSource=section.id==='cash_uses'&&state.cashUseView==='equity'&&viewMetadata?viewMetadata.missing||[]:[...(section.missing||[]),...(viewMetadata&&viewMetadata.missing||[])];
    if(section.cashResearch){const research=section.cashResearch;missingSource=missingSource.concat((research.cashScope||{}).missing||[],(research.merchant||{}).missing||[]);}
    const missing=missingSource.filter(key=>!visibleMissing.has(key));
    const missingCount=unknownRows.length+new Set(missing).size;
    if(missingCount){
      const disclosure=el('details',{class:'analysis-pending','data-missing-count':missingCount},el('summary',{},message('analysisPending',{count:missingCount})));
      if(unknownRows.length)factTable(disclosure,unknownRows,'analysis-pending-table');
      if(missing.length){const list=el('ul',{class:'analysis-pending-notes'});Array.from(new Set(missing)).forEach(key=>list.appendChild(el('li',{},text(key))));disclosure.appendChild(list);}
      data.appendChild(disclosure);
    }
    if(section.status==='partial'&&!missing.length&&!(section.observations||[]).length)panel.appendChild(el('p',{class:'detail-note analysis-status'},text('analysisPartial')));
  }
  function createDetail(label,sectionId){
    pause();updateControls();if(!document.querySelector('.detail'))lastFocus=document.activeElement;
    closeDetail(false);
    const backdrop=el('div',{class:'detail-backdrop'}),panel=el('section',{class:'detail',role:'dialog','aria-modal':'true','aria-labelledby':'detail-heading',tabindex:-1,'data-detail-section':sectionId||'fact'}),close=el('button',{class:'close-button','aria-label':text('detailClose')},icon('close'));
    panel.appendChild(el('div',{class:'detail-header'},el('h2',{id:'detail-heading'},label),close));
    document.body.append(backdrop,panel);document.body.style.overflow='hidden';
    close.addEventListener('click',()=>closeDetail(true));backdrop.addEventListener('click',()=>closeDetail(true));
    return panel;
  }
  function openAnalysis(id,year){
    const p=report().periods.find(row=>row.year===Number(year))||period(),section=analysisSections(p).find(row=>row.id===id);
    if(state.year!==p.year){state.year=p.year;state.detail=null;update();}
    analysisContext={id,year:p.year};state.detail=null;markSelection();
    const panel=createDetail(section?analysisTitle(section):text('analysisExplore'),id);
    analysisYears(panel,p);
    panel.appendChild(el('p',{class:'detail-period analysis-period'},'FY'+p.year+' · '+p.start+' — '+p.end+' · '+report().company.currency));
    analysisLinks(panel,p,id);analysisContent(panel,p,section);panel.focus();
  }
  function addRelated(panel,fact){
    const r=report(),p=factPeriod(fact);
    if(!p)return;
    let entries=[],label='relatedFacts',note=null;
    const fromKeys=keys=>keys.map(key=>({key,fact:analysisFact(p,key)||p.metrics[key],label:text(key)}));
    if(fact.key==='revenue'){
      entries=(p.business.items||[]).map(value=>({fact:value,label:value.name}));label='revenueBreakdown';note=presentationKey('businessNoteKey','businessNoteGeneric');
    }else if(/^(begin_|end_)?unearned_revenue(_current|_noncurrent)?$/.test(fact.key)||fact.key==='cf_unearned_revenue'){
      entries=fromKeys(['begin_unearned_revenue','unearned_revenue','cf_unearned_revenue']);note='unearnedRelatedNote';
    }else if(['finance_lease_assets_obtained','finance_lease_principal_paid','finance_lease_interest_paid'].includes(fact.key)){
      entries=fromKeys(['ppe_purchases','finance_lease_assets_obtained','finance_lease_principal_paid','finance_lease_interest_paid']);note='leaseRelatedNote';
    }else if(['net_income','gross_profit','operating_income','pretax_income','income_tax','operating_expenses'].includes(fact.key)){
      entries=fromKeys(['revenue','cost_of_revenue','gross_profit','operating_expenses','operating_income','pretax_income','equity_method_income','income_tax','net_income']);note='incomeRelatedNote';
    }else if(/research|selling_general|sales_marketing|general_admin|marketing_ratio|sga_ratio/.test(fact.key)){
      entries=fromKeys(['operating_expenses','research_development','selling_general_admin','sales_marketing','general_admin','research_ratio','sga_ratio','marketing_ratio']);note='expenseRelatedNote';
    }else if(/interest_|nonoperating|equity_method|effective_tax|pretax_before/.test(fact.key)&&!fact.key.startsWith('cf_')){
      entries=fromKeys(['operating_income','interest_income','interest_expense','nonoperating_income','other_nonoperating_income','pretax_before_equity','equity_method_income','pretax_income','income_tax','effective_tax_rate']);note='nonOperatingRelatedNote';
    }else if(/_change_effect$|_profit_change$/.test(fact.key)){
      entries=fromKeys(['revenue_change_effect','cost_change_effect','expense_change_effect','operating_profit_change','net_profit_change']);note='profitChangeRelatedNote';
    }else if(fact.key==='cfo'){
      entries=(p.reconciliation.items||[]).map(value=>({fact:value,label:metricLabel(value)}));label='cashAdjustments';note=reconciliationNote(p);
      if(!entries.length)entries=['net_income','cfo','sbc'].map(key=>({fact:p.metrics[key],label:text(key)}));
    }else if(['assets','bs_cash','ppe','rou'].includes(fact.key)){
      entries=['bs_cash','ppe','rou'].map(key=>({fact:p.metrics[key],label:text(key)}));note='assetRelatedNote';
    }else if(['cash_begin','cash_end','cash_change','cfi','cff','fx'].includes(fact.key)){
      entries=['cash_begin','cfo','cfi','cff','fx','cash_end','bs_cash'].map(key=>({fact:p.metrics[key],label:text(key)}));note='cashRelatedNote';
    }else if(['liabilities','equity','begin_assets','begin_liabilities','begin_equity'].includes(fact.key)){
      const keys=fact.key.startsWith('begin_')?['begin_assets','begin_liabilities','begin_equity']:['assets','liabilities','equity'];
      entries=keys.map(key=>({fact:p.metrics[key],label:text(key.replace('begin_',''))}));note='balancesNote';
    }
    const capital=analysisSections(p).find(row=>row.id==='working_capital');
    const capitalFamily=/receiv/.test(fact.key)?/receiv/:/inventor/.test(fact.key)?/inventor/:/payable/.test(fact.key)?/payable/:null;
    if(capital&&(capitalFamily||(capital.rows||[]).some(row=>row.factId===fact.factId))){
      const keys=capitalFamily&&/receiv/.test(fact.key)?['revenue','receivable_days']:capitalFamily&&/inventor/.test(fact.key)?['cost_of_revenue','inventory_days']:capitalFamily?['cost_of_revenue','payable_days_cost_proxy']:['revenue','cost_of_revenue'];
      entries=fromKeys(keys).concat((capital.rows||[]).filter(row=>!capitalFamily||capitalFamily.test(row.key)).map(row=>({key:row.key,fact:r.facts[row.factId],label:text(row.labelKey||row.key)})));
      note='capitalBalanceVsCash';label='capitalRelatedFacts';
    }
    const cashSection=analysisSections(p).find(row=>row.id==='cash_conversion'),research=cashSection&&cashSection.cashResearch;
    if(research){
      const matches=identity=>{const candidate=r.facts[identity];return identity===fact.factId||Boolean(candidate&&(candidate.inputs||[]).includes(fact.factId));};
      const merchant=(research.merchant&&research.merchant.rows||[]).find(row=>[row.beginFactId,row.endFactId,row.changeFactId,row.cashEffectFactId].some(matches));
      const group=(research.bridge&&research.bridge.groups||[]).find(row=>(row.rows||[]).some(entry=>matches(entry.factId))||matches(row.factId));
      const scope=research.cashScope||{},scopeEntries=['begin','end'].flatMap(phase=>['cash','restricted','total'].map(key=>({key:'cash_scope_'+phase+'_'+key,identity:(scope[phase]||{})[key+'FactId']})));
      if(merchant){
        entries=[{key:'begin_'+merchant.key,identity:merchant.beginFactId},{key:'end_'+merchant.key,identity:merchant.endFactId},{key:merchant.key+'_balance_change',identity:merchant.changeFactId},{key:(r.facts[merchant.cashEffectFactId]||{}).key,identity:merchant.cashEffectFactId}].map(row=>({key:row.key,label:text(row.key),fact:r.facts[row.identity]}));
        label='settlementRelatedFacts';note='settlementEffectsCaption';
      }else if(group){
        entries=cashGroupRows(group);if(group.factId)entries.push({key:group.key,label:text(group.labelKey||group.key),fact:r.facts[group.factId]});label='cashGroupDetails';note='cashGroupDetailsCaption';
      }else if(scopeEntries.some(row=>matches(row.identity))){
        entries=scopeEntries.map(row=>({key:row.key,label:text(row.key),fact:r.facts[row.identity]}));label='cashScopeChart';note='cashScopeCaption';
      }
    }
    entries=entries.filter((entry,index,all)=>entry.fact&&entry.fact.factId!==fact.factId&&all.findIndex(row=>row.fact&&row.fact.factId===entry.fact.factId)===index);
    if(!entries.length)return;
    panel.appendChild(el('h3',{class:'detail-subtitle'},text(label)));
    factTable(panel,entries);
    if(note)panel.appendChild(el('p',{class:'detail-note'},text(note)));
  }
  function openDetail(fact,label,ratioKey,seriesKey){
    if(!fact)return;
    const panel=createDetail(label||metricLabel(fact));state.detail=fact.factId;markSelection();
    if(analysisContext)panel.insertBefore(el('button',{class:'detail-back',...(analysisContext.groupKey?{'data-cash-group':analysisContext.groupKey}:{'data-analysis':analysisContext.id}),'data-analysis-year':analysisContext.year},'← '+text('backToAnalysis')),panel.firstChild);
    panel.appendChild(el('p',{class:'detail-value'},fact.displayValue||text('unknown')));
    const unit=fact.unit||(ratioKey?'percent':'currency');
    panel.appendChild(el('p',{class:'detail-period'},(fact.start?fact.start+' — '+fact.end:fact.end||text('unknown'))+' · '+(unit==='currency'?(fact.currency||report().company.currency):text('unit_'+unit))));
    const description=L['explain_'+fact.key]||L['explain_'+fact.key.replace(/_native$/,'')];if(description)panel.appendChild(el('p',{class:'metric-explanation'},description));
    const points=ratioKey?report().periods.map(p=>({year:p.year,fact:p.ratios[ratioKey]&&p.ratios[ratioKey].valueDecimal!==null?{...p.ratios[ratioKey],factId:'ratio:'+ratioKey+':'+p.year,key:ratioKey,unit:'percent',start:p.start,end:p.end,displayValue:p.ratios[ratioKey].displayValue,shortValue:p.ratios[ratioKey].displayValue}:null})):factPoints(fact,seriesKey);
    addTrend(panel,points);
    const current=factPeriod(fact);
    const previousIndex=current?report().years.indexOf(current.year)-1:-1,previous=report().years[previousIndex];
    const pair=current?report().comparisons.find(item=>item.fromYear===previous&&item.toYear===current.year):null,change=pair&&pair.metrics[fact.key];
    if(change&&change.status==='calculated')panel.appendChild(el('p',{class:'detail-note'},text('metricChange')+' FY'+previous+'：'+change.displayDelta+' · '+(change.displayPercent||text('compareMissing'))));
    addRelated(panel,fact);
    if(current){
      const related=analysisSections(current).filter(section=>(section.rows||[]).some(row=>row.factId===fact.factId));
      if(related.length){const links=el('div',{class:'detail-analysis-links'},el('span',{},text('continueAnalysis')));related.forEach(section=>links.appendChild(el('button',{'data-analysis':section.id,'data-analysis-year':current.year},analysisTitle(section))));panel.appendChild(links);}
    }
    panel.appendChild(el('h3',{class:'detail-subtitle'},text('detailBasis')));
    const fields=el('dl',{class:'detail-fields'});field(fields,text('normalizedValue'),fact.valueDecimal);field(fields,text(unit==='currency'?'currency':'metricUnit'),unit==='currency'?fact.currency||report().company.currency:text('unit_'+unit));field(fields,text('source'),fact.source==='IR_manual'?text('manualSource'):fact.source==='calculated'?text('derivedSource'):fact.source);
    const url=safeUrl(fact.sourceUrl);if(url){const linkLabel=text(fact.source==='Futu'?'providerLink':'sourceLink');field(fields,linkLabel,el('a',{href:url,target:'_blank',rel:'noopener noreferrer'},linkLabel));}panel.appendChild(fields);
    const provenance=el('details',{class:'detail-provenance'},el('summary',{},text('technicalBasis'))),advanced=el('dl',{class:'detail-fields'});
    field(advanced,text('sourceField'),fact.tag);field(advanced,text('originalDisclosureSymbol'),fact.originalDocumentSymbol);field(advanced,text('disclosed'),fact.filed);field(advanced,text('filing'),fact.accession);field(advanced,text('retrieved'),fact.retrievedAt);field(advanced,text('formula'),fact.formula);field(advanced,text('detailOriginalUnit'),fact.rawUnit||fact.currency);field(advanced,text('sourceDocumentValue'),fact.originalDocumentValue);field(advanced,text('sourceDocumentMultiplier'),fact.originalMultiplier||fact.documentMultiplier);field(advanced,text('note'),fact.location);if(fact.versionValuesChanged)field(advanced,text('factVersions'),text('partial'));const review=fact.documentReview;if(review){const reviewUrl=safeUrl(review.url);if(reviewUrl)field(advanced,text('disclosureReview'),el('a',{href:reviewUrl,target:'_blank',rel:'noopener noreferrer'},text('sourceLink')));field(advanced,text('disclosureReviewLocation'),review.location);field(advanced,text('sourceDocumentValue'),review.documentValue);field(advanced,text('sourceDocumentMultiplier'),review.documentMultiplier);field(advanced,text('disclosed'),review.publishedAt);field(advanced,text('retrieved'),review.retrievedAt);}provenance.appendChild(advanced);
    if(fact.inputs&&fact.inputs.length){provenance.appendChild(el('h3',{class:'detail-subtitle'},text('inputs')));const inputList=el('div',{class:'detail-inputs'});fact.inputs.forEach(id=>{const source=report().facts[id];if(source)inputList.appendChild(el('button',{'data-fact':id},metricLabel(source)+' '+source.shortValue));});provenance.appendChild(inputList);}panel.appendChild(provenance);panel.focus();
  }
  document.addEventListener('click',event=>{
    const cashBack=event.target.closest('[data-cash-research-back]');if(cashBack){const saved=cashGroupReturn;openAnalysis('cash_conversion',cashBack.getAttribute('data-analysis-year')||state.year);if(saved&&saved.year===state.year){const panel=document.querySelector('.detail');panel.scrollTop=saved.scroll;const target=Array.from(panel.querySelectorAll('button[data-cash-group]')).find(value=>value.getAttribute('data-cash-group')===saved.key);if(target)target.focus({preventScroll:true});}return;}
    const scopeBasis=event.target.closest('[data-cash-scope-basis]');if(scopeBasis){const panel=document.querySelector('.detail'),scroll=panel?panel.scrollTop:0;state.basis=scopeBasis.getAttribute('data-cash-scope-basis');update();openAnalysis('cash_conversion',analysisContext?analysisContext.year:state.year);const next=document.querySelector('.detail');next.scrollTop=scroll;next.querySelector('[data-cash-scope-basis="'+state.basis+'"]').focus({preventScroll:true});return;}
    const cashGroup=event.target.closest('[data-cash-group]');if(cashGroup){openCashGroup(cashGroup.getAttribute('data-cash-group'),cashGroup.getAttribute('data-analysis-year')||analysisContext&&analysisContext.year||state.year);return;}
    const profitView=event.target.closest('[data-profit-view]');if(profitView){state.profitView=profitView.getAttribute('data-profit-view');openAnalysis('profit',analysisContext?analysisContext.year:state.year);document.querySelector('[data-profit-view="'+state.profitView+'"]').focus();return;}
    const cashUseView=event.target.closest('[data-cash-use-view]');if(cashUseView){state.cashUseView=cashUseView.getAttribute('data-cash-use-view');openAnalysis('cash_uses',analysisContext?analysisContext.year:state.year);document.querySelector('[data-cash-use-view="'+state.cashUseView+'"]').focus();return;}
    if(event.target.closest('[data-open-equity]')){state.cashUseView='equity';openAnalysis('cash_uses',analysisContext?analysisContext.year:state.year);return;}
    const step=event.target.closest('[data-analysis-step]');if(step&&analysisContext){const years=report().years,index=years.indexOf(analysisContext.year),year=years[index+Number(step.getAttribute('data-analysis-step'))];if(year!==undefined)switchAnalysisYear(year,'[data-analysis-step="'+step.getAttribute('data-analysis-step')+'"]');return;}
    const analysis=event.target.closest('[data-analysis]');if(analysis){openAnalysis(analysis.getAttribute('data-analysis'),analysis.getAttribute('data-analysis-year')||state.year);return;}const company=event.target.closest('[data-company]');if(company){chooseCompany(company.getAttribute('data-company'));return;}const year=event.target.closest('[data-year]');if(year){pause();chooseYear(year.getAttribute('data-year'));return;}const cashView=event.target.closest('[data-cash-view]');if(cashView){state.cashView=cashView.getAttribute('data-cash-view');update();return;}const ratio=event.target.closest('[data-ratio]');if(ratio){const key=ratio.getAttribute('data-ratio'),p=period(),fact=analysisFact(p,key),value=p.ratios[key];if(fact)openDetail(fact,text(key));else if(value)openDetail({...value,factId:'ratio:'+key+':'+state.year,key,unit:'percent',source:text('derivedSource'),start:p.start,end:p.end},text(key),key);return;}const selected=event.target.closest('[data-fact]');if(selected){const fact=report().facts[selected.getAttribute('data-fact')];if(fact){const labeled=selected.closest('[data-label]');openDetail(fact,labeled?labeled.getAttribute('data-label'):fact.name||metricLabel(fact),null,selected.getAttribute('data-series-key'));}else if(selected.getAttribute('data-fact').startsWith('ratio:')){const parts=selected.getAttribute('data-fact').split(':'),p=report().periods.find(row=>row.year===Number(parts[2])),ratio=p&&p.ratios[parts[1]];if(ratio)openDetail({...ratio,factId:selected.getAttribute('data-fact'),key:parts[1],unit:'percent',source:text('derivedSource'),start:p.start,end:p.end},text(parts[1]),parts[1]);}}
  });
  document.addEventListener('change',event=>{if(event.target.matches('[data-analysis-year-select]'))switchAnalysisYear(event.target.value,'[data-analysis-year-select]');});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeDetail(true);return;}const detail=document.querySelector('.detail');if(detail&&event.key==='Tab'){const targets=Array.from(detail.querySelectorAll('a[href],button,select,summary,[tabindex="0"]')).filter(value=>!value.disabled&&value.getClientRects().length),first=targets[0],last=targets[targets.length-1];if(event.shiftKey&&(document.activeElement===first||document.activeElement===detail)){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}if((event.key==='Enter'||event.key===' ')&&event.target.closest('svg [data-fact]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  state.year=report().years[report().years.length-1];update();
}());
