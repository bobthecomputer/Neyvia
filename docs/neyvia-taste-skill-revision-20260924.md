# Neyvia taste guidance revision — 2026-09-24

## Why

The prior guidance correctly favored rendered criticism and calm hierarchy, but it did not encode the accepted visual direction in the user's six screenshots or distinguish a clean `preview.taste` report from aesthetic judgment. It also left two known proof gaps: a Light control that still rendered dark, and a scripted stream described beside live-model claims.

## Checkable cases

This is an instruction-coverage check, not a measured improvement in model design ability. Each case scores 1 only if the skill gives an explicit action and proof boundary.

| Case | Expected reviewer behavior | Before | After |
| --- | --- | ---: | ---: |
| Accepted screenshot | Keep the ink-navy, blue-action, gold-voice grammar, bundled Geist, quiet sidebar, and compact phone composer without letting the review panel bury the app. | 0 | 1 |
| Clean lens report | Inspect desktop and phone pixels; treat 100/100 as defect screening, not beauty proof. | 0 | 1 |
| Light or System selection | Inspect the selected mode and reject dark or white-on-white fallbacks rather than relying on a dark screenshot. | 0 | 1 |
| Stream evidence | Compare pending, summary, partial answer, and completion; separate scripted rendering from a live model and installed app. | 0 | 1 |

Explicit instruction coverage: **0/4 → 4/4**. The older skills had useful general principles, but none of these four acceptance boundaries was explicit.

## Changes and retained constraints

`neyvia-aesthetic-innovation-master` now records the user's current visual direction, puts the artifact ahead of evidence, requires rendered interpretation of lens findings, and separates streamed UI mechanics from provider behavior. `neyvia-design-taste-v2` now applies the same boundaries to its state review and replaces an arbitrary target score with a like-for-like comparison rule.

The edits retain user screenshots as authority, real pixel inspection, accessibility states, restrained novelty, and the rule that a metric cannot certify beauty. They do not alter product code, runtime permissions, or publication state.

## Limit

The 4/4 result checks the written guidance only. The next UI change must demonstrate it through the actual Light surface, a live turn, desktop and phone Preview, and the installed app before claiming product improvement.
