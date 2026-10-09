# Neyvia details library: sources, decisions, credits

Plan 17 A2, 3 to 4 Oct 2026. These are the small moments that make Neyvia feel finished: a count that rolls, a meter you can trust, a delete that asks right where you clicked, a step that gets crossed out, a copy that says it worked, an empty state that points forward, and a loading state that never flashes. Each one is original Neyvia code. The ideas came from the sources below. Each source is credited, and every licence was read before anything was used.

- Code: `web/src/neyvia/next/details/` (`nxDetails.jsx` + `nxDetails.css` for Neyvia, `nxDetailsModel.js` for the shared logic, `kit/` for generated apps, `details.manifest.json` for the App SDK template).
- Manual: `manuals/design.manual.json`, chapter `details` (16 executable checks, procedures `use-detail` and `prove-details`, judgement `detail-fit`).
- Specimens: design lab `?only=details-numbers | details-actions | details-states`.
- Proof: `python scripts/prove_details.py --url <dev UI origin>` writes `proof/a2-details/report.json` and screenshots: 51 checks across the lab, Neyvia itself (checklist, status strip, chat, Arrange) and the kit.

## Sources studied

| Source | Licence (read in the repo) | What we took | What we left |
|---|---|---|---|
| **Rare UI**, Swami Malode, https://rareui.com, github.com/swamimalode07/rare-ui @ baff15e | **MIT + Commons Clause + Attribution.** Free to use inside an application, including commercially. Shipping any part needs a visible link to https://rareui.com. Selling or redistributing the components themselves (alone, bundled or ported) is not allowed. | Ideas only: the odometer wheel keyed by place, with an eased fade mask and a roll the short way (`animated-counter`). A confirm that opens in place, keeps focus and returns it (`delete-button`). A strike that rides on the text so wrapped lines each get one (`task-list`). A loader that "holds short of the end so the run can never finish before the image does" (`grid-reveal`). | All code. The components need `motion` (framer), Tailwind classes with raw hex colours, and 0.6 s durations. All three break Neyvia's block checks (raw colour, literal duration, the 180 to 320 ms band). We did not install with `npx shadcn add`: Neyvia is JSX with `.nx` CSS, not a shadcn/TS project, and the Commons Clause rules out redistributing ported components through the app template. Not adopted: fluid-orb, gravity-letters, gooey-nav, emoji-reaction (decoration, or new loops). |
| **NumberFlow**, Maxwell Barvian, github.com/barvian/number-flow @ c5906cf | MIT | `Intl.NumberFormat` for grouping and decimals; the mask technique (fading through the air above and below a digit); `linear()` support for spring easing. | The custom element, registered properties and the width animation (layout). |
| **motion-primitives**, ibelick, github.com/ibelick/motion-primitives @ 120f64f | MIT | `sliding-number` confirmed the per-digit wheel. | `text-shimmer`: an infinite loop with `background-clip: text`, which design-craft flags as glow and as a new loop. Neyvia's live state is StatusDot pulse or NxGrowingTree. |
| **Sonner** and Emil Kowalski's skills, github.com/emilkowalski/sonner @ 8e4662b, emilkowalski/skills | MIT | Press feedback `scale(0.97)` on the snappy spring; never `scale(0)`; exit faster than enter; no motion on keyboard actions (so focus is never animated). | Stagger. Neyvia's "lists don't stagger" wins. |
| **better-writing**, Jakub Krehel (already vendored, MIT) | MIT | Empty states point forward; a confirm repeats the consequence ("Delete Focus?"); errors say what failed ("Copy failed"). | none |

## What we designed ourselves (nothing fitted)

- **Calm loading** (`useCalmLoading`, kit `calmLoading`): a loading state shows only after 240 ms. Once shown, it stays at least 480 ms. Fast loads show nothing, and slow ones never flicker.
- **Honest meter** (`Meter`, kit `meter`): it fills with `transform` (not width) on the drift spring. With only an estimate it creeps along `0.9 × (1 − 1/(1+t)³)`, which stays strictly under 90 % until the work reports done.
- **Copy with a result** (`CopyButton`, `useCopy`, kit `copyButton`): the check is revealed left to right with `clip-path` (lucide icons, no hand-drawn SVG in Neyvia). It says "Copied" or "Copy failed", announces it, and resets after 1.6 s.
- **Rolling digits as generated text**: the wheel faces are CSS `::before` content. The page text, screen readers and agents that read the app (T18 perception) see the number exactly once. A column is never re-inserted into the page, because a moved node loses its running transition.
- **Haptic-like feedback** (`haptic`): an 8 ms vibration (a short double for confirm) only on touch phones, and never with reduced motion. On desktop the press scale does this job.

## Where Neyvia uses them

1. Agent checklist above the composer (`NxChecklist.jsx`): the "1 of 3" count rolls, and finished steps are crossed out by `Strike` instead of a static line-through.
2. Status strip (`NxIndicators.jsx`): the Night Shift count rolls. The Night Shift and usage bars are `Meter`s (transform, not width). The usage bar is now a real `progressbar` with a value.
3. Chat (`NxThread.jsx`): copy on tool output and diffs uses `CopyButton` (adds the drawn check, the announcement and the failure state). The chat skeleton waits 240 ms. An empty chat uses `EmptyState`.
4. Arrange (`NxArrange.jsx`): deleting a saved scene asks in place. Before, it was gone with one click and no undo.
5. Files (`NxFilesApp.jsx`): "Copy path" used to give no feedback at all. It now uses `CopyButton`. This one is wired but was not driven live, because Files needs a signed-in backend.

## Credits shown in the product

Neyvia's More menu credits Rare UI with a link to https://rareui.com. No Rare UI code is in Neyvia. The credit is there because the ideas are theirs. Generated apps carry the same credit line through `details.manifest.json` (`kit.credit`).
