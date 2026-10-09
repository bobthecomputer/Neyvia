---
name: neyvia-design-taste-v2
description: Rendered visual critic and iteration engine. Use during and after UI implementation to prevent intention-only design claims.
version: 2.0
---

# Neyvia Design Taste V2 — Visual Critic

Do not declare a design beautiful because the CSS is clean, the component system is consistent, the prompt was fulfilled, or you can explain the intention convincingly.

The rendered experience is ground truth.

Neyvia's current screenshot reference favors ink navy, one action blue, a restrained north-star gold, bundled Geist, one icon language, quiet navigation, and an artifact or conversation that dominates its workspace. Carry the same hierarchy into light themes rather than keeping a dark screen behind a Light control.

## Required loop

> render → five-second scan → field analysis → anti-slop pass → state matrix → alternatives → comparative review → revise → render again

## Five-second scan

Ask:

1. Where does the eye land first?
2. Is that the correct object?
3. What competes with it?
4. Does the screen feel composed or assembled?
5. Is personality present without relying on logo or accent color?

Never rationalize unexpected attention.

## Field analysis

Inspect visual mass, alignment lines, rhythm, density, contrast topology, and salience budget. Count bordered boxes, cards, pills, badges, colored icons, fills, shadows, glass layers, helper sentences, and permanent actions. If removing 20–40% would not hurt comprehension, remove them.

Keep evidence subordinate to the object it proves. In Preview, the running app should stay visible when its design review opens; thumbnails and findings may expand on demand. On phones, keep the composer and current action reachable without covering most of the screen.

## Typography and geometry

Remove unnecessary words before shrinking them. Inspect size, weight, line height, wrapping, numeric alignment, icon baselines, optical heights, nested radii, panel edges, hover/focus consistency, and overlay anchoring. High-end quality often comes from many coherent 2–6px decisions.

## Color

Imagine grayscale. If hierarchy collapses, color is masking structure. Saturated color must carry stable identity, state, diff meaning, syntax, destructive action, or verification. Agent color binds to stable identity, never list position.

## State matrix

Inspect empty, sparse, typical, dense, loading, partial loading, error, recoverable error, offline/reconnect, selected, hover, keyboard focus, disabled, long text, compact viewport, large viewport, accessibility scaling, and reduced motion where relevant. The weakest realistic state caps quality.

Include the selected appearance mode and a live-operation frame. A dark screenshot cannot prove Light or System. A scripted stream can prove message rendering, while a real model turn is needed to prove provider timing and event order. Label the build, host, route, and state on every proof image; an older installed app is a different surface from a hot-reloaded browser.

## Alternative rule

When materially weak, create three genuine directions:

- reduction: remove structure and let content carry more;
- rehierarchy: keep information but change the primary object;
- reframe: alter the interaction model—inline vs modal, temporal vs tabbed, command vs toolbar, spatial vs list.

Color variants are not alternatives.

## Evidence and judgment

`preview.taste` can expose collisions, contrast failures, overflow, tiny targets, and font drift. Inspect the returned screenshots before accepting or rejecting a finding. A clean automated report is not a beauty score, and a false positive should be recorded with the visual reason, not silently ignored.

For a substantial review, assess these dimensions after rendered inspection:

- first-glance hierarchy
- calm
- information density
- coherence
- typography
- tonal depth
- semantic color
- geometry/alignment
- progressive disclosure
- interaction affordance
- native/platform feel
- motion/state continuity
- failure/recovery quality
- scalability under feature growth
- distinctiveness

Name the strongest and weakest visible decisions and the single highest-leverage revision. Use a numeric score only when comparing the same rubric and states before and after; never raise a score merely to finish. Re-render the exact failure state after the fix.

Use causal critique:

- “The inspector has equal contrast to the workspace, so metadata competes with the object.”
- “Five grouping mechanisms are visible; keep tonal fill and spacing, remove redundant border and heading.”
- “The selected state introduces a new radius and stroke language.”

Avoid vague phrases such as modern, clean, premium, more pop, or needs polish.
