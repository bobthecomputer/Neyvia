# Neyvia brand contract

Neyvia is the final operator-facing product name.

Tagline: `A brighter tomorrow.`

The identity is the tree and the sun (plans/07-neyvia.md §2):

- **the sun** is intelligence and energy: the models and the runtime, where the light comes from
- **the tree** is your work: projects are branches, conversations are leaves, agents are growth
- **the light through the leaves** is the result that reaches the ground

## The mark

A broad tree against a banded southern sunset: warm, screen-printed bands from gold to brick red,
a soft glow behind the canopy, light breaking through the leaves. The logo carries the warmth; the
working surface stays calm and green.

One generator makes every asset, so the in-app mark and the app icons cannot drift apart:

    python scripts/brand/neyvia_sun_mark.py          # SVGs + registry data
    node scripts/brand/rasterize_neyvia_icons.mjs    # PNG sources and PWA icons
    npx tauri icon src-tauri/icons/neyvia-desktop-1024.png -o src-tauri/icons
    # mobile sets: run `tauri icon` on neyvia-mobile-1024.png into a scratch folder, copy ios/ and android/

## Product assets

- Mark (transparent): `docs/brand/neyvia-sun-mark.svg`, `web/public/icons/neyvia-mark.svg` (favicon, splash)
- App tiles: `docs/brand/neyvia-app-icon-light.svg`, `-dark.svg`, `-maskable.svg`
- Desktop icon source: `src-tauri/icons/neyvia-icon.svg` (the disc alone, so the taskbar shows a sun, not a tile)
- In-app mark: `ProviderMark id="neyvia"` (data in `web/src/neyvia/next/neyviaSunMarkData.js`);
  `web/src/neyvia/NeyviaBrandMark.jsx` renders the same mark for the classic screens
- Generated desktop and mobile icons: `src-tauri/icons/`
- Operator-provided visual references: `docs/brand/references/`

## Colours

Mark (sunset bands, top to bottom): `#ffd862` `#ffc850` `#ffb544` `#fd9e39` `#f88630` `#f06d29`
`#e65424` `#d6401f` `#bf2e1c` `#a3231a`; ink `#17110c`.

Interface (`web/src/neyvia/next/nxThemes.css`), three themes:

- Forest (dark): near-black green `#0a0f0c`, cream text `#f1ede3`, leaf green actions `#3d9a63` / `#5ec189`
- Morning (light): first sun through the canopy on warm paper `#f5f1e6`, deep leaf `#245a35`, mid leaf `#3a774b`,
  forest ink `#17221a`. Depth comes from light, not from darker boxes: one low sun top-left, so a card or a
  selected row is lit paper (`#fffdf9` / white) with a bright top edge and a soft green-grey shadow down-right
  (`--nx-shade`, never brown); the sidebar is the shaded forest edge (moss paper `#ebe9da` fading to `#dfe5d1`).
  Leaf light pools bottom-right; the morning sun warms the top-left only while something runs, with small
  warm flecks for komorebi. Running text is ochre `#7a4f08` (the bright amber stays for dots and fills), so every
  text colour reads at 4.5:1 or better. Generated apps (App SDK web template, details kit, Scroll Study) use the
  same recipe.
- Sunset: twilight `#141020`, a violet sky over a warm horizon with the first stars, sunset-orange actions `#ff7a3d`
- Night Green: dark water `#05141a`, a blue-green lake at night, sea-green actions `#1aa98a` / `#36d0a8`,
  light from the surface above and glowing specks instead of sun patches
- Every theme has a slow komorebi layer (round sun patches) behind the home screen; reduced motion stills it.
- The sun means something is happening: amber `#f2b441` = running, sunset orange `#f2a23c` = needs you.
  The primary send button is the only other place the sun appears.
- Display serif for greetings and screen titles: Newsreader (SIL OFL); body text stays Geist.

## Motion

Work in progress is a growing tree (`web/src/neyvia/next/nxTree.css`, `NxGrowingTree.jsx`): trunk, branches,
leaves, a sway in the sun, then it grows again. The startup splash, the thread, Missions and bubbles all use it.

## Layout

Everything in the shell is movable (Arrange mode, the strip's Arrange button, or press and hold a home
widget): regions are reordered and resized, the chat docks left or right of an open app, home widgets
are dragged, resized S/M/L, removed and added back. The saved layout is what the user wants;
`fitLayout` in `nxLayoutModel.js` decides what fits the window right now, so narrowing the window never
rewrites the user's choice. Scenes (Focus, Workshop, Cockpit, or saved) switch a whole setup in one tap; any chat
can float as a bubble with a state ring and a mini window. The model can do all of it: `neyvia.view.arrange`,
`view.scene`, `view.float`, `view.theme`.

## Compatibility boundary

User-facing copy, window titles, icons, and navigation use Neyvia.

Existing `fluxio.*` receipt schemas, `.agent_control` paths, environment variables, Python modules, command names, and stored mission records remain valid. They are protocol identifiers, not current marketing copy. Renaming them would break old missions and NAS installations without improving the visible product.
