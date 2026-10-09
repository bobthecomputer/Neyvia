"""Task-only restrictions on real Playwright transports; no result substitution."""
from pathlib import Path
from urllib.parse import urlsplit

BLOCK_SERVICE_WORKERS = """(() => {
  let workers;
  try {
    workers = navigator.serviceWorker;
  } catch (error) {
    if (error.name === 'SecurityError') return;
    throw error;
  }
  if (workers) workers.register = () => Promise.reject(
    new DOMException('Service worker registration is disabled for this owned proof context.', 'SecurityError'));
})();"""


def block_service_workers(context):
    # Playwright's built-in block reads the getter in every frame without a
    # guard, which raises in an opaque sandbox before any app code executes.
    context.add_init_script(BLOCK_SERVICE_WORKERS)
    return context


def install(root, port):
    from playwright.sync_api import Browser, BrowserType
    root = Path(root).resolve()
    def route(request):
        url = urlsplit(request.request.url)
        if url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost'} and url.port == port:
            request.continue_()
        else:
            request.abort()
    def guarded(context):
        block_service_workers(context)
        context.route('**/*', route)
        # Authenticate the actual fresh context with this disposable backend.
        # This grants no saved account, desktop, provider or other origin.
        response = context.request.post(f'http://127.0.0.1:{port}/api/auth/local-session', data={})
        if not response.ok:
            raise PermissionError('Owned headless context could not authenticate locally')
        return context
    launch, persistent, context = BrowserType.launch, BrowserType.launch_persistent_context, Browser.new_context
    def headless(self, *args, **kwargs):
        import os
        if os.environ.get('NEYVIA_C8_ENGINE') == 'obscura':
            raise PermissionError('This C8 run grants only the explicit Obscura CDP transport')
        if kwargs.get('headless') is not True:
            raise PermissionError('C8 grants only explicitly headless Chromium')
        return launch(self, *args, **kwargs)
    def owned(self, user_data_dir, **kwargs):
        import os
        if os.environ.get('NEYVIA_C8_ENGINE') == 'obscura':
            raise PermissionError('This C8 run grants only the explicit Obscura CDP transport')
        if kwargs.get('headless') is not True or not Path(user_data_dir).resolve().is_relative_to(root):
            raise PermissionError('C8 requires a headless browser with a fresh task-owned profile')
        kwargs.update(accept_downloads=False, service_workers='allow')
        return guarded(persistent(self, user_data_dir, **kwargs))
    def isolated(self, **kwargs):
        kwargs.update(accept_downloads=False, service_workers='allow')
        return guarded(context(self, **kwargs))
    BrowserType.launch, BrowserType.launch_persistent_context, Browser.new_context = headless, owned, isolated


def install_capture_runtime(root):
    """Select the existing Playwright capture seam; CDP uses an unassigned port."""
    from contextlib import contextmanager
    from grant_agent.native_tools import NativeToolRegistry, ReusablePlaywrightRuntime
    original = NativeToolRegistry.__init__
    class CaptureRuntime:
        def __init__(self):
            self.browser_starts = self.contexts_created = 0
        @contextmanager
        def page(self, **dimensions):
            runtime = ReusablePlaywrightRuntime(root)
            try:
                with runtime.page(**dimensions) as page:
                    self.browser_starts += runtime.browser_starts
                    self.contexts_created += runtime.contexts_created
                    yield page
            finally:
                runtime.close()
    def registry(self, *args, **kwargs):
        if kwargs.get('browser_runtime') is None:
            kwargs['browser_runtime'] = CaptureRuntime()
        original(self, *args, **kwargs)
    NativeToolRegistry.__init__ = registry
