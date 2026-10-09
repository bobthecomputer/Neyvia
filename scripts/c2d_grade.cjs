#!/usr/bin/env node
'use strict';
// Independent human-reviewed verdicts, pinned to exact executor answers.
// Evidence matchers locate proof AFTER semantic review; they are not a generic grader.
const fs = require('node:fs'), crypto = require('node:crypto');
const runPath = 'scripts/evidence/C2d-webvoyager-final.json';
const taskPath = 'scripts/evidence/C2-webvoyager-tasks.json';
const referencePath = 'scripts/evidence/C2-webvoyager-references.json';
const outPath = 'scripts/evidence/C2d-webvoyager-grades.json';
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
const fileSha = p => digest(fs.readFileSync(p));
const norm = s => String(s || '').replace(/\s+/gu, ' ').trim();
const E = (suffix, text, field = 'text') => ({ suffix, text, field });
const C = (requirement, met, evidence, note = null) => ({ requirement, met, evidence, note });
const R = (outcome, reason, clauses, primary = null, secondary = [], referenceComparison = 'Possible upstream answers are examples; all current task constraints require captured live proof.') => ({ outcome, reason, clauses, primary, secondary, referenceComparison });
const priorReviews = /* prior-review-map */ {
 "GitHub--0": [
  {
   "reviewedAt": "2026-10-04T21:49:42.823Z",
   "answerSha256": "9c8ec20b6297383b2ffb7a022f6c8ef0239a294852336382fb1e052e02826380",
   "outcome": "failed",
   "reason": "Actual observed homepage Search clicks fail and reobservations show no query field. Topics recovery lacks an observed climate route; no matching repository set or star maximum established.",
   "primary": "engine",
   "secondary": [
    "search_box",
    "planning",
    "filters"
   ],
   "missingClauses": [
    "Climate-change-data-visualization open source GitHub project",
    "Most stars across matching projects"
   ],
   "finishedAt": "2026-10-04T21:15:20.871Z",
   "elapsedMs": 2131535,
   "evidence": []
  }
 ],
 "GitHub--1": [
  {
   "reviewedAt": "2026-10-04T21:49:42.823Z",
   "answerSha256": "3a438b2a130ad88da323063bed73064bbcd5a929788af1d37267e976e2695d2f",
   "outcome": "failed",
   "reason": "Observed search control fails in both prior headless and fresh native owner recovery; no decision-tree Python query or date-filtered repository result is captured.",
   "primary": "engine",
   "secondary": [
    "search_box",
    "filters",
    "planning"
   ],
   "missingClauses": [
    "Open source Python machine learning decision-tree repository",
    "Updated October2-4 2026"
   ],
   "finishedAt": "2026-10-04T21:16:08.428Z",
   "elapsedMs": 2092512,
   "evidence": []
  }
 ],
 "Wolfram Alpha--1": [
  {
   "reviewedAt": "2026-10-04T21:49:42.823Z",
   "answerSha256": "6c0380615973713e18dcb98e92050fbca54580bb546f7b82f989de78756a56b6",
   "outcome": "failed",
   "reason": "Captured filled-pentagram page contains the requested region-defining x,y inequalities, but answer supplies only size-parameter constraint a>0. Parameter positivity does not constrain a point to the inner region; no region-defining inequality is actually returned.",
   "primary": "extraction",
   "secondary": [
    "planning",
    "grader_disagreement"
   ],
   "missingClauses": [
    "Give a constraint from the set of region-defining inequalities"
   ],
   "finishedAt": "2026-10-04T21:46:38.294Z",
   "elapsedMs": 141768,
   "evidence": [
    {
     "path": "scripts/evidence/C2d-final-observations/Wolfram_Alpha--1-7.json",
     "sha256": "f96092ade439f79d7eec6808e2fc910f9e6fe797829b32be980daed23568de29",
     "url": "https://www.wolframalpha.com/input?i=pentagram&assumption=%22ClashPrefs%22+-%3E+%7B%22Lamina%22%2C+%22FilledPentagram%22%7D",
     "capturedAt": "2026-10-04T21:46:17.050Z",
     "field": "text",
     "quote": "is a lamina | Use as a geometric object or a word instead Input interpretation: D",
     "verifiedSha256": true,
     "whitespaceNormalized": true
    },
    {
     "path": "scripts/evidence/C2d-final-observations/Wolfram_Alpha--1-7.json",
     "sha256": "f96092ade439f79d7eec6808e2fc910f9e6fe797829b32be980daed23568de29",
     "url": "https://www.wolframalpha.com/input?i=pentagram&assumption=%22ClashPrefs%22+-%3E+%7B%22Lamina%22%2C+%22FilledPentagram%22%7D",
     "capturedAt": "2026-10-04T21:46:17.050Z",
     "field": "text",
     "quote": "Defining inequalities: Definitions Alternate names: Lamina properties: Approximate form More",
     "verifiedSha256": true,
     "whitespaceNormalized": true
    },
    {
     "path": "scripts/evidence/C2d-final-observations/Wolfram_Alpha--1-7.json",
     "sha256": "f96092ade439f79d7eec6808e2fc910f9e6fe797829b32be980daed23568de29",
     "url": "https://www.wolframalpha.com/input?i=pentagram&assumption=%22ClashPrefs%22+-%3E+%7B%22Lamina%22%2C+%22FilledPentagram%22%7D",
     "capturedAt": "2026-10-04T21:46:17.050Z",
     "field": "elements",
     "quote": "\"name\":\"a>0\",\"nameTruncated\":false,\"role\":\"image\",\"secret\":false,\"value\":null,\"val",
     "verifiedSha256": true,
     "whitespaceNormalized": false
    }
   ]
  }
 ]
};
const reviewedAnswerSha = /* reviewed-sha-map */ {
 "Allrecipes--0": "d9214d594fbf82683ab654c23eb1f73cad80675036e034e1dd2f11ca6098ea0a",
 "Allrecipes--1": "c229cf02d145c98c6cbecffe6a2347e87381557d6d1f8723eb4484c90088dec4",
 "Allrecipes--2": "e87c0b29b11703b2cdd0a8ffc1a4a1633deda84cd987dc506a6967ab8c36e583",
 "Apple--0": "e5cca7a816c6b718e4b7b7d231e49ed0e7ade39a8a894fb55efb2c63cc810c09",
 "ArXiv--0": "cd34adf4ab70a78583ab762e129dd1571615083201baedd1c5b13d4a607cc99b",
 "ArXiv--1": "96acbcc94765dae87a92ce121949ef65ae281199849d17ff03435df1e0086525",
 "ArXiv--2": "e52ea6dde26e73de4d53d5794958ec4a61ff27b9c915307bd877af6a9b1bf9c9",
 "BBC News--0": "274b00da399145c83f56f83f2f96a1008b6585b881814f189877e4e2036ff391",
 "BBC News--1": "20877949b3aa899602204f8a6feb02f6f3b9706b580c22bc11d0a01156b2797c",
 "BBC News--2": "8c05057b5eac7122d8b4cd9308e5c3001f384b8e4060d9fbb46f12e93298a99c",
 "Cambridge Dictionary--0": "ab4c835547e3c093ea858274f518be7c72a99c3762cf08b8eea766c1dc5c4e2c",
 "Cambridge Dictionary--1": "481b949c99ac081bc489d0806c04cf2cd1477e0192ecd08a10e0ccd3e17999c4",
 "Cambridge Dictionary--2": "88425bbee973ca2711d3f1eca34a1f4ce7ce6189b3895745daf3b5c00ecd247a",
 "Coursera--0": "5d0af43a04301bf25bd979b2479fa93143ead690522e4a4869ab8d56fe7119e8",
 "Coursera--1": "f8a5902b1793994055817f906de6796a3f4fa3c4c863ec39977ef51ac9e25b5d",
 "Coursera--2": "6847728b4c5f7df2871c9421869a9b4d323257ce92f1d1e4950f7b530a352d58",
 "Huggingface--3": "7adaa64a39a8ff4cef7b45687e7210ad93163fc605c6ef72e4acceb78e6d2e98",
 "Apple--1": "98d49c911f1a4440d3984b089c391e0a52e8f86d6c41c3df0114b1e7f7472e4d",
 "Huggingface--0": "04be841114557ea79abbfb35305e30dc4978f8e400194d6cc76ce87f62e8989a",
 "Google Search--0": "08e9424fa8409a4b2bac7d1119f5ff2f45f270cd56430abf80803561548bc01e",
 "Google Search--1": "b3c136e992923287526800c2ac1acf6e7404183ecc7430a9e9e594dfd927a362",
 "Google Search--2": "56651fac405e921bb827c493f633eb6e2a7d24699e06f30e6aa4b1db64441682",
 "Huggingface--2": "29f2d3356b7ec4ec5a9b30df66b61e4a688671ae4cf99c2944ccc279632552d4",
 "Apple--2": "57a9400d7169a50c710b08056cccb32042eaa480645c036434fc16093475aa64",
 "GitHub--0": "7a621da3f1b18e326d3f6ec649099c0055c573af4382b9ebf09cffcfbea5a9d0",
 "ESPN--0": "4e897979ee19c789876a85bfe7aab21b6de5f6cc5fb85ed9729af18128293b09",
 "ESPN--1": "ceed2a2ea0cebf185bf2c67398f20049136d42bb55d9e0669a9707a048801dd3",
 "GitHub--1": "d880479e9dc49d08ea6099e2c51e0cfbfd71ab53b11b49067abc71a79ef726ed",
 "ESPN--2": "306946eb3ef925a90378e3458a3c707dfac445d5ed4daee72de7ab9d595c48c2",
 "GitHub--2": "f2778b9147864076508be7d13a99d0108df5ce5bd0db247d6d601a6dfb1e4dab",
 "Booking--0": "5ce5c8132ab0ece3d26637828b7b72a145eea5e6d2d28a355135623ccbbefc6e",
 "Booking--2": "2d957b3359e3e1d40303325b93a519d3dd3e496b8c866ba64ad8b512d232c699",
 "Wolfram Alpha--0": "509a215d35f91e585fda7df8ec4633c2b3a9ab9f6136bfe8510eaaeaee3c1b95",
 "Wolfram Alpha--1": "faa1088e9d6d946968e74fe31a5bbc3310acc630693c6c2eca4516f9670dba04",
 "Wolfram Alpha--2": "a2968feb37e5310577cb77c53bd10ee7bd1086aaea5f71001e3fae39788b4869",
 "Booking--1": "9ce3840e1600cc218af5f8c3d7396802bb80de6ebe6faaac854bf5015f69dcb9"
};
const reviews = {
 'Booking--1': R('passed','Live Hotel-only and lowest-price ordering establish first available Jakarta hotel room at€17 for January1-4,2027,2adults. Final answer contains only hotel,room and price as requested; longer original answer and complete original timer remain retained.',[C('Hotel room in Jakarta',true,[E('-37.json','Trier par : Tarif (le - cher en premier) Hôtel'),E('-37.json','Voici les résultats pour Jakarta Marson Interkota Residence Mitra RedDoorz'),E('-37.json','Chambre Double Standard 1 lit double')]),C('Three nights starting January1 for2adults',true,[E('-37.json','checkin=2027-01-01&checkout=2027-01-04&group_adults=2&no_rooms=1','url'),E('-37.json','3 nuits, 2 adultes € 17 Tarif : € 17 Taxes et frais compris')]),C('Cheapest available matching hotel room and price',true,[E('-37.json','order=price','url'),E('-37.json','Tarif (le - cher en premier)'),E('-37.json','€ 17 Tarif : € 17'),E('-37.json','€ 18 Tarif : € 18')]),C('Answer only hotel room and price',true,[E('-37.json','Marson Interkota Residence Mitra RedDoorz'),E('-37.json','Chambre Double Standard'),E('-37.json','€ 17 Tarif : € 17')], 'Pinned reviewed final answer is a single hotel/room/price sentence.')]),
 'Booking--0': R('passed','Actual Mexico result card supplies a discounted hotel for December25-26,2026, supported by selected calendar, result header and URL. Answer date mojibake is a formatting defect but later explicit checkin/checkout dates are correct; availability wording says more than5 whereas the French card says only5 remain. These extras do not alter the required hotel/deal/date finding.',[C('Hotel in Mexico',true,[E('-30.json','Hotel Estrella de Oriente'),E('-30.json','Iztacalco, Mexico'),E('-30.json','Accueil Mexique District Fédéral de Mexico Mexico')]),C('December25-26 next future stay',true,[E('-27.json','ven. 25 déc. — sam. 26 déc.'),E('-27.json','décembre 2026'),E('-30.json','checkin=2026-12-25&checkout=2026-12-26','url')]),C('Deal for specified dates',true,[E('-30.json','Tarif initial : € 52. Tarif actuel : € 31. Taxes et frais compris')])]),
 'Booking--2': R('passed','Actual Ohio property and live room recommendation prove December20-23,2026 for3adults and2rooms. €503 total, cancellation and breakfast match the captured property recommendation.',[C('Hotel in Ohio',true,[E('-23.json',"Comfort Inn River's Edge 132 North Main Street, Huron, OH 44839")]),C('December20-23 next future dates',true,[E('-23.json','dim. 20 déc. — mer. 23 déc.'),E('-23.json','checkin=2026-12-20&checkout=2026-12-23','url')]),C('Three adults and two available rooms',true,[E('-23.json','3 adultes · 0 enfant · 2 chambres'),E('-23.json','Recommandé pour 3 adultes 2 × Queen Room with Two Queen Beds - Accessible/Non-Smoking'),E('-23.json','Il nous reste 3 options'),E('-23.json','3 nuits, 3 adultes € 503 Tarif € 503 Taxes et frais compris')])]),
 'Wolfram Alpha--0': R('passed','Captured Wolfram image accessible names supply derivative2x and evaluated result11.2. Answer matches static expected value.',[C('Derivative evaluated at x=5.6',true,[E('-6.json','derivative of x^2 at x=5.6'),E('-6.json','"name":"11.2"','elements'),E('-6.json','"name":"d/dx(x^2) = 2 x"','elements')])],null,[],'Static golden11.2 matches exactly; computation is supported by page accessible image names rather than body text.'),
 'Wolfram Alpha--1': R('passed','Final answer reproduces the complete actual captured region image39 coordinate inequalities, including every AND/OR group, plus size-parameter constraint. Earlier positivity-only answer failed independently; original answer/timer and that verdict remain retained. This is a post-run extraction correction from existing live evidence, not a new live interaction.',[C('Use filled pentagram inner-region definition',true,[E('-7.json','is a lamina'),E('-7.json','Defining inequalities:')]),C('Give region-defining coordinate constraints',true,[E('-7.json','"name":"2 a + 3 sqrt(5) x + 5 x>=sqrt(2 (5 + sqrt(5))) y and 2 a + sqrt(50 + 22 sqrt(5)) y>=(5 + sqrt(5)) x','elements'),E('-7.json','"name":"a>0"','elements')], 'Full answer compared exactly to the actual captured image39 name; all logical groups retained.')],null,[],'Current answer contains the actual captured inequality set and satisfies the possible example semantically. It was derived from live observation, not grader reference content.'),
 'Wolfram Alpha--2': R('passed','Captured integer and scientific-notation image names match3^71; rounding to five significant figures is correct.',[C('Calculate3^71',true,[E('-3.json','3^71'),E('-3.json','"name":"7509466514979724803946715958257547"','elements')]),C('Scientific notation with five significant figures',true,[E('-3.json','"name":"7.509466514979724803946715958257547 × 10^33"','elements')], 'Sixth significant digit6 rounds7.5094 to7.5095 ×10^33.')],null,[],'Static golden7.5095*10^33 matches semantically. Independent BigInt3**71 confirms the full captured integer.'),
 'GitHub--2': R('passed','Python/Today Trending page contains all13 displayed repository cards through the footer; totals and daily gains are compared explicitly. Global truncated flag reflects capped controls; retained text includes the complete displayed list and footer.',[C('Trending Python repositories',true,[E('-8.json','/trending/python?since=daily','url'),E('-8.json','Language: Python'),E('-8.json','Date range: Today')]),C('Identify greatest star totals across complete displayed list',true,[E('-8.json','Panniantong / Agent-Reach'),E('-8.json','Python 90,779 7,979 Built by 979 stars today'),E('-8.json','Python 63,134 8,053 Built by 361 stars today'),E('-8.json','Python 45,362 4,903 Built by 152 stars today'),E('-8.json','experientiallabs / experiential'),E('-8.json','Footer navigation')])],null,[],'Historical possible winner OpenVoice is stale. Current captured full displayed Python trending set establishes Agent-Reach greatest total stars and daily gain; ranking is limited to that set, not all GitHub repositories.'),
 'ESPN--2': R('failed','Captured complete preseason schedule starts October5 and supports no preseason game in October2-4; no score/highlight is invented. Regular Season select changes only the control while table remains preseason, so the broader absence claim lacks complete season/filter proof. Retain the limited negative finding, not a full-task pass.',[C('Qualifying Milwaukee Bucks game in October2-4 2026',false,[E('-11.json','Milwaukee Bucks Schedule 2026-27'),E('-11.json','Mon, Oct 5')], 'First captured preseason match is outside window.'),C('Score and main highlight, or complete verified no-game outcome',false,[], 'No score/highlight exists in captured preseason set; regular-season content did not follow the selected filter, so full task-scope absence is unproved.')], 'filters',['engine','grader_disagreement']),
 'ESPN--1': R('passed','Newest complete transaction ledger and current buzz article establish no completed trade in October2-4. Waivers and re-signing are correctly distinguished; newest actual trade September27 is outside the window.',[C('Inspect latest ESPN NBA trade-related news',true,[E('-4.json','Oct. 2 Hawkins, Grizzlies mutually agree to part ways'),E('-4.json','agreed to part ways via waivers'),E('-4.json','three weeks after arriving as part of a four-player trade')]),C('Verify October2-4 window and trade outcome',true,[E('-3.json','Friday, October 2 TRANSACTION Re-signed C Jalen Duren to a contract.'),E('-3.json','Sunday, September 27 TRANSACTION Acquired G Rob Dillingham from Chicago Bulls for G Buddy Hield.'),E('-3.json','Acquired G Buddy Hield from Charlotte in exchange for G Rob Dillingham.')])],null,[],'Possible upstream reference explicitly permits no article. Current complete ledger plus newest dated news supports a negative answer; older trade tracker is not used as freshness proof.'),
 'GitHub--1': R('failed','Search control fails in prior headless/native attempts. Current pointer/priority retry still rejects fresh semantic batch stale_projection before dispatch as animated homepage revision changes. No decision-tree Python query or date-filtered repository result is captured.',[C('Open source Python machine learning decision-tree repository',false,[E('-9.json','https://github.com/?locale=fr-fr','url')]),C('Updated October2-4 2026',false,[])], 'engine',['search_box','filters','planning','timing']),
 'ESPN--0': R('passed','Complete aligned Eastern Conference name/statistics tables contain all15 teams. Answer reports the current preseason/2026-27 context and correctly distinguishes display order from substantive tie ranking.',[C('Current NBA Eastern Conference standings',true,[E('-3.json','NBA Preseason Standings 2026-27'),E('-3.json','Eastern Conference'),E('-3.json','MIAMiami Heat'),E('-3.json','TORToronto Raptors')]),C('Complete team standings with accurate records',true,[E('-3.json','["1","0","1.000","-"','tables'),E('-3.json','["0","0",".000","0.5"','tables'),E('-3.json','["0","1",".000","1"','tables')])]),
 'GitHub--0': R('failed','Earlier Search clicks failed; current pointer/priority retry rejects three fresh native batches stale_projection before dispatch. Normal Obscura retry clicks observed Search once, effect_unconfirmed with unchanged revision and no query control. No climate repository search, star sorting or maximum established.',[C('Climate-change-data-visualization open source GitHub project',false,[E('-20.json','https://github.com/?locale=fr-fr','url')]),C('Most stars across matching projects',false,[])], 'engine',['search_box','planning','filters','timing']),
 'Apple--2': R('failed','Repeated real historical-product searches produce a count without article rows, then current-product global results. Input/submit actions time out or fail expectations; no captured historical price/chip values for both products. No supported comparison was supplied.',[C('iPhone 14 Pro price and chip from Apple',false,[]),C('iPhone 15 Pro price and chip from Apple',false,[]),C('Compare both models prices and chips',false,[])], 'engine',['search_box','timing','extraction']),
 'Huggingface--2': R('passed','Three identified NLP text-translation models have open licenses, popularity indicators in Trending, and initial public commits within one month. Initial commit is treated as public release evidence; no claim of globally greatest popularity.',[C('Three NLP translation models',true,[E('-6.json','supports text translation across 150 languages'),E('-10.json','supports text translation across 150 languages'),E('-17.json','text-to-text simultaneous machine translation')]),C('Open source licenses',true,[E('-6.json','License: apache-2.0'),E('-10.json','License: apache-2.0'),E('-17.json','License: apache-2.0')]),C('Popular with observable indicators',true,[E('-5.json','Sort: Trending IndexTeam/Index-Translate-2B Translation'),E('-5.json','474 • 35 IndexTeam/Index-Translate-9B'),E('-5.json','579 • 33'),E('-5.json','netease-youdao/Confucius4-T3PO Translation • 15B • Updated 5 days ago • 1.57k • 73')]),C('Released within September 4-October 4 2026',true,[E('-8.json','initial commit b340f22 VERIFIED qijiv2000 commited on 7 days ago'),E('-13.json','initial commit 60369d5 VERIFIED qijiv2000 commited on 7 days ago'),E('-21.json','initial commit d304e00 VERIFIED ZhengFengyun commited on 27 days ago')])]),
 'Apple--1': R('passed','Captured Apple Support iOS 17 update notes list the stated features and explicitly support keyboard enhancements on iPhone 12 and later; compatibility conclusion is supported.',[C('iOS 17 features on Apple Support',true,[E('-22.json','StandBy delivers a new full-screen experience'),E('-22.json','NameDrop for contact sharing'),E('-22.json','Contact Posters'),E('-22.json','Live Voicemail')]),C('iPhone 12 compatibility',true,[E('-22.json','iPhone 12 and later')])]),
 'Huggingface--0': R('passed','A sentiment model card supports pretrained NLP use and the paginated directory explicitly supplies March 17, 2023 update date for that same model.',[C('Pretrained NLP sentiment analysis model',true,[E('-8.json','Model Card for RuBERT for Sentiment Analysis'),E('-8.json','from_pretrained'),E('-8.json','0: NEUTRAL 1: POSITIVE 2: NEGATIVE')]),C('Last update in March 2023',true,[E('-7.json','MonoHime/rubert-base-cased-sentiment-new Text Classification • 0.2B • Updated Mar 17, 2023')])]),
 'Google Search--0': R('passed','Captured official Disney Movies search snippet gives May 5, 2023; answer distinguishes US release from May 3 international release and premiere events.',[C('Initial theatrical release date with source support',true,[E('-8.json','Disney Movies | Official Site'),E('-8.json','Release Date: May 5, 2023'),E('-8.json','released on 3 May 2023')])],null,[],'Static golden May 5, 2023 is explicitly included as US theatrical release. Geographic release-date distinctions explain the additional May 3 date; expected fact is not contradicted.'),
 'Google Search--1': R('passed','Birthday and current professional status have independent result snippets; other biographical facts are present in the captured overview and Olympics snippet. No historical-team reference substituted for current evidence.',[C('Kevin Durant biographical facts',true,[E('-6.json','Kevin Wayne Durant (born September 29, 1988)'),E('-6.json','Born on September 29, 1988, in Washington, D.C.'),E('-6.json','Drafted second overall by the Seattle SuperSonics'),E('-6.json','Rookie of the Year Award')]),C('Current professional status from live results',true,[E('-6.json','TeamHouston Rockets. Position Forward.'),E('-6.json','two titles with the Golden State Warriors (2017, 2018)'),E('-6.json','four Olympic gold medals')])],null,[],'Possible reference team Phoenix is historical and stale. Live ESPN/Wikipedia snippets support Houston; birth date matches unchanged fact. Career-summary details partly use captured Google AI overview and are not independent source-page verification.'),
 'Google Search--2': R('failed','A valid title with 4-hour age is captured, but latest visible Top Stories is a narrower claim than latest news. News-mode ordering attempt reaches explicit unusual-traffic reCAPTCHA; no bypass.',[C('Los Angeles Lakers news title',true,[E('-5.json',"Lakers' Bronny James trade rumors gain traction")]),C('Establish latest through date/order coverage',false,[E('-6.json','trafic exceptionnel'),E('-6.json','reCAPTCHA')], 'Four visible Top Stories ages do not establish globally latest news; chronological verification was access-blocked.')], 'access_wall',['planning','filters','extraction']),
 'Allrecipes--0': R('passed', 'Qualifying recipe, rating, reviews and six-person suitability are supported. Scaling is explicit arithmetic; the unscaled eight portions also feed six.', [C('Vegetarian lasagna recipe with ingredients and method', true, [E('-7.json','Vegetarian Four Cheese Lasagna'),E('-7.json','2 cups peeled and diced pumpkin'),E('-7.json','Bake in preheated oven 30 to 40 minutes')]), C('More than 100 reviews and rating at least 4.5',true,[E('-7.json','4.6 (243) 170 REVIEWS')]), C('Suitable for six people',true,[E('-7.json','Original recipe (1X) yields 8 servings')])], null, [], 'Same recipe as possible reference; live 170 reviews differs from historical 181 and remains above threshold.'),
 'Allrecipes--1': R('passed','Legitimate later owner retry reaches the actual meatless recipe,4.7 rating and zucchini ingredient; original challenge attempt and full original timer remain separately preserved.',[C('Vegetarian lasagna',true,[E('-7.json','VEGETARIAN LASAGNA RECIPES'),E('-7.json',"Debbie's Vegetable Lasagna")]),C('At least four-star rating',true,[E('-7.json','4.7 (20)')]),C('Uses zucchini',true,[E('-7.json','2 cups coarsely chopped zucchini')])]),
 'Allrecipes--2': R('passed', 'Meatless recipe has 451 calories per serving and 15-minute preparation. Longer cooking/total time does not contradict the prep-time constraint.', [C('Vegetarian lasagna',true,[E('-5.json','Vegetarian Four Cheese Lasagna'),E('-5.json','1 eggplant, sliced into 1/2 inch rounds')]),C('Under 600 calories per serving',true,[E('-5.json','Nutrition Facts (per serving) 451 Calories')]),C('Preparation under one hour',true,[E('-5.json','Prep Time: 15 mins')])]),
 'Apple--0': R('passed','Latest live M5 13-inch and 15-inch prices captured; $200 difference is correct arithmetic.',[C('Latest MacBook Air models',true,[E('-6.json','Now supercharged by M5')]),C('Both starting prices and comparison',true,[E('-7.json','13-inch Footnote 1 Buy from $1299'),E('-7.json','15-inch Footnote 1 Buy from $1499')])],null,[],'Historical M1/M2 prices are stale examples; captured current M5 models and US starting prices satisfy the unchanged task.'),
 'ArXiv--0': R('passed','Newest announcement sorting, tied submission dates and all three identified recent related papers are captured.',[C('Quantum-computing preprints',true,[E('-3.json','Robust exponential lower bounds for fermionic and bosonic Gaussian ranks'),E('-3.json','Polynomial-time classical and quantum simulation of quantum impurity models'),E('-3.json','A provable quantum advantage for approximate optimization via decoded quantum interferometry')]),C('Latest with date/order proof',true,[E('-3.json','order=-announced_date_first','url'),E('-3.json','Submitted 1 October, 2026')])]),
 'ArXiv--1': R('passed','Legitimate negative answer: query and original-submission date filter cover October 2-4 UTC and the search reports no results. Answer explicitly limits absence to this indexed search.',[C('Search quantum computing with submission dates October 2-4 2026',true,[E('-4.json','terms-0-term=%22quantum+computing%22','url'),E('-4.json','date-from_date=2026-10-02&date-to_date=2026-10-04','url'),E('-4.json','date-date_type=submitted_date_first','url')]),C('Return latest qualifying papers or verified empty filtered result',true,[E('-4.json','Sorry, your query returned no results')])],null,[],'Real-time possible reference permits current evidence; no matching indexed papers exist in the captured exact-topic date query. This pass is a supported negative answer and is separately reported, not an invented positive result.'),
 'ArXiv--2': R('passed','Top latest cs.CL item selected, its abstract read and accurately paraphrased, including all stated benchmark quantities.',[C('Recent cs.CL list and selected paper',true,[E('-2.json','Fri, 2 Oct 2026'),E('-2.json','[1] arXiv:2610.02206')]),C('Provide selected paper abstract',true,[E('-3.json','Abstract:LLMs are increasingly applied to cybersecurity workflows'),E('-3.json','8,504 query--command pairs spanning 1,642 tools'),E('-3.json','no open-weight model exceeds 42% exact-command accuracy'),E('-3.json','comparable to a 685B MoE model')])]),
 'BBC News--0': R('passed','BBC report dated September 7 describes approved UK biogas technology, 27 days before run; recent development satisfies this task with no stricter date clause.',[C('BBC News report',true,[E('-10.json','Chicken waste plant approved amid fears over smell')]),C('Recent UK renewable energy technology development',true,[E('-10.json','7 September 2026'),E('-10.json','120,000 tonnes of chicken waste and feedstock into renewable gas each year'),E('-10.json','Anwick, near Sleaford')])]),
 'BBC News--1': R('failed','Source-backed summary is supplied, but only editorial health cards and tied ages are compared. Executor explicitly says global latest remains unverified; no chronological coverage or latest-order proof.',[C('Read a health-related BBC article and summarize key points',true,[E('-5.json','How to spot a psychopath at work'),E('-5.json','Robert Snowden')]),C('Establish latest health-related BBC News article',false,[], 'Editorial landing page and a few compared ages do not establish global latest.')], 'planning',['search_box','extraction','engine']),
 'BBC News--2': R('failed','Earth and Climate Solutions were browsed, but no deforestation-impact article within October 2-4 was acquired. Limited editorial browsing does not prove a valid zero-match answer.',[C('Environmental impacts of deforestation article',false,[]),C('Publication within October 2-4 and latest qualifying article',false,[]),C('Read and report qualifying content',false,[])], 'search_box',['planning','filters','extraction','engine']),
 'Cambridge Dictionary--0': R('passed','Definition paraphrase and both IPA pronunciations match captured Cambridge and static golden reference.',[C('Cambridge pronunciation of sustainability',true,[E('-11.json','/səˌsteɪ.nəˈbɪl.ə.ti/'),E('-11.json','/səˌsteɪ.nəˈbɪl.ə.t̬i/')]),C('Definition',true,[E('-11.json','the quality of being able to continue over a period of time')])],null,[],'Static golden pronunciation and definition match semantically.'),
 'Cambridge Dictionary--1': R('passed','Both pronunciations, definition and Cambridge corpus example are correct.',[C('Pronunciation',true,[E('-3.json','/ˌser.ənˈdɪp.ə.ti/'),E('-3.json','/ˌser.ənˈdɪp.ə.t̬i/')]),C('Definition',true,[E('-3.json','finding interesting or valuable things by chance')]),C('Sample Cambridge sentence',true,[E('-3.json','There is a real element of serendipity in archaeology.')])]),
 'Cambridge Dictionary--2': R('passed','Both requested IPA variants and definitions/examples are present on Cambridge.',[C('UK and US pronunciations',true,[E('-3.json','/juːˈbɪk.wɪ.təs/'),E('-3.json','/juːˈbɪk.wə.t̬əs/')]),C('Definition',true,[E('-3.json','seeming to be everywhere')]),C('Cambridge example sentence',true,[E('-3.json','Leather is very much in fashion this season, as is the ubiquitous denim.'),E('-3.json','The eel grass limpet used to be ubiquitous on the New England coast.')])]),
 'Coursera--0': R('passed','French results card explicitly ties 3D Printing Software to Illinois, beginner level, course and 1-3 months; different possible upstream example is legitimate.',[C('3D-printing course',true,[E('-9.json',"logiciel d'impression 3D")]),C('Beginner and duration 1-3 months',true,[E('-9.json','Débutant · Cours · 1 à 3 mois')]),C('Renowned university provider',true,[E('-9.json','University of Illinois Urbana-Champaign')])]),
 'Coursera--1': R('passed','Full Michigan Python course explicitly says beginner, no prior experience and no prerequisites; selected alternative to upstream example satisfies every clause.',[C('Online Python programming course',true,[E('-10.json','Programming for Everybody (Getting Started with Python)')]),C('Beginner suitable without programming experience',true,[E('-10.json','Beginner level'),E('-10.json','No prior experience required'),E('-10.json','no pre-requisites')])]),
 'Coursera--2': R('passed','UC Davis beginner Spanish specialization and all five course cards captured. French displayed titles translate accurately to supplied English list.',[C('Beginner Spanish specialization',true,[E('-8.json',"Vocabulaire de base de l'espagnol"),E('-8.json','niveau Débutant'),E('-8.json','Aucune connaissance prérequise')]),C('All courses',true,[E('-8.json','Série de 5 cours'),E('-8.json','Vocabulaire espagnol : Rencontrer des gens'),E('-8.json','Vocabulaire espagnol : Expérience culturelle'),E('-8.json','Vocabulaire espagnol : Sports, voyages et maison'),E('-8.json','Vocabulaire espagnol : Carrières et événements sociaux'),E('-8.json','Projet de vocabulaire espagnol')])]),
 'Huggingface--3': R('passed','License-filtered most-liked order places replit first at 744, ahead of 446,320,316; model card confirms license and likes.',[C('cc-by-sa-4.0 license',true,[E('-19.json','License: cc-by-sa-4.0')]),C('Most likes within matching license set',true,[E('-16.json','license=license:cc-by-sa-4.0&sort=likes','url'),E('-18.json','Sort: Most likes'),E('-18.json','replit/replit-code-v1-3b'),E('-19.json','Like 744')])]),
};
function locate(locator, observations) {
 const rows = observations.filter(o => o.ref.path.endsWith(locator.suffix));
 const wanted = norm(locator.text);
 for (const o of rows) {
  const structured = ['tables','elements'].includes(locator.field);
  const content = structured ? JSON.stringify(o.value[locator.field]) : norm(o.value[locator.field]);
  const at = content.indexOf(wanted);
  if (at >= 0) return { path:o.ref.path, sha256:o.ref.sha256, url:o.value.url || o.ref.url, capturedAt:o.ref.capturedAt, field:locator.field, quote:content.slice(at,at+Math.min(280,wanted.length+70)), verifiedSha256:true, whitespaceNormalized:!structured };
 }
 throw Error('Reviewed evidence locator missing: '+JSON.stringify(locator));
}
function quantile(values, q) { const s=values.filter(Number.isFinite).sort((a,b)=>a-b); return s.length ? s[Math.min(s.length-1,Math.ceil(q*s.length)-1)] : null; }
function grade() {
 const runBytes=fs.readFileSync(runPath), run=JSON.parse(runBytes), frozen=JSON.parse(fs.readFileSync(taskPath)), refs=JSON.parse(fs.readFileSync(referencePath));
 const buildPath='scripts/evidence/C2d-native-build.json';
 const nativeBuild=fs.existsSync(buildPath)?JSON.parse(fs.readFileSync(buildPath)):null;
 const nativeBinding=nativeBuild?{receiptPath:buildPath,receiptSha256:fileSha(buildPath),builtAt:nativeBuild.at,claimedBinarySha256:nativeBuild.sha256,actualBinarySha256:fs.existsSync(nativeBuild.exe)?fileSha(nativeBuild.exe):null,sourceHashes:nativeBuild.sources,currentSources:Object.fromEntries(Object.entries(nativeBuild.sources).map(([p,h])=>[p,{recordedSha256:h,currentSha256:fs.existsSync(p)?fileSha(p):null}]))}:null;
 if (fileSha(taskPath)!==run.taskSetSha256) throw Error('Frozen task set changed');
 const rows=frozen.tasks.map(goal=>{
  const task=run.tasks.find(t=>t.id===goal.id), review=reviews[goal.id];
  if(task && (task.goal!==goal.goal || task.startUrl!==goal.startUrl)) throw Error('Frozen goal/start URL differs for '+goal.id);
  const observations=(task?.observations||[]).map(ref=>{
   const hash=fileSha(ref.path); if(hash!==ref.sha256) throw Error('Observation SHA mismatch '+ref.path);
   return {ref,value:JSON.parse(fs.readFileSync(ref.path))};
  });
  const answerSha=digest(JSON.stringify({answer:task?.answer??null,reason:task?.reason??null,status:task?.status??null}));
  const terminal=['answered','failed','skipped'].includes(task?.status);
  const base={id:goal.id,goal:goal.goal,executorStatus:task?.status||'not_started',startedAt:task?.startedAt||null,finishedAt:task?.finishedAt||null,elapsedMs:task?.finishedAt?Date.parse(task.finishedAt)-Date.parse(task.startedAt):null,executorElapsedMs:task?.elapsedMs??null,semanticActionSteps:task?.steps??0,answer:task?.answer??null,answerSha256:answerSha,observationIntegrity:observations.map(o=>({path:o.ref.path,sha256:o.ref.sha256,verified:true,pageObservation:typeof o.value.text==='string'})),reference:{type:refs.answers[goal.id]?.type||null,path:referencePath+'#'+goal.id},attempts:{executorRetained:task?.attempts||[],trace:(task?.trace||[]).filter(s=>['acquisition_adapter_failure','recover_acquisition','explicit_owner_retry'].includes(s.kind))},firstAttempt:null,priorIndependentVerdicts:priorReviews[goal.id]||[],priorIndependentVerdict:reviewedAnswerSha[goal.id]&&reviewedAnswerSha[goal.id]!==answerSha?{answerSha256:reviewedAnswerSha[goal.id],outcome:review?.outcome,reason:review?.reason}:null};
  const initialFailure=base.attempts.trace.find(a=>a.kind==='acquisition_adapter_failure');
  base.firstAttempt=priorReviews[goal.id]?.length?{...priorReviews[goal.id][0],originalTimerRetained:true}:initialFailure?{outcome:'failed_or_interrupted',reason:initialFailure.reason,failedAt:initialFailure.failedAt,originalTimerRetained:true}:base.attempts.trace.length?{outcome:'recovered_without_separate_terminal_verdict',originalTimerRetained:true}:{outcome:terminal?task.status:'incomplete',originalTimerRetained:true};
  if(goal.id==='Allrecipes--1') base.firstAttempt={outcome:'skipped',reason:'Independently reviewed initial homepage challenge: repeated Just a moment title, blank text, no usable recipe controls.',finishedAt:'2026-10-04T20:16:32.662Z',elapsedMs:57205.9609,evidence:observations.filter(o=>/Allrecipes--1-[012]\.json$/.test(o.ref.path)).map(o=>({path:o.ref.path,sha256:o.ref.sha256,verified:true})),originalTimerRetained:true};
  if(!terminal || !review || reviewedAnswerSha[goal.id]!==answerSha) return {...base,outcome:'ungraded',reason:!terminal?'Task incomplete; not scored as failure.':'Terminal answer has not received matching independent human review.',clauses:[],success:false};
  const clauses=review.clauses.map(c=>({...c,evidence:c.evidence.map(e=>locate(e,observations))}));
  if(review.outcome==='passed'&&clauses.some(c=>!c.met||!c.evidence.length)) throw Error('Pass without all-clause proof '+goal.id);
  return {...base,...review,clauses,success:review.outcome==='passed',missingClauses:clauses.filter(c=>!c.met).map(c=>c.requirement),reference:{...base.reference,comparison:review.referenceComparison}};
 });
 const summary=Object.fromEntries(['passed','failed','skipped','ungraded'].map(k=>[k,rows.filter(r=>r.outcome===k).length]));
 const elapsed=rows.filter(r=>r.finishedAt).map(r=>r.elapsedMs);
 const report={schema:'neyvia.C2d.webvoyager-grades@1',gradedAt:new Date().toISOString(),draft:summary.ungraded>0,totalFrozenTasks:36,run:{path:runPath,sha256:digest(runBytes)},taskSet:{path:taskPath,sha256:fileSha(taskPath)},references:{path:referencePath,sha256:fileSha(referencePath),executorAccess:false},grader:{identity:'Independent Codex /root/failure_meter',source:{path:'scripts/c2d_grade.cjs',sha256:fileSha('scripts/c2d_grade.cjs')},method:'Clause-level human semantic review pinned to exact answer/status/reason digest. All retained observation hashes checked before citations. Reference answers never supplied to executor. Evidence string matching locates previously reviewed passages; cannot award a new answer automatically.'},protocol:{utcRunDate:'2026-10-04',required:'All frozen clauses and current live constraints; static facts semantically compare to golden answers. Possible examples are not exclusive; dated/ranking references can drift and must be explained.',negativeAnswers:'Supported empty sets can pass only with exact topic/date/filter/order coverage; browsing a few cards does not establish absence. A missing game cannot be invented.',latency:'Original startedAt to finishedAt includes interruption/recovery; no reset or exclusion. Unfinished tasks remain ungraded.',costUSD:null},summary,metrics:{taskLatencyP50Ms:quantile(elapsed,.5),taskLatencyP95Ms:quantile(elapsed,.95),latencyTargetMet:summary.ungraded===0&&quantile(elapsed,.5)<30000,successTargetMet:summary.passed===36,terminalTasks:elapsed.length},runtimeBoundary:{native:run.native||null,nativeBinding,runtimeSegments:run.runtimeSegments||[],note:'Fresh C2d native build receipt is bound to the independently hashed binary and sources above. Earlier native attempts occurred before that build; retained run embeddedSourceBoundary text was stale hardcoded metadata. Post-build source proof must not retroactively reclassify pre-build actions. This grade evaluates live answer evidence and retains original timing/recovery traces.'},grades:rows};
 fs.writeFileSync(outPath,JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({out:outPath,summary,metrics:report.metrics}));
 return report;
}
module.exports={grade,reviews};
if(require.main===module)try{grade()}catch(e){console.error(e.message);process.exitCode=1}
