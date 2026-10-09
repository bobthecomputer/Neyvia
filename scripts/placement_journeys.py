"""The shot list for scripts/placement_shots.py: each app through every placement, with checks.

For every app: open it from the launcher (it lands beside the chat), then use the window's own
placement buttons to move it to the side panel and full screen, leave full screen with Esc,
collapse it to a bubble, peek it with Enter on the bubble, and put it back with R. Before the first
move each window is marked (a property on its body element and on its first work text field, with that field's value,
and a property on the window object of its first same-origin iframe); every later step checks the
marks are still there, which is only true when the app was never remounted or reloaded.
"""
from __future__ import annotations

import time

MARK = """id => {
  const frame = document.querySelector(`[data-window="${CSS.escape(id)}"]`);
  const body = frame.querySelector('.nx-stage-body');
  body.__placementMark = id;
  // A text field that holds work (an editor, a name, a prompt), never a search, filter or address box.
  // The field itself is marked and its current value recorded; nothing is typed, so no fixture
  // text reaches the app's state or the screenshots. A remount drops the mark and fails the check.
  const lookup = /search|filter|find|address|url|go to|jump/i;
  const field = [...frame.querySelectorAll('input[type=text], input:not([type]), textarea')].find(e => !e.disabled && !e.readOnly && e.offsetParent !== null
    && !e.closest('.xterm') && !lookup.test([e.placeholder, e.getAttribute('aria-label'), e.name, e.className].join(' ')));
  let typed = null;
  if (field) {
    field.__placementMark = id;
    field.dataset.placementField = '1';
    typed = field.value;
  }
  let iframe = null;
  const frameEl = frame.querySelector('iframe');
  if (frameEl) { try { frameEl.contentWindow.__placementMark = id; frameEl.__placementMark = id; iframe = frameEl.getAttribute('src'); } catch { iframe = 'cross-origin'; } }
  return { typed, iframe };
}"""

CHECK = """id => {
  const frame = document.querySelector(`[data-window="${CSS.escape(id)}"]`);
  if (!frame) return { present: false };
  const body = frame.querySelector('.nx-stage-body');
  const field = frame.querySelector('[data-placement-field]');
  const frameEl = frame.querySelector('iframe');
  let iframeKept = null;
  if (frameEl) { try { iframeKept = frameEl.contentWindow.__placementMark === id; } catch { iframeKept = 'cross-origin'; } }
  let iframeDocumentUrl = null, iframeTimeOrigin = null;
  try { iframeDocumentUrl = frameEl?.contentDocument?.URL; iframeTimeOrigin = frameEl?.contentWindow?.performance?.timeOrigin; } catch {}
  return { present: true, bodyKept: body?.__placementMark === id, typed: field ? field.value : null, iframeKept,
    fieldKept: field ? field.__placementMark === id : null, iframeElementKept: frameEl ? frameEl.__placementMark === id : null, iframeSrc: frameEl?.getAttribute('src'), iframeDocumentUrl, iframeTimeOrigin };
}"""


def check(receipt, label, ok, **extra):
    receipt["checks"].append({"label": label, "ok": bool(ok), **extra})
    print(("PASS " if ok else "FAIL ") + label)


def kept(rig, receipt, app, wid, step, marked):
    state = rig.js(CHECK, wid)
    # A same-origin iframe that was marked must still carry the mark: it was never reloaded.
    iframe_ok = state.get("iframeKept") is True if marked.get("iframe") not in (None, "cross-origin") else True
    ok = state.get("present") and state.get("bodyKept") and (marked["typed"] is None or (state["typed"] == marked["typed"] and state.get("fieldKept") is True)) and iframe_ok
    check(receipt, f"{app}: state kept after {step}", ok, state=state)


def mark_loaded_app(rig, wid):
    # Initial blank documents are navigation, not a placement reload. Every
    # subsequent loss of this mark still fails the existing state assertions.
    rig.wait("""id => {
      const frame = document.querySelector(`[data-window="${CSS.escape(id)}"]`);
      if (!frame || frame.querySelector('.nx-stage-loading')) return false;
      if (frame.querySelector('.nx-gd-scene') && !frame.querySelector('.nx-gd-frame')) return false;
      return [...frame.querySelectorAll('iframe')].every(el => {
        try {
          const doc = el.contentDocument;
          if (!doc || doc.readyState !== 'complete') return false;
          if (new URL(el.src, location.href).pathname === '/api/gamedev/browser'
              && !doc.getElementById('status-text')?.textContent?.startsWith('Connected')) return false;
          return !el.getAttribute('src') || el.src === 'about:blank' || doc.URL !== 'about:blank';
        } catch { return true; }
      });
    }""", 30, wid)
    return rig.js(MARK, wid)


def record(rig, receipt, app, placement, viewport, wid, note=""):
    name = f"{app}-{placement}" + ("-phone" if viewport == "phone" else "")
    rig.shot(name)
    receipt["shots"].append({"file": f"{name}.png", "app": app, "placement": placement, "viewport": viewport, "rect": rig.js("id => { const f = document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`); if (!f) return null; const r = f.getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), hidden: f.classList.contains('is-hidden') }; }", wid), "note": note})


ISOLATE = """on => { let s = document.getElementById('placement-isolate'); if (!on) { s?.remove(); return; }
  if (!s) { s = document.createElement('style'); s.id = 'placement-isolate'; document.head.append(s); }
  s.textContent = '.nx-os, .nx-strip, .nx-surface.is-main, .nx-surface.is-side { visibility: hidden !important; }'; }"""


def isolated(rig, receipt, app, placement, viewport, wid):
    """The same moment with the shell under the floating window hidden for this shot only:
    Obscura paints the text of lower layers through any floating layer (see probe-home.png)."""
    rig.js(ISOLATE, True)
    name = f"{app}-{placement}-isolated" + ("-phone" if viewport == "phone" else "")
    rig.shot(name)
    rig.js(ISOLATE, False)
    receipt["shots"].append({"file": f"{name}.png", "app": app, "placement": placement, "viewport": viewport, "rect": None,
                             "note": "Shell under the peek hidden for this shot only (engine paints lower text through floating layers)"})


def bubble_key(rig, wid, key):
    rig.js("""([id, key]) => { const b = document.querySelector(`[data-bubble-for="${CSS.escape(id)}"]`); b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })); }""", [wid, key])
    time.sleep(0.9)


def frame_key(rig, wid, key, alt=False, shift=False):
    rig.js("""([id, key, alt, shift]) => { const f = document.querySelector(`[data-window="${CSS.escape(id)}"] .nx-stage-head button`); f.focus(); f.dispatchEvent(new KeyboardEvent('keydown', { key, altKey: alt, shiftKey: shift, bubbles: true, cancelable: true })); }""", [wid, key, alt, shift])
    time.sleep(0.9)


def drag_title(rig, wid, to_x, to_y):
    """A real pointer gesture on the title bar (down, moves, up), the way a mouse drags it."""
    rig.js("""([id, tx, ty]) => {
      const head = document.querySelector(`[data-window="${CSS.escape(id)}"] .nx-stage-head`);
      const title = head.querySelector('.nx-stage-title');
      const r = title.getBoundingClientRect();
      const x0 = r.x + 20, y0 = r.y + r.height / 2;
      const fire = (type, x, y) => title.dispatchEvent(new PointerEvent(type, { pointerId: 7, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' ? 0 : 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
      fire('pointerdown', x0, y0);
      for (let i = 1; i <= 8; i += 1) fire('pointermove', x0 + (tx - x0) * i / 8, y0 + (ty - y0) * i / 8);
      window.__dragZones = document.querySelectorAll('.nx-dropzone').length;
      window.__dragOver = document.querySelector('.nx-dropzone.is-over span')?.textContent || null;
    }""", [wid, to_x, to_y])
    time.sleep(0.5)
    zones = rig.js("() => ({ zones: window.__dragZones, over: window.__dragOver, live: document.querySelectorAll('.nx-dropzone').length, liveOver: document.querySelector('.nx-dropzone.is-over span')?.textContent || null })")
    return zones


def drop_title(rig, wid, x, y):
    rig.js("""([id, x, y]) => { const t = document.querySelector(`[data-window="${CSS.escape(id)}"] .nx-stage-title`); t.dispatchEvent(new PointerEvent('pointerup', { pointerId: 7, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 0, clientX: x, clientY: y, bubbles: true, cancelable: true })); }""", [wid, x, y])
    time.sleep(1.0)


def desktop_app(rig, receipt, shots, app, query, title):
    shots.open_from_launcher(rig, query, title)
    wid = shots.window_id(rig, title)
    expected = 'pane:terminal:' if app == 'terminal' else 'pane:preview:' if app == 'cua-preview' else 'app:' + app
    check(receipt, f"{app}: launcher opens the requested surface", wid == expected, actual=wid, expected=expected)
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: opens beside the chat from the launcher", place and place["placement"] == "main" and place["w"] > 400, place=place)
    marked = mark_loaded_app(rig, wid)
    receipt.setdefault("marks", {})[app] = marked
    record(rig, receipt, app, "main", "desktop", wid)

    shots.press_place(rig, wid, "Side panel")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: side panel button", place["placement"] == "side" and place["x"] > 700 and 300 <= place["w"] <= 620, place=place)
    kept(rig, receipt, app, wid, "moving to the side", marked)
    record(rig, receipt, app, "side", "desktop", wid)

    # Narrow desktop widths cause the real side panel to float over the chat.
    rig.page.set_viewport_size({"width": 820, "height": 900})
    rig.wait("id => document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`)?.classList.contains('is-floating')", 15, wid)
    kept(rig, receipt, app, wid, "a floating side panel", marked)
    record(rig, receipt, app, "side-floating", "desktop", wid)
    rig.page.set_viewport_size(shots.DESKTOP)
    rig.wait("id => !document.querySelector(`[data-window=\"${CSS.escape(id)}\"]`)?.classList.contains('is-floating')", 15, wid)

    shots.press_place(rig, wid, "Full screen")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: full screen button", place["placement"] == "full" and place["w"] == 1440 and place["h"] == 900, place=place)
    kept(rig, receipt, app, wid, "full screen", marked)
    record(rig, receipt, app, "full", "desktop", wid)

    frame_key(rig, wid, "Escape")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: Esc leaves full screen back to the side", place["placement"] == "side", place=place)

    shots.press_place(rig, wid, "Collapse to a bubble")
    place = shots.placement_of(rig, wid)
    bubble = rig.js("id => !!document.querySelector(`[data-bubble-for=\"${CSS.escape(id)}\"]`)", wid)
    check(receipt, f"{app}: collapses to a bubble (app hidden, still mounted)", place["placement"] == "bubble" and place["hidden"] and bubble, place=place)
    kept(rig, receipt, app, wid, "collapsing to a bubble", marked)
    record(rig, receipt, app, "bubble", "desktop", wid)

    bubble_key(rig, wid, "Enter")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: Enter on the bubble peeks the live app", place["placement"] == "bubble" and not place["hidden"], place=place)
    kept(rig, receipt, app, wid, "peeking from the bubble", marked)
    record(rig, receipt, app, "bubble-peek", "desktop", wid)
    isolated(rig, receipt, app, "bubble-peek", "desktop", wid)

    bubble_key(rig, wid, "r")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: R on the bubble restores it to the side", place["placement"] == "side" and not place["hidden"], place=place)
    frame_key(rig, wid, "Home", alt=True, shift=True)
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: Alt+Shift+Home puts it back beside the chat", place["placement"] == "main", place=place)
    kept(rig, receipt, app, wid, "the whole round trip", marked)
    return wid


def dock_elsewhere(rig, receipt, shots, app, query, title):
    """Drag the window by its title bar to the left side, then to full screen, then back: the user moving it."""
    shots.open_from_launcher(rig, query, title)
    wid = shots.window_id(rig, title)
    marked = rig.js(MARK, wid)
    zones = drag_title(rig, wid, 60, 450)
    check(receipt, f"{app}: dragging the title bar shows the drop zones", zones["live"] == 5 and zones["liveOver"] == "Left side", zones=zones)
    rig.shot(f"{app}-dragging")
    receipt["shots"].append({"file": f"{app}-dragging.png", "app": app, "placement": "dragging", "viewport": "desktop", "rect": None, "note": "Title bar dragged to the left edge: drop zones shown"})
    drop_title(rig, wid, 60, 450)
    place = shots.placement_of(rig, wid)
    order = rig.js("() => JSON.parse(localStorage.getItem('nx.os.layout') || '{}').order || null")
    check(receipt, f"{app}: dropped on the left side, the side panel region moved left of the conversation", place["placement"] == "side" and place["x"] < 700, place=place, order=order)
    kept(rig, receipt, app, wid, "a drag to the left side", marked)
    record(rig, receipt, app, "side-left", "desktop", wid, "Moved by dragging the title bar to the left edge")
    drag_title(rig, wid, 720, 40)
    drop_title(rig, wid, 720, 40)
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: dragged to the top band goes full screen", place["placement"] == "full", place=place)
    frame_key(rig, wid, "ArrowRight", alt=True, shift=True)
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app}: Alt+Shift+Right docks it in the right side panel", place["placement"] == "side" and place["x"] > 700, place=place)
    kept(rig, receipt, app, wid, "drag, full screen and keyboard docking", marked)
    shots.close_all(rig)


def phone_app(rig, receipt, shots, app, query, title):
    shots.open_from_launcher(rig, query, title)
    wid = shots.window_id(rig, title)
    expected = 'pane:terminal:' if app == 'terminal' else 'pane:preview:' if app == 'cua-preview' else 'app:' + app
    check(receipt, f"{app}: phone launcher opens the requested surface", wid == expected, actual=wid, expected=expected)
    marked = mark_loaded_app(rig, wid)
    record(rig, receipt, app, "main", "phone", wid)
    shots.press_place(rig, wid, "Full screen")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app} (phone): full screen fills the viewport", place['placement'] == 'full' and place['w'] == 390 and place['h'] == 844, place=place)
    kept(rig, receipt, app, wid, 'phone full screen', marked)
    record(rig, receipt, app, 'full', 'phone', wid)
    frame_key(rig, wid, 'Escape')
    check(receipt, f"{app} (phone): Esc restores the main placement", shots.placement_of(rig,wid)['placement'] == 'main')
    shots.press_place(rig, wid, "Split the screen")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app} (phone): splits the screen with the chat", place["placement"] == "side" and place["y"] > 300 and place["w"] == 390, place=place)
    kept(rig, receipt, app, wid, "phone split", marked)
    record(rig, receipt, app, "side", "phone", wid)
    shots.press_place(rig, wid, "Collapse to a bubble")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app} (phone): collapsed bubble keeps the hidden app", place['placement'] == 'bubble' and place['hidden'], place=place)
    kept(rig, receipt, app, wid, 'phone collapsed bubble', marked)
    record(rig, receipt, app, 'bubble', 'phone', wid)
    bubble_key(rig, wid, "Enter")
    place = shots.placement_of(rig, wid)
    check(receipt, f"{app} (phone): bubble peeks along the bottom", place["placement"] == "bubble" and not place["hidden"] and place["w"] == 374, place=place)
    kept(rig, receipt, app, wid, "phone bubble", marked)
    record(rig, receipt, app, "bubble-peek", "phone", wid)
    isolated(rig, receipt, app, "bubble-peek", "phone", wid)
    shots.close_all(rig)


def attempt(rig, receipt, label, journey):
    """Run one journey; if the page reloaded under it (Obscura sometimes navigates on first load), retry once."""
    for tries in (1, 2):
        try:
            journey()
            return
        except Exception as exc:
            if tries == 1 and "context was destroyed" in str(exc):
                receipt["errors"].append(f"{label}: page reloaded mid-journey, retried")
                time.sleep(3)
                rig.wait("() => !!document.querySelector('.nx-root')", 40)
                time.sleep(1.5)
                continue
            raise


def library_handoff(rig, receipt, shots, viewport):
    """Observe the real domain preparation; never send a chat or substitute a draft."""
    shots.open_from_launcher(rig, "Library", "Library")
    rig.js("""() => [...document.querySelectorAll('.neyvia-library-disclosure summary')]
      .find(e => e.textContent.trim() === 'Domain experiences').click()""")
    rig.js("""() => [...document.querySelectorAll('.neyvia-domain-list button')]
      .find(e => e.querySelector('strong')?.textContent === 'Writing and publishing').click()""")
    goal = "Preserve my Library handoff wording " + viewport
    rig.js("() => document.querySelector('.neyvia-domain-detail textarea').focus()")
    rig.js(shots.TYPE, goal)
    submitted = []
    def observe_request(request):
        if request.method == 'POST' and '/api/backend' in request.url:
            try:
                body = request.post_data_json
                if isinstance(body, dict):
                    submitted.append(body.get('command'))
            except Exception:
                pass
    rig.page.on('request', observe_request)
    try:
        rig.js("() => document.querySelector('.neyvia-domain-detail button').click()")
        rig.wait("""goal => !document.querySelector('[data-window="app:library"]')
          && [...document.querySelectorAll('.nx-composer textarea')].some(e => e.value.includes(goal))""", 60, goal)
        settings = rig.context.request.post(f'http://127.0.0.1:{shots.BACKEND}/api/backend',
            data={'command':'settings_get_command','payload':{}}, timeout=30000)
        value = settings.json()
        prefs = value.get('data', value)
        check(receipt, 'library: ' + viewport + ' chosen layout saved in canonical Settings',
              settings.status == 200 and value.get('ok') is not False and prefs.get('density') == 'calm', density=prefs.get('density'))
        state = rig.js("""() => ({density:document.querySelector('.nx-root')?.getAttribute('data-nx-density'),
          transparency:localStorage.getItem('nx.os.transparency'),
          draft:[...document.querySelectorAll('.nx-composer textarea')].map(e=>e.value).find(Boolean)})""")
        check(receipt, 'library: ' + viewport + ' prepared wording remains in the real composer',
              goal in (state.get('draft') or ''), state=state)
        check(receipt, 'library: ' + viewport + ' chosen layout applied to the shell',
              state.get('density') == 'calm' and state.get('transparency') == '"minimal"', state=state)
        # Domain context preparation and preference saving are the only expected
        # backend mutations here. Session creation or chat submission must fail.
        allowed = {'build_neyvia_ecosystem_context_pack_command', 'settings_get_command',
                   'settings_update_command', 'get_capability_ui_contract_command', 'search_capabilities_command'}
        check(receipt, 'library: ' + viewport + ' no chat was submitted',
              bool(submitted) and all(command in allowed for command in submitted), commands=submitted)
        rig.shot('library-prepared-' + viewport)
    finally:
        rig.page.remove_listener('request', observe_request)


def run_journeys(rig, receipt, args, shots):
    only = {name for name in args.only.split(",") if name}
    apps = [entry for entry in shots.APPS if not only or entry[0] in only]
    if not args.phone_only:
        for app, query, title in apps:
            try:
                attempt(rig, receipt, app, lambda: desktop_app(rig, receipt, shots, app, query, title))
            except Exception as exc:
                check(receipt, f"{app}: desktop journey ran", False, error=f"{type(exc).__name__}: {exc}")
                rig.shot(f"{app}-failure")
            shots.close_all(rig)
        if not only or "3d-studio" in only:
            dock_elsewhere(rig, receipt, shots, "3d-studio", "3D Studio", "3D Studio")
        if getattr(args, 'library_handoff', False):
            library_handoff(rig, receipt, shots, 'desktop')
    rig.session(shots.PHONE)
    for app, query, title in apps:
        try:
            attempt(rig, receipt, app, lambda: phone_app(rig, receipt, shots, app, query, title))
        except Exception as exc:
            check(receipt, f"{app}: phone journey ran", False, error=f"{type(exc).__name__}: {exc}")
            rig.shot(f"{app}-phone-failure")
            shots.close_all(rig)
    if getattr(args, 'library_handoff', False):
        library_handoff(rig, receipt, shots, 'phone')
