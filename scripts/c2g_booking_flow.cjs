'use strict';
// Booking plans use goal inputs and freshly observed semantic controls only.
const fold=s=>String(s??'').normalize('NFD').replace(/\p{Diacritic}/gu,'').replace(/\s+/gu,' ').trim().toLowerCase();
const usable=(e,a='click')=>e.enabled!==false&&!e.secret&&!e.nameTruncated&&e.actions?.includes(a);
const months=['january|janvier|janv|jan','february|fevrier|fevr|feb','march|mars|mar','april|avril|avr|apr','may|mai','june|juin|jun','july|juillet|juil|jul','august|aout|aug','september|septembre|sept|sep','october|octobre|oct','november|novembre|nov','december|decembre|dec'];
function monthNumber(text){text=fold(text);return months.findIndex(pattern=>new RegExp('(?:^|[^a-z])(?:'+pattern+')(?=[^a-z]|$)').test(text))+1;}
function iso(year,month,day){const date=new Date(Date.UTC(year,month-1,day));if(date.getUTCMonth()!==month-1||date.getUTCDate()!==day)throw Error('Invalid requested stay date');return date.toISOString().slice(0,10);}
function constraints(goal,asOf=new Date().toISOString()){
 const destination=goal.match(/\bin\s+(.+?)(?=\s+(?:from|for|on|with)\b|[.?!]|$)/i)?.[1]||goal.match(/\ba\s+(.+?)\s+hotel\b/i)?.[1];
 if(!destination||destination.length>120)return null;
 const monthNames='(?:'+months.join('|')+')';let match=fold(goal).match(new RegExp('('+monthNames+')\\s+(\\d{1,2})(?:st|nd|rd|th)?(?:\\s*[-–]\\s*(\\d{1,2}))?'));
 let month,day,checkoutDay,checkoutMonth;
 if(match){month=monthNumber(match[1]);day=Number(match[2]);checkoutDay=Number(match[3])||null;checkoutMonth=month;}
 else{match=fold(goal).match(new RegExp('(\\d{1,2})(?:st|nd|rd|th)?\\s+('+monthNames+')'));if(!match)return null;day=Number(match[1]);month=monthNumber(match[2]);}
 const next=fold(goal).match(new RegExp('\\bto\\s+(?:('+monthNames+')\\s+)?(\\d{1,2})(?:st|nd|rd|th)?'));
 if(next){checkoutDay=Number(next[2]);checkoutMonth=next[1]?monthNumber(next[1]):month;}
 const today=new Date(asOf),explicitYear=goal.match(/\b(20\d{2})\b/);let year=explicitYear?Number(explicitYear[1]):today.getUTCFullYear();
 if(!explicitYear&&iso(year,month,day)<=today.toISOString().slice(0,10))year++;
 const checkin=iso(year,month,day);let checkout;
 if(checkoutDay)checkout=iso(year+(checkoutMonth<month?1:0),checkoutMonth,checkoutDay);
 else{const nights=fold(goal).match(/\b(one|two|three|four|five|six|seven|\d+)\s+night/);if(!nights)return null;const count=/^\d+$/.test(nights[1])?Number(nights[1]):['one','two','three','four','five','six','seven'].indexOf(nights[1])+1;const end=new Date(checkin+'T00:00:00Z');end.setUTCDate(end.getUTCDate()+count);checkout=end.toISOString().slice(0,10);}
 if(checkout<=checkin)throw Error('Checkout must follow checkin');
 return {destination:destination.trim(),checkin,checkout,adults:Number(goal.match(/\b(?:for|is for)\s+(\d+)\s+adults?/i)?.[1]||2),rooms:Number(goal.match(/\b(\d+)\s+rooms?\b/i)?.[1]||1),hotelOnly:true,lowestFirst:/cheapest|lowest (?:price|priced)/i.test(goal),deal:/\bdeals?\b/i.test(goal)};
}
function semantic(row,observation){const keys=['role','name','inputName','placeholder','frame'];const target=Object.fromEntries(keys.filter(k=>row[k]!==undefined).map(k=>[k,row[k]]));const matches=observation.elements.filter(e=>usable(e,'click')||usable(e,'fill')).filter(e=>Object.entries(target).every(([k,v])=>e[k]===v));if(matches.length>1)target.id=row.id;return target;}
function batch(observation,rows,requires){return {ok:true,kind:'batch',revision:observation.revision,steps:rows.map(({row,action='click',value,expect})=>({action,target:semantic(row,observation),...(value===undefined?{}:{value}),...(expect?{expect}:{})})),requires};}
function one(rows){return rows.length===1?rows[0]:null;}
function calendarDate(row){const name=fold(row.name),month=monthNumber(name),year=Number(name.match(/\b(20\d{2})\b/)?.[1]);if(!month||!year)return null;const day=Number(name.match(/\b(\d{1,2})(?:er|st|nd|rd|th)?\b/)?.[1]);return day?iso(year,month,day):null;}
function captionDate(text){const month=monthNumber(text),day=Number(fold(text).match(/\b(\d{1,2})(?:er|st|nd|rd|th)?\b/)?.[1]);return month&&day?`${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`:null;}
function taskPlan(goal,observation,context={}){
 const here=new URL(observation.url);if(!/(?:^|\.)booking\.com$/.test(here.hostname))return {ok:false,frontier:'Booking flow requires an observed Booking document'};
 const c=constraints(goal,context.asOf);if(!c)return {ok:false,frontier:'Unparsed explicit destination or stay dates'};
 const content=observation.title+' '+observation.text.slice(0,3000);if(/captcha|verify.*human|unusual traffic|^just a moment/i.test(content)||observation.authentication?.required)return {ok:false,frontier:'needs-owner: observed access wall'};
 const state=context.booking??={};state.constraints=c;const elements=observation.elements;
 const dismissed=one(elements.filter(e=>e.role==='button'&&usable(e)&&/^(?:Refuser|Reject all|Decline|Ignorer les infos relatives à la connexion|Dismiss sign-in info|Dismiss sign in information)$/i.test(e.name.trim())));
 if(dismissed)return batch(observation,[{row:dismissed}],'Fresh ordinary dismissal; never log in or solve an access challenge');
 const input=one(elements.filter(e=>usable(e,'fill')&&(e.inputName==='ss'||e.role==='combobox'&&/destination|where are you going|ou allez/i.test(fold(e.name+' '+e.placeholder)))));
 if(!input)return {ok:false,frontier:'No unique fresh destination control'};
 if(fold(input.value)!==fold(c.destination))return batch(observation,[{row:input,action:'fill',value:c.destination}],'Fresh destination value must match requested place');
 const dateButton=one(elements.filter(e=>e.role==='button'&&usable(e)&&/choisir des dates|select dates|check-in date.*check-out date/i.test(e.name)));
 const hasServerDates=here.searchParams.get('checkin')===c.checkin&&here.searchParams.get('checkout')===c.checkout;
 if(state.pendingDates&&observation.revision!==state.pendingDates.revision&&dateButton){const parts=dateButton.name.split(/[—–]/);if(captionDate(parts[0])===c.checkin.slice(5)&&captionDate(parts[1])===c.checkout.slice(5)){state.datesReady=true;state.dateEvidence={observedNames:state.pendingDates.names,caption:dateButton.name,revision:observation.revision};delete state.pendingDates;}}
 if(!hasServerDates&&!state.datesReady){
  const dates=elements.filter(e=>usable(e)&&['checkbox','button'].includes(e.role)).map(row=>({row,date:calendarDate(row)})).filter(x=>x.date);
  if(!dates.length)return dateButton?batch(observation,[{row:dateButton}],'Fresh calendar with explicit month/year and actionable dates must appear'):{ok:false,frontier:'No unique date calendar opener'};
  const checkin=one(dates.filter(x=>x.date===c.checkin).map(x=>x.row)),checkout=one(dates.filter(x=>x.date===c.checkout).map(x=>x.row));
  if(checkin&&checkout){state.pendingDates={revision:observation.revision,names:[checkin.name,checkout.name]};return batch(observation,[{row:checkin},{row:checkout}],'Two freshly observed full dates; verify selected caption then final server date parameters');}
  const earliest=dates.map(x=>x.date).sort()[0],direction=c.checkin<earliest?'previous':'next';
  const month=one(elements.filter(e=>e.role==='button'&&usable(e)&&new RegExp(direction==='next'?'^(?:Mois suivant|Next month)$':'^(?:Mois précédent|Previous month)$','i').test(e.name.trim())));
  if(!month)return {ok:false,frontier:'No unique observed month navigation'};
  const edge=new Date((direction==='next'?dates.map(x=>x.date).sort().at(-1):earliest).slice(0,7)+'-01T00:00:00Z');edge.setUTCMonth(edge.getUTCMonth()+(direction==='next'?1:-1));
  const locale=/\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\b/i.test(dates[0].row.name)?'fr-FR':'en-US',expectedMonth=new Intl.DateTimeFormat(locale,{month:'long',year:'numeric',timeZone:'UTC'}).format(edge);
  return batch(observation,[{row:month,expect:{path:'/text',contains:expectedMonth}}],'Fresh newly introduced '+expectedMonth+' calendar must appear before selecting dates');
 }
 const party=one(elements.filter(e=>e.role==='button'&&usable(e)&&/nombre de personnes|number of travelers|select occupancy|adults.*rooms?|adultes.*chambres?/i.test(e.name)));
 const counts=party&&party.name.replace(/\s+/gu,' ').toLowerCase().match(/(\d+)\s+adult(?:e)?s?\s*[·.]\s*(\d+)\s+(?:children|child|enfants?)\s*[·.]\s*(\d+)\s+(?:rooms?|chambres?)/);
 const done=one(elements.filter(e=>e.role==='button'&&usable(e)&&/^(?:Terminer|Done)$/i.test(e.name.trim())));
 const adult=one(elements.filter(e=>usable(e,'fill')&&/^(?:Adults|Adultes)$/i.test(e.name.trim()))),room=one(elements.filter(e=>usable(e,'fill')&&/^(?:Rooms|Chambres)$/i.test(e.name.trim())));
 if(done&&adult&&room){const rows=[];if(Number(adult.value)!==c.adults)rows.push({row:adult,action:'fill',value:String(c.adults)});if(Number(room.value)!==c.rooms)rows.push({row:room,action:'fill',value:String(c.rooms)});rows.push({row:done});return batch(observation,rows,'Fresh party summary must show requested adults and rooms before search');}
 if(!counts||Number(counts[1])!==c.adults||Number(counts[3])!==c.rooms)return party?batch(observation,[{row:party}],'Fresh occupancy controls must appear; do not infer hidden increment buttons'):{ok:false,frontier:'No observed party control for requested occupancy'};
 const matchingResults=here.pathname.startsWith('/searchresults')&&hasServerDates&&Number(here.searchParams.get('group_adults'))===c.adults&&Number(here.searchParams.get('no_rooms'))===c.rooms;
 if(!matchingResults){const search=one(elements.filter(e=>e.role==='button'&&usable(e)&&/^(?:Rechercher|Search)$/i.test(e.name.trim())));return search?batch(observation,[{row:search}],'Actual result URL must carry requested dates and occupancy'):{ok:false,frontier:'No unique observed stay search button'};}
 const hotels=elements.filter(e=>e.role==='checkbox'&&usable(e)&&(e.value==='ht_id=204'||e.inputName==='ht_id=204')&&/^(?:Hotel|Hotels|Hôtel|Hôtels)\s*:/i.test(e.name));
 if(!here.searchParams.get('nflt')?.split(';').includes('ht_id=204')||!hotels.some(e=>e.checked===true)){
  const unchecked=hotels.filter(e=>e.checked!==true);if(!unchecked.length)return {ok:false,frontier:'No observed hotel-only checkbox; classification remains unproven'};
  return batch(observation,[{row:unchecked[0]}],'Both checked hotel control and observed ht_id=204 query must confirm hotel-only results; duplicate popular/type labels require current observed id');
 }
 if(c.lowestFirst&&!(here.searchParams.get('order')==='price'&&/price \(lowest first\)|tarif \(le - cher en premier\)/i.test(observation.text))){
  const option=one(elements.filter(e=>usable(e)&&['menuitem','option'].includes(e.role)&&/^(?:Price \(lowest first\)|Tarif \(le - cher en premier\))$/i.test(e.name.trim())));
  if(option)return batch(observation,[{row:option}],'Fresh price order and first available hotel room/price must be verified');
  const sort=one(elements.filter(e=>e.role==='button'&&usable(e)&&/^(?:Trier par\s*:|Sort by\s*:)/i.test(e.name.trim())));
  return sort?batch(observation,[{row:sort}],'Fresh observed lowest-first sorting menu must appear'):{ok:false,frontier:'No unique observed price sort opener'};
 }
 state.resultEvidence={url:observation.url,revision:observation.revision,constraints:c,hotelOnlyControls:hotels.filter(e=>e.checked===true).map(e=>({id:e.id,name:e.name,value:e.value})),lowestFirst:!c.lowestFirst||here.searchParams.get('order')==='price'};
 return {ok:false,frontier:'Matching hotel-only stay results acquired; return only freshly observed available hotel/room/price/deal evidence',evidence:state.resultEvidence};
}
function resultCards(observation){return require('./c2f_answers.cjs').bookingCards(observation).map(card=>{
 const lines=card.sourceQuote.split('\n').map(x=>x.trim()),money='([€$£]\\s*[\\d.,]+)';
 const current=card.sourceQuote.match(new RegExp('(?:Tarif actuel|Current price)\\s*:\\s*'+money,'i'))?.[1],previous=card.sourceQuote.match(new RegExp('(?:Tarif initial|Original price)\\s*:\\s*'+money,'i'))?.[1];
 const numeric=value=>{let text=String(value||'').replace(/[^\d.,]/g,'');const decimal=text.match(/[.,](\d{1,2})$/);if(decimal){const at=text.lastIndexOf(decimal[0]);text=text.slice(0,at).replace(/[.,]/g,'')+'.'+decimal[1];}else text=text.replace(/[.,]/g,'');return Number(text);};
 const visibleReduction=current&&previous&&numeric(current)<numeric(previous)?card.sourceQuote.match(/(?:Tarif initial|Original price)[^\n]+/i)?.[0]:null;
 return {...card,room:card.room||lines.find(x=>/^(?:\d+\s*(?:[x×]\s*)?)?(?:Chambres?|Suites?|Standard|Double|Twin|King|Queen)\b/i.test(x))||null,price:current||card.price,previousPrice:previous||null,deal:card.deal||visibleReduction||null};
});}
module.exports={taskPlan,constraints,resultCards};

// Explicit opt-in real journey; never connects/reconnects the native launcher.
if(require.main===module){
 const fs=require('fs'),path=require('path'),crypto=require('crypto');
 const port=Number(process.argv[2]),out=process.argv[3];if(port<48721||port>48729||!Number.isInteger(port)||!/^scripts\/evidence\/C2g-booking-recovery[a-zA-Z0-9-]*\.json$/.test(out||'')||fs.existsSync(out))throw Error('Explicit assigned port and fresh scoped recovery receipt required');
 const report={schema:'neyvia.C2g.booking-recovery@1',startedAt:new Date().toISOString(),engine:'WebView2',route:'agent-private-desktop',port,stealth:false,providerCalls:0,tasks:[],calls:[]},base='http://127.0.0.1:'+port;
 let cookie,tab;const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),sleep=ms=>new Promise(r=>setTimeout(r,ms)),save=()=>fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');
 async function call(op,args={}){const start=performance.now(),response=await fetch(base+'/api/ui/browser',{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie},body:JSON.stringify({op,args}),signal:AbortSignal.timeout(60000)}),v=await response.json();report.calls.push({op,ms:performance.now()-start,status:response.status,ok:v.ok});save();if(!response.ok||v.ok===false){const e=Error(JSON.stringify(v));e.value=v;throw e;}return v;}
 async function done(v){if(v.status==='queued'||v.status==='running')v=await call('wait',{actionId:v.actionId||v.id,timeoutMs:30000});if(v.status==='failed'){const e=Error(JSON.stringify(v));e.value=v;throw e;}return v.result?.observation||v.result||v;}
 function snapshot(task,o){if(!o.elements)throw Error('Actual projection missing');const file=out.replace(/\.json$/,'')+'-'+task.id+'-'+task.observations.length+'.json',bytes=JSON.stringify(o)+'\n';fs.writeFileSync(file,bytes);task.observations.push({path:file,sha256:hash(bytes),url:o.url,revision:o.revision});save();return o;}
 async function observe(task){return snapshot(task,await done(await call('observe',{tabId:tab})));}
 async function ready(task){let o;for(let i=0;i<24;i++){o=await observe(task);if(o.readyState==='complete'&&o.elements.some(e=>e.inputName==='ss'&&usable(e,'fill'))||/captcha|^just a moment/i.test(o.title+' '+o.text.slice(0,500)))break;await sleep(500);}return o;}
 (async()=>{
  const auth=await fetch(base+'/api/auth/local-session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(!auth.ok)throw Error('Owner bootstrap unavailable');cookie=auth.headers.get('set-cookie').split(';')[0];
  const state=await call('state');if(!state.runtime?.connected)throw Error('Existing attached private native runtime required');
  const launch=JSON.parse(fs.readFileSync('.agent_control/C2g/private-native-'+port+'/native-live-guard.json'));if(launch.route!=='agent-private-desktop'||!launch.guard?.ok)throw Error('Healthy actual private-desktop guard required');
  report.launch={pid:launch.pid,controllerPid:launch.controllerPid,desktop:launch.desktop,guard:launch.guard};
  report.sourceSha256=hash(fs.readFileSync(__filename));const reuseIndex=process.argv.indexOf('--reuse'),reuseFile=reuseIndex<0?null:process.argv[reuseIndex+1];if(reuseFile&&!/^scripts\/evidence\/C2g-booking-recovery[a-zA-Z0-9-]*\.json$/.test(reuseFile))throw Error('Reuse only a scoped owned proof');const reuse=reuseFile?JSON.parse(fs.readFileSync(reuseFile)):null;if(reuse)report.reusedProfiles={receipt:reuseFile,sha256:hash(fs.readFileSync(reuseFile))};
  const definitions=JSON.parse(fs.readFileSync('scripts/evidence/C2-webvoyager-tasks.json')).tasks.filter(t=>new URL(t.startUrl).hostname.endsWith('booking.com'));
  for(const definition of definitions){const task={id:definition.id,goal:definition.goal,startedAt:new Date().toISOString(),steps:0,observations:[],flow:[]};report.tasks.push(task);save();
   try{
    const owned=reuse?.tasks.find(t=>t.id===definition.id&&t.profileId&&t.spaceId),profile=owned?{id:owned.profileId}:await call('profile.create',{name:'Booking recovery '+definition.id}),space=owned?{id:owned.spaceId}:await call('space.create',{name:'Booking recovery '+definition.id,profileId:profile.id});task.profileId=profile.id;task.spaceId=space.id;
    const opened=await call('tab.open',{url:definition.startUrl,engine:'webview2',spaceId:space.id});tab=opened.tabId;await done(opened);await done(await call('layout',{tabs:[{tabId:tab,x:0,y:0,width:1280,height:900,visible:true}]}));await sleep(1000);await done(await call('tab.grant',{tabId:tab,enabled:true}));let o=await ready(task),context={asOf:report.startedAt};const used=new Set();
    while(task.steps<24){
     o=await observe(task);const plan=taskPlan(task.goal,o,context);task.flow.push({plan});save();if(!plan.ok){task.frontier=plan.frontier;break;}
     const key=JSON.stringify([o.url,o.revision,plan.steps]);if(used.has(key)){task.frontier='Repeated unchanged plan; no blind replay';break;}used.add(key);
     for(const step of plan.steps){await done(await call('tab.grant',{tabId:tab,enabled:true}));o=await observe(task);const matches=o.elements.filter(e=>Object.entries(step.target).every(([k,v])=>e[k]===v));if(matches.length!==1)throw Error('Fresh semantic target changed or ambiguous');const effect=await done(await call('action',{tabId:tab,revision:o.revision,element:matches[0].id,action:step.action,...(step.value===undefined?{}:{value:step.value}),...(step.expect?{expect:step.expect}:{})}));task.steps++;task.flow.push({effect:{step,verification:effect.verification}});await sleep(step.action==='click'&&/Search|Rechercher|Hotel|Hôtel|Price|Tarif/i.test(step.target.name)?1200:350);o=await ready(task);}
    }
    const documents=task.observations.map(ref=>({ref,observation:JSON.parse(fs.readFileSync(ref.path))})),last=documents.at(-1).observation,cards=resultCards(last);
    const requested=constraints(task.goal,report.startedAt),chosen=requested.deal?cards.find(c=>c.deal&&c.room&&c.price):requested.lowestFirst?cards[0]:cards.find(c=>c.room&&c.price),u=new URL(last.url);
    task.resultConstraints=context.booking?.resultEvidence||null;task.candidate=chosen||null;task.checks=[{name:'Actual requested stay and occupancy',ok:u.searchParams.get('checkin')===requested.checkin&&u.searchParams.get('checkout')===requested.checkout&&Number(u.searchParams.get('group_adults'))===requested.adults&&Number(u.searchParams.get('no_rooms'))===requested.rooms},{name:'Actual hotel-only filter and classification',ok:(u.searchParams.get('nflt')||'').split(';').includes('ht_id=204')&&last.elements.some(e=>e.checked===true&&(e.value==='ht_id=204'||e.inputName==='ht_id=204'))},{name:'Fresh available hotel room and price',ok:!!chosen?.room&&!!chosen?.price&&last.text.includes(chosen.hotel)},{name:'Requested deal or lowest-first evidence',ok:requested.deal?!!chosen?.deal:!requested.lowestFirst||u.searchParams.get('order')==='price'&&/price \(lowest first\)|tarif \(le - cher en premier\)/i.test(last.text)}];task.success=task.checks.every(c=>c.ok);task.answerReturnedAt=new Date().toISOString();
   }catch(error){task.error=error.message;task.success=false;}
   finally{if(tab){await done(await call('tab.close',{tabId:tab})).catch(error=>task.closeError=error.message);tab=null;}task.finishedAt=new Date().toISOString();save();}
  }
 })().catch(error=>{report.error=error.message;process.exitCode=1;}).finally(async()=>{if(tab)await done(await call('tab.close',{tabId:tab})).catch(()=>{});report.finishedAt=new Date().toISOString();report.sourceUnchanged=report.sourceSha256===hash(fs.readFileSync(__filename));save();console.log(JSON.stringify({tasks:report.tasks.map(({id,steps,success,frontier,error,checks})=>({id,steps,success,frontier,error,checks})),sourceUnchanged:report.sourceUnchanged,error:report.error}));});
}
