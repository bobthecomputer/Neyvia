"""Real mounted actions for the layout, setup and launcher proof chapters.

This is a witness, not an alternative model runner. It drives the candidate's
own headless page, reads real product owners and independently checks durable
files. Unreachable exported helpers remain unproved. No inference is started.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]


def apply(bindings):
    overlay = json.loads((ROOT / 'config/inception_c8e_ui_effects.json').read_text(encoding='utf-8'))['bindings']
    result = copy.deepcopy(bindings)
    for identity, values in overlay.items():
        result[identity].update(values)
        result[identity]['c8eEffect']['renderedWitness'] = 'c8e-ui-' + values['c8eUiEffect']
    return result


def before_manual(worker, binding, inputs, root):
    if binding.get('c8eUiEffect'):
        worker.c8e_ui_effect = {'startedAt': time.time(), 'group': binding['c8eUiEffect']}
    return getattr(worker, 'c8e_ui_effect', None)


def _check(identity, passed, observed):
    return {'id': 'c8e.ui.' + identity, 'passed': bool(passed), 'fresh': True,
            'boundary': 'rendered-user-action', 'observed': observed}


def _contract(identity, checks, applicability):
    return {'id': identity, 'passed': bool(checks) and all(c['passed'] for c in checks),
            'fresh': True, 'boundary': 'rendered-user-action',
            'observed': {'applicability': applicability, 'actions': checks}}


def _skip_setup(worker):
    # First-run state arrives asynchronously after the shell is already mounted.
    button = worker.page.get_by_role('button', name='Skip setup', exact=True)
    try:
        button.wait_for(state='visible', timeout=6000)
        button.click()
        worker.page.locator('.nx-onb-scrim').wait_for(state='hidden', timeout=15000)
    except Exception:
        if worker.page.locator('.nx-onb-scrim').count():
            raise


def _home(worker):
    _skip_setup(worker)
    if worker.page.locator('.nx-arrange-bar').count():
        worker.page.locator('.nx-arrange-bar').get_by_role('button',name='Done',exact=True).click()
        worker.page.locator('.nx-arrange-bar').wait_for(state='hidden',timeout=10000)
    # "Go home" is intentionally stage.close and returns to the current chat.
    # New chat is the actual control that opens the home/widget surface.
    worker.page.get_by_role('button',name='New chat',exact=True).click()
    worker.page.locator('.nx-new').wait_for(timeout=15000)


def _search(worker, query):
    if not worker.page.locator('.nx-launcher').count():
        worker.page.keyboard.press('Control+Space')
    search = worker.page.locator('.nx-launcher').get_by_role('combobox', name='Search', exact=True)
    search.fill(query)
    worker.page.wait_for_timeout(150)
    return worker.page.locator('#nx-launch-results [role="option"]')


def _fresh_summary(worker, conversation_id):
    # Connected list snapshots are cached; the durable newly created identity
    # must actually appear before it is used as a UI navigation prerequisite.
    deadline = time.monotonic() + 20
    samples = []
    while time.monotonic() < deadline:
        listed = worker.tool('backend:connected_sessions_list_command',
                             {'app':'neyvia','limit':100,'includeHarness':False})
        matched = [row for row in listed['sessions'] if row['id'].endswith(':'+conversation_id)]
        samples.append({'count':len(listed['sessions']),'matches':len(matched)})
        if len(matched) == 1:
            return matched[0]
        worker.page.wait_for_timeout(250)
    raise ValueError('New real transcript never entered the authoritative connected list: '+json.dumps(samples))


def _launcher(worker, root):
    _home(worker)
    name = 'C8e launcher project'
    project = Path(root) / 'c8' / 'launcher-project'
    from c8e_prerequisites import approve_request
    project_args = {'name': name, 'path': str(project), 'template': 'empty'}
    approve_request(worker,'neyvia.project.create',project_args)
    worker.tool('neyvia.project.create',project_args)
    created = worker.tool('backend:create_neyvia_conversation_command',
                          {'kind': 'chat', 'title': 'C8e launcher conversation', 'titleMode': 'off',
                           'metadata': {'workspacePath': str(project), 'source': 'C8e-user-fixture'}})
    cid = created['conversationId']
    worker.tool('backend:append_neyvia_conversation_turn_command',
                {'conversationId': cid, 'role': 'user', 'content': 'An actual saved conversation for launcher navigation.',
                 'source': 'C8e-user-fixture'})
    identity = _fresh_summary(worker,cid)['id']
    worker.tool('neyvia.session.move', {'id': identity, 'project': str(project)})
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-root').wait_for(timeout=15000)
    _skip_setup(worker)
    checks, contracts = [], []
    parse_checks = []
    aliases = [('codex', 'Codex', 'codex'), ('claude code', 'Claude Code', 'claude-code'),
               ('claude', 'Claude Code', 'claude-code'), ('neyvia', 'Neyvia', 'neyvia'),
               ('opencode', 'OpenCode', 'opencode'), ('open code', 'OpenCode', 'opencode')]
    for alias, label, app in aliases:
        options = _search(worker, 'new ' + alias + ' conversation in ' + name)
        first = options.first
        expected = 'New ' + label + ' chat in ' + name
        first.get_by_text(expected, exact=True).wait_for(timeout=10000)
        ranked = first.get_attribute('aria-disabled') != 'true'
        first.click()
        worker.page.locator('.nx-new').wait_for(timeout=10000)
        observed = worker.page.evaluate("""() => ({app:JSON.parse(localStorage.getItem('nx.new.app')),
          folder:JSON.parse(localStorage.getItem('nx.new.folder')), url:location.href,
          placeholder:document.querySelector('.nx-new textarea')?.placeholder})""")
        parse_checks.append(_check('launcher-phrase-' + alias.replace(' ', '-'),
                                    ranked and observed['app'] == app and observed['folder']['path'] == str(project)
                                    and observed['placeholder'] == 'Ask ' + label + ' to…',
                                    {'query': alias, 'expectedTitle': expected, 'selected': observed}))
    # Unknown agent phrases must not create a new-chat action or alter the composer.
    options = _search(worker, 'new nonexistent-harness chat in ' + name)
    titles = options.locator('.nx-result-title').all_text_contents()
    parse_checks.append(_check('launcher-unknown-harness', not any(t.startswith('New ') and t.endswith(' chat in ' + name) for t in titles), {'titles': titles}))
    # An unmatched project remains an explicit no-match composer action.
    options = _search(worker, 'new neyvia session in zzz-unmatched-c8e-project')
    unknown = options.first.inner_text()
    parse_checks.append(_check('launcher-unmatched-project', 'No project matches “zzz-unmatched-c8e-project”' in unknown
                              and 'New Neyvia chat in' not in unknown, {'first': unknown}))
    checks.extend(parse_checks)
    contracts.append(_contract('proofs-e.shell.parseNewChat', parse_checks,
                               'All shipped aliases, conversation/session grammar, exact registered folder, unknown harness and unmatched project; no message submitted'))
    rank_checks = list(parse_checks)
    # Search a saved chat and use its actual selection to navigate.
    options = _search(worker, 'C8e launcher conversation')
    chat = options.filter(has=worker.page.get_by_text('C8e launcher conversation', exact=True))
    chat.wait_for(timeout=10000)
    chat.click()
    worker.page.wait_for_function('id => new URL(location.href).searchParams.get("chat") === id', arg=identity, timeout=15000)
    rank_checks.append(_check('launcher-real-chat-navigation', True, {'id': identity, 'url': worker.page.url}))
    # Ready/coming comes from the actual registry, never the plan fallback.
    registry = worker.page.evaluate("""async () => { const r=await fetch('/api/apps');
      return {status:r.status,body:await r.json()}; }""")
    suites = registry['body'].get('data', registry['body'])
    suites = suites if isinstance(suites, list) else suites.get('suites', [])
    for suite in suites:
        for app in suite.get('apps', []):
            options = _search(worker, app['name'])
            exact = options.filter(has=worker.page.locator('.nx-result-title').get_by_text(app['name'], exact=True))
            if exact.count() != 1:
                rank_checks.append(_check('launcher-app-' + app['id'], False, {'app': app, 'count': exact.count()}))
                continue
            disabled = exact.get_attribute('aria-disabled') == 'true'
            rank_checks.append(_check('launcher-app-' + app['id'], disabled == (app.get('status') != 'ready'),
                                      {'app': app, 'disabled': disabled, 'rankedTitles': options.locator('.nx-result-title').all_text_contents()}))
    options = _search(worker, 'theme')
    before = options.first.get_attribute('id')
    worker.page.locator('.nx-launcher').get_by_role('combobox').press('ArrowDown')
    selected = worker.page.locator('#nx-launch-results [aria-selected="true"]').get_attribute('id')
    rank_checks.append(_check('launcher-keyboard-selection', selected != before and options.count() <= 24,
                              {'before': before, 'after': selected, 'count': options.count()}))
    _search(worker, '')
    rank_checks.append(_check('launcher-empty-query', worker.page.locator('#nx-launch-results').count() == 0,
                              {'homeVisible': worker.page.locator('.nx-launcher-home').is_visible()}))
    worker.page.keyboard.press('Escape')
    checks.extend(c for c in rank_checks if c not in parse_checks)
    contracts.append(_contract('proofs-e.shell.searchLauncher', rank_checks,
                               'Real source apps ready/coming, ranked new-chat action, saved conversation navigation, folder lookup, empty input, keyboard cursor and 24-result bound'))
    return checks, {'contractEffects': contracts, 'rendered': {'witness': 'c8e-ui-launcher',
                    'artifact': worker.screenshot('effect-launcher'), 'url': worker.page.url}}


def _read_layout(worker):
    return worker.page.evaluate("() => JSON.parse(localStorage.getItem('nx.os.layout'))")


def _arrange(worker):
    _skip_setup(worker)
    if not worker.page.locator('.nx-arrange-bar').count():
        worker.page.locator('.nx-strip').get_by_role('button', name='Arrange', exact=True).click()
    worker.page.locator('.nx-arrange-bar').wait_for(timeout=10000)


def _width_controls(worker, identity, label, minimum, maximum, side):
    """Check the same shipped splitter path for each actual mounted region."""
    handle = worker.page.get_by_role('separator',name='Resize '+label,exact=True)
    handle.wait_for(state='visible',timeout=10000)
    grow_key = 'ArrowRight' if side == 'start' else 'ArrowLeft'
    shrink_key = 'ArrowLeft' if side == 'start' else 'ArrowRight'
    keys, pointers = [], []
    for key,wanted in [('Home',minimum),(grow_key,minimum+16),('Shift+'+grow_key,minimum+64),
                       (shrink_key,minimum+48),('Shift+'+shrink_key,minimum),
                       ('End',maximum),('Home',minimum),('a',minimum)]:
        before = _read_layout(worker)
        handle.focus(); handle.press(key)
        after = _read_layout(worker)
        preserved = copy.deepcopy(before); preserved['widths'][identity] = wanted
        keys.append(_check('layout-'+identity+'-key-'+key,after == preserved,
            {'side':side,'key':key,'before':before,'after':after,'expected':wanted,
             'ariaWidth':handle.get_attribute('aria-valuenow')}))
    for goal,delta in [(maximum,1000),(minimum,-1000)]:
        before = _read_layout(worker)
        box = handle.bounding_box()
        # The Arrange toolbar overlaps the top of some splitters. Use the
        # exposed body of the same actual control, below its toolbar.
        x,y = box['x']+box['width']/2,box['y']+min(250,box['height']/2)
        direction = 1 if side == 'start' else -1
        worker.page.mouse.move(x,y); worker.page.mouse.down()
        worker.page.mouse.move(x+direction*delta,y,steps=10)
        during = _read_layout(worker)
        worker.page.mouse.up()
        after = _read_layout(worker)
        preserved = copy.deepcopy(before); preserved['widths'][identity] = goal
        pointers.append(_check('layout-'+identity+'-pointer-clamp-'+str(goal),
            during == before and after == preserved,
            {'before':before,'during':during,'after':after,'expected':goal}))
    before = _read_layout(worker)
    handle.dblclick()
    after = _read_layout(worker)
    preserved = copy.deepcopy(before); preserved['widths'].pop(identity,None)
    pointers.append(_check('layout-'+identity+'-reset-width',after == preserved,
                          {'before':before,'after':after}))
    return keys,pointers


def _drag_widget(worker, grip, target):
    """Activate dnd-kit's pointer sensor and move the widget centre to target."""
    grip.scroll_into_view_if_needed(); target.scroll_into_view_if_needed()
    handle = grip.bounding_box()
    source = grip.locator('xpath=ancestor::section').bounding_box()
    destination = target.bounding_box()
    x,y = handle['x']+handle['width']/2,handle['y']+handle['height']/2
    dx = destination['x']+destination['width']/2-(source['x']+source['width']/2-x)
    dy = destination['y']+destination['height']/2-(source['y']+source['height']/2-y)
    worker.page.mouse.move(x,y); worker.page.mouse.down()
    worker.page.mouse.move(x+8,y+8,steps=4)
    worker.page.locator('.nx-widget.is-dragging').wait_for(timeout=5000)
    worker.page.mouse.move(dx,dy,steps=20)
    worker.page.wait_for_timeout(100)
    active = worker.page.locator('.nx-widget.is-dragging').count()
    worker.page.mouse.up()
    worker.page.locator('.nx-widget.is-dragging').wait_for(state='hidden',timeout=5000)
    worker.page.wait_for_timeout(250)
    return {'grip':handle,'source':source,'target':destination,'pointerTarget':[dx,dy],'activeDraggingCount':active}


def _region_keyboard_drag(worker, label, steps, expected_order):
    """Advance only after the shipped DnD sensor reports each real phase."""
    chip = worker.page.locator('.nx-arrange-map').get_by_role('button', name=label, exact=True)
    chip.focus()
    chip.press('Space')
    worker.page.locator('.nx-arrange-chip.is-dragging').wait_for(state='visible', timeout=10000)
    # onDragOver can replace the pickup live announcement in the same render.
    # The mounted active chip is the durable pickup witness.
    for key, target in steps:
        chip.press(key)
        worker.page.get_by_text(f'{label} is over {target}.', exact=True).wait_for(state='attached', timeout=10000)
    chip.press('Space')
    worker.page.get_by_text(f'{label} dropped at {steps[-1][1]}.', exact=True).wait_for(state='attached', timeout=10000)
    worker.page.locator('.nx-arrange-chip.is-dragging').wait_for(state='hidden', timeout=10000)
    worker.page.wait_for_function("order => JSON.stringify(JSON.parse(localStorage.getItem('nx.os.layout') || '{}').order) === JSON.stringify(order)",
                                  arg=expected_order, timeout=10000)


def _layout(worker, root):
    _home(worker)
    worker.page.set_viewport_size({'width': 1800, 'height': 1200})
    original = _read_layout(worker)
    original_widgets = worker.page.locator('.nx-widget').evaluate_all("items=>items.map(e=>({label:e.getAttribute('aria-label'),size:[...e.classList].find(c=>/^is-[sml]$/.test(c))}))")
    checks, contracts = [], []
    # Malformed persisted user preferences are legitimate inputs; rendering and
    # an actual UI edit must normalize them before the preference is saved.
    junk = {'order': ['main', 'sidebar', 'sidebar', 'unknown'], 'widths': {'sidebar': 9000, 'canopy': -2, 'unknown': 123},
            'widgets': [{'id': 'usage', 'size': 'invalid'}, {'id': 'usage', 'size': 'm'}, {'id': 'unknown', 'size': 's'}],
            'canopy': 'bad', 'dock': 'bad', 'sidebarHidden': 'yes'}
    worker.page.evaluate("value => localStorage.setItem('nx.os.layout', JSON.stringify(value))", junk)
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-root').wait_for(timeout=15000)
    _arrange(worker)
    worker.page.locator('.nx-arrange-bar [aria-label="Canopy"] button').filter(has_text=re.compile('^With Grove$')).click()
    normalized = _read_layout(worker)
    expected = {'order': ['main', 'sidebar', 'panel', 'canopy'], 'widths': {'sidebar': 440, 'canopy': 240},
                'widgets': [{'id': 'usage', 'size': 's'}], 'canopy': 'auto', 'dock': 'right', 'sidebarHidden': False}
    c = _check('layout-normalized-mounted-preferences', normalized == expected and worker.page.locator('.nx-widget[aria-label="Usage"]').count() == 1,
               {'input': junk, 'saved': normalized, 'expected': expected})
    checks.append(c)
    contracts.append(_contract('layout.normalizeLayout', [c], 'Malformed real browser preferences normalized during mounted boot and persisted by user Arrange'))
    worker.page.locator('.nx-arrange-bar').get_by_role('button', name='Reset', exact=True).click()
    baseline = _read_layout(worker)
    # Keyboard DnD is the real shipped RegionChip path.
    _region_keyboard_drag(worker, 'Chats', [('ArrowRight', 'Conversation')], ['main', 'sidebar', 'panel', 'canopy'])
    moved = _read_layout(worker)
    region = worker.page.locator('[data-region="sidebar"]')
    c = _check('layout-region-keyboard-drag', moved['order'] == ['main', 'sidebar', 'panel', 'canopy']
               and {k:v for k,v in moved.items() if k != 'order'} == {k:v for k,v in baseline.items() if k != 'order'},
               {'before': baseline, 'after': moved, 'renderedOrder': region.evaluate('e => e.style.order')})
    checks.append(c)
    contracts.append(_contract('layout.moveRegion', [c], 'Real keyboard DnD moves Chats after Conversation while preserving every other saved field'))
    side = region.get_attribute('data-side')
    c = _check('layout-region-side-after-reorder', side == 'end', {'order': moved['order'], 'side': side})
    checks.append(c)
    contracts.append(_contract('layout.sideOf', [c], 'Mounted sidebar side follows movement across the conversation'))
    # Two keyboard steps before dropping exercise onDragEnd's absolute-target
    # arm, separately from the adjacent nudge path above. Restore through the
    # same real control so all later width expectations keep their arrangement.
    before_absolute = _read_layout(worker)
    _region_keyboard_drag(worker, 'Conversation', [('ArrowRight', 'Chats'), ('ArrowRight', 'Side panel')],
                          ['sidebar', 'panel', 'main', 'canopy'])
    absolute = _read_layout(worker)
    absolute_check = _check('layout-region-absolute-target-keyboard-drag',
        absolute['order'] == ['sidebar','panel','main','canopy']
        and {k:v for k,v in absolute.items() if k != 'order'} == {k:v for k,v in before_absolute.items() if k != 'order'},
        {'before':before_absolute,'after':absolute})
    start_side = _check('layout-region-side-after-absolute-reorder',
        worker.page.locator('[data-region="sidebar"]').get_attribute('data-side') == 'start',
        {'order':absolute['order'],'side':worker.page.locator('[data-region="sidebar"]').get_attribute('data-side')})
    _region_keyboard_drag(worker, 'Conversation', [('ArrowLeft', 'Side panel'), ('ArrowLeft', 'Chats')], before_absolute['order'])
    restored_absolute = _read_layout(worker)
    restore_check = _check('layout-region-absolute-target-keyboard-restore',restored_absolute == before_absolute
        and worker.page.locator('[data-region="sidebar"]').get_attribute('data-side') == 'end',
        {'expected':before_absolute,'restored':restored_absolute,
         'restoredSide':worker.page.locator('[data-region="sidebar"]').get_attribute('data-side')})
    checks.extend([absolute_check,start_side,restore_check])
    contracts = [x for x in contracts if x['id'] not in ['layout.moveRegion','layout.sideOf']]
    contracts.append(_contract('layout.moveRegion',[next(x for x in checks if x['id'] == 'c8e.ui.layout-region-keyboard-drag'),absolute_check,restore_check],
        'Actual adjacent nudge and separate two-step absolute-target mounted RegionChip DnD; each preserves every unrelated preference and exact reversal.'))
    contracts.append(_contract('layout.sideOf',[c,start_side,restore_check],
        'Actual sidebar side follows position both before and after Conversation, then restores after absolute user reorder.'))
    splitter = worker.page.get_by_role('separator', name='Resize Chats', exact=True)
    width_checks = []
    for key, wanted in [('Home', 220), ('ArrowRight', 220), ('ArrowLeft', 236), ('Shift+ArrowLeft', 284),
                        ('ArrowRight', 268), ('Shift+ArrowRight', 220), ('End', 440), ('ArrowLeft', 440),
                        ('Home', 220), ('UnknownKey', 220)]:
        # Sidebar is at the end: physical Left grows, Right shrinks.
        old = _read_layout(worker)
        splitter.focus()
        splitter.press('a' if key == 'UnknownKey' else key)
        current = _read_layout(worker)
        width_checks.append(_check('layout-width-' + key, current['widths'].get('sidebar') == wanted
                                  and {k:v for k,v in current['widths'].items() if k != 'sidebar'} == {k:v for k,v in old['widths'].items() if k != 'sidebar'},
                                  {'key': key, 'before': old, 'after': current, 'ariaWidth': splitter.get_attribute('aria-valuenow')}))
    checks.extend(width_checks)
    contracts.append(_contract('layout.keyWidth', width_checks, 'Mounted splitter Home/End, normal and shifted physical arrows, clamps and unknown key no effect'))
    # Actual pointer resize commits only on release; no desktop input is used.
    box = splitter.bounding_box()
    start = _read_layout(worker)
    start_x = box['x'] + box['width'] / 2
    worker.page.mouse.move(start_x, box['y'] + 10)
    worker.page.mouse.down()
    worker.page.mouse.move(start_x - 80, box['y'] + 10, steps=8)
    during = _read_layout(worker)
    worker.page.mouse.up()
    end = _read_layout(worker)
    c = _check('layout-pointer-release-commit', during == start and end['widths']['sidebar'] == 300
               and {k:v for k,v in end.items() if k != 'widths'} == {k:v for k,v in start.items() if k != 'widths'},
               {'before': start, 'during': during, 'after': end})
    checks.append(c)
    contracts.append(_contract('layout.setWidth', [c] + width_checks, 'Headless browser pointer resize keeps saved layout during drag and commits bounded target on release'))
    # Actual widget controls expose size/remove/add and the missing list.
    widget_checks = {}
    for title, identity in [('Continue', 'continue'), ('Needs you', 'needs'), ('Running', 'running'), ('Night Shift', 'nightshift'), ('Usage', 'usage'), ('Projects', 'projects')]:
        widget = worker.page.locator('.nx-widget').filter(has=worker.page.locator('h2').get_by_text(title, exact=True))
        if not widget.count():
            widget_checks.setdefault('cycleWidgetSize', []).append(_check('layout-size-cycle-'+identity,False,
                {'requiredWidget':identity,'renderedCount':0}))
            continue
        before = _read_layout(worker)
        sizes = {'continue':['m','l'], 'needs':['s','m','l'], 'running':['s','m','l'], 'nightshift':['s','m'], 'usage':['s','m'], 'projects':['s','m','l']}[identity]
        seen_sizes, valid_sizes = [], True
        prior_size = next(w['size'] for w in before['widgets'] if w['id'] == identity)
        for _ in sizes:
            widget.get_by_role('button', name=re.compile('Change size of ' + re.escape(title))).click()
            state = _read_layout(worker)
            current_size = next(w['size'] for w in state['widgets'] if w['id'] == identity)
            seen_sizes.append(current_size)
            valid_sizes = valid_sizes and current_size == sizes[(sizes.index(prior_size)+1) % len(sizes)] and widget.evaluate('(e,size)=>e.classList.contains("is-"+size)',current_size)
            prior_size = current_size
        after = _read_layout(worker)
        widget_checks.setdefault('cycleWidgetSize', []).append(_check('layout-size-cycle-' + identity, after == before and valid_sizes,
                         {'before': before, 'after': after, 'cycle': sizes,'seenRenderedSizes':seen_sizes}))
    widget = worker.page.locator('.nx-widget[aria-label="Usage"]')
    before = _read_layout(worker)
    widget.get_by_role('button', name='Remove Usage', exact=True).click()
    removed = _read_layout(worker)
    add = worker.page.locator('.nx-widget-add')
    hidden = add.locator('.nx-wline-title').all_text_contents()
    widget_checks['removeWidget'] = [_check('layout-widget-remove', removed['widgets'] == [w for w in before['widgets'] if w['id'] != 'usage']
                         and widget.count() == 0, {'before': before, 'after': removed})]
    widget_checks['hiddenWidgets'] = [_check('layout-exact-add-list', hidden == ['Usage'], {'hidden': hidden})]
    add.get_by_role('button', name='Usage', exact=True).click()
    added = _read_layout(worker)
    widget_checks['addWidget'] = [_check('layout-widget-add', added['widgets'] == removed['widgets'] + [{'id':'usage','size':'s'}]
                         and worker.page.locator('.nx-widget-add').count() == 0, {'after': added})]
    # Nonadjacent pointer movement exercises moveWidget itself; adjacent
    # movement separately exercises the nudge wrapper below.
    grip = worker.page.get_by_role('button', name='Move Usage', exact=True)
    before = _read_layout(worker)
    drag = _drag_widget(worker,grip,worker.page.locator('.nx-widget[aria-label="Continue"]'))
    after = _read_layout(worker)
    wanted_widgets = [before['widgets'][-1]] + before['widgets'][:-1]
    widget_checks['moveWidget'] = [_check('layout-widget-nonadjacent-drag', after['widgets'] == wanted_widgets
                          and sorted(after['widgets'],key=lambda w:w['id']) == sorted(before['widgets'],key=lambda w:w['id'])
                          and {k:v for k,v in after.items() if k != 'widgets'} == {k:v for k,v in before.items() if k != 'widgets'},
                          {'before': before, 'after': after,'actualDrag':drag})]
    for identity, cases in widget_checks.items():
        checks.extend(cases)
        contracts.append(_contract('layout.' + identity, cases, 'Actual mounted home widget controls and exact durable layout preservation'))
    # Responsive fitting includes the real conversation side panel, so the
    # last stage (floating it rather than squeezing the chat) is observed too.
    created = worker.tool('backend:create_neyvia_conversation_command',
                          {'kind':'chat','title':'C8e responsive layout conversation','titleMode':'off',
                           'metadata':{'workspacePath':str(Path(root)/'c8'),'source':'C8e-user-fixture'}})
    session = _fresh_summary(worker,created['conversationId'])
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-root').wait_for(timeout=15000)
    _skip_setup(worker)
    options = _search(worker,'C8e responsive layout conversation')
    options.filter(has=worker.page.get_by_text('C8e responsive layout conversation',exact=True)).click()
    _arrange(worker)
    worker.tool('neyvia.view.layout',{'level':'grove'})
    # Arrange's toolbar covers this thread's header. Finish arranging before
    # using Details, then reopen it to configure the visible panel's layout.
    worker.page.locator('.nx-arrange-bar').get_by_role('button',name='Done',exact=True).click()
    worker.page.locator('.nx-arrange-bar').wait_for(state='hidden',timeout=10000)
    worker.page.get_by_role('button',name='Details',exact=True).click()
    worker.page.locator('[data-region="panel"]').wait_for(timeout=15000)
    _arrange(worker)
    worker.page.locator('.nx-arrange-bar [aria-label="Canopy"] button').filter(has_text=re.compile('^Always$')).click()
    # Exercise every currently visible column, then reset their widths using
    # the real double-click gesture before observing responsive fitting.
    extra_key_checks, extra_pointer_checks = [], []
    for identity, label, minimum, maximum in [('panel','Side panel',300,600),('canopy','Canopy',240,440)]:
        region_side = worker.page.locator('[data-region="'+identity+'"]').get_attribute('data-side')
        keys,pointers = _width_controls(worker,identity,label,minimum,maximum,region_side)
        extra_key_checks.extend(keys); extra_pointer_checks.extend(pointers)
    checks.extend(extra_key_checks+extra_pointer_checks)
    saved = _read_layout(worker)
    frames = []
    for width in [1800, 1450, 1200, 1050, 800, 1800]:
        worker.page.set_viewport_size({'width':width,'height':1200})
        worker.page.wait_for_timeout(200)
        frames.append(worker.page.evaluate("""() => ({width:innerWidth,
          saved:JSON.parse(localStorage.getItem('nx.os.layout')),
          sidebar:document.querySelector('[data-region=sidebar]')?.getBoundingClientRect().width,
          main:document.querySelector('#nx-main')?.getBoundingClientRect().width,
          canopy:!!document.querySelector('[data-region=canopy]'),
          panel:!!document.querySelector('[data-region=panel]'),
          floatingPanel:!!document.querySelector('.nx-panel-overlay'),
          widths:document.querySelector('.nx-root')?.getAttribute('style'),
          sidebarWidth:parseInt(document.querySelector('.nx-root')?.style.getPropertyValue('--nx-sidebar-w')),
          panelWidth:parseInt(document.querySelector('.nx-root')?.style.getPropertyValue('--nx-panel-w')),
          canopyWidth:parseInt(document.querySelector('.nx-root')?.style.getPropertyValue('--nx-canopy-w'))})"""))
    c = _check('layout-responsive-fit-preserves-preferences', all(f['saved'] == saved for f in frames)
               and frames[0]['canopy'] and frames[1]['canopy'] and not frames[2]['canopy']
               and frames[-2]['floatingPanel'] and not frames[-2]['panel'] and frames[-1]['panel'] and frames[-1]['canopy']
               and all(f['main'] >= 440 for f in frames)
               and [frames[1]['sidebarWidth'],frames[1]['panelWidth'],frames[1]['canopyWidth']] == [237,321,251],
               {'frames': frames,'proportionalShrinkExpected':{'sidebar':237,'panel':321,'canopy':251}})
    checks.append(c)
    contracts.append(_contract('layout.fitLayout', [c], 'Real viewport resize shrinks regions, drops Canopy, keeps conversation minimum, floats actual conversation panel, restores everything on grow and preserves saved widths'))
    # The fourth region is the chat dock inside a staged app. Open actual
    # Notes through the launcher; the same saved conversation stays beside it.
    worker.page.locator('.nx-arrange-bar').get_by_role('button',name='Done',exact=True).click()
    worker.page.locator('.nx-arrange-bar').wait_for(state='hidden',timeout=10000)
    options = _search(worker,'Notes')
    options.filter(has=worker.page.get_by_text('Notes',exact=True)).click()
    worker.page.locator('.nx-stage[aria-label="Notes"]').wait_for(timeout=15000)
    dock_side = worker.page.locator('.nx-work').get_attribute('data-dock')
    dock_keys,dock_pointers = _width_controls(worker,'dock','Chat',300,680,'start' if dock_side == 'left' else 'end')
    checks.extend(dock_keys+dock_pointers)
    worker.page.get_by_role('button',name='Close Notes',exact=True).click()
    worker.page.locator('.nx-stage').wait_for(state='hidden',timeout=10000)
    restored = _check('layout-dock-stage-preserves-preferences',_read_layout(worker) == saved,
                      {'before':saved,'after':_read_layout(worker),'stageClosed':True})
    checks.append(restored); extra_key_checks.extend(dock_keys); extra_pointer_checks.extend(dock_pointers)
    contracts = [c for c in contracts if c['id'] not in ['layout.keyWidth','layout.setWidth']]
    contracts.append(_contract('layout.keyWidth',width_checks+extra_key_checks,
        'All four actual region splitters: Chats, Side panel, Canopy, and Chat dock beside staged Notes; Home/End, 16/48px physical arrows, unknown-key no change.'))
    contracts.append(_contract('layout.setWidth',[c for c in checks if c['id'] == 'c8e.ui.layout-pointer-release-commit']+extra_pointer_checks+[restored],
        'All four mounted region pointer paths; exact bounds, save-only-on-release, other-field preservation, actual double-click restoration and app-stage close.'))
    # Adjacent moves now call the existing nudge wrappers in the shipped DnD
    # handlers. The movement above is an adjacent real region move.
    region_nudge = next(c for c in checks if c['id'] == 'c8e.ui.layout-region-keyboard-drag')
    contracts.append(_contract('layout.nudgeRegion', [region_nudge], 'Adjacent mounted RegionChip DnD invokes checked nudgeRegion'))
    # The grid keyboard step may cross a row. A neighboring pointer drag
    # provides the exact adjacent move rather than assuming its target index.
    _home(worker)
    _arrange(worker)
    before = _read_layout(worker)
    widgets = before['widgets']
    titles = {'continue':'Continue','needs':'Needs you','running':'Running','nightshift':'Night Shift','projects':'Projects','usage':'Usage'}
    source = worker.page.get_by_role('button',name='Move ' + titles[widgets[-1]['id']],exact=True)
    target = worker.page.get_by_role('button',name='Move ' + titles[widgets[-2]['id']],exact=True)
    target_section = target.locator('xpath=ancestor::section')
    drag = _drag_widget(worker,source,target_section)
    after = _read_layout(worker)
    expected_widgets = widgets[:-2] + [widgets[-1], widgets[-2]]
    c = _check('layout-adjacent-widget-pointer-drag', after['widgets'] == expected_widgets
               and {k:v for k,v in before.items() if k != 'widgets'} == {k:v for k,v in after.items() if k != 'widgets'},
               {'before':before,'after':after,'expected':expected_widgets,'actualDrag':drag})
    checks.append(c)
    contracts.append(_contract('layout.nudgeWidget', [c], 'Adjacent mounted widget grip pointer DnD invokes checked nudgeWidget'))
    artifact = worker.screenshot('effect-layout')
    worker.page.evaluate("value => {if(value===null)localStorage.removeItem('nx.os.layout');else localStorage.setItem('nx.os.layout',JSON.stringify(value))}", original)
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-new').wait_for(timeout=15000)
    _skip_setup(worker)
    worker.page.locator('.nx-widget').last.wait_for(timeout=15000)
    restored_widgets = worker.page.locator('.nx-widget').evaluate_all("items=>items.map(e=>({label:e.getAttribute('aria-label'),size:[...e.classList].find(c=>/^is-[sml]$/.test(c))}))")
    checks.append(_check('layout-restored-preferences-survive-mounted-reload',_read_layout(worker) == original
        and restored_widgets == original_widgets,
        {'expectedPreferences':original,'actualPreferences':_read_layout(worker),
         'expectedMountedWidgets':original_widgets,'actualMountedWidgets':restored_widgets}))
    return checks, {'contractEffects': contracts, 'rendered': {'witness':'c8e-ui-layout','artifact':artifact,'url':worker.page.url}}


def _pack_files(status, root):
    """Independent proof that the real owner produced every receipt byte."""
    receipt_path = Path(status['receipt']).resolve()
    receipt_path.relative_to(Path(root).resolve())
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    target = Path(receipt['target']).resolve()
    target.relative_to(Path(root).resolve())
    rows = []
    for entry in receipt['files']:
        path = (target / entry['path']).resolve()
        path.relative_to(target)
        observed_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        observed_size = path.stat().st_size if path.is_file() else None
        rows.append({'path':str(path),'expected':entry,'sha256':observed_hash,'size':observed_size,
                     'passed':observed_hash == entry['sha256'] and observed_size == entry['size']})
    return {'receipt':str(receipt_path),'files':rows,'passed':bool(rows) and all(r['passed'] for r in rows)}


def _actual_ack(worker,root,event,ok=True,error_fragment=None):
    path = Path(root)/'.agent_control/ui_commands.sqlite3'
    path.resolve().relative_to(Path(root).resolve())
    rows = []
    for _ in range(100):
        with sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True) as db:
            rows = db.execute('SELECT client,ok,error FROM acks WHERE event_id=?',(event['id'],)).fetchall()
        if rows:
            break
        worker.page.wait_for_timeout(100)
    return {'event':event,'acknowledgements':rows,'passed':bool(rows) and all(bool(row[1]) == ok
        and (error_fragment is None or error_fragment in (row[2] or '')) for row in rows)}


def _strict_refusal(worker,tool,args,fragments):
    try:
        accepted = worker.tool(tool,args)
        return {'refused':False,'unexpectedAccepted':accepted}
    except Exception as error:
        reply = getattr(error,'reply',None)
        if not isinstance(reply,dict):
            raise
        body = reply.get('body',{})
        data = body.get('data',{})
        reasons = [body.get('error'),data.get('error'),data.get('reason'),data.get('failure')]
        result = data.get('result',{})
        if isinstance(result,dict):
            reasons += [result.get('error'),result.get('reason')]
        reason = json.dumps(reasons,ensure_ascii=False)
        refused = (body.get('ok') is False or data.get('ok') is False) and any(text in reason for text in fragments)
        return {'refused':refused,'reason':reason,'reply':reply}


def _design_shell(worker,root):
    """Mounted initial state plus all four design scene/bubble/theme cases."""
    _home(worker)
    worker.page.set_viewport_size({'width':1800,'height':1200})
    identities,conversation_ids = [],[]
    for index in range(8):
        title = 'C8e shell bubble '+str(index+1)
        created = worker.tool('backend:create_neyvia_conversation_command',
            {'kind':'chat','title':title,'titleMode':'off','metadata':{'workspacePath':str(root/'c8'),'source':'C8e-user-fixture'}})
        worker.tool('backend:append_neyvia_conversation_turn_command',
            {'conversationId':created['conversationId'],'role':'user','content':'Saved local bubble content '+str(index+1),
             'source':'C8e-user-fixture'})
        conversation_ids.append(created['conversationId'])
        identities.append(_fresh_summary(worker,created['conversationId'])['id'])
    junk = [{'id':identities[0],'x':-2,'y':-3},{'id':identities[0],'x':.8,'y':.8},
            {'id':identities[1],'x':'2','y':'2'},{'id':identities[2]},
            {'id':identities[3],'x':'bad','y':.4},{'id':identities[4],'x':1,'y':.5},
            {'id':identities[5],'x':1,'y':.6},{'id':identities[6]},{'id':identities[7]}]
    expected = [{'id':identities[0],'x':0,'y':0},{'id':identities[1],'x':1,'y':1},
                {'id':identities[2],'x':1,'y':.3},{'id':identities[3],'x':0,'y':.4},
                {'id':identities[4],'x':1,'y':.5},{'id':identities[5],'x':1,'y':.6}]
    worker.page.evaluate("v=>{localStorage.setItem('nx.os.theme',JSON.stringify('bad-theme'));localStorage.setItem('nx.os.bubbles',JSON.stringify(v))}",junk)
    worker.page.reload(wait_until='domcontentloaded')
    worker.page.locator('.nx-bubble-float').nth(5).wait_for(timeout=15000)
    _skip_setup(worker)
    rendered = worker.page.locator('.nx-bubble-float').evaluate_all("items=>items.map(e=>({label:e.getAttribute('aria-label'),x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y}))")
    initial = [_check('shell-initial-malformed-saved-state',len(rendered) == 6
        and [r['label'].split(':')[0] for r in rendered] == ['C8e shell bubble '+str(i+1) for i in range(6)]
        and rendered[0]['x'] == 10 and rendered[0]['y'] == 10
        and rendered[1]['x'] == 1738 and rendered[1]['y'] == 1108
        and worker.page.locator('.nx-root').get_attribute('data-nx-theme') == 'dark'
        and worker.page.locator('.nx-stage').count() == 0 and worker.page.locator('.nx-toast').count() == 0,
        {'storedInput':junk,'mounted':rendered,'theme':worker.page.locator('.nx-root').get_attribute('data-nx-theme'),
         'stageCount':worker.page.locator('.nx-stage').count(),'noticeCount':worker.page.locator('.nx-toast').count()})]
    bubble = worker.page.get_by_role('button',name='C8e shell bubble 1: idle',exact=True)
    box = bubble.bounding_box(); x,y=box['x']+26,box['y']+26
    worker.page.mouse.move(x,y);worker.page.mouse.down();worker.page.mouse.move(100,400,steps=12);worker.page.mouse.up()
    normalized = worker.page.evaluate("()=>JSON.parse(localStorage.getItem('nx.os.bubbles'))")
    expected[0] = {'id':identities[0],'x':0,'y':1/3}
    initial.append(_check('shell-initial-normalized-preferences-persist-on-real-drag',normalized == expected,
                          {'expected':expected,'saved':normalized}))
    checks = list(initial)
    for index in range(6):
        widget = worker.page.get_by_role('button',name='C8e shell bubble '+str(index+1)+': idle',exact=True)
        widget.focus();widget.press('Delete')
        widget.wait_for(state='hidden',timeout=10000)
    first = worker.tool('neyvia.view.float',{'id':identities[0]})
    ack = _actual_ack(worker,root,first['event'])
    mini = worker.page.get_by_role('dialog',name='C8e shell bubble 1, floating',exact=True)
    mini.get_by_text('Saved local bubble content 1',exact=True).wait_for(timeout=15000)
    before = worker.page.evaluate("()=>JSON.parse(localStorage.getItem('nx.os.bubbles'))")
    duplicate = worker.tool('neyvia.view.float',{'id':identities[0]})
    duplicate_ack = _actual_ack(worker,root,duplicate['event'])
    after = worker.page.evaluate("()=>JSON.parse(localStorage.getItem('nx.os.bubbles'))")
    checks.append(_check('shell-bubble-floats-once-opens-real-saved-content',ack['passed'] and duplicate_ack['passed']
        and before == after == [{'id':identities[0],'x':1,'y':.18}] and worker.page.locator('.nx-bubble-float').count() == 1,
        {'first':ack,'duplicate':duplicate_ack,'before':before,'after':after,'content':mini.inner_text()}))
    for index in (1,2):
        produced = worker.tool('neyvia.view.float',{'id':identities[index]})
        checks.append(_check('shell-bubble-lineup-'+str(index),_actual_ack(worker,root,produced['event'])['passed'],{'event':produced['event']}))
    lined = worker.page.evaluate("()=>JSON.parse(localStorage.getItem('nx.os.bubbles'))")
    checks.append(_check('shell-bubble-exact-right-lineup',lined == [{'id':identities[i],'x':1,'y':.18+i*.1} for i in range(3)],{'saved':lined}))
    for identity in identities[:3]:
        produced = worker.tool('neyvia.view.float',{'id':identity,'floating':False})
        checks.append(_check('shell-bubble-return-'+identity,_actual_ack(worker,root,produced['event'])['passed'],{'event':produced['event']}))
    checks.append(_check('shell-bubbles-return-without-destroying-chat',worker.page.locator('.nx-bubble-float').count() == 0
        and _fresh_summary(worker,conversation_ids[0])['id'] == identities[0],{'remainingBubbles':worker.page.locator('.nx-bubble-float').count()}))
    refused = _strict_refusal(worker,'neyvia.view.float',{'id':'c8e-unknown-session'},['Unknown session'])
    checks.append(_check('shell-bubble-unknown-session-refused',refused['refused'] and worker.page.locator('.nx-bubble-float').count() == 0,refused))
    patch = {'order':['main','sidebar'],'dock':'left','canopy':'off','widgets':[{'id':'usage','size':'l'}]}
    moved = worker.tool('neyvia.view.arrange',patch)
    arranged = _actual_ack(worker,root,moved['event'])
    layout = _read_layout(worker)
    wanted = {'order':['main','sidebar','panel','canopy'],'widths':{},'canopy':'off','dock':'left','sidebarHidden':False,
              'widgets':[{'id':'usage','size':'s'}]}
    checks.append(_check('shell-bus-arrange-normalizes-and-mounts',arranged['passed'] and layout == wanted
        and worker.page.locator('.nx-widget[aria-label="Usage"].is-s').count() == 1
        and worker.page.locator('[data-region="sidebar"]').get_attribute('data-side') == 'end',
        {'request':patch,'event':arranged,'saved':layout,'expected':wanted}))
    second = worker.tool('neyvia.view.arrange',{'canopy':'on'})
    second_ack = _actual_ack(worker,root,second['event'])
    after = _read_layout(worker)
    checks.append(_check('shell-bus-arrange-preserves-omitted-fields',second_ack['passed'] and after == {**wanted,'canopy':'on'},
                          {'event':second_ack,'before':layout,'after':after}))
    refusal = _strict_refusal(worker,'neyvia.view.arrange',{'order':['main','main']},['each region once'])
    checks.append(_check('shell-bus-arrange-refused-duplicate-without-mutation',refusal['refused'] and _read_layout(worker) == after,refusal))
    # Reuse the maintained real Settings scene/theme witness, including its
    # actual canonical persistence, reload and malformed/unknown refusals.
    from c8e_effects import _settings_witness
    settings_checks,_ = _settings_witness(worker,root)
    checks.extend(settings_checks)
    scene = worker.page.evaluate("()=>JSON.parse(localStorage.getItem('nx.os.scenes'))['c8e-settings']")
    checks.append(_check('shell-scene-keeps-whole-user-arrangement',scene['layout'] == _read_layout(worker)
        and scene['layout']['order'] == wanted['order'] and scene['layout']['dock'] == 'left'
        and scene['layout']['widgets'] == wanted['widgets'] and scene['theme'] == 'sunset' and scene['density'] == 'grove',
        {'captured':scene,'restoredLayout':_read_layout(worker)}))
    # Retain explicit domain refusals as well as the shared witness's unchanged
    # state checks; an unrelated transport failure cannot prove these cases.
    stable = worker.page.locator('.nx-root').evaluate("e=>({theme:e.dataset.nxTheme,density:e.dataset.nxDensity,layout:JSON.parse(localStorage.getItem('nx.os.layout'))})")
    for tool,args,reasons in [('neyvia.view.theme',{'theme':'neon'},
                              ['Themes are','not one of',"Tool argument 'theme' must be one of: dark, light, sunset, night."]),
                             ('neyvia.view.scene',{'save':'Focus'},['built-in']),
                             ('neyvia.view.scene',{},['either name'])]:
        refused = _strict_refusal(worker,tool,args,reasons)
        now = worker.page.locator('.nx-root').evaluate("e=>({theme:e.dataset.nxTheme,density:e.dataset.nxDensity,layout:JSON.parse(localStorage.getItem('nx.os.layout'))})")
        checks.append(_check('shell-explicit-domain-refusal-'+tool+'-'+json.dumps(args,sort_keys=True),
                             refused['refused'] and now == stable,{'refusal':refused,'before':stable,'after':now}))
    return checks,{'contractEffects':[_contract('proofs-e.shell.initial',initial,'Mounted malformed stored theme and eight real floating chats normalize, clamp, deduplicate and limit to six; actual pointer edit persists normalized state'),
        _contract('proofs-e.shell.reducer',checks[len(initial):],'Design chapter four source cases: bus arrange, whole scenes and durable restoration, real floating chats, all themes and actual malformed/unknown refusals')],
        'rendered':{'witness':'c8e-ui-design-shell','artifact':worker.screenshot('effect-design-shell'),'url':worker.page.url}}


def _two_page_pdf(path):
    """A disposable actual document input, not a PDF result fixture."""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for text in ('Alpha C8e actual first page','Beta C8e actual second page'):
        stream = ('BT /F1 18 Tf 50 700 Td ('+text+') Tj ET').encode('ascii')
        objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    payload,offsets = b'%PDF-1.4\n',[0]
    for index,content in enumerate(objects,1):
        offsets.append(len(payload));payload += str(index).encode()+b' 0 obj\n'+content+b'\nendobj\n'
    start = len(payload)
    payload += b'xref\n0 8\n0000000000 65535 f \n'+b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
    payload += f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)


def _pdf_state(worker,predicate):
    states = []
    until = time.monotonic()+15
    while time.monotonic() < until:
        state = worker.tool('neyvia.pdf.state',{})['state']
        states.append(state)
        if state is not None and predicate(state):
            return state,states
        worker.page.wait_for_timeout(250)
    raise RuntimeError('The actual rendered PDF state did not reach the requested effect: '+json.dumps(states,ensure_ascii=False))


def _pdf_shell(worker,root):
    """Actual PDF bus ordering/refusal plus the maintained Outputs witness."""
    _home(worker)
    worker.page.set_viewport_size({'width':1800,'height':1200})
    path = root/'c8/c8e-ordered.pdf'
    _two_page_pdf(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checks,events = [],[]
    opened = worker.tool('neyvia.pdf.open',{'source':str(path),'page':1});events.append(opened['event'])
    worker.page.locator('.nx-pdf-page[data-page="1"] .textLayer').get_by_text('Alpha C8e actual first page',exact=True).wait_for(timeout=45000)
    state,states = _pdf_state(worker,lambda s:s['status'] == 'ready' and s['pages'] == 2 and s['page'] == 1 and s['source'] == str(path))
    ack = _actual_ack(worker,root,opened['event'])
    checks.append(_check('pdf-open-starts-real-app-and-document',ack['passed'] and opened.get('pages') == 2
        and worker.page.locator('.nx-pdf-page').count() == 2,
        {'tool':opened,'ack':ack,'actualUserState':state,'observedStates':states,'inputHash':digest}))
    goto = worker.tool('neyvia.pdf.goto',{'page':2});events.append(goto['event'])
    state,states = _pdf_state(worker,lambda s:s['page'] == 2)
    worker.page.locator('.nx-pdf-page[data-page="2"] .textLayer').get_by_text('Beta C8e actual second page',exact=True).wait_for(timeout=15000)
    checks.append(_check('pdf-ordered-goto-render-and-report',_actual_ack(worker,root,goto['event'])['passed']
        and worker.page.get_by_role('textbox',name='Page',exact=True).input_value() == '2',
        {'event':goto['event'],'actualUserState':state,'observedStates':states}))
    zoom = worker.tool('neyvia.pdf.zoom',{'scale':1.5});events.append(zoom['event'])
    state,states = _pdf_state(worker,lambda s:s['scale'] == 1.5 and s['fitWidth'] is False)
    checks.append(_check('pdf-ordered-zoom-render-and-report',_actual_ack(worker,root,zoom['event'])['passed']
        and worker.page.locator('.nx-pdf-zoom').inner_text() == '150%',
        {'event':zoom['event'],'actualUserState':state,'observedStates':states}))
    searched = worker.tool('neyvia.pdf.search',{'query':'Beta'});events.append(searched['event'])
    state,states = _pdf_state(worker,lambda s:s['search']['query'] == 'Beta' and s['search']['hits'] == 1)
    checks.append(_check('pdf-ordered-search-real-text-shared-query',_actual_ack(worker,root,searched['event'])['passed']
        and worker.page.get_by_role('searchbox',name='Search in PDF',exact=True).input_value() == 'Beta'
        and worker.page.locator('.nx-pdf-hit').count() == 1,
        {'tool':searched,'actualUserState':state,'observedStates':states}))
    highlighted = worker.tool('neyvia.pdf.highlight',{'page':2,'text':'Beta','note':'C8e queued highlight'});events.append(highlighted['event'])
    state,states = _pdf_state(worker,lambda s:len(s['highlights']) == 1 and s['highlights'][0]['page'] == 2
        and s['highlights'][0]['text'] == 'Beta' and s['highlights'][0]['by'] == 'model')
    worker.page.locator('.nx-pdf-mark.is-model[title="C8e queued highlight"]').wait_for(timeout=15000)
    checks.append(_check('pdf-ordered-highlight-real-overlay-source-preserved',_actual_ack(worker,root,highlighted['event'])['passed']
        and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
        {'event':highlighted['event'],'actualUserState':state,'observedStates':states,'sourceHashAfter':hashlib.sha256(path.read_bytes()).hexdigest()}))
    checks.append(_check('pdf-source-events-preserve-command-order',
        [e['action'] for e in events] == ['pdf.open','pdf.goto','pdf.zoom','pdf.search','pdf.highlight']
        and [int(e['id']) for e in events] == sorted({int(e['id']) for e in events}),{'events':events}))
    # User controls update the same state observed by the model.
    worker.page.get_by_role('button',name='Previous page',exact=True).click()
    state,states = _pdf_state(worker,lambda s:s['page'] == 1)
    checks.append(_check('pdf-user-page-control-shared-back-to-model',
        worker.page.get_by_role('textbox',name='Page',exact=True).input_value() == '1',{'actualUserState':state,'observedStates':states}))
    worker.page.get_by_role('searchbox',name='Search in PDF',exact=True).fill('Alpha')
    state,states = _pdf_state(worker,lambda s:s['search']['query'] == 'Alpha' and s['search']['hits'] == 1)
    checks.append(_check('pdf-user-search-control-shared-back-to-model',worker.page.locator('.nx-pdf-hit').count() == 1,
                          {'actualUserState':state,'observedStates':states}))
    worker.page.locator('.nx-stage-head').get_by_role('button',name=re.compile('^Close ')).click()
    worker.page.locator('.nx-pdf').wait_for(state='hidden',timeout=10000)
    closed = worker.tool('neyvia.pdf.goto',{'page':1})
    refused_ack = _actual_ack(worker,root,closed['event'],ok=False,error_fragment='The pdf app is not open; send pdf.open first')
    checks.append(_check('pdf-closed-app-command-refused-by-real-ui',refused_ack['passed'] and worker.page.locator('.nx-pdf').count() == 0,
                          {'acceptedBackendRequest':closed,'actualUiRefusal':refused_ack}))
    for tool,args,reason in [('neyvia.pdf.goto',{'page':3},['Page is outside this PDF']),
                            ('neyvia.pdf.zoom',{'scale':99},['scale must be 0.25']),
                            ('neyvia.pdf.highlight',{'page':1,'text':'missing-C8e-phrase'},['Highlight text was not found']),
                            ('neyvia.pdf.open',{'source':str(root/'c8/absent.pdf')},['Choose an existing .pdf file'])]:
        refusal = _strict_refusal(worker,tool,args,reason)
        checks.append(_check('pdf-malformed-refused-'+tool.split('.')[-1],refusal['refused']
            and worker.page.locator('.nx-pdf').count() == 0 and hashlib.sha256(path.read_bytes()).hexdigest() == digest,refusal))
    # The source's second PDF-shell case is publication/output refresh. Reuse
    # its existing real product witness with actual owned file bytes.
    from c8e_effects import _outputs_witness
    output_checks,output_observed = _outputs_witness(worker,root)
    checks.extend(output_checks)
    return checks,{'contractEffects':[_contract('proofs-e.shell.reducer',checks,
        'PDF chapter two named source cases: actual ordered PDF app commands, shared rendered text/page/search/highlight state, closed-app and malformed refusal, actual artifact publication/Outputs refresh and offscreen-only notice')],
        'rendered':{'witness':'c8e-ui-pdf-shell','artifact':worker.screenshot('effect-pdf-shell'),'url':worker.page.url},
        'outputs':output_observed,'pdfInput':{'path':str(path),'sha256':digest}}


def _expected_base_failure(worker):
    """Inspect only this deliberate checksum refusal, retaining ok:false."""
    try:
        value = worker.tool('neyvia.onboarding.base_pack',{'action':'status'})
    except Exception as error:
        reply = getattr(error,'reply',None)
        if not isinstance(reply,dict) or reply.get('httpStatus') != 200:
            raise
        data = reply.get('body',{}).get('data',{})
        value = data.get('result')
        if (not isinstance(value,dict) or value.get('schema') != 'neyvia.base-pack-status/v1'
                or value.get('state') != 'failed' or 'failed its checksum twice' not in value.get('error','')):
            raise
        # No field is relabelled. The caller proves that this failure was the
        # intended refusal and checks the target still has no bad payload.
    if value.get('state') != 'failed' or 'failed its checksum twice' not in value.get('error',''):
        raise ValueError('The intended local checksum corruption did not produce its exact declared refusal')
    return value


def _setup(worker):
    if worker.page.locator('.nx-onb-scrim').count():
        worker.page.keyboard.press('Escape')
        worker.page.locator('.nx-onb-scrim').wait_for(state='hidden',timeout=15000)
    options = _search(worker, 'Setup and tour')
    options.filter(has=worker.page.get_by_text('Setup and tour',exact=True)).click()
    worker.page.locator('.nx-onb-rail').wait_for(timeout=15000)
    worker.page.locator('.nx-onb-loading').wait_for(state='hidden',timeout=45000)


def _onboarding(worker, root):
    _home(worker)
    checks, contracts = [], []
    # Preserve any real first-run staging. A fresh staged copy is necessary to
    # observe the procedure's actual start/pause/resume, not only read status.
    for _ in range(100):
        status = worker.tool('neyvia.onboarding.base_pack',{'action':'status'})
        if status.get('state') not in {'starting','running','verifying'}:
            break
        worker.page.wait_for_timeout(100)
    else:
        raise ValueError('Actual base pack did not finish before isolated fresh-copy journey')
    base = Path(root).resolve() / '.agent_control/onboarding/base-pack'
    if base.exists():
        preserved = Path(root).resolve() / 'c8/base-pack-before-ui-journey'
        base.relative_to(Path(root).resolve()); preserved.relative_to(Path(root).resolve())
        if preserved.exists():
            raise ValueError('Fresh base pack preservation destination already exists')
        base.rename(preserved)
    manifest_path = (Path(root).resolve() / 'c8/base-ui-manifest.json').resolve()
    manifest_path.relative_to(Path(root).resolve())
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    damaged = copy.deepcopy(manifest)
    damaged['files'][0]['sha256'] = '0' * 64
    manifest_path.write_text(json.dumps(damaged),encoding='utf-8')
    _setup(worker)
    worker.page.get_by_role('button',name='Start',exact=True).click()
    worker.page.get_by_text('The download stopped',exact=True).wait_for(timeout=45000)
    failed = _expected_base_failure(worker)
    failed_words = worker.page.locator('.nx-onb-card.is-download').inner_text()
    failed_target = Path(failed['target']).resolve()
    failed_target.relative_to(Path(root).resolve())
    bad_file = failed_target / manifest['files'][0]['path']
    failed_check = _check('setup-base-checksum-failure-is-real',failed['state'] == 'failed'
                          and 'checksum twice' in failed_words and not bad_file.is_file()
                          and failed.get('packId') == 'base' and failed.get('manifest') == str(manifest_path)
                          and failed.get('current',{}).get('path') == manifest['files'][0]['path']
                          and not (failed_target / 'installed.json').exists(),
                          {'owner':failed,'rendered':failed_words,'badPayloadCommitted':bad_file.is_file(),
                           'ownedManifest':str(manifest_path),'originalManifestSha256':hashlib.sha256(manifest_bytes).hexdigest()})
    manifest_path.write_bytes(manifest_bytes)
    worker.page.get_by_role('button',name='Try again',exact=True).click()
    worker.page.get_by_role('button',name='Pause',exact=True).wait_for(timeout=10000)
    samples = []
    for _ in range(30):
        current = worker.tool('neyvia.onboarding.base_pack',{'action':'status'})
        percent = worker.page.get_by_role('progressbar',name='Essentials download',exact=True).get_attribute('aria-valuenow')
        samples.append({'status':current,'renderedPercent':percent})
        if current.get('doneBytes',0) > 0 and current.get('state') in {'running','verifying'}:
            break
        worker.page.wait_for_timeout(100)
    worker.page.get_by_role('button',name='Pause',exact=True).click()
    worker.page.get_by_text('Paused',exact=True).wait_for(timeout=10000)
    paused = worker.tool('neyvia.onboarding.base_pack',{'action':'status'})
    paused_text = worker.page.locator('.nx-onb-card.is-download').inner_text()
    worker.page.get_by_role('button',name='Resume',exact=True).click()
    worker.page.get_by_text('Essentials ready',exact=True).wait_for(timeout=45000)
    finished = worker.tool('neyvia.onboarding.base_pack',{'action':'status'})
    staged = _pack_files(finished,root)
    percent = worker.page.get_by_role('progressbar',name='Essentials download',exact=True).get_attribute('aria-valuenow')
    download_checks = [failed_check, _check('setup-download-real-pause',paused['state'] == 'paused' and 'resumes where it left off' in paused_text
                              and any(s['status'].get('doneBytes',0) > 0 for s in samples),
                              {'samples':samples,'paused':paused,'text':paused_text}),
                       _check('setup-download-resume-exact-files',finished['state'] == 'done' and finished['doneBytes'] == finished['totalBytes']
                              and percent == '100' and staged['passed'], {'finished':finished,'percent':percent,'staging':staged})]
    checks.extend(download_checks)
    contracts.append(_contract('onboarding.downloadView',download_checks,'Actual local shipped base test-pack checksum failure without committed bad payload, rendered Try again/Pause/Resume and100% only with independently verified final files'))
    worker.page.locator('.nx-onb-rail').get_by_role('button',name=re.compile('Agents')).click()
    worker.page.get_by_role('button',name='Check again',exact=True).wait_for(timeout=45000)
    worker.page.get_by_role('button',name='Check again',exact=True).click()
    worker.page.get_by_role('button',name='Check again',exact=True).wait_for(state='visible',timeout=60000)
    worker.page.wait_for_function("() => !document.querySelector('.nx-onb-step-head button')?.disabled",timeout=60000)
    runtimes = worker.tool('neyvia.onboarding.runtimes',{})
    found = [r['label'] for r in runtimes.get('runtimes',[]) if r.get('found')]
    heading = worker.page.locator('#nx-onb-title').inner_text()
    words = worker.page.locator('.nx-onb-step-head p').inner_text()
    names = found[0] if len(found) == 1 else ', '.join(found[:-1]) + ' and ' + found[-1] if found else None
    c = _check('setup-runtime-detection-matches-owner',heading == ("You're set to start" if found else 'Begin with…')
               and words == ('Found ' + names + ' on this PC.' if found else 'No agent app was found on this PC yet. Pick one to set up, or start with Neyvia Native.'),
               {'heading':heading,'words':words,'actualDetection':runtimes})
    checks.append(c)
    contracts.append(_contract('onboarding.runtimeHeadline',[c],'Actual installed runtime scan through Check again; found names exactly match owner, no authentication/inference claim'))
    worker.page.locator('.nx-onb-rail').get_by_role('button',name=re.compile('Interests')).click()
    state = worker.tool('neyvia.onboarding.state',{})
    catalog = state['catalog']
    # Tier fallback then direct selections overriding that tier are real controls.
    worker.page.get_by_role('radio',name='Beginner',exact=True).click()
    tier = next(t for t in catalog['tiers'] if t['id'] == 'beginner')
    chosen_labels = [i['label'] for i in catalog['interests'] if i['id'] in tier['interests']]
    mounted = worker.page.locator('.nx-onb-interests [aria-pressed="true"] b').all_text_contents()
    tier_check = _check('setup-tier-interest-fallback',mounted == chosen_labels,{'tier':tier,'selectedLabels':mounted})
    for label in list(mounted):
        worker.page.locator('.nx-onb-interests').get_by_role('button',name=re.compile('^'+re.escape(label))).click()
    desired = ['coding','studying']
    for identity in desired:
        row = next(i for i in catalog['interests'] if i['id'] == identity)
        worker.page.locator('.nx-onb-interests').get_by_role('button',name=re.compile('^'+re.escape(row['label']))).click()
    direct_labels = worker.page.locator('.nx-onb-interests [aria-pressed="true"] b').all_text_contents()
    union = lambda key: list(dict.fromkeys(v for i in catalog['interests'] if i['id'] in desired for v in i[key]))
    expected_apps = union('apps')
    app_names = {a['id']:a['name'] for a in state['apps']}
    mounted_apps = worker.page.locator('.nx-onb-picks b').all_text_contents()
    wanted_chapters = set(union('chapters'))
    chapters = [c for c in catalog['tutorial']['chapters'] if not c['interests'] or c['id'] in wanted_chapters]
    direct_check = _check('setup-direct-interest-overrides-tier',direct_labels == [i['label'] for i in catalog['interests'] if i['id'] in desired]
                         and worker.page.locator('[aria-label="Experience level"] [aria-checked="true"]').count() == 0,
                         {'chosen':direct_labels,'expected':desired})
    rec_check = _check('setup-recommendations-exact-catalog-order',mounted_apps == [app_names[i] for i in expected_apps],
                      {'expectedIds':expected_apps,'expectedNames':[app_names[i] for i in expected_apps],'rendered':mounted_apps})
    checks.extend([tier_check,direct_check,rec_check])
    contracts.append(_contract('onboarding.interestsFor',[tier_check,direct_check],'Mounted tier selection followed by direct interests; direct choices replace tier indication'))
    contracts.append(_contract('onboarding.recommend',[rec_check],'Union of two actual interests rendered in catalog order without duplicates; unconditional chapters checked in player'))
    # SDK is a shipped local-component pack, copied by the production owner.
    all_addons = worker.page.locator('.nx-onb-more').filter(has=worker.page.locator('summary').get_by_text(re.compile('All add-ons')))
    if all_addons.count() and all_addons.get_attribute('open') is None:
        all_addons.locator('summary').click()
    sdk_name = next(p['name'] for p in state['packs'] if p['id'] == 'pack.creator-sdk')
    sdk = worker.page.locator('.nx-onb-pack').filter(has=worker.page.locator('b').get_by_text(sdk_name,exact=True))
    before = worker.tool('neyvia.onboarding.pack',{'action':'status','packId':'pack.creator-sdk'})['packs'][0]
    if before['state'] != 'not-installed':
        raise ValueError('SDK fresh-copy fixture already has a staging result; refusing status-only success')
    sdk.get_by_role('button',name='Install',exact=True).click()
    sdk.get_by_role('button',name='Receipt',exact=True).wait_for(timeout=45000)
    installed = worker.tool('neyvia.onboarding.pack',{'action':'status','packId':'pack.creator-sdk'})['packs'][0]
    files = _pack_files(installed,root)
    sdk.get_by_role('button',name='Receipt',exact=True).click()
    receipt_words = sdk.inner_text()
    pack_checks = [_check('setup-sdk-installed-exact-payload',installed['state'] == 'installed' and files['passed']
                         and str(installed['files']['total']) + ' files checked' in receipt_words,
                         {'owner':installed,'staging':files,'receiptText':receipt_words})]
    # Damage a freshly staged owned copy, never the source. Owner must reject
    # the stale install receipt; the mounted Try again then performs recovery.
    corrupted = Path(files['files'][0]['path']).resolve()
    corrupted.relative_to(Path(root).resolve())
    corrupted.write_bytes(b'C8e controlled corruption of disposable staged SDK copy')
    refusal = worker.tool('neyvia.onboarding.pack',{'action':'status','packId':'pack.creator-sdk'})['packs'][0]
    _setup(worker)
    worker.page.locator('.nx-onb-rail').get_by_role('button',name=re.compile('Interests')).click()
    all_addons = worker.page.locator('.nx-onb-more').filter(has=worker.page.locator('summary').get_by_text(re.compile('All add-ons')))
    if all_addons.count() and all_addons.get_attribute('open') is None:
        all_addons.locator('summary').click()
    sdk = worker.page.locator('.nx-onb-pack').filter(has=worker.page.locator('b').get_by_text(sdk_name,exact=True))
    sdk.get_by_role('button',name='Try again',exact=True).wait_for(timeout=15000)
    failure_words = sdk.inner_text()
    sdk.get_by_role('button',name='Try again',exact=True).click()
    sdk.get_by_role('button',name='Receipt',exact=True).wait_for(timeout=45000)
    repaired = worker.tool('neyvia.onboarding.pack',{'action':'status','packId':'pack.creator-sdk'})['packs'][0]
    repaired_files = _pack_files(repaired,root)
    pack_checks.append(_check('setup-sdk-corruption-refused-and-repaired',refusal['state'] == 'failed'
                              and 'checksum' in failure_words and repaired['state'] == 'installed' and repaired_files['passed'],
                              {'refusal':refusal,'renderedFailure':failure_words,'repaired':repaired,'staging':repaired_files}))
    checks.extend(pack_checks)
    contracts.append(_contract('onboarding.packView',pack_checks,'Real SDK install, checksum receipt, damaged owned staged payload yields failed/Try again, actual recovery'))
    raw, install_controls = [], []
    unavailable = worker.page.locator('.nx-onb-pack.is-unavailable')
    for index in range(unavailable.count()):
        row = unavailable.nth(index)
        row.get_by_role('button',name="What's missing",exact=True).click()
        raw.extend(row.locator('.nx-onb-pack-more li').evaluate_all('(items) => items.map(e=>({raw:e.title,text:e.innerText}))'))
        install_controls.append(row.get_by_role('button',name='Install',exact=True).count())
    sdk.get_by_role('button',name='Receipt',exact=True).click()
    sdk_missing = sdk.locator('.nx-onb-pack-more .nx-onb-fine').all_text_contents()
    c = _check('setup-plain-unavailable-pack-notes',bool(raw) and all('tool.' not in r['text'] for r in raw)
               and all(n == 0 for n in install_controls) and bool(sdk_missing) and all('tool.' not in t for t in sdk_missing),
               {'actualMissingNotes':raw,'installControls':install_controls,'installedSdkMissingNotes':sdk_missing})
    checks.append(c)
    contracts.append(_contract('onboarding.plainMissing',[c],'Real unavailable catalog pack gap notes rendered plainly with no install action; no payload readiness fabricated'))
    # Reapply choices because reopening after recovery reloaded persisted state.
    for i in catalog['interests']:
        button = worker.page.locator('.nx-onb-interests').get_by_role('button',name=re.compile('^'+re.escape(i['label'])))
        selected = button.get_attribute('aria-pressed') == 'true'
        if selected != (i['id'] in desired):
            button.click()
    worker.page.emulate_media(reduced_motion='no-preference')
    worker.page.locator('.nx-onb-rail').get_by_role('button',name=re.compile('Tour')).click()
    tour = worker.page.locator('.nx-tour')
    tour.wait_for(timeout=15000)
    pause = tour.get_by_role('button',name='Pause',exact=True)
    if pause.count():
        pause.click()
    segments = tour.locator('.nx-tour-seg')
    durations = segments.evaluate_all('(items)=>items.map(e=>Number(e.style.flexGrow))')
    total = min(90000,max(60000,sum(c['durationMs'] for c in chapters)))
    expected_durations, at = [], 0
    for index,chapter in enumerate(chapters):
        duration = total-at if index == len(chapters)-1 else int(chapter['durationMs']*total/sum(c['durationMs'] for c in chapters)+.5)
        expected_durations.append(duration); at += duration
    titles = segments.evaluate_all('(items)=>items.map(e=>e.title)')
    c = _check('setup-tour-exact-proportional-timeline',durations == expected_durations
               and titles == [c['title'] for c in chapters] and tour.locator('.nx-tour-time').inner_text() == str(round(total/1000)) + ' s',
               {'chapters':chapters,'durations':durations,'expectedDurations':expected_durations,'titles':titles,'totalMs':total})
    checks.append(c)
    contracts.append(_contract('onboarding.timeline',[c],'Mounted real tour segments expose every proportional chapter duration and exact rounding remainder; rendered total60–90s'))
    locate_checks = []
    for index,chapter in enumerate(chapters):
        segments.nth(index).click()
        title = tour.locator('.nx-tour-caption h3').inner_text()
        caption = tour.locator('.nx-tour-caption small')
        caption_index = caption.inner_text()
        semantic_index = caption.evaluate('e=>e.textContent')
        caption_transform = caption.evaluate('e=>getComputedStyle(e).textTransform')
        expected_index = str(index+1) + ' of ' + str(len(chapters))
        rendered_index = expected_index.upper() if caption_transform == 'uppercase' else expected_index
        current = segments.nth(index).get_attribute('aria-current')
        locate_checks.append(_check('setup-tour-chapter-'+chapter['id'],title == chapter['title']
                                    and semantic_index == expected_index and caption_index == rendered_index and current == 'true',
                                    {'title':title,'position':caption_index,'semanticPosition':semantic_index,
                                     'textTransform':caption_transform,'current':current}))
    # End navigation clamps rather than wrapping or escaping the tour.
    locate_checks.append(_check('setup-tour-last-bound',tour.get_by_role('button',name='Next chapter',exact=True).is_disabled(),
                                {'last':tour.locator('.nx-tour-caption h3').inner_text()}))
    segments.first.click()
    locate_checks.append(_check('setup-tour-first-bound',tour.get_by_role('button',name='Previous chapter',exact=True).is_disabled(),
                                {'first':tour.locator('.nx-tour-caption h3').inner_text()}))
    tour.get_by_role('button',name='Play',exact=True).click()
    worker.page.wait_for_timeout(250)
    tour.get_by_role('button',name='Pause',exact=True).click()
    progress = segments.first.locator('i').evaluate('e=>parseFloat(e.style.width)')
    locate_checks.append(_check('setup-tour-measured-in-chapter-progress',0 < progress < 100
                                and tour.locator('.nx-tour-caption h3').inner_text() == chapters[0]['title'],
                                {'progressPercent':progress,'title':tour.locator('.nx-tour-caption h3').inner_text()}))
    segments.last.click()
    tour.get_by_role('button',name='Play',exact=True).click()
    tour.get_by_role('button',name='Watch again',exact=True).wait_for(timeout=expected_durations[-1]+10000)
    end_progress = segments.last.locator('i').evaluate('e=>parseFloat(e.style.width)')
    locate_checks.append(_check('setup-tour-real-end-maps-last-chapter',end_progress == 100
                                and tour.locator('.nx-tour-caption h3').inner_text() == chapters[-1]['title'],
                                {'progressPercent':end_progress,'title':tour.locator('.nx-tour-caption h3').inner_text()}))
    tour.get_by_role('button',name='Watch again',exact=True).click()
    tour.get_by_role('button',name='Pause',exact=True).click()
    locate_checks.append(_check('setup-tour-replay-resets-first-chapter',tour.locator('.nx-tour-caption h3').inner_text() == chapters[0]['title'],
                                {'title':tour.locator('.nx-tour-caption h3').inner_text()}))
    checks.extend(locate_checks)
    contracts.append(_contract('onboarding.locate',locate_checks,'Actual player chapter jumps and first/last bounds, caption/index/current marker match selected catalog chapter'))
    artifact = worker.screenshot('effect-onboarding')
    worker.page.get_by_role('button',name='Finish',exact=True).click()
    worker.page.locator('.nx-onb-scrim').wait_for(state='hidden',timeout=15000)
    saved = worker.tool('neyvia.onboarding.state',{})['state']
    worker.page.emulate_media(reduced_motion='reduce')
    c = _check('setup-choices-durable-after-finish',set(saved['interests']) == set(desired) and saved['completed'] is True,
               {'state':saved})
    checks.append(c)
    return checks, {'contractEffects':contracts,'rendered':{'witness':'c8e-ui-onboarding','artifact':artifact,'url':worker.page.url},'savedChoices':saved}


def run_effects(worker, binding, inputs, root):
    group = binding.get('c8eUiEffect')
    if not group:
        return [], {}
    runner = {'layout':_layout,'launcher':_launcher,'onboarding':_onboarding,
              'design-shell':_design_shell,'pdf-shell':_pdf_shell}[group]
    return runner(worker,Path(root))
