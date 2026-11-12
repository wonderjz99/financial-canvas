(function () {
  'use strict';
  const r=window.__FV_REPORT__,L=window.__FV_LOCALE__;
  if(!r||!r.delivery||r.delivery.mode!=='single_company')return;
  const label=key=>L[key]||key;
  function element(tag,attrs,...children){const node=document.createElement(tag);Object.entries(attrs||{}).forEach(([key,value])=>node.setAttribute(key,value));children.flat().forEach(child=>{if(child!==null&&child!==undefined)node.append(child instanceof Node?child:document.createTextNode(String(child)));});return node;}
  function safeUrl(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:null;}catch(_){return null;}}
  const period=()=>r.periods.find(p=>p.year===Number(document.querySelector('.year-slider').value))||r.periods[r.periods.length-1];
  document.querySelectorAll('.companies').forEach(node=>node.remove());
  const deliveryNote=element('div',{class:'delivery-note'});
  document.querySelector('.page-head').after(deliveryNote);
  document.querySelector('.page-head > div').prepend(element('p',{class:'report-brand'},label('brandEn')+' / '+label('brand')));
  function updateDelivery(){
    const p=period(),details=element('details',{class:'delivery-sources'},element('summary',{},label('v2SourcesAndGaps')));
    deliveryNote.replaceChildren(element('p',{},label(r.delivery.status==='conflict'?'v2Conflict':'v2Partial')+' · '+label('asOf')+' '+r.snapshot.asOf+' · '+r.company.currency+' · '+r.delivery.identity.accounting));
    details.appendChild(element('p',{},label('v2FiscalPeriods')+' '+r.periods.map(row=>'FY'+row.year+' '+row.start+'—'+row.end+' ('+row.fiscalDays+label('v2Days')+')').join('；')));
    details.appendChild(element('p',{},label('v2Gaps')+' '+p.missingMetrics.map(key=>label(key)).join('、')+' · '+label('v2BusinessStatus')+' '+label(p.business.status)+' · '+label('v2CfoStatus')+' '+label(p.reconciliation.status)));
    (r.snapshot.warnings||[]).forEach(warning=>details.appendChild(element('p',{},label('v2SourceWarning')+' '+label(warning.code)+(warning.version?' · '+label('v2Version')+' '+warning.version:'')+(warning.retrievedAt?' · '+warning.retrievedAt:''))));
    const list=element('ul');[...(r.snapshot.sources||[]),...(r.delivery.research.sources||[])].forEach(source=>{const url=safeUrl(source.url);list.appendChild(element('li',{},url?element('a',{href:url,target:'_blank',rel:'noopener noreferrer'},source.name||source.id):source.name||source.id,' · '+source.retrievedAt+' · '+label('v2Version')+' '+source.sha256));});details.appendChild(list);
    (r.delivery.notes||[]).forEach(note=>details.appendChild(element('p',{},note.text+' · '+note.location+' ',element('a',{href:safeUrl(note.url),target:'_blank',rel:'noopener noreferrer'},label('source')))));
    deliveryNote.appendChild(details);
  }
  function update(){
    updateDelivery();
    document.title=r.symbol+' · '+r.company.name+' · '+label('brand');
    const p=period(),note=document.querySelector('.business-chart').closest('.section').querySelector('.status-note');
    if(p.business.comparableToPrevious===false)note.textContent=label('fixedBusinessBasis')+' '+label('businessNoteGeneric')+' '+label('v2NotComparable')+' '+p.business.comparabilityNote;
  }
  new MutationObserver(update).observe(document.querySelector('.lead'),{childList:true});
  update();
})();
