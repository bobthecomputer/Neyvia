/* Neyvia Mobile Studio phone helper. Injected first into a previewed app's pages
   so the app behaves as on a phone: touch events from the mouse with drag-to-scroll,
   a phone user agent, coarse pointer, safe-area insets, hidden scrollbars, working
   localStorage (the preview runs sandboxed) and hot reload. Talks to Neyvia only by
   postMessage and to its own token path. */
(function () {
  "use strict";
  var config = window.__NX_MOBILE__ || {};
  var desktop = config.platform === "macos";
  var textScale = Math.max(0.8, Math.min(2, Number(config.textScale) || 1));
  // Browser approximation of Dynamic Type. Apps using fixed px text may not
  // scale like Apple's native controls; that limit is visible in the manual.
  document.documentElement.style.fontSize = (16 * textScale) + "px";
  document.documentElement.style.setProperty("--nx-dynamic-type-scale", String(textScale));
  var base = config.base || "./";
  var post = function (message) {
    try { window.parent.postMessage(Object.assign({ source: "nx-mobile" }, message), "*"); } catch (error) { /* top-level */ }
  };
  // Only this mounted frame's state/identity capability is available. The
  // parent authenticates the sender and selects the URL; no child URL or
  // cookie is forwarded. Child promises settle through ordinary messages.
  var sdkRequests = new Map(), sdkSequence = 0;
  var keyboardInput = null;
  addEventListener("focusin", function(event) { if (event.target.matches("input,textarea")) keyboardInput = event.target; });
  if (window.parent !== window) window.__neyviaPreviewRequest = function (operation, body) {
    return new Promise(function (resolve, reject) {
      var id = "sdk-" + (++sdkSequence);
      var timer = setTimeout(function () { sdkRequests.delete(id); reject(new Error("Preview host did not respond")); }, 15000);
      sdkRequests.set(id, { resolve: resolve, timer: timer });
      post({ type: "sdk-request", id: id, operation: operation, body: body });
    });
  };
  addEventListener("message", function (event) {
    if (event.source !== window.parent || event.data?.source !== "nx-studio") return;
    var data = event.data;
    if (data.type === "keyboard-key" && config.keyboard && keyboardInput && !keyboardInput.disabled && !keyboardInput.readOnly) {
      var element = keyboardInput, key = String(data.key), start = element.selectionStart, end = element.selectionEnd;
      if (typeof start !== "number") return;
      if (key === "Enter" && element.tagName === "INPUT") { element.form?.requestSubmit(); return; }
      if (key === "Backspace") { start = start === end ? Math.max(0,start - 1) : start; key = ""; }
      if (key === "Enter") key = "\n";
      element.setRangeText(key,start,end,"end"); element.dispatchEvent(new Event("input",{bubbles:true}));
      return;
    }
    if (data.type === "sdk-response" && sdkRequests.has(data.id)) {
      var pending = sdkRequests.get(data.id); sdkRequests.delete(data.id); clearTimeout(pending.timer); pending.resolve(data);
    }
    if (data.type === "sdk-control" && window.neyviaApp?.describe().actions.includes(data.action)) {
      var before = window.neyviaApp.state();
      var button = Array.from(document.querySelectorAll("button[data-action]")).find(function (node) { return node.dataset.action === data.action; });
      if (!button) return;
      button.click();
      var attempts = 0;
      var observeControl = function () {
        var after = window.neyviaApp.state();
        if (after.revision === before.revision && ++attempts < 100) return setTimeout(observeControl, 50);
        post({ type: "sdk-control-result", id: data.id, before: before, after: after,
          instance: window.neyviaApp.describe().instance, text: document.body.innerText });
      };
      setTimeout(observeControl, 50);
    }
  });

  // --- phone identity -------------------------------------------------------
  var define = function (target, key, value) {
    try { Object.defineProperty(target, key, { get: function () { return value; }, configurable: true }); } catch (error) { /* frozen */ }
  };
  if (config.ua) {
    define(navigator, "userAgent", config.ua);
    define(navigator, "platform", desktop ? "MacIntel" : config.platform === "ipados" ? "iPad" : config.platform === "android" ? "Linux armv8l" : "iPhone");
    define(navigator, "vendor", config.platform === "android" ? "Google Inc." : "Apple Computer, Inc.");
  }
  define(navigator, "maxTouchPoints", desktop ? 0 : 5);
  if (!desktop && !("ontouchstart" in window)) window.ontouchstart = null;
  var nativeMatch = window.matchMedia ? window.matchMedia.bind(window) : null;
  if (nativeMatch) {
    window.matchMedia = function (query) {
      var text = String(query);
      var forced = null;
      if (/\(\s*(any-)?pointer\s*:\s*coarse\s*\)/.test(text) || /\(\s*(any-)?hover\s*:\s*none\s*\)/.test(text)) forced = !desktop;
      if (/\(\s*(any-)?pointer\s*:\s*fine\s*\)/.test(text) || /\(\s*(any-)?hover\s*:\s*hover\s*\)/.test(text)) forced = desktop;
      if (/\(\s*prefers-color-scheme\s*:\s*dark\s*\)/.test(text)) forced = Boolean(config.dark);
      if (/\(\s*prefers-color-scheme\s*:\s*light\s*\)/.test(text)) forced = !config.dark;
      var real = nativeMatch(query);
      if (forced === null) return real;
      return { matches: forced, media: real.media, onchange: null,
        addListener: function () {}, removeListener: function () {},
        addEventListener: function () {}, removeEventListener: function () {}, dispatchEvent: function () { return false; } };
    };
  }

  // --- storage (an opaque-origin page has none; keep it per app in Neyvia) ---
  var makeStorage = function (seed, persist) {
    var data = Object.assign({}, seed || {});
    var timer = 0;
    var flush = function () {
      if (!persist) return;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fetch(base + "__nx/storage", { method: "POST", headers: { "Content-Type": "text/plain" }, body: JSON.stringify(data) }).catch(function () {});
      }, 250);
    };
    var api = {
      getItem: function (key) { key = String(key); return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
      setItem: function (key, value) { data[String(key)] = String(value); flush(); },
      removeItem: function (key) { delete data[String(key)]; flush(); },
      clear: function () { data = {}; flush(); },
      key: function (index) { return Object.keys(data)[index] || null; },
    };
    Object.defineProperty(api, "length", { get: function () { return Object.keys(data).length; } });
    return api;
  };
  var storageWorks = function (name) {
    try { var store = window[name]; store.setItem("__nx", "1"); store.removeItem("__nx"); return true; } catch (error) { return false; }
  };
  if (!storageWorks("localStorage")) define(window, "localStorage", makeStorage(config.storage, true));
  if (!storageWorks("sessionStorage")) define(window, "sessionStorage", makeStorage({}, false));

  // --- look: no scrollbars, a fingertip instead of a cursor ------------------
  var finger = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='28' height='28'%3E%3Ccircle cx='14' cy='14' r='11' fill='rgba(120,120,120,.28)' stroke='rgba(255,255,255,.85)' stroke-width='2'/%3E%3C/svg%3E\") 14 14, pointer";
  var style = document.createElement("style");
  style.id = "nx-mobile-look";
  style.textContent = "html{scrollbar-width:none;-webkit-text-size-adjust:100%}::-webkit-scrollbar{display:none}"
    + (desktop ? "" : "html,html *{cursor:" + finger + "!important}") + "html.nx-dragging,html.nx-dragging *{user-select:none!important;-webkit-user-select:none!important}";
  (document.head || document.documentElement).appendChild(style);

  // --- safe areas, updated live when Neyvia rotates the phone ---------------
  var setSafe = function (safe) {
    var element = document.getElementById("nx-mobile-safe");
    if (!element || !safe) return;
    element.textContent = ":root{" + ["top", "right", "bottom", "left"].map(function (side) {
      return "--nx-safe-area-inset-" + side + ":" + (Number(safe[side]) || 0) + "px;";
    }).join("") + "}";
  };

  // --- touch from the mouse --------------------------------------------------
  var drag = null;
  var touchOf = function (event, target) {
    return new Touch({ identifier: 1, target: target, clientX: event.clientX, clientY: event.clientY, pageX: event.pageX, pageY: event.pageY,
      screenX: event.screenX, screenY: event.screenY, radiusX: 11, radiusY: 11, force: 1 });
  };
  var fire = function (type, event, target, ended) {
    var touch = touchOf(event, target);
    var list = ended ? [] : [touch];
    var touchEvent = new TouchEvent(type, { bubbles: true, cancelable: true, composed: true, touches: list, targetTouches: list, changedTouches: [touch] });
    return target.dispatchEvent(touchEvent); // false: the app called preventDefault
  };
  var scroller = function (element) {
    for (var node = element; node && node !== document.documentElement; node = node.parentElement) {
      var css = getComputedStyle(node);
      if (/(auto|scroll)/.test(css.overflowY + css.overflowX) && (node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1)) return node;
    }
    return document.scrollingElement || document.documentElement;
  };
  var gliding = 0;
  var glide = function (element, vx, vy) {
    var run = ++gliding;
    var step = function () {
      if (run !== gliding || drag || (Math.abs(vx) < 0.02 && Math.abs(vy) < 0.02)) return;
      element.scrollBy(-vx * 16, -vy * 16);
      vx *= 0.94; vy *= 0.94;
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  if (!desktop && typeof Touch === "function" && typeof TouchEvent === "function") {
    window.addEventListener("mousedown", function (event) {
      if (event.button !== 0) return;
      var target = event.target;
      var allowed = fire("touchstart", event, target, false);
      drag = { target: target, x: event.clientX, y: event.clientY, lastX: event.clientX, lastY: event.clientY, t: performance.now(),
        vx: 0, vy: 0, moved: false, blocked: !allowed, scroll: scroller(target) };
    }, true);
    window.addEventListener("mousemove", function (event) {
      if (!drag) return;
      var allowed = fire("touchmove", event, drag.target, false);
      if (!allowed) drag.blocked = true;
      var dx = event.clientX - drag.lastX, dy = event.clientY - drag.lastY;
      var now = performance.now(), dt = Math.max(1, now - drag.t);
      if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 8) {
        drag.moved = true;
        document.documentElement.classList.add("nx-dragging");
        var selection = window.getSelection && window.getSelection();
        if (selection) selection.removeAllRanges();
      }
      if (drag.moved && !drag.blocked) drag.scroll.scrollBy(-dx, -dy);
      drag.vx = dx / dt; drag.vy = dy / dt;
      drag.lastX = event.clientX; drag.lastY = event.clientY; drag.t = now;
    }, true);
    window.addEventListener("mouseup", function (event) {
      if (!drag) return;
      fire("touchend", event, drag.target, true);
      var done = drag;
      drag = null;
      document.documentElement.classList.remove("nx-dragging");
      if (done.moved) {
        // A drag is a swipe, not a tap: swallow the click it would make.
        var swallow = function (click) { click.stopPropagation(); click.preventDefault(); };
        window.addEventListener("click", swallow, true);
        setTimeout(function () { window.removeEventListener("click", swallow, true); }, 0); // the click comes right after mouseup
        if (!done.blocked && performance.now() - done.t < 80) glide(done.scroll, done.vx, done.vy);
      }
    }, true);
  }

  // --- hot reload, keeping the scroll position ------------------------------
  var known = null;
  var SCROLL = "nx-mobile-scroll:";
  try {
    if (window.name.indexOf(SCROLL) === 0) {
      var saved = JSON.parse(window.name.slice(SCROLL.length));
      window.name = "";
      if (saved.path === location.pathname) addEventListener("load", function () { scrollTo(saved.x, saved.y); });
    }
  } catch (error) { window.name = ""; }
  var reload = function () {
    try { window.name = SCROLL + JSON.stringify({ path: location.pathname, x: scrollX, y: scrollY }); } catch (error) { /* ignore */ }
    location.reload();
  };
  var poll = function () {
    if (document.hidden) return;
    fetch(base + "__nx/version", { cache: "no-store" }).then(function (response) { return response.json(); }).then(function (version) {
      if (known && version.other !== known.other) { post({ type: "reloaded", what: "page" }); reload(); return; }
      if (known && version.css !== known.css) {
        document.querySelectorAll("link[rel~=stylesheet]").forEach(function (link) {
          var url = new URL(link.href, location.href);
          url.searchParams.set("nxv", version.css);
          link.href = url.href;
        });
        post({ type: "reloaded", what: "styles" });
      }
      known = version;
    }).catch(function () {});
  };
  setInterval(poll, 700);
  poll();

  // --- tell Neyvia what the app looks like ----------------------------------
  var describe = function () {
    var dark = Boolean(config.dark);
    var theme = "";
    document.querySelectorAll("meta[name=theme-color]").forEach(function (meta) {
      if (!theme && (!meta.media || window.matchMedia(meta.media).matches)) theme = meta.content;
    });
    var viewport = document.querySelector("meta[name=viewport]");
    post({ type: "ready", title: document.title, themeColor: theme, dark: dark,
      background: document.body ? getComputedStyle(document.body).backgroundColor : "",
      cover: Boolean(viewport && /viewport-fit\s*=\s*cover/.test(viewport.content)), path: location.pathname,
      documentText: document.body ? document.body.innerText.slice(0, 4096) : "",
      sdkInstance: window.neyviaApp && window.neyviaApp.describe ? window.neyviaApp.describe().instance : null });
  };
  addEventListener("load", describe);
  // Async SDK setup can finish after load. Publish its actual identity then.
  addEventListener("neyvia-app-ready", describe);
  addEventListener("error", function (event) { post({ type: "error", message: String(event.message || "Script error"), where: event.filename ? event.filename.split("/").pop() + ":" + event.lineno : "" }); });
  addEventListener("unhandledrejection", function (event) { post({ type: "error", message: String((event.reason && event.reason.message) || event.reason || "Unhandled promise") }); });
  addEventListener("message", function (event) {
    if (event.source !== window.parent || !event.data || event.data.source !== "nx-studio") return;
    if (event.data.type === "safe") setSafe(event.data.safe);
    if (event.data.type === "reload") reload();
  });
})();
