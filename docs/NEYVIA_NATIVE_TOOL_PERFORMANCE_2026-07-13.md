# Neyvia native tool performance proof

Date: 2026-07-13

## Change

Desktop screenshot and annotation calls now use a supervised persistent Python worker. The worker keeps one Playwright Chromium process warm and creates a new isolated browser context for every request. If the worker exits, returns malformed protocol data, or stops responding, Tauri kills it, starts it once more, and then falls back to the existing one-shot CLI path.

Only `preview.screenshot` and `preview.annotate` use the serialized capture worker. Search, video, context, and file tools retain independent CLI execution, so a long capture cannot block unrelated tool categories.

## Measured baseline

Local static page, 1000 by 700 viewport, no artificial delay:

- first one-shot screenshot: 12,076 ms
- second one-shot screenshot: 1,793 ms
- third one-shot screenshot: 1,290 ms
- one-shot Python CLI process and repository search: 960 ms
- direct registry repository search: 550 ms

The first screenshot included a cold Playwright and Chromium startup. Later one-shot calls still launched new processes, but benefited from operating-system caches.

## Measured persistent worker

Same local target and viewport:

- first pooled screenshot: 1,847 ms
- second pooled screenshot: 892 ms
- pooled annotation with screenshot, crop, overlay, receipt, and hashes: 793 ms
- browser starts across all three requests: 1
- isolated contexts created: 3

This reduced the measured cold capture by about 85 percent. The warm screenshot was about 50 percent faster than the comparable second one-shot capture. The pooled annotation completed in under one second in this run.

A later release-gate rerun under concurrent build load recorded 5,611 ms cold, 775 ms warm screenshot, and 796 ms warm annotation. The browser still started exactly once and all three calls used separate contexts. This confirms that cold startup varies with machine load while the reusable warm path remains below one second on this machine.

## Isolation and lifecycle

- Browser process: reused.
- Browser context, cookies, local storage, permissions, and pages: new for every call.
- Context: explicitly closed after every call.
- Worker: scoped to the resolved workspace and NAS root.
- Root change: old worker is killed and replaced.
- Protocol mismatch, EOF, timeout, or crash: one restart attempt, then CLI fallback.
- App exit: worker uses kill-on-drop and also exits naturally when stdin closes.

The context-per-request model follows Playwright's recommended isolation approach: https://playwright.dev/python/docs/browser-contexts

## Rebuilt desktop packages

- MSI SHA-256: `b48fa974950bdb62aa477135ef2a8cbbf60b1c262868e4bddd0ddbc94eeef1a6`
- NSIS SHA-256: `5c50732ed3a3a0bd3d2ca94a94d0f56216346f04a70a30706270173bbce7c1fb`
