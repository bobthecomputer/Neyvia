/* Approved backend packs use the same player as the bundled sample. */
window.SS_BOOT = (async function () {
  var file = new URLSearchParams(location.search).get("pack") || "generated-pack.json";
  if (!/^[A-Za-z0-9_.-]+\.json$/.test(file)) throw new Error("Choose a local pack JSON file");
  var response = await fetch(file);
  if (response.status === 404 && file === "generated-pack.json" && !new URLSearchParams(location.search).has("pack")) return;
  if (!response.ok) throw new Error("The generated pack could not be loaded. Export and preview it again.");
  var value = await response.json();
  if (!value.meta || !Array.isArray(value.concepts) || !Array.isArray(value.cards)) throw new Error("Invalid study pack");
  var textsResponse = await fetch("generated-sources.json");
  var texts = textsResponse.ok ? await textsResponse.json() : {};
  function escape(text) { return String(text == null ? "" : text).replace(/[&<>"']/g, function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];}); }
  value.title = value.meta.title;
  value.id = value.meta.id;
  value.subject = value.meta.subjects[0];
  value.source = {title: value.sources.map(function(s){return s.title;}).join(", "), text:{}};
  value.cards.forEach(function(card){
    var view = {formula:'explainer', when:'explainer', write:'explainer', pattern:'explainer', course_example:'worked', your_exercise:'flashcard', variations_traps:'explainer', pattern_drill:'flashcard', exercise_variant:'flashcard'};
    var labels = {formula:'FORMULA',when:'WHEN?',write:'WHAT DO I WRITE?',pattern:'PATTERN',course_example:'COURSE EXAMPLE',your_exercise:'YOUR EXERCISE',variations_traps:'VARIATIONS/TRAPS',pattern_drill:'Recognise the type',exercise_variant:'Changed exercise'};
    if(view[card.type]) {card.studyType=card.type;card.title=labels[card.type];card.type=view[card.type];}
    card.title = escape(card.title || card.body || card.id);
    if (card.type === "recap") card.bullets = (card.body || "").split("\n").filter(Boolean).map(escape);
    ["body","front","back","before","after","blank","explanation","fix"].forEach(function(key){if(card[key] != null)card[key]=escape(card[key]);});
    if(card.cloze){card.before=escape(card.cloze.before);card.blank=escape(card.cloze.blank);card.after=escape(card.cloze.after);}
    if(card.options)card.options=card.options.map(function(o){return Object.assign({},o,{text:escape(o.text),why:escape(o.why)});});
    if(card.steps)card.steps=card.steps.map(function(s){return typeof s === "string"?{text:escape(s)}:Object.assign({},s,{text:escape(s.text),why:escape(s.why),answer:s.answer?escape(s.answer):undefined});});
    if(card.items)card.items=card.items.map(escape);
    if(card.lines)card.lines=card.lines.map(escape);
    if(card.spot){card.lines=card.spot.lines.map(escape);card.wrong=card.spot.wrong;card.fix=escape(card.spot.fix);}
    if(card.source){card.src=card.id;var text=texts[card.source.doc]||"";value.source.text[card.src]=text.slice(card.source.span[0],card.source.span[1]);}
    if(card.part && card.type==='explainer')card.body=card.body.replace(/\n/g,'<br>');
  });
  window.SS_PACK = value;
  window.SS_GENERATED = true;
})();
