/* Fixture pack: math, derivatives. Hand-written for the prototype; same shape as the
   plan 13 pack format (concepts[], cards[], sources[]). Math is plain HTML here; the
   real player renders KaTeX. `prior` marks concepts learned in an earlier session
   (FSRS has them due today), so the feed has real reviews from the first minute. */
(function () {
  "use strict";
  var m = function (s) { return '<span class="math">' + s + "</span>"; };

  var source = {
    id: "notes/analyse-ch2.md",
    title: "Analyse, chapter 2: derivatives (your notes)",
    text: {
      slope: "The slope of a line through two points is rise over run: (y2 − y1) / (x2 − x1).",
      def: "The derivative f'(a) is the limit of the difference quotient (f(a+h) − f(a)) / h as h → 0. It is the slope of the tangent at a.",
      power: "Power rule: d/dx xⁿ = n·xⁿ⁻¹ for any real n.",
      sum: "Derivatives are linear: (c·f + g)' = c·f' + g'.",
      product: "Product rule: (f·g)' = f'·g + f·g'. Not f'·g'.",
      comp: "A composition f(g(x)) applies g first, then f. Example: (3x+1)⁴ is u⁴ with u = 3x+1.",
      chain: "Chain rule: (f∘g)'(x) = f'(g(x))·g'(x). Outer derivative, evaluated at the inside, times the inner derivative.",
      exp: "eˣ is its own derivative: d/dx eˣ = eˣ.",
      tangent: "Tangent line at a: y = f(a) + f'(a)(x − a).",
      extrema: "At an interior local max or min of a differentiable f, f'(x) = 0. The converse is false (x³ at 0)."
    }
  };

  var concepts = [
    { id: "func.slope", name: "Slope of a line", chapter: "derivatives", prereqs: [], prior: true, src: "slope" },
    { id: "deriv.def", name: "Derivative as a limit", chapter: "derivatives", prereqs: ["func.slope"], prior: true, src: "def" },
    { id: "deriv.power", name: "Power rule", chapter: "derivatives", prereqs: ["deriv.def"], prior: true, src: "power" },
    { id: "deriv.sum", name: "Sum and constant rule", chapter: "derivatives", prereqs: ["deriv.power"], src: "sum" },
    { id: "deriv.product", name: "Product rule", chapter: "derivatives", prereqs: ["deriv.sum"], src: "product", confusableWith: ["deriv.chain"] },
    { id: "func.composition", name: "Composition", chapter: "derivatives", prereqs: [], src: "comp" },
    { id: "deriv.chain", name: "Chain rule", chapter: "derivatives", prereqs: ["deriv.power", "func.composition"], src: "chain", confusableWith: ["deriv.product"] },
    { id: "deriv.exp", name: "Derivative of eˣ", chapter: "derivatives", prereqs: ["deriv.def"], src: "exp" },
    { id: "deriv.tangent", name: "Tangent line", chapter: "derivatives", prereqs: ["deriv.def", "func.slope"], src: "tangent" },
    { id: "deriv.extrema", name: "Critical points", chapter: "derivatives", prereqs: ["deriv.def"], src: "extrema" }
  ];

  // c(id, type, teaches, tests, requires, extra)
  var c = function (id, type, teaches, tests, requires, extra) {
    var card = { id: id, type: type, concepts: { teaches: teaches, tests: tests, requires: requires }, seconds: 15 };
    for (var key in extra) card[key] = extra[key];
    return card;
  };

  var cards = [
    // --- prior concepts: reviews only (their teach cards were seen in an earlier session)
    c("slope.tf.01", "truefalse", [], ["func.slope"], [], {
      body: "A horizontal line has slope 0.", answer: true, seconds: 8,
      explanation: "Rise is 0 for any run, so rise over run is 0.", src: "slope" }),
    c("slope.flash.01", "flashcard", [], ["func.slope"], [], {
      front: "Slope of the line through (1, 2) and (3, 8)?", back: "3", seconds: 12,
      explanation: "Rise 8 − 2 = 6 over run 3 − 1 = 2.", src: "slope" }),
    c("def.mcq.01", "mcq", [], ["deriv.def"], ["func.slope"], {
      body: "What is " + m("f′(a)") + " the limit of, as " + m("h → 0") + "?", seconds: 20,
      options: [
        { text: m("(f(a+h) − f(a)) / h"), correct: true },
        { text: m("f(a+h) − f(a)"), why: "That is the rise only; it tends to 0, not to a slope." },
        { text: m("h / (f(a+h) − f(a))"), why: "Upside down: run over rise." }
      ],
      explanation: "The difference quotient is the slope of a secant; as h shrinks it becomes the tangent's slope.", src: "def" }),
    c("power.cloze.01", "cloze", [], ["deriv.power"], ["deriv.def"], {
      before: "Power rule: d/dx " + m("x<sup>n</sup>") + " =", blank: m("n·x<sup>n−1</sup>"), after: "", seconds: 10,
      explanation: "Bring the exponent down, then lower it by one.", src: "power" }),
    c("power.flash.01", "flashcard", [], ["deriv.power"], ["deriv.def"], {
      front: "Differentiate " + m("x<sup>5</sup>"), back: m("5x<sup>4</sup>"), seconds: 8,
      explanation: "n = 5: bring down 5, exponent becomes 4.", src: "power" }),

    // --- sum and constant rule
    c("sum.fact.01", "fact", ["deriv.sum"], [], ["deriv.power"], {
      title: "Derivatives are linear",
      body: "Constants come out and sums split: " + m("(c·f + g)′ = c·f′ + g′") + ".",
      why: "A limit of a sum is the sum of the limits, and constants factor out of a limit.", seconds: 10, src: "sum" }),
    c("sum.cloze.01", "cloze", [], ["deriv.sum"], ["deriv.power"], {
      before: "d/dx (" + m("4x<sup>3</sup> + x") + ") =", blank: m("12x<sup>2</sup> + 1"), after: "", seconds: 12,
      explanation: "4 · 3x² = 12x², and x′ = 1.", src: "sum" }),
    c("sum.tf.01", "truefalse", [], ["deriv.sum"], ["deriv.power"], {
      body: "d/dx (" + m("7x<sup>2</sup>") + ") = " + m("7x") + ".", answer: false, seconds: 10,
      explanation: "The 7 stays, and x² gives 2x: the answer is 14x.", src: "sum" }),

    // --- product rule (worked example, faded later)
    c("product.explainer.01", "explainer", ["deriv.product"], [], ["deriv.sum"], {
      title: "The product rule",
      body: "<p>To differentiate a product, take turns: differentiate one factor while the other stays.</p><p class=\"formula\">" + m("(f·g)′ = f′·g + f·g′") + "</p><p>The tempting shortcut " + m("f′·g′") + " is wrong: try it on " + m("x·x") + ".</p>",
      figure: "product", seconds: 20, src: "product" }),
    c("product.worked.01", "worked", ["deriv.product"], [], ["deriv.product"], {
      title: "Differentiate " + m("x<sup>2</sup>·eˣ"), seconds: 30, src: "product",
      steps: [
        { text: "Name the factors: " + m("f = x<sup>2</sup>") + ", " + m("g = eˣ") + "." },
        { text: "Differentiate each: " + m("f′ = 2x") + ", " + m("g′ = eˣ") + "." },
        { text: "Take turns: " + m("f′g + fg′ = 2x·eˣ + x<sup>2</sup>·eˣ") + ".", why: "Each term differentiates one factor and keeps the other." },
        { text: "Factor: " + m("eˣ(x<sup>2</sup> + 2x)") + "." }
      ] }),
    c("product.flash.01", "flashcard", [], ["deriv.product"], ["deriv.sum"], {
      front: "State the product rule.", back: m("(f·g)′ = f′·g + f·g′"), seconds: 10,
      explanation: "Differentiate one factor at a time and add.", src: "product" }),
    c("product.mcq.01", "mcq", [], ["deriv.product"], ["deriv.sum", "deriv.exp"], {
      body: "d/dx (" + m("x·eˣ") + ") = ?", seconds: 20,
      options: [
        { text: m("eˣ + x·eˣ"), correct: true },
        { text: m("eˣ"), why: "That is f′·g′ = 1·eˣ: the shortcut that skips a term." },
        { text: m("x·eˣ"), why: "Only the second term of the rule." }
      ],
      explanation: "f′g + fg′ = 1·eˣ + x·eˣ.", src: "product" }),
    c("product.why.01", "why", [], ["deriv.product"], ["deriv.product"], {
      front: "Why is " + m("(f·g)′") + " not " + m("f′·g′") + "?", seconds: 15,
      back: "Try f = g = x: (x·x)′ = 2x, but f′·g′ = 1. When both factors change, the product grows from each change separately.",
      explanation: "Area picture: a rectangle f by g grows by a strip f′·g and a strip f·g′.", src: "product" }),

    // --- composition and chain rule
    c("comp.fact.01", "fact", ["func.composition"], [], [], {
      title: "A function inside a function",
      body: m("f(g(x))") + " applies g first, then f. In " + m("(3x+1)<sup>4</sup>") + " the inside is " + m("u = 3x+1") + " and the outside is " + m("u<sup>4</sup>") + ".",
      why: "Spotting the inside is the first step of the chain rule.", seconds: 12, src: "comp" }),
    c("comp.tf.01", "truefalse", [], ["func.composition"], [], {
      body: "In " + m("√(x<sup>2</sup>+1)") + " the inner function is " + m("√x") + ".", answer: false, seconds: 10,
      explanation: "The inside is x² + 1; the square root is applied last, so it is the outer function.", src: "comp" }),
    c("comp.flash.01", "flashcard", [], ["func.composition"], [], {
      front: "In " + m("sin(x<sup>2</sup>)") + ", which function is applied first?", back: m("x<sup>2</sup>") + " (the inside), then sin.", seconds: 10,
      explanation: "Read from the inside out: square, then take the sine.", src: "comp" }),
    c("chain.explainer.01", "explainer", ["deriv.chain"], [], ["deriv.power", "func.composition"], {
      title: "The chain rule",
      body: "<p>Differentiate the outside, keep the inside, then multiply by the inside's derivative.</p><p class=\"formula\">" + m("(f(g(x)))′ = f′(g(x))·g′(x)") + "</p><p>Forgetting the last factor is the most common mistake.</p>",
      figure: "chain", seconds: 22, src: "chain" }),
    c("chain.worked.01", "worked", ["deriv.chain"], [], ["deriv.chain"], {
      title: "Differentiate " + m("(3x+1)<sup>4</sup>"), seconds: 30, src: "chain",
      steps: [
        { text: "Inside " + m("u = 3x+1") + ", outside " + m("u<sup>4</sup>") + "." },
        { text: "Outer derivative: " + m("4u<sup>3</sup> = 4(3x+1)<sup>3</sup>") + "." },
        { text: "Inner derivative: " + m("u′ = 3") + "." },
        { text: "Multiply: " + m("12(3x+1)<sup>3</sup>") + ".", why: "The inside changes 3 times as fast as x, so every change of the outside is scaled by 3." }
      ] }),
    c("chain.cloze.01", "cloze", [], ["deriv.chain"], ["deriv.power", "func.composition"], {
      before: "Chain rule: " + m("(f(g(x)))′ = f′(g(x))") + " ×", blank: m("g′(x)"), after: "", seconds: 10,
      explanation: "The inner derivative is the factor people forget.", src: "chain" }),
    c("chain.mcq.01", "mcq", [], ["deriv.chain"], ["deriv.power", "func.composition"], {
      body: "What is d/dx " + m("(3x+1)<sup>4</sup>") + "?", seconds: 20,
      options: [
        { text: m("12(3x+1)<sup>3</sup>"), correct: true },
        { text: m("4(3x+1)<sup>3</sup>"), why: "Forgot the inner derivative (3)." },
        { text: m("4·3<sup>3</sup>"), why: "Differentiated the inside as if it were the whole thing." },
        { text: m("12x<sup>3</sup>"), why: "Dropped the inside after differentiating." }
      ],
      explanation: "Outer 4u³ times inner 3.", src: "chain" }),
    c("chain.order.01", "order", [], ["deriv.chain"], ["deriv.power", "func.composition"], {
      body: "Put the chain rule steps in order.", seconds: 25, src: "chain",
      items: ["Find the inside u", "Differentiate the outside in u", "Put u back in", "Multiply by u′"],
      explanation: "Inside first, then outside, then the inner factor." }),
    c("chain.spot.01", "spot", [], ["deriv.chain"], ["deriv.power", "func.composition"], {
      body: "One line is wrong. Tap it.", seconds: 25, src: "chain",
      title: "d/dx " + m("(x<sup>2</sup>+1)<sup>3</sup>"),
      lines: [m("u = x<sup>2</sup>+1"), m("outer: 3u<sup>2</sup>"), m("inner: u′ = 2x"), m("result: 3(x<sup>2</sup>+1)<sup>2</sup>")],
      wrong: 3, fix: m("6x(x<sup>2</sup>+1)<sup>2</sup>"),
      explanation: "The last line forgot to multiply by u′ = 2x." }),
    c("chain.why.01", "why", [], ["deriv.chain"], ["deriv.chain"], {
      front: "Why multiply by the inner derivative?", seconds: 15,
      back: "The outside reacts to changes in u, not in x. g′ converts a change in x into a change in u.",
      explanation: "Rates multiply along a chain: dy/dx = dy/du · du/dx.", src: "chain" }),

    // --- exp, tangent, extrema
    c("exp.fact.01", "fact", ["deriv.exp"], [], ["deriv.def"], {
      title: m("eˣ") + " is its own derivative",
      body: "d/dx " + m("eˣ = eˣ") + ". Its slope at every point equals its height.",
      why: "e is the base for which the slope at 0 is exactly 1.", seconds: 10, src: "exp" }),
    c("exp.tf.01", "truefalse", [], ["deriv.exp"], ["deriv.def"], {
      body: "d/dx " + m("eˣ = x·eˣ<sup>−1</sup>") + ".", answer: false, seconds: 10,
      explanation: "That is the power rule misapplied: x is in the exponent, not the base. The derivative is eˣ.", src: "exp" }),
    c("exp.cloze.01", "cloze", [], ["deriv.exp"], ["deriv.def"], {
      before: "d/dx " + m("eˣ") + " =", blank: m("eˣ"), after: "", seconds: 8,
      explanation: "The one function equal to its own slope everywhere.", src: "exp" }),
    c("tangent.explainer.01", "explainer", ["deriv.tangent"], [], ["deriv.def", "func.slope"], {
      title: "The tangent line",
      body: "<p>A line through " + m("(a, f(a))") + " with slope " + m("f′(a)") + ":</p><p class=\"formula\">" + m("y = f(a) + f′(a)(x − a)") + "</p>",
      figure: "tangent", seconds: 18, src: "tangent" }),
    c("tangent.mcq.01", "mcq", [], ["deriv.tangent"], ["deriv.def", "deriv.power"], {
      body: "Tangent to " + m("y = x<sup>2</sup>") + " at " + m("x = 1") + "?", seconds: 25,
      options: [
        { text: m("y = 2x − 1"), correct: true },
        { text: m("y = 2x"), why: "Right slope, but the line must pass through (1, 1)." },
        { text: m("y = x"), why: "Slope 1 is f(1), not f′(1) = 2." }
      ],
      explanation: "f(1) = 1, f′(1) = 2: y = 1 + 2(x − 1) = 2x − 1.", src: "tangent" }),
    c("extrema.fact.01", "fact", ["deriv.extrema"], [], ["deriv.def"], {
      title: "Flat at the top",
      body: "At an interior maximum or minimum of a smooth function, " + m("f′(x) = 0") + ". The converse fails: " + m("x<sup>3</sup>") + " is flat at 0 but keeps rising.",
      why: "Just before a peak the slope is positive, just after it is negative; it passes through 0.", seconds: 14, src: "extrema" }),
    c("extrema.tf.01", "truefalse", [], ["deriv.extrema"], ["deriv.def"], {
      body: "If " + m("f′(c) = 0") + ", then c is a maximum or a minimum.", answer: false, seconds: 12,
      explanation: "x³ has f′(0) = 0 but no max or min there.", src: "extrema" }),

    c("extrema.flash.01", "flashcard", [], ["deriv.extrema"], ["deriv.def"], {
      front: "What is " + m("f′") + " at an interior peak of a smooth f?", back: m("f′ = 0"), seconds: 10,
      explanation: "The slope changes sign there, so it passes through 0.", src: "extrema" }),

    // --- recap
    c("recap.rules.01", "recap", [], [], ["deriv.sum", "deriv.product"], {
      title: "So far today",
      bullets: ["Constants come out, sums split.", "Product: " + m("f′g + fg′") + ", never " + m("f′g′") + ".", "Take turns: differentiate one factor, keep the other."], seconds: 10 })
  ];

  // Reward/surprise cards are never graded and never on the hard-rule path.
  var surprises = [
    { id: "surprise.leibniz", type: "reward", kind: "fact", title: "A curious one", body: "Leibniz wrote dy/dx so the chain rule looks like cancelling fractions: dy/du · du/dx. It is not really cancelling, but it never misleads you." }
  ];

  window.SS_PACK = { meta: { title: "Derivatives", subject: "math", version: 1, generator: "neyvia (fixture)" },
    concepts: concepts, cards: cards, surprises: surprises, source: source };
})();
