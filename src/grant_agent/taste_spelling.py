"""Offline English/French Hunspell checks of rendered text."""
from functools import lru_cache
from pathlib import Path
import re
import sys
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / '.agent_control/c13h-deps'))
DOMAIN = set('neyvia luna sol laya claude openai chatgpt codex obscura html css svg javascript api github hci doi acm workflow workflows inline viewport viewports figma webgl fullscreen dragdrop alphaslider fisheye multiscale zoomable toolglass touchpad trackpad stylus bimanual font typography tooltip tooltips dataset datasets lightbox scrollbar onboarding keyboard shortcut shortcuts raster vector render rendered rendering cursor cursors papercraft toggles toggle nav metadata backend frontend timestamp timestamps'.split())
DOMAIN.update('metres metre labelled labelling centred centring colour colours thurs'.split())
# Named typefaces are legitimate labels in the real print-bench font chooser.
# Their absence from general prose dictionaries must not flatten that UI into
# generic descriptions. Exact names only; near misspellings still fail.
DOMAIN.update('arial trebuchet verdana palatino tahoma helvetica unfiled'.split())


@lru_cache(maxsize=1)
def dictionaries():
    from spylls.hunspell import Dictionary
    base = REPO / '.agent_control/c13h-assets/dictionaries'
    return [Dictionary.from_files(str(base / lang / 'index')) for lang in ('en', 'fr')]


def check(records, allowed=()):
    words = DOMAIN | {str(word).casefold() for word in allowed}
    loaded = dictionaries()
    hits, seen = [], set()
    for record in records:
        if record.get('code') or record.get('citation'):
            continue
        for token in re.findall(r"[^\W\d_]+(?:['’][^\W\d_]+)?", record.get('text', ''), re.UNICODE):
            lower = token.casefold().replace('’', "'")
            if len(lower) < 3 or lower in words or lower in seen or token.isupper() and len(token) <= 4:
                continue
            seen.add(lower)
            stem = token.replace('’', "'").removesuffix("'s")
            if any(d.lookup(token) or d.lookup(lower) or stem != token and d.lookup(stem) for d in loaded):
                continue
            hits.append({'selector': record.get('selector', 'body'), 'word': token,
                         'detail': 'Unknown to offline English and French dictionaries: ' + token})
    return hits
