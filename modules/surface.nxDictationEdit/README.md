# nxDictationEdit

Provides COMMAND_LABELS, LANGUAGE_LABELS, shiftAnchor, endsMidSentence for Neyvia's UI state and behavior.

- **Public API:** `COMMAND_LABELS`, `LANGUAGE_LABELS`, `applySegments`, `dropLastPhrase`, `dropLastSentence`, `endsMidSentence`, `joinSpoken`, `lastSentenceStart`, `liveCommands`, `normalizeAnswer`, `previewParts`, `shiftAnchor`, `withoutOverlap`.
- **Manual:** [dictation.cl](../../manuals/cl/dictation.cl), [neyvia.cl](../../manuals/cl/neyvia.cl).
- **Contracts:** `run modules.verify-map()`.
- **Outcome contracts:** `dictation.anchor`, `dictation.answer`, `dictation.commands`, `dictation.delete-sentence`, `dictation.edit`, `dictation.join`, `dictation.overlap`, `dictation.preview`, `dictation.scratch`, `dictation.sentence-boundary`, `dictation.sentence-state`.
- **Dependencies:** [surface.nxDictationContracts](../surface.nxDictationContracts/README.md).
- **Owner:** Neyvia / nxDictationEdit.
- **Files:** [web/src/neyvia/next/nxDictationEdit.js](../../web/src/neyvia/next/nxDictationEdit.js).
