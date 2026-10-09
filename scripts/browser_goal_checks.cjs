'use strict';
// Exact extracted facts from current observations; never a benchmark answer table.
const norm=s=>String(s??'').replace(/\s+/gu,' ').trim();
function verify(goal,answer,documents,asOf=new Date().toISOString()){
 const sourceGoal=require('./browser_source_goals.cjs').verify(goal,answer,documents,asOf);if(sourceGoal)return sourceGoal;
 const checks=[],add=(requirement,passed,evidence)=>checks.push({requirement,passed:!!passed,evidence});
 const content=norm(documents.map(o=>o.url+' '+o.title+' '+o.text+' '+JSON.stringify(o.elements?.filter(e=>!e.secret).map(e=>e.name)||[])).join(' '));
 const supported=value=>!!norm(value)&&content.includes(norm(value));
 if(answer.kind==='selected-recipe'&&/vegetarian lasagna/i.test(goal)){
  add('Observed vegetarian recipe ingredients and method',documents.some(o=>{const heading=o.elements.find(e=>e.role==='h1')?.name||'',at=o.text.indexOf(heading);return o.url===answer.url&&new URL(o.url).hostname==='www.allrecipes.com'&&(/vegetarian/i.test(heading)||/vegetarian\s+lasagna\s+recipes/i.test(o.text.slice(Math.max(0,at-600),at)));})&&supported(answer.ingredients)&&supported(answer.method),answer.url);
  if(/more than 100 reviews/i.test(goal)){
   add('Review count, distinct from rating count',answer.reviews>100&&supported(answer.reviewQuote),answer.reviewQuote);
   add('Minimum rating and sufficient servings',answer.rating>=4.5&&answer.servings>=Number(goal.match(/(?:for|suitable for)\s+(\d+)\s+people/i)?.[1]||1)&&supported(answer.servingsQuote),answer.servingsQuote);
  }else if(/zucchini/i.test(goal))add('Zucchini and minimum rating',answer.rating>=4&&/zucchini/i.test(answer.ingredients),answer.ingredients);
  else if(/under 600/i.test(goal)){
   add('Observed per-serving calories',Number.isFinite(answer.calories)&&answer.calories<600&&documents.some(o=>o.url===answer.url&&o.tables?.flat().some(row=>Number(row[0])===answer.calories&&row[1]==='Calories')),answer.calories);
   add('Preparation under one hour',Number.isFinite(answer.prepMinutes)&&answer.prepMinutes<60&&supported(answer.prepQuote),answer.prepQuote);
  }
 }else if(answer.kind==='dictionary'){
  const requested=goal.match(/["']([^"']+)["']/)?.[1];
  add('Requested dictionary entry',requested&&answer.word.toLowerCase()===requested.toLowerCase(),answer.word);
  add('Definition',supported(answer.definition),answer.definition);
  add('UK pronunciation',supported(answer.pronunciation?.uk),answer.pronunciation?.uk);
  add('US pronunciation',supported(answer.pronunciation?.us),answer.pronunciation?.us);
  if(/example|sample sentence/i.test(goal))add('Sample sentence',answer.examples?.some(supported),answer.examples?.find(supported));
 }else if(answer.kind==='product-price-comparison'&&/prices.*latest.*MacBook Air/i.test(goal)){
  const shop=documents.find(o=>new URL(o.url).hostname==='www.apple.com'&&new URL(o.url).pathname.includes('/shop/buy-mac/macbook-air')&&o.text.includes(answer.chip));
  const models=shop?.elements.filter(e=>e.role==='radio'&&/^\d{2}[-‑]inch\b/.test(e.name)&&/Buy from \$[\d,]+/.test(e.name))||[];
  add('Current MacBook Air model selectors',!!answer.chip&&models.length>=2&&answer.comparison?.length===models.length,answer.comparison);
  add('All observed starting purchase prices',answer.comparison?.every(row=>models.some(e=>e.name===row.sourceQuote&&e.name.includes(row.price))&&row.model.includes(row.sourceQuote.match(/^\d{2}[-‑]inch/)?.[0])),answer.comparison);
  add('Fresh purchase price comparison',answer.priceDifferenceUSD===Number(answer.comparison?.[1]?.price.replace(/[$,]/g,''))-Number(answer.comparison?.[0]?.price.replace(/[$,]/g,'')),answer.priceDifferenceUSD);
 }else if(answer.kind==='historical-product-comparison'&&/compare.*prices and chips/i.test(goal)){
  const requested=[...new Set(goal.match(/\biPhone\s+\d+\s*(?:Pro\s*Max|Pro|Plus|Mini)?/gi)||[])].map(v=>v.trim());
  add('Every requested historical model',requested.length>=2&&answer.comparison?.length===requested.length&&requested.every(model=>answer.comparison.some(row=>row.model===model)),requested);
  add('Fresh Apple releases contain each price and chip',answer.comparison?.every(row=>!!row.price&&!!row.chip&&documents.some(o=>o.url===row.url&&new URL(o.url).hostname==='www.apple.com'&&/^\/newsroom\/(?:19|20)\d{2}\/\d{2}\//.test(new URL(o.url).pathname)&&norm(o.text).includes(norm(row.priceQuote))&&norm(o.text).includes(norm(row.chipQuote))&&row.priceQuote.includes(row.price)&&row.chipQuote.includes(row.chip))),answer.comparison);
  add('Returned numerical comparison',answer.priceDifferenceUSD===Number(answer.comparison?.[1]?.price?.replace(/[$,]/g,''))-Number(answer.comparison?.[0]?.price?.replace(/[$,]/g,'')),answer.priceDifferenceUSD);
 }else if(answer.kind==='ranked-repositories'&&/trending.*Python.*most stars/i.test(goal)){
  const list=documents.find(o=>new URL(o.url).hostname==='github.com'&&new URL(o.url).pathname==='/trending/python'&&!o.truncated&&!o.elementsTruncated);
  const stars=list?.elements.filter(e=>e.href&&/^https:\/\/github\.com\/[^/]+\/[^/]+\/stargazers$/.test(e.href)&&/^[\d,]+$/.test(e.name.trim())).map(e=>({repository:e.href.split('/').slice(3,5).join('/'),stars:Number(e.name.replaceAll(',',''))}))||[];
  add('Complete observed Python trending list',stars.length>0&&answer.ranking?.length===stars.length,stars);
  add('Greatest displayed total stars',!!answer.selection&&stars.some(row=>row.repository===answer.selection.repository&&row.stars===answer.selection.stars)&&stars.every(row=>row.stars<=answer.selection.stars),answer.selection);
 }else if(answer.kind==='selected-course'&&/beginner.*1-3 months/i.test(goal)){
  const topic=goal.match(/about ['"]([^'"]+)['"]/i)?.[1];
  add('Requested university course',!!topic&&answer.title?.toLowerCase().includes(topic.toLowerCase())&&/university|college|universidad|institut/i.test(answer.provider)&&supported(answer.sourceQuote)&&!!answer.url&&documents.some(o=>o.elements.some(e=>e.href===answer.url&&(e.name.trim()===answer.title||e.name.startsWith(answer.title+', offered by '+answer.provider+', COURSE')))),answer.sourceQuote);
  add('Observed beginner and duration metadata',answer.level==='Beginner'&&answer.duration==='1–3 months'&&/Beginner.*Course.*1\s*[-–]\s*3 Months/i.test(norm(answer.sourceQuote)),answer.sourceQuote);
 }else if(answer.kind==='news-updates'&&/trades.*(?:past|last)\s+(?:two|2)\s+days/i.test(goal)){
  const transaction=documents.find(o=>/(?:^|\.)espn\.(?:com|co\.uk)$/.test(new URL(o.url).hostname)&&new URL(o.url).pathname==='/nba/transactions'&&!o.truncated&&!o.tablesTruncated);
  add('Fresh chronological transaction feed',!!transaction&&answer.coverage?.completeThroughNewestPublishedEntry&&supported(answer.sourceQuotes?.[0]),answer.coverage);
  add('Latest trade article also inspected',documents.some(o=>/(?:^|\.)espn\.(?:com|co\.uk)$/.test(new URL(o.url).hostname)&&/trade.tracker/i.test(o.title)&&!o.truncated&&supported(o.title)),answer.sourceQuotes);
  add('Scoped negative applies to the requested UTC dates',answer.trades?.length===0&&answer.coverage?.newestPublishedEntry<answer.dateWindow?.from&&answer.dateWindow?.from===require('./c2f_site_flows.cjs').recentDate(goal,asOf)&&answer.dateWindow?.to===String(asOf).slice(0,10)&&answer.answer?.includes("No NBA trade is listed in ESPN's latest transaction feed"),answer.answer);
 }else if(answer.kind==='selected-hotel-room'&&/cheapest.*Jakarta/i.test(goal)){
  const nextYear=new Date().getUTCFullYear()+(new Date().toISOString().slice(5,10)>'01-01'?1:0);
  add('Requested three-night dates and party',answer.checkin===nextYear+'-01-01'&&answer.checkout===nextYear+'-01-04'&&answer.adults===2&&answer.rooms===1,answer.sources?.map(s=>s.url));
  add('Cheapest ordered available hotel room',supported(answer.hotel)&&supported(answer.room)&&supported(answer.price)&&documents.some(o=>new URL(o.url).searchParams.get('order')==='price'&&new URL(o.url).searchParams.get('ss')?.toLowerCase().includes('jakarta')&&/Price \(lowest first\)|Tarif \(le - cher en premier\)/i.test(o.text)),answer.sourceQuote);
  add('Answer only hotel room and price',typeof answer.answer==='string'&&answer.answer.includes(answer.hotel)&&answer.answer.includes(answer.price),answer.answer);
 }else if(answer.kind==='selected-hotel-deal'&&/Mexico.*December 25-26/i.test(goal)){
  const year=new Date().getUTCFullYear()+(new Date().toISOString().slice(5,10)>'12-25'?1:0);
  add('Mexico destination and requested dates',/Mexico|Mexique|México/i.test(answer.destination)&&answer.checkin===year+'-12-25'&&answer.checkout===year+'-12-26',answer.sources?.map(s=>s.url));
  add('Observed hotel deal',supported(answer.hotel)&&supported(answer.deal),answer.sourceQuote);
  add('Hotel property type, independently selected',answer.sources?.some(s=>new URL(s.url).searchParams.get('nflt')?.split(';').includes('ht_id=204')),answer.sources?.map(s=>s.url));
 }else if(answer.kind==='selected-hotel-stay'){
  const requested=require('./c2g_booking_flow.cjs').constraints(goal,asOf);
  add('Requested destination, dates and party',requested&&answer.destination?.toLowerCase()===requested.destination.toLowerCase()&&answer.checkin===requested.checkin&&answer.checkout===requested.checkout&&answer.adults===requested.adults&&answer.rooms===requested.rooms,requested);
  add('Fresh available hotel room and price',supported(answer.hotel)&&supported(answer.room)&&supported(answer.price)&&supported(answer.sourceQuote),answer.sourceQuote);
  add('Hotel-only applied result filter',documents.some(o=>new URL(o.url).searchParams.get('nflt')?.split(';').includes('ht_id=204')&&o.elements.some(e=>e.checked===true&&(e.value==='ht_id=204'||e.inputName==='ht_id=204'))),answer.sources?.map(s=>s.url));
 }else if(answer.kind==='calculation'){
  add('Fresh rendered Wolfram result',answer.results?.length>0&&answer.results.every(supported),answer.results);
  if(/significant figures/i.test(goal))add('Requested significant-figure scientific notation',answer.significantFigures===Number(goal.match(/(\d+) significant figures/i)?.[1])&&supported(answer.formattingBasis)&&!!answer.formattedResult,answer.formattedResult);
  else if(/pentagram/i.test(goal))add('Inner-region constraint observed',answer.results?.some(x=>/[<>≤≥]/.test(x)&&/x|y/.test(x)),answer.results);
  else add('Requested derivative point observed',/derivative.*x\^2.*5\.6/i.test(answer.query)&&answer.results?.some(x=>/^\s*[-+]?\d+(?:\.\d+)?\s*$/.test(x)),answer.query);
 }
 return {verified:checks.length>0&&checks.every(c=>c.passed),checks};
}
module.exports={verify};
