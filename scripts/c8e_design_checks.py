"""Run existing design owners with owned output and a real headless browser.

The adapter uses the installed Vite CLI and production CL craft/details probes.
It keeps the candidate origin explicit and replaces CDP's ephemeral-port
transport with Neyvia's existing Playwright renderer. No fixture bus is admitted.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

MODES = ('build', 'craft', 'details-lab', 'details-shell', 'details-kit')


class ReviewPage:
    def __init__(self, page):
        self.page = page
    def __getattr__(self, name):
        return getattr(self.page, name)
    def evaluate(self, expression):
        # ChromiumReviewPage evaluates expressions as CDP does and explicitly
        # invokes only its () => observer convention. Playwright otherwise
        # invokes a function-valued assignment, which accidentally *calls* a
        # freshly installed refused clipboard function before the UI can use
        # it. Evaluate inside an outer callback to preserve the owner's API.
        return self.page.evaluate("""expression => {
          const source = expression.trimStart();
          return (0, eval)(source.startsWith('() =>') ? '(' + expression + ')()' : expression);
        }""", expression)
    def _send(self, method, args):
        if method != 'Emulation.setEmulatedMedia':
            raise ValueError('Unsupported details transport command: ' + method)
        features = {row['name']: row['value'] for row in args.get('features', [])}
        self.page.emulate_media(reduced_motion=features.get('prefers-reduced-motion', 'no-preference'))
        return {}


def actual_shell(runtime, url, out):
    """Drive the production saved-scene confirmation, including reload checks."""
    checks, observed = {}, {}
    with runtime.page(width=1280, height=900) as (page, _):
        def arrange():
            from playwright.sync_api import TimeoutError
            try:
                page.get_by_role('button', name='Skip setup', exact=True).wait_for(timeout=6000)
            except TimeoutError:
                pass
            else:
                page.get_by_role('button', name='Skip setup', exact=True).click()
                page.locator('.nx-onb-scrim').wait_for(state='hidden', timeout=15000)
            # The home widget and the status strip both expose Arrange. Drive
            # the documented strip control and honor already-open state after
            # reload, rather than letting an ambiguous selector pick a host.
            if not page.get_by_role('button', name='Save as scene', exact=True).is_visible():
                page.locator('.nx-strip').get_by_role('button', name='Arrange', exact=True).click()
        page.goto(url + '/control?ui=next', wait_until='domcontentloaded')
        page.locator('.nx-root').wait_for(timeout=45000)
        try:
            page.get_by_role('button', name='Skip setup', exact=True).click(timeout=3000)
        except Exception:
            pass
        arrange()
        theme = page.evaluate("""async () => {
          const response = await fetch('/api/ui/tools/call', {method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({tool:'neyvia.view.theme',arguments:{theme:'dark'}})});
          return {status:response.status,body:await response.json()};
        }""")
        page.locator('.nx-root[data-nx-theme="dark"]').wait_for(timeout=15000)
        checks['dark-theme-visible'] = theme['status'] == 200
        observed['theme'] = theme
        page.get_by_role('button', name='Save as scene', exact=True).click()
        name = 'C8e proof scene'
        page.get_by_label('Scene name', exact=True).fill(name)
        page.get_by_label('Scene name', exact=True).press('Enter')
        trigger = page.get_by_label('Delete scene ' + name, exact=True)
        trigger.wait_for()
        checks['scene-created-rendered'] = True
        page.reload(wait_until='domcontentloaded')
        page.locator('.nx-root').wait_for()
        arrange()
        trigger = page.get_by_label('Delete scene ' + name, exact=True)
        trigger.wait_for()
        checks['scene-survives-reload'] = True
        trigger.click()
        group = page.locator('.nx-confirm')
        group.wait_for()
        observed['asked'] = group.get_attribute('aria-label')
        checks['confirm-focuses-keep'] = page.evaluate("document.activeElement.textContent") == 'Keep'
        page.screenshot(path=str(out / 'shell-real-confirm.png'))
        page.keyboard.press('Escape')
        checks['escape-keeps-scene'] = trigger.is_visible() and group.count() == 0
        checks['escape-refocuses-trigger'] = page.evaluate('document.activeElement.getAttribute("aria-label")') == 'Delete scene ' + name
        trigger.click()
        page.locator('.nx-confirm').get_by_role('button', name='Delete', exact=True).click()
        trigger.wait_for(state='detached')
        checks['confirm-removes-scene'] = True
        page.reload(wait_until='domcontentloaded')
        page.locator('.nx-root').wait_for()
        arrange()
        checks['deletion-survives-reload'] = page.get_by_label('Delete scene ' + name, exact=True).count() == 0
        page.screenshot(path=str(out / 'shell-real-deleted.png'))
    report = out / 'report.json'
    previous = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    previous.setdefault('checks', {}).update({'shell-' + key: value for key, value in checks.items()})
    # Preserve the authored legacy assertion, now backed by the complete real
    # scene/confirmation/reload journey rather than the old mock-bus probe.
    previous['checks']['shell-arrange-confirm-dark'] = bool(checks) and all(checks.values())
    previous.setdefault('data', {})['shell-real-scenes'] = observed
    failed = sorted(key for key, passed in previous['checks'].items() if not passed)
    previous.update(status='fail' if failed else 'ok', failed=failed,
        boundary='Real rendered component lab and kit, plus actual saved-scene shell confirmation. No mock bus.')
    report.write_text(json.dumps(previous, indent=2) + '\n', encoding='utf-8')
    return 1 if failed else 0


def run(mode, root_value):
    if mode not in MODES:
        raise ValueError('Unknown design mode')
    root = Path(root_value).resolve()
    if root != Path.cwd().resolve():
        raise PermissionError('Design cwd must equal the owned root')
    source = Path(os.environ['NEYVIA_C8_SOURCE']).resolve(strict=True)
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(source / 'src'), str(source / 'scripts')]
    from grant_agent.proof_credential_guard import install as credential_guard
    from c8_scope import install as scope_guard
    credential_guard(root)
    scope_guard(allow_children=False, writable_root=root,
        headless_driver_source=source / 'src/grant_agent/perception_browser.py')
    if mode == 'build':
        out = root / '.agent_control/build-check'
        config = root / '.agent_control/c8e-build.config.mjs'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("import config from " + json.dumps((source / 'vite.config.mjs').as_posix()) + ";\n"
            "export default env => { const base=config(env); return {...base, cacheDir:" +
            json.dumps((root / '.agent_control/vite-cache').as_posix()) + ",build:{...base.build,outDir:" +
            json.dumps(out.as_posix()) + "}}; };\n", encoding='utf-8')
        node = shutil.which('node')
        if not node:
            raise RuntimeError('Installed Node executable missing')
        command = [node, str(source / 'node_modules/vite/bin/vite.js'), 'build', '--config', str(config),
            '--configLoader', 'runner', '--outDir', str(out)]
        completed = subprocess.run(command, cwd=source, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=115, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        (root / '.agent_control/build-check.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        if completed.returncode or not (out / 'index.html').is_file():
            raise RuntimeError('Actual Vite build failed; inspect retained build-check.log')
        print('Actual Vite production output completed:', out)
        return
    request_path = root / ('.agent_control/details/request.json' if mode.startswith('details-') else '.agent_control/craft/requests/c8.json')
    request = json.loads(request_path.read_text(encoding='utf-8'))
    parsed = urlsplit(request['url'])
    from c8_scope import assigned_ports
    if parsed.hostname != '127.0.0.1' or parsed.scheme != 'http' or parsed.port not in assigned_ports():
        raise PermissionError('Design requires an explicit owned candidate origin')
    from c8_headless import install as headless_guard
    headless_guard(root, parsed.port)
    from grant_agent.native_tools import ReusablePlaywrightRuntime
    runtime = ReusablePlaywrightRuntime(root)
    from grant_agent import chromium_review
    @contextmanager
    def review(*, width, height):
        with runtime.page(width=width, height=height) as (page, _):
            yield ReviewPage(page)
    chromium_review.chromium_review_page = review
    try:
        if mode == 'craft':
            from grant_agent.cl_skill import main
            code = main(['check', '--latest-request', str(request_path.parent)])
        else:
            out = root / request.get('out', 'proof/a2-details')
            out.mkdir(parents=True, exist_ok=True)
            if mode == 'details-shell':
                code = actual_shell(runtime, request['url'].rstrip('/'), out)
            else:
                import prove_details
                code = prove_details.main(['--request', str(request_path), '--part', mode.removeprefix('details-')])
        if code:
            raise RuntimeError('Production design helper refused its actual checks; inspect retained report')
    finally:
        runtime.close()


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2])
