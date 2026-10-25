"""NOAA WPC coded surface frontal positions (CODSUS, North America + adjacent oceans) -> compact JSON.
Points are LLOOO / LLOO: whole degrees N, degrees W. 4-digit points are ambiguous (LL OO vs L OOO): the reading
closest to the previous point of the same line is used."""
import re, urllib.request
URL = 'https://tgftp.nws.noaa.gov/data/raw/as/asus01.kwbc.cod.sus.txt'
KINDS = {'COLD': 'cold', 'WARM': 'warm', 'STNRY': 'stationary', 'OCFNT': 'occluded', 'TROF': 'trough', 'DRYLINE': 'dryline'}

def cands(tok):
    out = []
    if len(tok) == 5: out.append((int(tok[:2]), int(tok[2:])))
    elif len(tok) == 4:
        out.append((int(tok[:2]), int(tok[2:]))); out.append((int(tok[:1]), int(tok[1:])))
    elif len(tok) == 3: out.append((int(tok[:1]), int(tok[1:])))
    return [(la, -lo if lo <= 180 else 360 - lo) for la, lo in out if la <= 90 and lo <= 360]

def pick(tok, prev):
    c = cands(tok)
    if not c: return None
    if prev is None or len(c) == 1: return c[0]
    return min(c, key=lambda p: (p[0] - prev[0]) ** 2 + (p[1] - prev[1]) ** 2)

def parse(txt):
    lines = txt.split('\n')
    vi = next((i for i, l in enumerate(lines) if l.startswith('VALID')), None)
    if vi is None: return None
    valid = lines[vi].split()[1]
    issued = next((l.strip() for l in lines[:vi] if re.match(r'^\d{3,4} (AM|PM) ', l.strip())), None)
    items, cur = [], None
    for tok in ' '.join(lines[vi + 1:]).split():
        if tok in KINDS or tok in ('HIGHS', 'LOWS'): cur = [tok]; items.append(cur)
        elif tok.isdigit() and cur is not None: cur.append(tok)
        elif not tok.isdigit(): cur = None  # $$ / end of product
    centers, fronts = [], []
    for t in items:
        if t[0] in ('HIGHS', 'LOWS'):
            for i in range(1, len(t) - 1, 2):
                p = pick(t[i + 1], None)
                if p: centers.append({'k': 'H' if t[0] == 'HIGHS' else 'L', 'p': int(t[i]), 'lat': p[0], 'lon': p[1]})
        else:
            pts, prev = [], None
            for tok in t[1:]:
                p = pick(tok, prev)
                if p: pts.append([p[1], p[0]]); prev = p
            if len(pts) >= 2: fronts.append({'k': KINDS[t[0]], 'c': pts})
    return {'valid': valid, 'issued': issued, 'centers': centers, 'fronts': fronts}

def fetch_fronts():
    with urllib.request.urlopen(URL, timeout=30) as r: return parse(r.read().decode('latin-1'))

if __name__ == '__main__':
    import json; d = fetch_fronts(); print(d['valid'], d['issued'], len(d['centers']), len(d['fronts'])); print(json.dumps(d['fronts'][:3]))
