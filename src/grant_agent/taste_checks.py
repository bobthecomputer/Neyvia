"""Deterministic page checks the C13 critic kept missing (taste.cl, section "deterministic page checks").

Each check reads only files the host already produced: the deliverable HTML and the render report with
its screenshots. No model call, no browser. Every hit carries a region or a text excerpt a person can
open, so a failure is a repairable difference row, not an opinion.

Checks (ids match the C lines in manuals/cl/taste.cl):
  theme-dark       block  the dark captures are dark and differ from the light ones; a page that declares a
                          dark theme but renders light is an invalid render (engine/adapter gap), a page with
                          no dark theme is a page defect. Either way the dark tiles prove nothing.
  side-void        block  a heading block whose side column (>= 25% of the content width) is empty beside it
                          (an eyebrow alone in a wide left column, round 3 and round 9 Luna landings)
  visible-dash     block  em/en dash or spaced hyphen as punctuation in visible text (no-slop decorative-dash),
                          e.g. eyebrows "01 — CAPABILITIES"
  stock-phrase     block  slogans from the taste.cl stock list in visible text
  abstract-art     warn   the largest inline illustration labels nothing concrete: only process words
                          (question, step, plan, decide...) and no number, name or subject noun
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re

THEME_DARK_MAX_LUMA = 110       # median luma (0..255) of a dark capture; r7-r8 dark captures measure 24-33
THEME_IDENTICAL_MEAN_DIFF = 2.0  # mean absolute luma difference below which light and dark are the same picture
SIDE_VOID_MIN_SHARE = 0.25       # side column width / content width
SIDE_VOID_MAX_FILL = 0.15        # share of the block's rows with any ink in that column (a lone eyebrow: 0.04-0.06)
SIDE_VOID_MIN_OTHER = 0.45       # the other side carries text through the block
SIDE_VOID_MIN_HEIGHT = 110       # px at 1440 desktop width
STOCK = ('think with care', 'make things real', 'what comes next', 'made for what comes next', 'curated for the curious',
         'collected in the wild', 'in motion', 'at the center', 'open possibility', 'from what if', "let's make a start",
         'your next good question', 'bring me the task', 'good help', 'more capable', 'built for', 'designed for', 'crafted',
         'reimagined', 'the future of', 'a new way to', 'everything you need')
PROCESS_WORDS = {'question', 'questions', 'open', 'way', 'through', 'understand', 'make', 'decide', 'idea', 'ideas', 'step',
                 'steps', 'plan', 'draft', 'working', 'checked', 'check', 'signal', 'clarity', 'clear', 'next', 'listen',
                 'sort', 'build', 'think', 'learn', 'explore', 'insight', 'flow', 'focus', 'path', 'journey', 'goal',
                 'notebook', 'answer', 'result', 'input', 'output', 'process', 'start', 'end', 'a', 'the', 'of', 'to', 'and'}


def _luma(path):
    from PIL import Image
    return Image.open(path).convert('L')


def _median(image):
    histogram = image.histogram()
    half, seen = image.width * image.height / 2, 0
    for value, count in enumerate(histogram):
        seen += count
        if seen >= half:
            return value
    return 255


def declares_dark(html):
    """The page has its own dark theme: a dark media query or a matchMedia dark branch."""
    return bool(re.search(r'prefers-color-scheme\s*:\s*dark', html, re.I))


def theme_dark(report, html):
    hits = []
    shots = {(row['viewport'], row['theme']): row['path'] for row in report.get('screenshots', [])}
    declared = declares_dark(html)
    for viewport in ('desktop', 'phone'):
        light, dark = shots.get((viewport, 'light')), shots.get((viewport, 'dark'))
        if not dark:
            hits.append({'viewport': viewport, 'cause': 'missing-capture', 'detail': 'no dark capture in the render report'})
            continue
        dark_image = _luma(dark)
        median = _median(dark_image)
        same = None
        if light and Path(light).is_file():
            light_image = _luma(light)
            if light_image.size == dark_image.size:
                from PIL import ImageChops, ImageStat
                same = ImageStat.Stat(ImageChops.difference(light_image, dark_image)).mean[0] < THEME_IDENTICAL_MEAN_DIFF
        if median > THEME_DARK_MAX_LUMA or same:
            cause = 'render-ignored-dark-theme' if declared else 'page-has-no-dark-theme'
            hits.append({'viewport': viewport, 'cause': cause, 'darkMedianLuma': median, 'identicalToLight': bool(same),
                         'capture': str(dark),
                         'detail': ('the page declares prefers-color-scheme: dark but the dark capture is light; the render '
                                    'is invalid and its dark tiles may not be scored' if declared else
                                    'the page has no dark theme; add one from prefers-color-scheme')})
    return hits


def _row_background(row):
    return Counter(value >> 3 for value in row).most_common(1)[0][0]


def side_voids(path, *, threshold=24):
    """Empty side columns beside heading blocks in a desktop full-page capture.

    Rows are segmented into blocks by blank bands; within a block the content box is cut into 24 strips and
    each strip's fill is the share of block rows that carry ink there. A run of strips at the left or right
    edge of the content box that stays nearly empty, while the other side carries text, is a void column.
    """
    image = _luma(path)
    width, height = image.size
    pixels = image.load()
    ink_rows = []
    columns = Counter()
    for y in range(height):
        row = [pixels[x, y] for x in range(0, width, 2)]
        background = _row_background(row) << 3
        xs = [index * 2 for index, value in enumerate(row) if abs(value - background - 4) > threshold]
        ink_rows.append(xs)
        columns.update(xs)
    if not columns:
        return []
    # Content box: the 20th percentile of left ink edges and the 80th of right edges over inked rows, so
    # full-bleed art, marquees and sticky bars do not widen it and short text lines do not narrow it.
    inked = [xs for xs in ink_rows if len(xs) >= 3]
    lefts, rights = sorted(xs[0] for xs in inked), sorted(xs[-1] for xs in inked)
    left, right = lefts[len(lefts) // 5], rights[len(rights) * 4 // 5]
    span = max(1, right - left)
    strips = 24
    content = [y for y in range(height) if sum(left <= x <= right for x in ink_rows[y]) >= 3]
    blocks, start, last = [], None, None
    for y in content:
        if start is None:
            start = last = y
        elif y - last > 28:
            blocks.append((start, last)); start = y
        last = y
    if start is not None:
        blocks.append((start, last))
    voids = []
    for top, bottom in blocks:
        tall = bottom - top + 1
        if tall < SIDE_VOID_MIN_HEIGHT:
            continue
        rows = range(top, bottom + 1)
        # Vertical rules (a 1-3 px column inked through the block) are borders, not content.
        column_fill = Counter(x for y in rows for x in ink_rows[y] if left <= x <= right)
        rules = {x for x, count in column_fill.items() if count > 0.9 * tall
                 and column_fill.get(x - 6, 0) < 0.1 * tall and column_fill.get(x + 6, 0) < 0.1 * tall}
        fill = []
        for strip in range(strips):
            low, high = left + span * strip / strips, left + span * (strip + 1) / strips
            fill.append(sum(any(low <= x < high and x not in rules for x in ink_rows[y]) for y in rows) / tall)
        # Left only: ragged right space beside left-aligned text is normal reading rhythm; an empty column that
        # pushes the heading to the right is the generated-template tell.
        for side in ('left',):
            order = range(strips) if side == 'left' else range(strips - 1, -1, -1)
            run = 0
            for strip in order:
                if fill[strip] > SIDE_VOID_MAX_FILL:
                    break
                run += 1
            share = run / strips
            if share < SIDE_VOID_MIN_SHARE or run == strips:
                continue
            other = fill[run:] if side == 'left' else fill[:strips - run]
            if max(other) < SIDE_VOID_MIN_OTHER:
                continue
            mirror = 0
            for strip in range(strips - 1, -1, -1):
                if fill[strip] > SIDE_VOID_MAX_FILL:
                    break
                mirror += 1
            if mirror * 2 >= run:
                continue  # centred block: the space is symmetric margin, not an empty column
            x0 = left + span * (0 if side == 'left' else (strips - run) / strips)
            voids.append({'side': side, 'region': [round(x0), top, round(span * share), tall], 'share': round(share, 2),
                          'columnFill': round(max(fill[:run] if side == 'left' else fill[strips - run:]), 2),
                          'capture': str(path)})
    return voids


class _Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip, self.text, self.svg_text, self.svg_depth, self.svgs = 0, [], [], 0, []
        self.described = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'template', 'noscript'}:
            self.skip += 1
        if tag in {'title', 'desc'} and self.svg_depth:
            self.described += 1  # accessible names describe the drawing; they are not drawn labels
        if tag == 'svg':
            if not self.svg_depth:
                self.svg_text = []
            self.svg_depth += 1

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'template', 'noscript'} and self.skip:
            self.skip -= 1
        if tag in {'title', 'desc'} and self.described:
            self.described -= 1
        if tag == 'svg' and self.svg_depth:
            self.svg_depth -= 1
            if not self.svg_depth:
                self.svgs.append(' '.join(self.svg_text))

    def handle_data(self, data):
        if self.skip or not data.strip():
            return
        self.text.append(data.strip())
        if self.svg_depth and not self.described:
            self.svg_text.append(data.strip())


def visible_text(html):
    parser = _Visible()
    parser.feed(html)
    return parser


def visible_dashes(html):
    from .neyvia_language import TextOutput, _html
    output = TextOutput()
    output.segments = _html('page.html', html)
    return [{'text': hit['text'], 'match': hit['match'], 'line': hit['line']} for hit in output.dashes()]


def stock_phrases(html):
    text = ' '.join(visible_text(html).text).lower().replace('’', "'")
    return [{'phrase': phrase, 'text': text[max(0, m.start() - 30):m.end() + 30]}
            for phrase in STOCK for m in re.finditer(r'\b' + re.escape(phrase) + r'\b', text)]


def abstract_art(html):
    """The labelled inline illustrations whose labels name nothing concrete."""
    hits = []
    for index, labels in enumerate(visible_text(html).svgs):
        words = re.findall(r"[A-Za-z][A-Za-z'-]*|\d[\d.,%:]*", labels)
        if len(words) < 3:
            continue  # an unlabelled drawing is judged by the critic, not by words
        # Sequence markers (01, 3) are not content; a measured number (2,827, 40%, 11:00) is.
        concrete = [w for w in words if (w[0].isdigit() and not re.fullmatch(r'0?\d', w)) or
                    (not w[0].isdigit() and w.lower() not in PROCESS_WORDS)]
        if not concrete:
            hits.append({'svg': index, 'labels': labels[:160],
                         'detail': 'every label is a process word; the drawing shows a metaphor, not the subject'})
    return hits


def _localize(report, base):
    """Screenshot paths are absolute where the host rendered; a copied proof folder keeps them beside report.json."""
    if base is None:
        return report
    shots = []
    for row in report.get('screenshots', []):
        local = Path(base) / Path(row['path']).name
        shots.append({**row, 'path': str(local if local.is_file() else row['path'])})
    return {**report, 'screenshots': shots}



def observed_checks(report):
    motion = report.get('motion', {})
    reduced = motion.get('reduced', {})
    normal = [s for s in motion.get('sequences', []) if not s.get('reduced')]
    sequence_hits = [] if motion.get('changed') and motion.get('meaningful', 0) >= 2 and any(not s.get('theme') and s.get('intermediate') and s.get('changed') for s in normal) else [{'detail': 'Need changing entrance frames and a meaningful before/intermediate/settled interaction, at least two observed transitions'}]
    theme_hits = [] if motion.get('themeToggle') else [{'detail': 'Need reversible light/dark toggle and observed intermediate normal-motion palette'}]
    reduced_hits = []
    if not reduced or not reduced.get('preference') or reduced.get('changed') or reduced.get('active', 0):
        reduced_hits.append({'detail': 'Reduced-motion frames missing, moving, preference not applied or active animation running'})
    if any(not s.get('reducedStill') for s in motion.get('sequences', []) if s.get('reduced')):
        reduced_hits.append({'detail': 'Reduced-motion interaction is still animating after its state change'})
    for error in motion.get('errors', []):
        sequence_hits.append({'detail': 'Motion observation unavailable: ' + error.get('message', '')})
    geometry = [hit for variant in report.get('variants', []) for hit in variant.get('diagramIssues', [])]
    if not report.get('variants') or any('diagramIssues' not in v for v in report.get('variants', [])):
        geometry.append({'detail': 'Missing rendered diagram geometry observation'})
    return [('motion-sequence', 'block', sequence_hits), ('theme-toggle', 'block', theme_hits),
            ('reduced-motion', 'block', reduced_hits), ('diagram-geometry', 'block', geometry)]

def control_coverage(report):
    """Require all discovered input modes to have observed page effects."""
    hits=[]
    if len(report.get('variants',[]))!=4:
        hits.append({'detail':'Missing actual four-variant interaction coverage'})
    for variant in report.get('variants',[]):
        for control in variant.get('controls',[]):
            failed=[{'mode':m['mode'],'effect':m.get('effect'),'status':m.get('status'),'error':m.get('error'),
                    'assertion':m.get('assertion',{}).get('text'),'coordinateBasis':m.get('gesturePathCompilation',{}).get('viewBox'),
                    'deliveredKeys':m.get('keyboardInput')}
                    for m in control.get('modes',[]) if not m.get('effect')]
            missing=sorted({'pointer','keyboard','touch'}-{m['mode'] for m in control.get('modes',[])})
            if failed or missing:
                hits.append({'selector':control['id'],'viewport':variant['viewport'],'theme':variant['theme'],
                    'detail':'Actual control has failed or unexercised input modes','label':control.get('label'),
                    'key':control.get('key'),'path':control.get('path'),'target':control.get('target'),
                    'modes':failed,'missingModes':missing})
        if variant.get('errors') or not variant.get('coverage_complete'):
            hits.append({'detail':'Incomplete actual variant coverage','viewport':variant['viewport'],
                         'theme':variant['theme'],'errors':variant.get('errors',[])})
    return hits


def page_checks(html_path, report, *, base=None, corrective=False, require_controls=False):
    """All deterministic checks for one rendered deliverable. report is the c13_render report dict;
    base is the folder of report.json, used when the absolute screenshot paths moved with the proof."""
    html = Path(html_path).read_text(encoding='utf-8')
    report = _localize(report, base)
    desktop_light = next((row['path'] for row in report.get('screenshots', [])
                          if row['viewport'] == 'desktop' and row['theme'] == 'light'), None)
    rows = [('theme-dark', 'block', theme_dark(report, html)),
            ('side-void', 'block', side_voids(desktop_light) if desktop_light and Path(desktop_light).is_file() else
             [{'detail': 'no desktop light capture'}]),
            ('visible-dash', 'block', visible_dashes(html)),
            ('stock-phrase', 'block', stock_phrases(html)),
             ('abstract-art', 'warn', abstract_art(html))] + observed_checks(report)
    if corrective:
        from .taste_spelling import check as spellcheck
        variants = report.get('variants', [])
        missing = [{'detail': 'Missing actual rendered corrective geometry'}] if not variants or any('corrective' not in v for v in variants) else []
        new_rows = [('spelling', 'block', spellcheck([r for v in variants for r in v.get('corrective', {}).get('text', [])])),
                 ('text-box-fit', 'block', missing + [r for v in variants for r in v.get('corrective', {}).get('overflow', [])]),
                 ('figure-centering', 'block', missing + [r for v in variants for r in v.get('corrective', {}).get('centering', [])])]
        rows += new_rows[:int(corrective)]
    if require_controls:rows.append(('control-coverage','block',control_coverage(report)))
    checks = [{'check': name, 'level': level, 'passed': not hits, 'hits': hits} for name, level, hits in rows]
    return {'schema': 'neyvia.taste-page-checks.v1', 'checks': checks,
            'blocks': sum(1 for row in checks if row['level'] == 'block' and not row['passed']),
            'renderValid': not any(hit.get('cause') == 'render-ignored-dark-theme' for hit in rows[0][2])}


def _summary(check):
    hits = check['hits']
    if check['check'] == 'theme-dark':
        return '; '.join(f"{hit['viewport']} {hit['cause']}" for hit in hits)
    if check['check'] == 'side-void':
        return '; '.join(f"empty {hit.get('side', '')} column at {hit.get('region')}" for hit in hits[:3])
    if check['check'] == 'visible-dash':
        return '; '.join(repr(hit['text'][:60]) for hit in hits[:3])
    if check['check'] == 'stock-phrase':
        return '; '.join(repr(hit['phrase']) for hit in hits[:3])
    def label(hit):
        value=hit.get('labels',hit.get('detail',''))
        return (', '.join(map(str,value)) if isinstance(value,list) else str(value))[:80]
    return '; '.join(label(hit) for hit in hits[:3])


FIX = {'control-coverage': 'Repair the recorded failing input mode or declare its actual accessible keyboard starter with data-c13-key. Preserve the mechanism. Every available control must yield a measured effect; do not bypass missing or undecided modes.',
       'spelling': 'Correct each unknown word using offline English/French dictionaries; keep technical names in code or exact credited citations',
       'text-box-fit': 'Widen or wrap the measured overflowing label inside its button or box, retaining readable font size and padding',
       'figure-centering': 'Align the figure center with its owning centered container',
       'motion-sequence': 'Animate one short entrance and the actual demonstrated state change; provide data-c13-motion-probe on its control; use observed attribute updates if CSS does not render',
       'theme-toggle': 'Provide data-c13-theme-toggle; switch light/dark tokens both ways with a smooth normal transition and immediate reduced-motion state',
       'reduced-motion': 'Guard all animation loops and timers with prefers-reduced-motion; draw the final state immediately and disable CSS transitions',
       'diagram-geometry': 'Fit SVG labels in their nodes and viewport; widen or wrap labels, separate nodes, keep connectors aligned; identify connector endpoint IDs with data-c13-connector',
'theme-dark': 'render-ignored-dark-theme is a renderer gap for the browser owner (the critique may not score '
                     'dark from these tiles); page-has-no-dark-theme -> add prefers-color-scheme: dark tokens',
       'side-void': 'put the label above the heading, or give the column real content (a figure, a fact, a list), '
                    'or let the heading take the full measure',
       'visible-dash': 'replace the dash with a colon, full stop or brackets; drop the 01/02 marker unless it is a real sequence',
       'stock-phrase': 'replace the slogan with the most specific true sentence about the subject, or delete it',
       'abstract-art': 'draw the subject itself (a real artifact, data, a named thing) instead of a process metaphor'}


def prompt_view(report):
    """Compact failed checks for model prompts: id, level, a short summary and the fix."""
    return [{'check': row['check'], 'level': row['level'], 'found': _summary(row), 'fix': FIX[row['check']], 'measurements': row['hits'][:6] if row['check'] in {'diagram-geometry','motion-sequence','theme-toggle','reduced-motion','control-coverage'} else []}
            for row in report['checks'] if not row['passed']]


def gate_reasons(report):
    return ['page check ' + row['check'] + ' failed: ' + _summary(row) for row in report['checks']
            if row['level'] == 'block' and not row['passed']]


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True, help='c13_render report.json')
    args = parser.parse_args(argv)
    result = page_checks(args.html, json.loads(args.report.read_text(encoding='utf-8')), base=args.report.parent)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 1 if result['blocks'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
