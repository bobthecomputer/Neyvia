# neyviaShellPreferences

Provides NEYVIA_SHELL_PREFERENCES_KEY, NEYVIA_SHELL_SURFACES, NEYVIA_UI_PRESETS, NEYVIA_APPEARANCE_THEMES for Neyvia's UI state and behavior.

- **Public API:** `DEFAULT_NEYVIA_SHELL_PREFERENCES`, `NEYVIA_APPEARANCE_THEMES`, `NEYVIA_EFFECT_INTENSITIES`, `NEYVIA_SESSION_TOOL_PANE_LAYOUTS`, `NEYVIA_SHELL_PREFERENCES_KEY`, `NEYVIA_SHELL_SURFACES`, `NEYVIA_SYSTEM_PROMPT_PROFILES`, `NEYVIA_TEXT_SIZES`, `NEYVIA_TOOLBAR_CATALOG`, `NEYVIA_TRANSPARENCY_LEVELS`, `NEYVIA_UI_PRESETS`, `appearanceThemeForScheme`, `applyNeyviaAdaptiveExperience`, `applyNeyviaUiPreset`, `densityForUiPreset`, `loadNeyviaShellPreferences`, `neyviaIdToShellSurface`, `neyviaShellCssVariables`, `normalizeNeyviaShellPreferences`, `resolveEffectiveColorScheme`, `saveNeyviaShellPreferences`, `shellSurfaceToNeyviaId`.
- **Manual:** [neyvia.cl](../../manuals/cl/neyvia.cl), [settings.cl](../../manuals/cl/settings.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `preferences.normalize`.
- **Dependencies:** [surface.neyviaFrontendContracts](../surface.neyviaFrontendContracts/README.md).
- **Owner:** Neyvia / neyviaShellPreferences.
- **Files:** [web/src/neyvia/neyviaShellPreferences.js](../../web/src/neyvia/neyviaShellPreferences.js).
