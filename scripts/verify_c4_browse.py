"""Compare the R4 Markdown table to the real page's supported-version table."""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.request import Request,urlopen

URL='https://devguide.python.org/versions/'
class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables=[]; self.table=None; self.row=None; self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='table': self.table=[]
        elif self.table is not None and tag=='tr': self.row=[]
        elif self.row is not None and tag in {'td','th'}: self.cell=[]
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in {'td','th'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell=None
        elif tag=='tr' and self.row is not None:
            if self.row: self.table.append(self.row)
            self.row=None
        elif tag=='table' and self.table is not None:
            self.tables.append(self.table); self.table=None

def plain(text):
    text=re.sub(r'\[([^\]]+)\]\([^)]*\)',r'\1',text)
    return re.sub(r'\s+',' ',text.replace('`','').replace('**','')).strip().lower()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('artifact',type=Path);p.add_argument('destination',type=Path)
    args=p.parse_args();args.destination.mkdir(parents=True,exist_ok=True)
    request=Request(URL,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                                'Accept':'text/html,application/json;q=0.9,*/*;q=0.5'})
    with urlopen(request,timeout=30) as response:
        data=response.read(2*1024*1024+1)
        if len(data)>2*1024*1024: raise ValueError('Source exceeds 2 MiB bound')
        final=response.geturl()
    (args.destination / 'source.html').write_bytes(data)
    parser=Tables();parser.feed(data.decode('utf-8'))
    table=next(t for t in parser.tables if len(t[0])>=5 and 'branch' in plain(t[0][0]))
    # The real page also has Release manager, outside the task's five columns.
    table=[r[:5] for r in table]
    expected={r[0]:r for r in table[1:] if len(r)==5}
    text=args.artifact.read_text(encoding='utf-8')
    rows=[list(map(plain,line.strip().strip('|').split('|'))) for line in text.splitlines() if line.strip().startswith('|')]
    actual={r[0]:r for r in rows if len(r)==5 and (r[0]=='main' or re.fullmatch(r'3\.\d+',r[0]))}
    comparisons={branch:[plain(cell)==got for cell,got in zip(row,actual.get(branch,[]))]
                 if branch in actual else [False] for branch,row in expected.items()}
    before2028=[branch for branch,row in expected.items() if re.search(r'202[0-7]',row[4])]
    prose=' '.join(line for line in text.splitlines() if not line.strip().startswith('|'))
    checks={'all_supported_rows':set(actual)==set(expected),'exact_table_cells':all(all(c) for c in comparisons.values()),
            'source_cited':URL in text,'eol_versions_in_prose':bool(before2028) and all(b in prose for b in before2028)}
    result={'passed':all(checks.values()),'checks':checks,'sourceUrl':URL,'finalUrl':final,
            'sourceSha256':hashlib.sha256(data).hexdigest(),'artifactSha256':hashlib.sha256(args.artifact.read_bytes()).hexdigest(),
            'expectedRows':table,'actualRows':rows,'cellComparisons':comparisons,'before2028':before2028,
            'limits':['Exact cell equality can reject alternate equivalent date notation; lead reviews any mismatch','EOL prose reviewed separately for extra incorrect versions']}
    (args.destination / 'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':result['passed'],'checks':checks,'expectedRows':table}),flush=True)
    return 0 if result['passed'] else 1
if __name__=='__main__':sys.exit(main())
