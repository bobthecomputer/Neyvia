'use strict';
// Source-shaped goal guards: facts are extracted from this run, never saved answers.
const norm = value => String(value ?? '').replace(/\s+/gu, ' ').trim();
const hostIs = (o, host) => { const h = new URL(o.url).hostname; return h === host || h.endsWith('.' + host); };
const espn = o => /(?:^|\.)espn\.(?:com|co\.uk)$/.test(new URL(o.url).hostname);
function extract(goal, documents, asOf) {
  const rows = documents.map(({observation, ref}) => ({o: observation, ref}));
  const sources = rows.map(({o,ref}) => ({url:o.url,path:ref.path,sha256:ref.sha256,title:o.title}));
  const runDate = new Date(asOf);
  if (/latest (?:preprints|research papers)/i.test(goal)) {
    const topic = goal.match(/about ['"]([^'"]+)['"]/i)?.[1] || goal.match(/papers on (.+?) submitted/i)?.[1];
    for (const {o} of rows) {
      const u = new URL(o.url); if (!hostIs(o,'arxiv.org') || !u.pathname.startsWith('/search')) continue;
      const query = u.searchParams.get('query') || u.searchParams.get('terms-0-term');
      const sorted = o.elements.some(e=>e.name === 'Sort results by' && e.options?.some(v=>v.selected && v.label === 'Announcement date (newest first)'));
      if (norm(query).replace(/^"|"$/g,'').toLowerCase() !== norm(topic).toLowerCase() || u.searchParams.get('order') !== '-announced_date_first') continue;
      const days = goal.match(/last (two|\d+) days/i); let window;
      if (days) { const floor = new Date(runDate); floor.setUTCDate(floor.getUTCDate() - (days[1] === 'two' ? 2 : Number(days[1])));
        window = {from:floor.toISOString().slice(0,10),to:runDate.toISOString().slice(0,10)};
        if (u.searchParams.get('date-from_date') !== window.from || u.searchParams.get('date-to_date') !== window.to || u.searchParams.get('date-date_type') !== 'submitted_date_first') continue;
        if (/Sorry, your query returned no results/.test(o.text) && o.text.includes('date_range: from ' + window.from + ' to ' + window.to))
          return {kind:'dated-preprint-search',topic,window,papers:[],answer:'No results for the explicitly submitted-date-filtered query ' + query + ' from ' + window.from + ' through ' + window.to + '.',query,url:o.url,scope:'Exact filtered query only, not absence of all topic research',sources};
      }
      if (!sorted || !/Showing 1[–-]/.test(o.text)) continue;
      const links = o.elements.filter(e => e.href && /^https:\/\/arxiv\.org\/abs\//.test(e.href));
      const papers = links.slice(0,5).map(e => { const start=o.text.indexOf(e.name), end=o.text.indexOf('arXiv:',start+e.name.length), block=o.text.slice(start,end < 0 ? undefined : end), lines=block.split('\n').map(norm).filter(Boolean), authors=lines.findIndex(s=>s.startsWith('Authors:'));
        return {id:e.name,url:e.href,title:authors > 0 ? lines[authors-1] : null,submitted:block.match(/Submitted ([^;]+);/)?.[1],sourceQuote:block.trim()}; });
      if (papers.length && papers.every(p=>p.title && p.submitted)) return {kind:'dated-preprint-search',topic,query,window:window||null,papers,url:o.url,order:'Announcement date (newest first)',scope:'First results from the observed newest-first query',sources};
    }
  }
  const subject = goal.match(/['"]([a-z]+\.[A-Z]+)['"]/i)?.[1];
  if (subject && /recent papers.*select one.*abstract/i.test(goal)) {
    for (const {o:paper} of [...rows].reverse()) {
      if (!hostIs(paper,'arxiv.org') || !/^\/abs\//.test(new URL(paper.url).pathname)) continue;
      const id = new URL(paper.url).pathname.slice(5).replace(/v\d+$/, '');
      const title = paper.text.match(/Title:\s*([^\n]+)/)?.[1]?.trim();
      const abstract = paper.text.match(/Abstract:\s*([\s\S]*?)(?=\s+(?:Comments:|Subjects:|Cite as:)|\n\s*Submission history|$)/)?.[1]?.trim();
      if (!title || !abstract || abstract.length < 100 || paper.truncated || !paper.text.includes('(' + subject + ')')) continue;
      for (const {o:list} of rows) {
        if (!hostIs(list,'arxiv.org') || new URL(list.url).pathname !== '/list/' + subject + '/recent') continue;
        const sections = [...list.text.matchAll(/(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+20\d{2})\s*\(showing[^\n]*\)/g)];
        if (!sections.length) continue;
        const first = sections[0], date = Date.parse(first[1] + ' 00:00:00 GMT');
        if (!Number.isFinite(date) || date > runDate || runDate - date > 7 * 86400000) continue;
        const batch = list.text.slice(first.index, sections[1]?.index ?? list.text.length);
        const start = batch.indexOf('arXiv:' + id);
        if (start < 0 || !list.elements.some(e => e.href === paper.url)) continue;
        const quote = batch.slice(start).split(/\n\s*\[\d+\]/)[0].trim();
        if (!norm(quote).includes(norm(title))) continue;
        return {kind:'recent-paper-abstract',title,url:paper.url,id,subject,abstract,
          listUrl:list.url,listDate:first[1],listHeading:first[0],membershipQuote:quote,
          selection:'One paper in the most recent dated batch, as requested',sources};
      }
    }
  }
  if (/BBC News.*recent developments in renewable energy technologies in the UK/i.test(goal)) {
    for (const {o} of rows) {
      if (!hostIs(o,'bbc.com') || !new URL(o.url).pathname.startsWith('/news/articles/')) continue;
      const heading = o.elements.find(e => e.role === 'h1');
      const dates = heading?.dates?.filter(d => Number.isFinite(Date.parse(d.datetime))) || [];
      const date = dates.map(d => Date.parse(d.datetime)).find(d => d <= runDate && runDate - d <= 60 * 86400000);
      if (!Number.isFinite(date)) continue;
      const body = o.text.slice(o.text.indexOf(heading.name) + heading.name.length).split(/\nRelated\n|\nMore from the BBC\n/)[0];
      const lines = body.split('\n').map(norm).filter(Boolean);
      const technology = lines.find(s => /renewable\s+(?:gas|energy|electricity)|wind (?:turbine|power)|solar (?:panel|power)/i.test(s) && s.length > 70);
      const uk = lines.find(s => /\b(?:UK|United Kingdom|England|Scotland|Wales|Northern Ireland)\b/.test(s));
      const development = lines.find(s => /\b(?:approved|permission|develop(?:ment|er)|build|launch|new plant)\b/i.test(s) && s.length > 70);
      if (technology && uk && development) return {kind:'renewable-news-report',title:heading.name,url:o.url,
        published:new Date(date).toISOString(),technologyQuote:technology,ukQuote:uk,developmentQuote:development,
        facts:[technology,uk,development],scope:'Recent BBC report; no global latest claim',sources};
    }
  }
  if (/current standings.*NBA (Eastern|Western) Conference/i.test(goal)) {
    const conference = goal.match(/NBA (Eastern|Western) Conference/i)[1];
    for (const {o} of rows) {
      if (!espn(o) || new URL(o.url).pathname !== '/nba/standings' || o.truncated || o.tablesTruncated) continue;
      const season = o.elements.find(e => e.name === 'Standings Season')?.options?.find(v => v.selected)?.label;
      const seasonType = o.elements.find(e => e.name === 'Standings Season Type')?.options?.find(v => v.selected)?.label;
      const expectedYear = runDate.getUTCFullYear() - (runDate.getUTCMonth() < 6 ? 1 : 0);
      if (season !== expectedYear + '-' + String(expectedYear + 1).slice(-2) || !seasonType) continue;
      const offset = conference === 'Eastern' ? 0 : 2, names = o.tables[offset], stats = o.tables[offset+1];
      if (!names || !stats || names.length !== 16 || stats.length !== names.length || stats[0][0] !== 'W' || stats[0][1] !== 'L') continue;
      const standings = names.slice(1).map((row,index) => ({team:norm(row[0]),...Object.fromEntries(stats[0].map((key,column) => [key,stats[index+1][column]]))}));
      if (new Set(standings.map(r=>r.team)).size !== 15 || !standings.every(r=>/^\d+$/.test(r.W) && /^\d+$/.test(r.L))) continue;
      return {kind:'conference-standings',conference,season,seasonType,standings,url:o.url,
        scope:'Current selected ESPN season, including its explicitly labeled season type',sources};
    }
  }
  if (/three new and popular open-source NLP models for language translation.*past month/i.test(goal)) {
    const floor = new Date(runDate); floor.setUTCMonth(floor.getUTCMonth()-1);
    const models=[];
    for (const {o:history} of rows) {
      const u=new URL(history.url); if (!hostIs(history,'huggingface.co') || !/\/commits\/[^/]+$/.test(u.pathname) || history.truncated) continue;
      const initial=history.elements.find(e=>e.role==='h3' && /^initial commit\b/i.test(e.name));
      const stamp=initial?.dates?.[0]?.datetime, date=Date.parse(stamp?.endsWith('Z') ? stamp : stamp + 'Z');
      if (!Number.isFinite(date) || date < floor || date > runDate) continue;
      const model=u.pathname.replace(/\/commits\/[^/]+$/, '').slice(1);
      const card=rows.find(({o})=>hostIs(o,'huggingface.co') && new URL(o.url).pathname==='/'+model)?.o;
      const license=card?.text.match(/License:\s*(apache-2\.0|mit|bsd(?:-[\w.-]+)?)/i)?.[1];
      const downloads=card?.text.match(/Downloads last month\s*([\d,.]+[kM]?)/)?.[1];
      const likes=card?.text.match(/Like\s+([\d,.]+k?)/)?.[1];
      if (!card || !license || !downloads || !likes || !/\bTranslation\b/.test(card.text) || models.some(m=>m.model===model)) continue;
      models.push({model,url:card.url,license,downloadsLastMonth:downloads,likes,initialCommit:stamp,initialCommitQuote:initial.name,releaseBasis:'Fresh repository initial commit within the past calendar month',task:'Translation'});
    }
    if (models.length>=3) return {kind:'recent-translation-models',models:models.slice(0,3),window:{from:floor.toISOString(),to:runDate.toISOString()},popularityBasis:'Displayed downloads and likes, not a global popularity ranking',sources};
  }
  if (/decision trees.*Python.*updated.*(?:last|past).*days|Python.*decision trees.*updated.*(?:last|past).*days/i.test(goal)) {
    const days=goal.match(/(?:last|past)\s+(two|\d+)\s+days/i)?.[1];const floor=new Date(runDate);floor.setUTCDate(floor.getUTCDate()-(days==='two'?2:Number(days)));
    for (const {o:search} of rows) {
      const u=new URL(search.url),query=u.searchParams.get('q');
      if (!hostIs(search,'github.com') || u.pathname!=='/search' || !query || !/decision trees language:Python/i.test(query) || !query.includes('pushed:>='+floor.toISOString().slice(0,10))) continue;
      for (const {o:repo} of rows) {
        if (!hostIs(repo,'github.com') || !/^\/[^/]+\/[^/]+$/.test(new URL(repo.url).pathname) || !search.elements.some(e=>e.href===repo.url)) continue;
        const name=new URL(repo.url).pathname.slice(1), start=search.text.indexOf(name), tail=search.text.slice(start), update=tail.match(/Updated (\d+ (?:days?|hours?|minutes?) ago|yesterday)/)?.[0];
        if (start<0 || !update || !/Languages\s+Python/.test(repo.text) || !/MIT license|License: MIT/.test(repo.text)) continue;
        return {kind:'recent-repository',repository:name,url:repo.url,language:'Python',license:'MIT',topic:'decision trees',updated:update,query,queryUrl:search.url,dateFloor:floor.toISOString().slice(0,10),sources};
      }
    }
  }
  return null;
}
function verify(goal, answer, documents, asOf) {
  const rows = documents.map(observation => ({observation,ref:{}}));
  const fresh = extract(goal,rows,asOf);
  if (!fresh || answer.kind !== fresh.kind) return null;
  const keys = Object.keys(fresh).filter(key => key !== 'sources');
  return {verified:keys.every(key => JSON.stringify(answer[key]) === JSON.stringify(fresh[key])),
    checks:[{requirement:'Requested source-shaped goal and every returned fact match fresh documents',passed:keys.every(key => JSON.stringify(answer[key]) === JSON.stringify(fresh[key])),evidence:{kind:fresh.kind,url:fresh.url}}]};
}
function calculationReady(observation) {
  const query = new URL(observation.url).searchParams.get('i');
  if (!query) return false;
  const images = observation.elements.filter(e => ['image','img'].includes(e.role) && !e.secret && norm(e.name) !== norm(query)).map(e=>norm(e.name));
  return images.some(s => /^[-+]?\d[\d,]*(?:\.\d+)?$/.test(s) || /[<>≤≥].*[xy]|[xy].*[<>≤≥]/.test(s));
}
module.exports = {extract,verify,calculationReady};
