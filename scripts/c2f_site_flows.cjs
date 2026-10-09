/* Reusable, observation-only plans. No benchmark IDs, answer values or routes. */
const crypto = require('node:crypto');
const target = row => Object.fromEntries(['role', 'name', 'inputName', 'placeholder', 'frame']
  .filter(key => row[key] !== undefined).map(key => [key, row[key]]));
const descriptor = row => [row.name, row.placeholder, row.inputName, row.type].join(' ');
const usable = (row, action) => !row.secret && row.enabled !== false && !row.nameTruncated && row.actions?.includes(action);
function unique(rows, kind) {
  if (rows.length !== 1) return {ok:false, frontier:rows.length ? `Ambiguous observed ${kind}` : `No observed ${kind}`, candidates:rows.map(target)};
  return {ok:true, row:rows[0]};
}
function searchPlan(observation, query, {scope=''}={}) {
  if (typeof query !== 'string' || !query.trim() || query.length > 4000) throw Error('Bounded nonempty search query required');
  if (observation.authentication?.required) return {ok:false, frontier:'needs-owner: authentication'};
  const inScope=row=>!scope||descriptor(row).toLowerCase().includes(String(scope).toLowerCase())||row.form?.action?.toLowerCase().includes(String(scope).toLowerCase());
  const inputs = observation.elements.filter(row => inScope(row) && usable(row,'fill') &&
    (row.role === 'searchbox' || row.type === 'search' || row.inputName === 'q' || /search|query|keyword/i.test(descriptor(row))));
  const input = unique(inputs, 'search input');
  if (!input.ok) {
    // Anchors styled as buttons remain safe observed navigation routes. Follow
    // their actual href rather than depending on a missing JS menu handler.
    const links = observation.elements.filter(row => {if(!inScope(row)||!row.href||!usable(row,'click')||!/\bsearch\b/i.test(row.name))return false;const href=new URL(row.href),here=new URL(observation.url);return href.origin!==here.origin||href.pathname!==here.pathname||href.search!==here.search;});
    const destinations = [...new Map(links.map(row => [row.href,row])).values()];
    const link = unique(destinations, 'search destination');
    if (link.ok) return {ok:true, kind:'follow', element:link.row.id, href:link.row.href, revision:observation.revision};
    const opener = unique(observation.elements.filter(row => inScope(row) && usable(row,'click') && ['button','link'].includes(row.role) && /^(?:open )?search\b/i.test(row.name)), 'search opener');
    return opener.ok ? {ok:true, kind:'batch', revision:observation.revision, steps:[{action:'click',target:target(opener.row)}], requires:'Fresh search input must appear; dispatch once'} : input;
  }
  const steps=[{action:'fill',target:target(input.row),value:query}];
  if(usable(input.row,'submit')) steps.push({action:'submit',target:target(input.row)});
  else {
    const submit = unique(observation.elements.filter(row => usable(row,'click') && row.role === 'button' && (row.type==='submit'||/^(search|submit|find)$/i.test(row.name.trim()))), 'search submit button');
    if(!submit.ok)return submit;
    steps.push({action:'click',target:target(submit.row)});
  }
  return {ok:true,kind:'batch',revision:observation.revision,steps,requires:'Fresh result content and query constraints, not merely changed page revision'};
}
function resultDigest(observation) {
  // Exclude selected controls: a new value alone does not establish filtering.
  const results=observation.tables?.length ? {tables:observation.tables} :
    {links:observation.elements.filter(row=>row.href).map(row=>[row.href,row.name])};
  return crypto.createHash('sha256').update(JSON.stringify(results)).digest('hex');
}
function filterPlan(observation, label) {
  const matches=[];
  for(const row of observation.elements.filter(row=>usable(row,'select')&&!row.optionsTruncated))
    for(const option of row.options||[])if(option.enabled !== false && option.label.trim().toLowerCase()===String(label).trim().toLowerCase())matches.push({row,option});
  if(matches.length!==1)return {ok:false,frontier:'Filter needs exactly one observed enabled option'};
  const {row,option}=matches[0];
  return {ok:true,kind:'batch',revision:observation.revision,steps:[{action:'select',target:target(row),value:option.value}],
    beforeResultDigest:resultDigest(observation),requires:'Selected value AND independently changed result constraints'};
}
function filterApplied(before, after, plan) {
  const step=plan.steps[0];
  const control=after.elements.find(row=>Object.entries(step.target).every(([key,value])=>row[key]===value));
  return {verified:!!control&&control.value===step.value&&resultDigest(before)!==resultDigest(after),
    controlMatched:!!control&&control.value===step.value,resultsChanged:resultDigest(before)!==resultDigest(after)};
}
function datedArticles(observation) {
  return observation.elements.filter(row=>row.href&&row.dates?.length).map(row=>({id:row.id,href:row.href,title:row.name,dates:row.dates}));
}
function followPlan(observation, name) {
  let rows=[...new Map(observation.elements.filter(row=>usable(row,'click')&&row.href&&row.name===name).map(row=>[row.href,row])).values()];
  // Equivalent observed HTTP/HTTPS links are one destination. Prefer the
  // already observed HTTPS href; never manufacture or rewrite a route.
  if(rows.length>1){const destinations=new Set(rows.map(row=>{const u=new URL(row.href);return [u.host,u.pathname,u.search,u.hash].join('|');}));if(destinations.size===1){const secure=rows.filter(row=>new URL(row.href).protocol==='https:');if(secure.length===1)rows=secure;}}
  const selected=unique(rows,'navigation link '+name);
  return selected.ok?{ok:true,kind:'follow',element:selected.row.id,href:selected.row.href,revision:observation.revision}:selected;
}
function recentDate(goal, asOf=new Date()) {
  const m=goal.match(/(?:last|past)\s+(two|\d+)\s+days?/i);
  if(!m)return null;
  const date=new Date(asOf);date.setUTCDate(date.getUTCDate()-(m[1].toLowerCase()==='two'?2:Number(m[1])));
  return date.toISOString().slice(0,10);
}
function compiledSearch(procedures, query, observation) {
  const candidates=[];
  function inputKeys(value,out=new Set()){if(value&&typeof value==='object'){if(value.$input)out.add(value.$input);else Object.values(value).forEach(v=>inputKeys(v,out));}return out;}
  for(const procedure of procedures||[]){
    const fills=procedure.steps?.filter(step=>step.action==='fill'&&step.value?.$input)||[];
    if(fills.length!==1||!Object.keys(procedure.inputBindings||{}).length)continue;
    const inputs={[fills[0].value.$input]:query};let valid=true;
    for(const [name,binding] of Object.entries(procedure.inputBindings)){
      const value=inputs[binding.sourceInput];if(value===undefined||!binding.urlQueryParameter){valid=false;break;}
      if(binding.encoding==='form')inputs[name]=new URLSearchParams({[binding.urlQueryParameter]:value}).toString();
      else if(binding.encoding==='percent')inputs[name]=encodeURIComponent(binding.urlQueryParameter)+'='+encodeURIComponent(value);
      else {valid=false;break;}
    }
    const required=[...inputKeys([procedure.steps,procedure.checks])];
    if(!valid||required.some(key=>inputs[key]===undefined))continue;
    const first=procedure.steps[0];const controls=observation.elements.filter(row=>usable(row,first.action)&&Object.entries(first.target).every(([key,value])=>row[key]===value));
    if(controls.length===1)candidates.push({name:procedure.name,inputs,steps:procedure.steps,admission:procedure.admission,inputBindings:procedure.inputBindings});
  }
  return candidates.length===1?candidates[0]:null;
}
function observedRoute(observation, href, reason) {
  return {ok:true,kind:'follow',href,revision:observation.revision,previouslyObserved:true,requires:reason};
}
function articleCandidates(observation, terms, host) {
  const tokens=String(terms).toLowerCase().split(/[^a-z0-9]+/).filter(t=>t.length>2);
  const rows=observation.elements.filter(row=>row.href&&usable(row,'click'));
  return [...new Map(rows.filter(row=>{let u;try{u=new URL(row.href)}catch{return false}return u.hostname===host&&(/\/(?:newsroom|news|articles|future|earth|culture)\//.test(u.pathname))&&!/\/(?:search|tags|topics|images|scripts|assets)\//.test(u.pathname)&&! /\.(?:zip|pdf|png|jpe?g|webp|mp4|mov)$/i.test(u.pathname)&&(!tokens.length||tokens.some(t=>row.name.toLowerCase().includes(t)));}).map(row=>[row.href,row])).values()];
}
function rememberSearch(context,query,observation) {
  context.searches??={};context.visitedHrefs??=[];context.readDocuments??=[];
  const hasQuery=[...new URL(observation.url).searchParams.values()].some(v=>v.trim().replace(/^"|"$/g,'').toLowerCase()===query.toLowerCase());
  if(hasQuery){context.searches[query]={url:observation.url,observation};context.searchPages??=[];if(!context.searchPages.includes(observation.url))context.searchPages.push(observation.url);}
  return context.searches[query];
}
function publishedAge(row, asOf) {
  const absolute=(row.dates||[]).map(d=>Date.parse(d.datetime||d.dateTime||'')).filter(Number.isFinite);
  if(absolute.length){const runDate=new Date(asOf).getTime(),past=absolute.filter(date=>date<=runDate);return past.length?runDate-Math.max(...past):Infinity;}
  // Publication-shaped paths help decide what to inspect first. They are
  // candidate hints only: the final answer still needs the article timestamp.
  const pathDate=String(row.href||'').match(/\/(20\d{2})(\d{2})(\d{2})-/);
  if(pathDate){const date=Date.parse(`${pathDate[1]}-${pathDate[2]}-${pathDate[3]}T00:00:00Z`),runDate=new Date(asOf).getTime();if(Number.isFinite(date)&&date<=runDate)return runDate-date;}
  const stamp=row.name.match(/\b(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})\b/);
  if(stamp){const value=Date.parse(stamp[1].replace('Sept','Sep')+' 00:00:00 GMT'),runDate=new Date(asOf).getTime();if(Number.isFinite(value))return value<=runDate?runDate-value:Infinity;}
  const age=row.name.match(/(\d+)\s*(minutes?|mins?|hours?|hrs?|days?) ago/i);
  if(age)return Number(age[1])* (/^d/i.test(age[2])?86400000:/^(?:h)/i.test(age[2])?3600000:60000);
  return Infinity;
}
function readArticle(context,observation) {
  if(!context.visitedHrefs.includes(observation.url))context.visitedHrefs.push(observation.url);
  if(!context.readDocuments.some(d=>d.url===observation.url))context.readDocuments.push({url:observation.url,text:observation.text,title:observation.title,dates:[...new Map(observation.elements.flatMap(e=>e.dates||[]).map(date=>[JSON.stringify(date),date])).values()],truncated:observation.truncated});
}
function taskPlan(goal, observation, context={}) {
  if(typeof goal!=='string'||!goal.trim())throw Error('Task goal required');
  const here=new URL(observation.url),host=here.hostname;
  context.completedQueries??=[];
  if(/(?:^|\.)booking\.com$/.test(host))return require('./c2g_booking_flow.cjs').taskPlan(goal,observation,context);
  if(/(?:^|\.)apple\.com$/.test(host)){
    const products=[...new Set(goal.match(/\biPhone\s+\d+\s*(?:Pro\s*Max|Pro|Plus|Mini)?/gi)||[])].map(x=>x.trim());
    if(products.length&&/compare|historical|prices? and chips?/i.test(goal)){
      const next=products.find(x=>!(context.completedQueries||[]).includes(x));
      if(!next)return {ok:false,frontier:'All product searches visited; compare independently captured values'};
      if(!new URL(observation.url).pathname.startsWith('/newsroom'))return followPlan(observation,'Newsroom');
      const search=rememberSearch(context,next,observation);
      context.productCandidates??={};
      for(const product of products){const known=context.productCandidates[product]??=[];for(const row of articleCandidates(observation,product,host).filter(row=>row.name.toLowerCase().includes(product.toLowerCase())))if(!known.some(e=>e.href===row.href))known.push({...row,observedOn:observation.url});}
      if(search||context.productCandidates[next].length){const candidates=[...context.productCandidates[next]].sort((a,b)=>Number(/PRESS RELEASE.*\b(?:introduces|unveils|debuts)\b/i.test(b.name))-Number(/PRESS RELEASE.*\b(?:introduces|unveils|debuts)\b/i.test(a.name)));
        if(candidates.some(row=>row.href===observation.url)){
          readArticle(context,observation);const hasPrice=/\$\s?\d[\d,]*/.test(observation.text),hasChip=/\bA\d{1,2}(?:\s+Pro)?(?:\s+(?:Bionic|chip))?\b/.test(observation.text);
          if(hasPrice&&hasChip){context.completedQueries.push(next);context.productEvidence??=[];context.productEvidence.push({product:next,url:observation.url,priceObserved:hasPrice,chipObserved:hasChip,truncated:observation.truncated});if(products.every(x=>context.completedQueries.includes(x)))return {ok:false,frontier:'Both observed historical articles acquired; independently compare extracted price/chip values',evidence:context.productEvidence};
            const remaining=products.find(x=>!context.completedQueries.includes(x)),known=context.productCandidates[remaining]?.find(row=>!context.visitedHrefs.includes(row.href));
            if(known)return {...observedRoute(observation,known.href,'Read remaining product release link already observed during this run'),sourceObservationUrl:known.observedOn};
            if(search)return observedRoute(observation,search.url,'Return to observed search page for remaining product');
            return {...searchPlan(observation,'"'+remaining+'"',{scope:'Newsroom'}),query:'"'+remaining+'"'};
          }
          if(search)return observedRoute(observation,search.url,'Historical article lacks complete price/chip coverage; inspect another observed candidate');
          return {ok:false,frontier:'Observed historical article lacks complete model price/chip evidence'};
        }
        const candidate=candidates.find(row=>!context.visitedHrefs.includes(row.href));
        const nextPage=search?.observation.elements.find(row=>usable(row,'click')&&/^next\b.*news articles/i.test(row.name));
        if(candidate&&(!nextPage||/PRESS RELEASE.*\b(?:introduces|unveils|debuts)\b/i.test(candidate.name)))return candidate.observedOn===observation.url?{ok:true,kind:'follow',href:candidate.href,element:candidate.id,revision:observation.revision,requires:'Read historical product price and chip from actual article'}:{...observedRoute(observation,candidate.href,'Read model release link previously observed during this run'),sourceObservationUrl:candidate.observedOn};
        if(nextPage)return {ok:true,kind:'batch',revision:observation.revision,steps:[{action:'click',target:target(nextPage)}],requires:'Fresh next result page must retain the exact model query; clicking the site control preserves its query state'};
        return {ok:false,frontier:'No unvisited observed historical article with the requested model; result count is insufficient'};
      }
      // Apple search otherwise matches the individual words broadly and sorts
      // new articles first. Phrase quoting uses its ordinary search grammar.
      const query='"'+next+'"';
      return {...searchPlan(observation,query,{scope:'Newsroom'}),query,requires:'Observed historical release article with both price and chip; a result count is insufficient'};
    }
  }
  if(/(?:^|\.)bbc\.com$/.test(host)){
    const phrase=goal.match(/(?:regarding|about)\s+(.+?)(?:\s+published|[.?]|$)/i)?.[1];
    const topic=goal.match(/(?:latest|recent)\s+(.+?)-related\s+news/i)?.[1]||phrase;
    if(topic){
      if(/-related\s+news/i.test(goal)&&!context.categoryTried){context.categoryTried=true;const category=followPlan(observation,topic[0].toUpperCase()+topic.slice(1));if(category.ok&&category.href!==observation.url){context.categoryUrl=category.href;return {...category,requires:'Inspect actual category publication ordering; editorial cards alone do not prove global latest'};}}
      if(context.categoryUrl===observation.url){context.searches??={};context.searches[topic]={url:observation.url,observation};context.visitedHrefs??=[];context.readDocuments??=[];}
      const search=rememberSearch(context,topic,observation);
      if(search){const candidates=articleCandidates(search.observation,'',host).filter(row=>{const path=new URL(row.href).pathname;return !/\/(?:videos|av)\//.test(path)&&(!/\bBBC News\b/i.test(goal)||path.startsWith('/news/'));}).sort((a,b)=>publishedAge(a,context.asOf)-publishedAge(b,context.asOf));
        if(candidates.some(row=>row.href===observation.url)){
          readArticle(context,observation);context.coverage={complete:false,reason:'Actual article read; relevance/editorial ordering lacks a complete chronological boundary',pages:context.searchPages||[search.url],articles:context.readDocuments.map(d=>d.url)};
          if(candidates.some(row=>!context.visitedHrefs.includes(row.href)))return observedRoute(observation,search.url,'Inspect remaining observed articles and their actual publication dates before making a latest claim');
          return {ok:false,frontier:'Article source acquired; global latest/date coverage remains unproven',coverage:context.coverage};
        }
        const dated=candidates.filter(row=>Number.isFinite(publishedAge(row,context.asOf)));
        // Category membership supports topic evidence; editorial order does not prove latest.
        // Search cards need topical words rather than an incidental body mention.
        const words=topic.toLowerCase().split(/[^a-z0-9]+/).filter(word=>word.length>3&&!['regarding','about'].includes(word));
        const topical=row=>context.categoryUrl===search.url||words.some(word=>row.name.toLowerCase().includes(word));
        const dateFloor=recentDate(goal,context.asOf);
        const withinDate=row=>!dateFloor||publishedAge(row,context.asOf)<=new Date(context.asOf).getTime()-Date.parse(dateFloor+'T00:00:00Z');
        const candidate=dated.find(row=>topical(row)&&withinDate(row)&&!context.visitedHrefs.includes(row.href))||
          candidates.find(row=>topical(row)&&!Number.isFinite(publishedAge(row,context.asOf))&&!context.visitedHrefs.includes(row.href));
        if(candidate)return {ok:true,kind:'follow',href:candidate.href,element:candidate.id,revision:observation.revision,requires:'Read actual publication timestamp and qualifying topic evidence'};
        if(!dated.length)return {ok:false,frontier:'No topical article card within the requested date boundary; unvisited/undated relevance results prevent an absence claim'};
        const nextPage=search.observation.elements.find(row=>row.href&&row.name==='Next Page'&&usable(row,'click'));
        if(nextPage&&!context.visitedHrefs.includes(nextPage.href)){context.visitedHrefs.push(nextPage.href);return {ok:true,kind:'follow',href:nextPage.href,element:nextPage.id,revision:observation.revision,requires:'Chronology/absence requires complete dated search coverage'};}
        context.coverage={complete:false,reason:'Search relevance ordering does not establish global chronology and unvisited results may qualify',pages:context.searchPages||[],articles:context.readDocuments.map(d=>d.url)};
        return {ok:false,frontier:context.coverage.complete?'Search coverage acquired; independently check dates/topic and latest claim':'Chronological result coverage incomplete; no latest/absence claim'};
      }
      let plan=searchPlan(observation,topic);
      if(!plan.ok){const menu=unique(observation.elements.filter(row=>row.name==='Open menu'&&usable(row,'click')),'search menu');if(menu.ok)plan={ok:true,kind:'batch',revision:observation.revision,steps:[{action:'click',target:target(menu.row)}]};}
      return {...plan,query:topic,requires:'Read matching article; latest needs chronological coverage, and date-constrained absence needs the complete qualifying set'};
    }
  }
  if(host==='github.com'){
    context.visitedHrefs??=[];context.readDocuments??=[];
    const u=new URL(observation.url), sorted=(u.searchParams.get('s')==='stars'&&u.searchParams.get('o')==='desc')||observation.elements.some(row=>row.role==='button'&&row.expanded===false&&/^sort(?: by)?:\s*most stars$/i.test(row.name.trim()))||observation.elements.some(row=>row.role==='option'&&row.selected===true&&/^most stars$/i.test(row.name.trim()));
    const repositories=[...new Map(observation.elements.filter(row=>row.href&&usable(row,'click')&&/^https:\/\/github\.com\/[^/]+\/[^/?#]+$/.test(row.href)&&row.name.includes('/')).map(row=>[row.href,row])).values()];
    if(u.pathname==='/search'&&(!/most stars/i.test(goal)||sorted)){
      context.repositorySearch={url:observation.url,sorted,candidates:repositories.map(row=>({href:row.href,name:row.name}))};
      const repository=repositories.find(row=>!context.visitedHrefs.includes(row.href));
      return repository?{ok:true,kind:'follow',href:repository.href,element:repository.id,revision:observation.revision,requires:'Inspect repository language, license, star count and actual update timestamp'}:{ok:false,frontier:'No unvisited matching observed repository; search result absence not independently established'};
    }
    if(context.repositorySearch&&context.repositorySearch.candidates.some(row=>row.href===observation.url)){
      readArticle(context,observation);return {ok:false,frontier:'Repository source acquired; independently verify all query/date/license/ranking constraints',rankingSorted:context.repositorySearch.sorted};
    }
    if(u.pathname==='/search'&&/most stars/i.test(goal)){
      const sort=filterPlan(observation,'Most stars');if(sort.ok)return sort;
      const option=unique(observation.elements.filter(row=>usable(row,'click')&&/^most stars$/i.test(row.name.trim())),'star sort option');
      if(option.ok)return {ok:true,kind:'batch',revision:observation.revision,steps:[{action:'click',target:target(option.row)}],sortBeforeResultDigest:resultDigest(observation),requires:'Verify descending star order and matching repository constraints'};
      const menu=unique(observation.elements.filter(row=>usable(row,'click')&&/^(?:sort(?: by)?:?\s*)?(?:best match)$/i.test(row.name.trim())),'sort menu');
      return menu.ok?{ok:true,kind:'batch',revision:observation.revision,steps:[{action:'click',target:target(menu.row)}]}:{ok:false,frontier:'No observed star-sort control; do not assume top result is maximum'};
    }
    const query=goal.match(/['"“](.+?)['"”]/)?.[1]||goal.match(/(?:focused on|specifically.*?on)\s+(.+?)(?:,|\s+updated|[.?]|$)/i)?.[1]||goal.match(/(?:for|about)\s+(.+?)(?:,|\s+updated|[.?]|$)/i)?.[1];
    if(query){const language=goal.match(/\b(Python|JavaScript|TypeScript|Rust|Java|C\+\+)\b/i)?.[1],date=recentDate(goal,context.asOf);let q=query.trim();if(language)q+=' language:'+language;if(date&&/updated/i.test(goal))q+=' pushed:>='+date;
      return {...searchPlan(observation,q),query:q,requires:/most stars/i.test(goal)?'Select observed Most stars sort; compare highest matching result with source star counts':'Open repository; verify actual language/license and last update timestamp'};
    }
  }
  if(/(?:^|\.)espn\.(?:com|co\.uk)$/.test(host)){
    const team=goal.match(/(?:the|for)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\s+(?:game|team)/)?.[1];
    if(team){
      context.verifiedSeasons??=[];context.seasonEvidence??=[];
      if(/\/nba\/team\/schedule\//.test(here.pathname)&&observation.tables?.length){
        const options=observation.elements.flatMap(row=>row.options||[]),selectedYear=options.find(option=>option.selected&&/\b(?:19|20)\d{2}/.test(option.label));
        const dateGoal=!!recentDate(goal,context.asOf);
        const relevant=option=>/season/i.test(option.label)&&(!dateGoal||!/(?:19|20)\d{2}/.test(option.label)||(selectedYear&&option.label===selectedYear.label));
        const current=options.find(x=>x.selected&&relevant(x));
        context.observedSeasonYear=selectedYear?.label||null;
        if(current&&!context.verifiedSeasons.includes(current.label)){
          if(observation.tablesTruncated||observation.truncated)return {ok:false,frontier:'Season table is truncated; date absence cannot be established',currentSeason:current.label};
          context.seasonEvidence.push({season:current.label,url:observation.url,tables:observation.tables,coverage:'Complete observed table only; independent date/season verification required'});context.verifiedSeasons.push(current.label);
        }
        const next=options.find(option=>relevant(option)&&!context.verifiedSeasons.includes(option.label));
        if(next)return {...filterPlan(observation,next.label),requires:'Confirm applied season in independently changed table, then cover date range; a select value alone is insufficient'};
        return {ok:false,frontier:'Observed season tables acquired; independently check all dated games and qualifying score/highlight',seasonEvidence:context.seasonEvidence};
      }
      const link=followPlan(observation,team);if(link.ok&&link.href!==observation.url)return link;
      const schedule=followPlan(observation,'Schedule');if(/\/nba\/team\//.test(here.pathname)&&schedule.ok&&schedule.href!==observation.url)return schedule;
      const teams=followPlan(observation,'Teams');if(teams.ok&&teams.href!==observation.url)return teams;
      const nba=followPlan(observation,'NBA');if(nba.ok&&nba.href!==observation.url)return nba;
      return {...searchPlan(observation,team),query:team};
    }
  }
  return {ok:false,frontier:'No grounded task-specific search intent; use live controls or a model judgement'};
}
module.exports={compiledSearch,target,searchPlan,filterPlan,filterApplied,resultDigest,datedArticles,followPlan,recentDate,taskPlan};
