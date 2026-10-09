"""Actual bounded Arlington PDF extraction and a disposable over-cap transport."""
from __future__ import annotations

from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from grant_agent import native_tools

URL = 'https://www.arlingtontx.gov/files/assets/city/v/2/grants-management/documents/2025-2029-consolidated-plan.pdf'
LIMIT = 32 * 1024 * 1024


def failure_checks(registry):
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    blank = output.getvalue()
    writer.encrypt('disposable-fixture')
    output = io.BytesIO()
    writer.write(output)
    rows = []
    for name, data in [('malformed', b'%PDF-1.7\ninvalid\n%%EOF'),
                       ('truncated', blank[:-20]), ('encrypted', output.getvalue()), ('noOCR', blank)]:
        class Response:
            headers = Message()
            headers['Content-Type'] = 'application/pdf'
            headers['Content-Length'] = str(len(data))
            status = 200

            def geturl(self):
                return 'https://public-fixture.invalid/' + name + '.pdf'

        with patch.object(native_tools, '_request', return_value=(data, Response())):
            actual = registry.call('web.fetch', {'url': Response().geturl(), 'refresh': True})
        rows.append({'name': name + 'Refused', 'passed': not actual['ok'],
                     'fixture': 'Disposable serialized bytes; explicitly replaced HTTP transport',
                     'reason': actual['error'], 'receiptPath': actual['receipt_path']})
    for name, options in [('defaultHTML2MiB', {}), ('optionalPDFHTML2MiB', {'pdf_max_bytes': LIMIT})]:
        class HTML(io.BytesIO):
            headers = Message()
            headers['Content-Type'] = 'text/html'

        with patch.object(native_tools.urllib.request, 'urlopen', return_value=HTML(b'x' * (2 * 1024 * 1024 + 1))):
            data, _ = native_tools._request('https://public-fixture.invalid/page', **options)
        rows.append({'name': name, 'passed': len(data) == 2 * 1024 * 1024,
                     'fixture': 'Disposable bounded HTTP body', 'receivedBytes': len(data)})
    return rows


def main():
    registry = native_tools.NativeToolRegistry(REPO / '.agent_control/C10/pdf-bounded32')
    started = time.monotonic()
    fetched = registry.call('web.fetch', {'url': URL, 'maxChars': 20000, 'refresh': True})
    result = fetched.get('result', {})
    receipt = {'schema': 'neyvia.C10.pdf-bounded32.v1', 'url': URL,
               'nativeFetch': {key: fetched.get(key) for key in
                               ('ok', 'status', 'error', 'duration_ms', 'receipt_path')},
               'elapsedMs': round((time.monotonic() - started) * 1000),
               'metadata': {key: result.get(key) for key in
                            ('status', 'finalUrl', 'contentType', 'document', 'contentSha256',
                             'textSha256', 'characters', 'responseTruncated', 'pdfExtraction')},
               'rawPDFPersisted': False, 'checks': []}
    if fetched['ok']:
        text, _ = registry.documents.get(result['document'])
        snippets = []
        for needle in ('Consolidated Plan', 'Arlington', 'Housing'):
            index = text.casefold().find(needle.casefold())
            if index >= 0:
                snippets.append({'needle': needle, 'start': index,
                                 'quote': text[max(0, index - 40):index + 240]})
        receipt['observedText'] = snippets
        extraction = result.get('pdfExtraction', {})
        receipt['checks'].extend([
            {'name': 'actualBoundedPDF', 'passed': extraction.get('engine') == 'pypdf'
             and extraction.get('responseByteLimit') == LIMIT
             and 16 * 1024 * 1024 < extraction.get('receivedBytes', 0) < LIMIT},
            {'name': 'actualPagesAndText', 'passed': extraction.get('pages', 0) > 0
             and bool(snippets) and extraction.get('pagesExtracted') > 0},
            {'name': 'actualContentBinding', 'passed': extraction.get('contentSha256') == result.get('contentSha256')
             and hashlib.sha256(text.encode()).hexdigest() == result.get('textSha256')},
        ])
        if snippets:
            selected = next((row for row in snippets if row['needle'] == 'Housing'), snippets[0])
            start = max(0, selected['start'] - 40)
            quote = text[start:start + 180]
            citation = registry.call('web.cite', {'document': result['document'], 'start': start,
                                                  'end': start + len(quote), 'expectedText': quote})
            receipt['literalCitation'] = citation.get('result', {}).get('citation')
            receipt['checks'].append({'name': 'actualLiteralCitation', 'passed': citation['ok'],
                                      'receiptPath': citation['receipt_path']})

    class Oversized(io.BytesIO):
        def __init__(self):
            super().__init__(b'%PDF-1.7\nsmall-disposable-body')
            self.headers = Message()
            self.headers['Content-Type'] = 'application/pdf'
            self.headers['Content-Length'] = str(LIMIT + 1)
            self.bytes_read = 0

        def read(self, size=-1):
            data = super().read(size)
            self.bytes_read += len(data)
            return data

    response = Oversized()
    refused = False
    with patch.object(native_tools.urllib.request, 'urlopen', return_value=response):
        try:
            native_tools._request('https://public-fixture.invalid/oversized.pdf', pdf_max_bytes=LIMIT)
        except ValueError as exc:
            refused = str(LIMIT) in str(exc)
            receipt['overCapReason'] = str(exc)
    receipt['checks'].append({'name': 'overCapRefusedBeforeBodyRead',
                              'fixture': 'Disposable mocked HTTP response with real declared byte bound',
                              'passed': refused and response.bytes_read == 0,
                              'bodyBytesRead': response.bytes_read})
    receipt['checks'].extend(failure_checks(registry))
    receipt['passed'] = fetched['ok'] and all(row['passed'] for row in receipt['checks'])
    receipt['sourceHashes'] = {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (REPO / 'src/grant_agent/native_tools.py', Path(__file__))}
    receipt['boundary'] = 'Native HTTP PDF bytes extracted by installed pypdf; immutable text cache and actual SHA/pages, no DOM substitution, OCR, invented text or raw PDF persistence.'
    path = REPO / 'scripts/evidence/C10-pdf-bounded32.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))
    if not receipt['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
