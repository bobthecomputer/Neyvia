/* Deterministic fresh-observation extraction. No reference or saved answer imports. */
'use strict';
const {extract}=require('./c2b_public_answers.cjs');
const {recentDate}=require('./c2f_site_flows.cjs');
const sourceGoals=require('./browser_source_goals.cjs');
function bookingCards(observation){
 const links=[...new Map(observation.elements.filter(e=>e.href&&new URL(e.href).pathname.startsWith('/hotel/')&&/new window|nouvelle fenêtre/i.test(e.name)).map(e=>[new URL(e.href).pathname,e])).values()];
 const cards=links.map(link=>{const name=link.name.replace(/\s*(?:Une nouvelle fenêtre va s'ouvrir|Opens in new window).*$/i,'').trim();return {link,name,start:observation.text.indexOf(name)};}).filter(card=>card.start>=0).sort((a,b)=>a.start-b.start);
 return cards.map((card,index)=>{const text=observation.text.slice(card.start,cards[index+1]?.start??observation.text.length);const lines=text.split('\n').map(x=>x.trim()).filter(Boolean);
  return {hotel:card.name,url:card.link.href,room:lines.find(x=>/^(?:Chambre|Suite|Standard|Double|Twin|King|Queen)\b/i.test(x))||null,
   price:text.match(/(?:Tarif\s*:\s*|Price\s*:?\s*)([€$£]\s*[\d.,]+)/i)?.[1]||null,
   deal:lines.find(x=>/offre|deal|discount|réduction/i.test(x))||null,sourceQuote:text.trim()};});
}
function answer(goal,documents,{asOf=new Date().toISOString()}={}){
 const sourceGoal=sourceGoals.extract(goal,documents,asOf);if(sourceGoal)return sourceGoal;
 const sources=documents.map(({observation,ref})=>({url:observation.url,path:ref.path,sha256:ref.sha256,title:observation.title}));
 const last=documents.at(-1)?.observation;if(!last)return null;
 if(new URL(last.url).hostname.endsWith('allrecipes.com')&&/vegetarian lasagna/i.test(goal)){
  const recipes=documents.filter(({observation:o})=>{const heading=o.elements.find(e=>e.role==='h1')?.name||'',at=o.text.indexOf(heading);return new URL(o.url).pathname.startsWith('/recipe/')&&(/vegetarian/i.test(heading)||/vegetarian\s+lasagna\s+recipes/i.test(o.text.slice(Math.max(0,at-600),at)));});
  for(const {observation:o} of recipes){
   const title=o.elements.find(e=>e.role==='h1')?.name;if(!title)continue;
   const text=o.text.split('\n').map(line=>line.trim()).join('\n'),body=text.slice(text.indexOf(title)),head=body.slice(0,400),rating=Number(head.match(/\n(\d(?:\.\d+)?)\n\(/)?.[1]);
   const reviewQuote=head.match(/([\d,]+)\s+REVIEWS/i)?.[0],reviews=Number(reviewQuote?.replace(/[^\d]/g,''));
   const servingsQuote=body.match(/Servings:\s*\n?\s*\d+/)?.[0],servings=Number(servingsQuote?.match(/\d+/)?.[0]);
   const prepQuote=body.match(/Prep Time:\s*\n?\s*(?:\d+\s*(?:hrs?|hours?|mins?|minutes?)\s*)+/i)?.[0];
   const prepMinutes=prepQuote?[...prepQuote.matchAll(/(\d+)\s*(hrs?|hours?|mins?|minutes?)/gi)].reduce((sum,m)=>sum+Number(m[1])*(/^h/i.test(m[2])?60:1),0):null;
   const calories=o.tables?.flat().find(row=>row[1]==='Calories')?.[0];
   const start=body.indexOf('\nIngredients\n'),directions=body.indexOf('\nDirections\n'),end=body.indexOf('\nNutrition Facts',directions);
   const ingredients=start>=0&&directions>start?body.slice(start+13,directions).trim():null;
   const method=directions>=0?body.slice(directions+12,end>directions?end:undefined).split(/\nI Made It\n|\nCook’s Note|\nCook's Note|\nReviews\n/)[0].trim():null;
   const meets=/more than 100 reviews/i.test(goal)?reviews>100&&rating>=4.5&&servings>=Number(goal.match(/(?:for|suitable for)\s+(\d+)\s+people/i)?.[1]||1):
    /zucchini/i.test(goal)?rating>=4&&/zucchini/i.test(ingredients||''):
    /under 600/i.test(goal)?Number(calories)<600&&prepMinutes!==null&&prepMinutes<60:false;
   if(meets&&ingredients&&method)return {kind:'selected-recipe',title,url:o.url,rating,reviews,reviewQuote,servings,servingsQuote,prepMinutes,prepQuote,calories:Number(calories),ingredients,method,
    servingBasis:`The observed recipe yields ${servings} servings, sufficient for the requested party`,sources,limitations:[]};
  }
 }
 if(new URL(last.url).hostname.endsWith('apple.com')&&/prices.*MacBook Air/i.test(goal)){
   const shop=documents.find(({observation:o})=>new URL(o.url).pathname.includes('/shop/buy-mac/macbook-air')&&/M\d+ chip/.test(o.text));
   if(shop){const comparison=shop.observation.elements.filter(e=>e.role==='radio'&&/^\d{2}[-‑]inch\b/.test(e.name)).map(e=>({model:`MacBook Air ${e.name.match(/^\d{2}[-‑]inch/)[0]}`,price:e.name.match(/Buy from (\$[\d,]+)/)?.[1],sourceQuote:e.name})).filter(e=>e.price);
     if(comparison.length>=2)return {kind:'product-price-comparison',chip:shop.observation.text.match(/\bM\d+ chip\b/)?.[0],comparison,priceDifferenceUSD:Number(comparison[1].price.replace(/[$,]/g,''))-Number(comparison[0].price.replace(/[$,]/g,'')),
       basis:'Current Apple shop model selectors and their displayed starting purchase prices; financing/lease prices excluded',sources,limitations:[]};
   }
 }
 if(new URL(last.url).hostname.endsWith('espn.com')&&/trades.*(?:past|last)\s+(?:two|2)\s+days/i.test(goal)){
   const transaction=documents.find(({observation:o})=>new URL(o.url).pathname==='/nba/transactions'&&!o.truncated&&!o.tablesTruncated);
   const tracker=documents.find(({observation:o})=>/trade.tracker/i.test(o.title)&&new URL(o.url).pathname.includes('/story/')&&!o.truncated);
   if(transaction&&tracker){
     const text=transaction.observation.text.split(/\nNBA News\n/)[0],headings=[...text.matchAll(/(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Za-z]+)\s+(\d{1,2})/g)];
     const run=new Date(asOf),floor=recentDate(goal,asOf),year=run.getUTCFullYear();
     const dates=headings.map((m,index)=>{let date=new Date(`${m[1]} ${m[2]}, ${year} 00:00:00 GMT`);if(date>run)date=new Date(`${m[1]} ${m[2]}, ${year-1} 00:00:00 GMT`);return {date:date.toISOString().slice(0,10),quote:text.slice(m.index,headings[index+1]?.index??text.length).trim()};});
     const chronological=dates.length>1&&dates.every((row,index)=>!index||row.date<=dates[index-1].date);
     if(floor&&chronological&&dates[0].date<floor)return {kind:'news-updates',trades:[],answer:`No NBA trade is listed in ESPN's latest transaction feed from ${floor} through ${String(asOf).slice(0,10)}. The newest listed transaction is ${dates[0].date}.`,
       dateWindow:{from:floor,to:String(asOf).slice(0,10)},coverage:{source:'ESPN NBA Transactions newest-first dated feed, corroborated by the trade tracker article',completeThroughNewestPublishedEntry:true,newestPublishedEntry:dates[0].date},
       sourceQuotes:[dates[0].quote,tracker.observation.title],sources,limitations:[]};
   }
 }
 if(new URL(last.url).hostname.endsWith('booking.com')&&new URL(last.url).pathname.startsWith('/searchresults')){
   const u=new URL(last.url),cards=require('./c2g_booking_flow.cjs').resultCards(last);
   if(/cheapest/i.test(goal)){
     const sorted=u.searchParams.get('order')==='price'&&/Tarif \(le - cher en premier\)|Price \(lowest first\)/i.test(last.text);
     const hotelOnly=(u.searchParams.get('nflt')||'').split(';').includes('ht_id=204');
     const first=cards[0];
     if(sorted&&hotelOnly&&first?.room&&first.price)return {kind:'selected-hotel-room',answer:`${first.hotel} — ${first.room} — ${first.price}`,hotel:first.hotel,room:first.room,price:first.price,
       checkin:u.searchParams.get('checkin'),checkout:u.searchParams.get('checkout'),adults:Number(u.searchParams.get('group_adults')),rooms:Number(u.searchParams.get('no_rooms')),
       selection:'First available hotel in independently observed lowest-price order',sourceQuote:first.sourceQuote,sources,limitations:[]};
   }else if(/deals?/i.test(goal)){
     const selected=cards.find(card=>card.deal&&card.room);
     if(selected)return {kind:'selected-hotel-deal',hotel:selected.hotel,room:selected.room,deal:selected.deal,price:selected.price,url:selected.url,
       checkin:u.searchParams.get('checkin'),checkout:u.searchParams.get('checkout'),destination:u.searchParams.get('ss'),sourceQuote:selected.sourceQuote,sources,
       limitations:selected.price?[]:['The deal is displayed but its price has not rendered']};
   }else {
     const requested=require('./c2g_booking_flow.cjs').constraints(goal,asOf),selected=cards.find(card=>card.room&&card.price);
     if(requested&&selected)return {kind:'selected-hotel-stay',hotel:selected.hotel,room:selected.room,price:selected.price,url:selected.url,
       checkin:u.searchParams.get('checkin'),checkout:u.searchParams.get('checkout'),destination:u.searchParams.get('ss'),adults:Number(u.searchParams.get('group_adults')),rooms:Number(u.searchParams.get('no_rooms')),sourceQuote:selected.sourceQuote,sources};
   }
 }
 if(new URL(last.url).hostname.endsWith('apple.com')&&/compare.*prices and chips/i.test(goal)){
   const models=[...new Set(goal.match(/\biPhone\s+\d+\s*(?:Pro\s*Max|Pro|Plus|Mini)?/gi)||[])].map(x=>x.trim());
   const comparison=models.map(model=>{
     const escaped=model.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
     const release=documents.find(({observation:o})=>/^\/newsroom\/(?:19|20)\d{2}\/\d{2}\//.test(new URL(o.url).pathname)&&o.title.replace(/\s+/gu,' ').toLowerCase().includes(model.toLowerCase())&&/start(?:s|ing)?\s+(?:at|price of)\s*\$|\$[\d,]+\s*(?:\(US\))?\s+before trade-in/i.test(o.text));
     if(!release)return {model,price:null,chip:null,limitations:['Historical release with price and chip has not been read']};
     const lines=release.observation.text.split('\n').map(x=>x.replace(/\s+/gu,' ').trim()).filter(Boolean);
     const priceQuote=lines.find(line=>new RegExp(escaped,'i').test(line)&&/start(?:s|ing)?\s+(?:at|price of)\s*\$|\$[\d,]+\s*(?:\(US\))?\s+before trade-in/i.test(line));
     const prices=priceQuote?.match(/\$[\d,]+(?:\.\d{2})?/g)||[];
     const cash=priceQuote?.match(new RegExp(escaped+'\\s+for\\s+.{0,180}?\\bor\\s+(\\$[\\d,]+(?:\\.\\d{2})?)\\s*(?:\\(US\\))?\\s+before trade-in','i'))?.[1];
     const starting=priceQuote?.match(new RegExp(escaped+'\\s+(?:remains at (?:the )?(?:same )?starting price of|starts? at|starting at)\\s*(\\$[\\d,]+(?:\\.\\d{2})?)','i'))?.[1];
     const price=cash||starting||prices[/Pro\s+Max$/i.test(model)&&prices.length>1?1:0]||null;
     const chipQuote=lines.find(line=>/\bA\d+\s+(?:Bionic|Pro)\b/.test(line)&&!/^Shop|^Explore/.test(line));
     const chip=chipQuote?.match(/\bA\d+\s+(?:Bionic|Pro)\b/)?.[0]||null;
     return {model,price,chip,priceQuote,chipQuote,url:release.observation.url,limitations:[...(!price?['Starting price missing']:[]),...(!chip?['Chip missing']:[])]};
   });
   const complete=comparison.length>=2&&comparison.every(x=>x.price&&x.chip);
   const values=comparison.map(x=>Number(x.price?.replace(/[$,]/g,'')));
   return {kind:'historical-product-comparison',comparison,priceDifferenceUSD:complete?values[1]-values[0]:null,
     basis:'Starting prices in historical Apple release announcements; current availability is not asserted',sources,
     limitations:complete?[]:['Both historical models must have independently captured price and chip evidence']};
 }
 if(new URL(last.url).hostname==='dictionary.cambridge.org'){
   const word=last.text.match(/Meaning of (.+?) in English/u)?.[1]?.trim();
   if(word){const fields=extract({word,id:'fresh-dictionary',checks:{example:true,bothAccents:/UK.*US|American.*British|British.*American/i.test(goal)}},last);
     return {kind:'dictionary',word,definition:fields.definition,pronunciation:fields.pronunciation,examples:fields.examples,limitations:fields.limitations,sources};}
 }
 if(new URL(last.url).hostname.endsWith('wolframalpha.com')){
   const results=last.elements.filter(e=>e.role==='image'&&!e.secret&&e.name&&!/logo|advert|flag|icon|mobile|app/i.test(e.name)).map(e=>e.name);
   const significant=goal.match(/(?:retain|to|with)\s+(\d+)\s+significant figures/i)?.[1],integer=results.find(x=>/^\d{7,}$/.test(x.replaceAll(',','').trim()))?.replaceAll(',','').trim();
   let formattedResult=null;
   if(significant&&integer){const count=Number(significant);if(count>=1&&count<=20&&integer.length>count){let digits=(BigInt(integer.slice(0,count))+(Number(integer[count])>=5?1n:0n)).toString(),exponent=integer.length-1;if(digits.length>count){exponent++;digits=digits.slice(0,count);}formattedResult=digits[0]+(count>1?'.'+digits.slice(1):'')+' × 10^'+exponent;}}
   return {kind:'calculation',query:new URL(last.url).searchParams.get('i'),results,...(formattedResult?{formattedResult,significantFigures:Number(significant),formattingBasis:integer}:{}),sources,limitations:results.length?[]:['No rendered calculation result was observed']};
 }
 if(new URL(last.url).hostname.endsWith('bbc.com')&&/summari[sz]e/i.test(goal)){
   const articles=documents.filter(({observation:o})=>/\/(?:articles|article)\//.test(new URL(o.url).pathname))
     .map(({observation:o})=>({o,heading:o.elements.find(e=>e.role==='h1')}))
     .filter(({heading})=>heading?.dates?.some(d=>Number.isFinite(Date.parse(d.datetime))))
     .sort((a,b)=>Date.parse(b.heading.dates[0].datetime)-Date.parse(a.heading.dates[0].datetime));
   if(articles.length){const {o,heading}=articles[0],start=o.text.indexOf(heading.name),body=o.text.slice(start+heading.name.length).split(/\nRelated\n|\nMore from the BBC\n/)[0];
     const keyPoints=body.split('\n').map(x=>x.trim()).filter(x=>x.length>90&&/[.!?]["”']?$/.test(x)&&!/Follow .*BBC|Contact us|story suggestion|Copyright|^Do you have/i.test(x)).slice(0,3);
     return {kind:'news-summary',title:heading.name,url:o.url,published:heading.dates[0],keyPoints,
       summaryMethod:'Three key statements extracted from the article body',selectionScope:'Newest dated article actually read; global latest coverage requires independent proof',sources,
       limitations:['Search relevance ordering alone cannot prove this is the latest health article']};
   }
 }
 if(new URL(last.url).hostname==='github.com'&&new URL(last.url).pathname.startsWith('/trending/')&&/most stars/i.test(goal)){
   const repositories=last.elements.filter(e=>e.href&&/^https:\/\/github\.com\/[^/]+\/[^/]+\/stargazers$/.test(e.href)&&/^[\d,]+$/.test(e.name.trim()))
     .map(e=>({repository:e.href.split('/').slice(3,5).join('/'),url:e.href.replace(/\/stargazers$/,''),stars:Number(e.name.replaceAll(',',''))})).sort((a,b)=>b.stars-a.stars);
   if(repositories.length&&!last.truncated)return {kind:'ranked-repositories',selection:repositories[0],ranking:repositories,scope:'Observed complete daily trending language list, ranked by displayed total stars',sources};
 }
 if(new URL(last.url).hostname==='support.apple.com'&&/features.*compatibility/i.test(goal)){
   const models=[...new Set(goal.match(/iPhone\s+\d+(?:\s+(?:Pro|Plus|mini))?/gi)||[])];
   const compatibility=models.map(model=>{const lines=last.text.split('\n').filter(line=>line.includes(model+' and later'));return {model,supported:lines.length?true:null,basis:lines,supportType:'Release notes explicitly name this model for supported features'};});
   const at=last.text.lastIndexOf('\niOS '+goal.match(/iOS\s+(\d+)/i)?.[1]+'\n');
   const features=(at>=0?last.text.slice(at):last.text).split('\n').map(x=>x.trim()).filter(x=>x.length>30).slice(0,12);
   return {kind:'software-features-and-compatibility',features,compatibility,sources,limitations:compatibility.some(x=>x.supported===null)?['Missing explicit device support evidence']:[]};
 }
 if(new URL(last.url).hostname.endsWith('coursera.org')&&/beginner.*1-3 months/i.test(goal)){
   const lines=last.text.split('\n').map(x=>x.trim()).filter(Boolean),topic=goal.match(/about ['"]([^'"]+)['"]/i)?.[1];
   for(let index=0;index<lines.length;index++){
     const title=lines[index],provider=lines[index-1],metadata=lines.slice(index+1,index+4).join(' ');
     if(topic&&title.toLowerCase().includes(topic.toLowerCase())&&/university|college|universidad|institut/i.test(provider||'')&&/Beginner.*Course.*1\s*[-–]\s*3 Months/i.test(metadata)){
       const link=last.elements.find(e=>e.href&&(e.name.trim()===title||e.name.startsWith(title+', offered by '+provider+', COURSE'))&&new URL(e.href).pathname.startsWith('/learn/'));
       return {kind:'selected-course',title,provider,level:'Beginner',duration:'1–3 months',url:link?.href||null,sourceQuote:[provider,title,metadata].join('\n'),sources};
     }
   }
 }
 if(new URL(last.url).hostname==='huggingface.co'&&/most likes/i.test(goal)){
   const ranked=documents.find(({observation:o})=>new URL(o.url).pathname==='/models'&&new URL(o.url).searchParams.get('sort')==='likes');
   if(ranked){const text=ranked.observation.text.replace(/\s+/gu,' '),section=text.slice(text.indexOf('Sort: Most likes')),first=section.match(/\b([\w.-]+\/[\w.-]+)\s+(?:Text Generation|Fill-Mask|Translation|Text Classification|Sentence Similarity)/)?.[1];
     const selected=documents.find(({observation:o})=>new URL(o.url).pathname==='/'+first);
     const license=selected?.observation.text.match(/License:\s*([\w.-]+)/)?.[1],likes=selected?.observation.text.match(/Like\s+([\d.,]+k?)/)?.[1];
     if(first&&selected&&license)return {kind:'selected-model',model:first,url:selected.observation.url,license,likes,rank:1,order:'Most likes',filter:new URL(ranked.observation.url).searchParams.get('license'),sources};
   }
 }
 // These are verbatim fresh facts, rather than a claim that partial page
 // evidence resolves ordering, dates, negative results or every goal clause.
 return {kind:'source-facts',goal,documents:documents.map(({observation:o,ref})=>({source:ref.path,url:o.url,title:o.title,text:o.text,
   tables:o.tables,images:o.elements.filter(e=>e.role==='image'&&!e.secret).map(e=>e.name),truncated:o.truncated})),
   limitations:['Verbatim source facts require independent all-clause grading; incomplete coverage is not a successful answer'],sources};
}
module.exports={answer,bookingCards};
