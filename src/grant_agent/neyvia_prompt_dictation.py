"""Prompt-only text policy shared by HTTP, desktop and model dictation callers.

Commands describe editor actions; this module never sends a prompt or edits a note.
Only final, unquoted command clauses may act. Live recognition remains a preview.
"""
from __future__ import annotations

import re

_FR = set("je tu nous vous le la les un une des du de ce ces ma mon mes ton ta tes leur leurs est sont pour avec dans sur cette ceci cela peux peut veux merci ouvre ajoute écris écrire fais donne explique prépare demain bonjour français envoie annule".split())
_EN = set("i you we they the a an is are for with this that please can could want write add open build tomorrow hello english send cancel".split())
_COMMANDS = {
    "undo that": "undo", "annule ça": "undo", "annule ca": "undo",
    "scratch that": "scratch", "strike that": "scratch", "efface ça": "scratch", "efface ca": "scratch",
    "delete the last sentence": "delete_last_sentence", "supprime la dernière phrase": "delete_last_sentence",
    "new line": "new_line", "newline": "new_line", "next line": "new_line", "à la ligne": "new_line", "a la ligne": "new_line", "nouvelle ligne": "new_line",
    "new paragraph": "new_paragraph", "nouveau paragraphe": "new_paragraph",
    "send it": "send", "send": "send", "send that": "send", "envoie": "send", "envoie-le": "send", "envoie le": "send",
    "cancel": "cancel", "cancel that": "cancel", "annule": "cancel", "undo": "undo",
    "delete last sentence": "delete_last_sentence",
}
_NAMES = {
    r"\b(?:claude|cloud|clod|clawed)\s+code\b": "Claude Code",
    r"\bcode\s*(?:x|ex)\b|\b(?:codex|codecs)\b": "Codex",
    r"\b(?:neyvia|ney\s*via|nevia|neevia|nayvia|naivia)\b": "Neyvia",
    r"\blaya\b|\blay\s+a\b": "LAYA",
    r"\bphonon(?:\s+(?:two|2)|-2)\b": "Phonon-2",
    r"\b(?:quen|qwen)\b": "Qwen",
    r"\bopen\s*code\b": "OpenCode",
}
BUILTIN_NAMES = {"Claude Code": ["claude code", "cloud code", "clawed code", "clod code"],
                 "Codex": ["codex", "code x", "code ex", "codecs"],
                 "Neyvia": ["neyvia", "nevia", "neevia", "nayvia", "ney via", "naivia"],
                 "LAYA": ["laya", "lay a"], "Phonon-2": ["phonon two", "phonon 2", "phonon-2"],
                 "Qwen": ["quen", "qwen"], "OpenCode": ["open code", "opencode"], "Tauri": ["tauri"]}
_QUOTED = re.compile(r'("[^"\n]*"|“[^”\n]*”|«[^»\n]*»|`[^`\n]*`|(?<!\w)\'[^\'\n]*\'(?!\w))')


def detect_language(text: str, history=()) -> dict:
    words = re.findall(r"[^\W\d_]+", text.casefold())
    fr = sum(word in _FR for word in words)
    en = sum(word in _EN for word in words)
    # Accents are supporting evidence; a proper name alone is not a French utterance.
    if fr:
        fr += min(2, len(re.findall(r"[àâçéèêëîïôûùüœ]", text.casefold()))) * .5
    if fr >= 2 and en >= 2:
        language = "mixed"
    elif fr or en:
        language = "fr" if fr > en else "en"
    else:
        language = "unknown"
        for prior in reversed(list(history)[-20:]):
            previous = {"language": prior, "route": "qwen" if prior in {"fr", "mixed"} else "phonon2"} if prior in {"en", "fr", "mixed"} else detect_language(str(prior))
            if previous["language"] != "unknown":
                return {**previous, "language_confidence": .45, "language_source": "history"}
    return {"language": language, "language_confidence": round(max(fr, en) / (fr + en), 3) if fr + en else 0,
            "language_source": "text", "route": "qwen" if language in {"fr", "mixed"} else "phonon2"}


def _cleanup(text: str, names: dict | None = None, terminal=True) -> tuple[str, list]:
    fixes = []
    def replace(pattern, replacement, kind, flags=0):
        nonlocal text
        def apply(match):
            new = replacement(match) if callable(replacement) else replacement
            if match[0] != new:
                fixes.append({"from": match[0], "to": new, "kind": kind})
            return new
        text = re.sub(pattern, apply, text, flags=flags)
    replace(r"\b(?:um+|uh+|erm|hmm|euh+|bah)\b[, ]*", "", "filler", re.I)
    replace(r"\b(\w+)(\s+\1)+\b", lambda m: m[1], "repeat", re.I)
    for pattern, replacement in _NAMES.items():
        replace(pattern, replacement, "name", re.I)
    replace(r"\bqueen\b(?=\s+(?:asr|model))|(?<=asr )\bqueen\b|(?<=model )\bqueen\b", "Qwen", "name", re.I)
    replace(r"\btory\b(?=\s+(?:app|build))|(?<=app )\btory\b|(?<=build )\btory\b", "Tauri", "name", re.I)
    for spoken, canonical in (names or {}).items():
        if isinstance(spoken, str) and isinstance(canonical, str) and spoken.strip():
            replace(r"(?<!\w)" + re.escape(spoken) + r"(?!\w)", canonical, "name", re.I)
    replace(r"[ \t]{2,}", " ", "punctuation")
    replace(r" +([,.;!?])", lambda m: m[1], "punctuation")
    text = text.strip()
    replace(r"(^|[.!?]\s+|\n+)([a-zà-ÿ])", lambda m: m[1] + m[2].upper(), "capital")
    if terminal and text and text[-1] not in '.!?;:,\n"”»`' and not text.endswith("'"):
        mark = "?" if re.match(r"(?i)^(what|how|why|can|could|should|would|is|are|do|does|did|est-ce que|pourquoi|comment|quand|où)\b", text) else "."
        fixes.append({"from": "", "to": mark, "kind": "punctuation"})
        text += mark
    return text, fixes


def process_prompt(text: str, history=(), final: bool = True, names: dict | None = None, stable: bool = False) -> dict:
    """Parse the shared policy and enforce its manual postconditions inline."""
    from .proofs_dictation import check_prompt
    result = _process_prompt(text, history, final, names, stable)
    check_prompt(text, history, final, names, stable, result)
    return result


def _process_prompt(text: str, history=(), final: bool = True, names: dict | None = None, stable: bool = False) -> dict:
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("Dictation text must be a string of at most 100000 characters")
    if not isinstance(history, (list, tuple)) or len(history) > 20 or any(not isinstance(row, str) or len(row) > 100_000 for row in history):
        raise ValueError("Dictation history must contain at most twenty utterances")
    language = detect_language(text, history)
    if not final and not stable:
        return {"text": text, "segments": [{"type": "text", "text": text}] if text else [],
                "commands": [], "fixes": [], "requiresPreview": True, **language}
    segments = []
    # Quotes are opaque. The rest is split into complete clauses; command phrases
    # inside an ordinary sentence stay literal except explicit line/paragraph breaks.
    anywhere = {"new_line", "new_paragraph", "scratch"}
    breaks = "|".join(re.escape(k) for k, v in sorted(_COMMANDS.items(), key=lambda row: -len(row[0])) if v in anywhere)
    enders = "|".join(re.escape(k) for k, v in sorted(_COMMANDS.items(), key=lambda row: -len(row[0])) if v in {"send", "delete_last_sentence"})
    # Whole-only actions are checked against the whole utterance, never subclauses.
    whole = _COMMANDS.get(text.casefold().strip(" \t.,;!?"))
    if final and whole:
        return {"text": "", "segments": [{"type": "command", "op": whole, "said": text.strip()}],
                "commands": [{"op": whole}], "fixes": [], "requiresPreview": True, **language}
    parts = _QUOTED.split(text)
    for part_index, part in enumerate(parts):
        if not part:
            continue
        if _QUOTED.fullmatch(part):
            if segments and segments[-1]["type"] == "text":
                segments[-1]["text"] += part
            else:
                segments.append({"type": "text", "text": part})
            continue
        for clause in [part]:
            normalized = clause.casefold().strip(" \t.,;!?")
            command = _COMMANDS.get(normalized)
            if command not in anywhere:
                command = None
            if command:
                segments.append({"type": "command", "op": command, "said": clause.strip()})
                continue
            pattern = r"(?i)((?:literally\s+)?\b(?:" + breaks + r")\b"
            if final and part_index == len(parts) - 1:
                pattern += r"|\b(?:" + enders + r")\b[.!?,;]*\s*$"
            pattern += ")"
            for bit in re.split(pattern, clause):
                if not bit:
                    continue
                if not bit.strip(" \t\n.,;!?"):
                    continue
                literal = bit.casefold().startswith("literally ")
                if literal:
                    bit = bit[len("literally "):]
                command = None if literal else _COMMANDS.get(bit.casefold().strip(" \t.,;!?"))
                if command:
                    segments.append({"type": "command", "op": command, "said": bit.strip()})
                elif segments and segments[-1]["type"] == "text":
                    segments[-1]["text"] += bit
                else:
                    segments.append({"type": "text", "text": bit})
    fixes = []
    for index, segment in enumerate(segments):
        if segment["type"] == "text":
            if index and segments[index - 1]["type"] == "command":
                prefix = re.match(r"^[\s.,;:]+", segment["text"])
                if prefix:
                    fixes.append({"from": prefix[0], "to": "", "kind": "punctuation"})
                    segment["text"] = segment["text"][prefix.end():]
            segment["text"], changes = _cleanup(segment["text"], names, terminal=final)
            fixes.extend(changes)
    segments = [s for s in segments if s["type"] != "text" or s["text"]]
    return {"text": " ".join(s["text"] for s in segments if s["type"] == "text"), "segments": segments,
            "commands": [{"op": s["op"]} for s in segments if s["type"] == "command"], "fixes": fixes, "requiresPreview": True, **language}


def revision_span(old: str, new: str) -> dict | None:
    if not old or new.startswith(old):
        return None
    at = 0
    while at < min(len(old), len(new)) and old[at] == new[at]:
        at += 1
    return {"at": at, "from": old[at:], "to": new[at:]}


def agreed_prefix(old: str, new: str) -> str:
    """LocalAgreement-2: only complete words at the shared leading boundary."""
    count = 0
    for before, after in zip(word_spans(old), word_spans(new)):
        if before[0] != after[0]:
            break
        count += 1
    return prefix_words(new, count)


def word_spans(text: str) -> list[tuple[str, int]]:
    """Normalised word + raw end offset, keeping offsets across punctuation/stutters."""
    words = []
    for match in re.finditer(r"\S+", text):
        word = re.sub(r"^[^\w]+|[^\w]+$", "", match[0].casefold())
        if not word:
            continue
        if words and words[-1][0] == word:
            words[-1] = (word, match.end())
        else:
            words.append((word, match.end()))
    return words


def prefix_words(text: str, count: int) -> str:
    words = word_spans(text)
    return text[:words[min(count, len(words)) - 1][1]] if count and words else ""


def frontier_text(previous: str, partial: str, committed: str, agreed: str, new_decode: bool) -> tuple[str, str]:
    """Keep the word frontier while explicitly revising its spelling from new evidence.

    The engine previews from the open piece's start, so current tokens share the
    utterance's origin. Word offsets (rather than cleaned string lengths) prevent
    a stutter or a comma from duplicating the stable prefix in provisional text.
    """
    count = max(len(word_spans(previous)), len(word_spans(committed)), len(word_spans(agreed)))
    raw = prefix_words(partial, count) if new_decode and len(word_spans(partial)) >= count else previous
    if len(word_spans(committed)) > len(word_spans(raw)):
        raw = committed
    if not raw:
        return "", partial
    current, stable_words = word_spans(partial), word_spans(raw)
    if len(current) >= len(stable_words) and [w[0] for w in current[:len(stable_words)]] == [w[0] for w in stable_words]:
        return raw, partial[current[len(stable_words) - 1][1]:].lstrip()
    return raw, partial
