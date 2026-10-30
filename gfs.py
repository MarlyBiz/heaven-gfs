#!/usr/bin/env python3
"""Heaven on Earth - GFS temperature/wind/pressure tiles (sky17).
Pulls NOAA GFS 0.5 deg (public domain) from the noaa-gfs-bdp-pds S3 bucket using .idx byte ranges (only the 4 fields
needed, ~1.5 MB per step), and writes compact PNG grids + meta.json to ./site:
  tw_fFFF.png  720x361 RGB  R = 2 m temperature (-70..+55 C), G/B = 10 m wind u/v (-50..+50 m/s)   lat 90..-90, lon -180..179.5
  pr_fFFF.png  720x361 gray  3 h precipitation (mm) = (v/255)^2 * 150, de-accumulated from APCP
  cl_fFFF.png  360x181 gray  total cloud cover % = v/255*100 (instantaneous)
  p_fFFF.png   360x181 RGB  R*256+G = mean sea level pressure in units of 0.1 hPa above 900 hPa (1 deg grid)
  gu_fFFF.png  720x361 gray  surface wind gust (m/s) = v/255*60 (sky26)
  fronts.json  WPC coded surface bulletin (fronts + H/L) as GeoJSON-ish lines (North America)
Usage: python gfs.py [--hours 72] [--step 3]"""
import json, os, sys, time, urllib.request, datetime as dt
import numpy as np
from PIL import Image
import eccodes

BUCKET = 'https://noaa-gfs-bdp-pds.s3.amazonaws.com'
FIELDS = [('TMP', '2 m above ground'), ('UGRD', '10 m above ground'), ('VGRD', '10 m above ground'), ('PRMSL', 'mean sea level'), ('GUST', 'surface')]
OUT = os.environ.get('OUT', 'site')
HOURS = int(os.environ.get('HOURS', '72')); STEP = int(os.environ.get('STEP', '3'))

def get(url, rng=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={'Range': f'bytes={rng[0]}-{rng[1]}'} if rng else {})
            with urllib.request.urlopen(req, timeout=60) as r: return r.read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(2 + 3 * i)

def exists(url):
    try: urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=20); return True
    except Exception: return False

def latest_cycle():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    for back in range(0, 48, 6):
        c = now - dt.timedelta(hours=back); c = c.replace(hour=c.hour // 6 * 6, minute=0, second=0, microsecond=0)
        base = f"{BUCKET}/gfs.{c:%Y%m%d}/{c:%H}/atmos/gfs.t{c:%H}z.pgrb2.0p50"
        if exists(f"{base}.f{HOURS:03d}.idx"): return c, base
    raise SystemExit('no complete GFS cycle found')

def fetch_step(base, fh):
    idx = get(f"{base}.f{fh:03d}.idx").decode().strip().split('\n')
    rows = [l.split(':') for l in idx]
    out = {}
    for i, r in enumerate(rows):
        key = (r[3], r[4])
        if r[3] == 'APCP' and r[5] == f'0-{fh} hour acc fcst': key = ('APCP', 'surface')
        elif r[3] == 'TCDC' and r[4] == 'entire atmosphere' and r[5] in ('anl', f'{fh} hour fcst'): key = ('TCDC', 'entire atmosphere')
        elif key not in FIELDS: continue
        if key[0] not in out:
            start = int(r[1]); end = int(rows[i + 1][1]) - 1 if i + 1 < len(rows) else ''
            msg = get(f"{base}.f{fh:03d}", (start, end))
            h = eccodes.codes_new_from_message(msg)
            ni, nj = eccodes.codes_get(h, 'Ni'), eccodes.codes_get(h, 'Nj')
            v = eccodes.codes_get_values(h).reshape(nj, ni); eccodes.codes_release(h)
            out[key[0]] = np.roll(v, ni // 2, axis=1)  # lon 0..359.5 -> -180..179.5
    return out

def q8(a, lo, hi): return np.clip(np.rint((a - lo) / (hi - lo) * 255), 0, 255).astype(np.uint8)

def main():
    cyc, base = latest_cycle()
    os.makedirs(OUT, exist_ok=True)
    steps = []
    prev_tot = None
    for fh in range(0, HOURS + 1, STEP):
        f = fetch_step(base, fh)
        # precipitation: de-accumulate the 0-fh total into the 3 h bucket ending at fh (mm); f000 has none
        if 'APCP' in f:
            tot = f['APCP']; pr = np.clip(tot - (prev_tot if prev_tot is not None else 0), 0, None); prev_tot = tot
            Image.fromarray(np.rint(np.sqrt(np.clip(pr, 0, 150) / 150) * 255).astype(np.uint8), 'L').save(f"{OUT}/pr_f{fh:03d}.png", optimize=True)
        t = f['TMP'] - 273.15
        Image.fromarray(np.dstack([q8(t, -70, 55), q8(f['UGRD'], -50, 50), q8(f['VGRD'], -50, 50)]), 'RGB').save(f"{OUT}/tw_f{fh:03d}.png", optimize=True)
        p = np.clip(np.rint(f['PRMSL'][::2, ::2] / 10 - 9000), 0, 65535).astype(np.uint16)  # 0.1 hPa above 900
        Image.fromarray(np.dstack([(p >> 8).astype(np.uint8), (p & 255).astype(np.uint8), np.zeros_like(p, np.uint8)]), 'RGB').save(f"{OUT}/p_f{fh:03d}.png", optimize=True)
        if 'GUST' in f:  # sky26: surface wind gust m/s
            Image.fromarray(q8(f['GUST'], 0, 60), 'L').save(f"{OUT}/gu_f{fh:03d}.png", optimize=True)
        if 'TCDC' in f:  # total cloud cover %, 1 deg is plenty for a soft cloud field
            Image.fromarray(q8(f['TCDC'][::2, ::2], 0, 100), 'L').save(f"{OUT}/cl_f{fh:03d}.png", optimize=True)
        steps.append({'fh': fh, 'valid': (cyc + dt.timedelta(hours=fh)).strftime('%Y-%m-%dT%H:%MZ'), 'pr': 'APCP' in f, 'cl': 'TCDC' in f, 'gu': 'GUST' in f})
        print('step', fh, flush=True)
    meta = {'model': 'NOAA GFS 0.5°', 'run': cyc.strftime('%Y-%m-%dT%HZ'), 'runLabel': f"GFS {cyc:%H}Z", 'generated': dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime('%Y-%m-%dT%H:%MZ'),
            'tw': {'w': 720, 'h': 361, 'lat0': 90, 'lon0': -180, 'd': 0.5, 't': [-70, 55], 'u': [-50, 50], 'v': [-50, 50]},
            'p': {'w': 360, 'h': 181, 'lat0': 90, 'lon0': -180, 'd': 1.0, 'scale': 0.1, 'offset': 900},
            'pr': {'w': 720, 'h': 361, 'lat0': 90, 'lon0': -180, 'd': 0.5, 'enc': 'mm per 3 h = (v/255)^2 * 150', 'max': 150},
            'cl': {'w': 360, 'h': 181, 'lat0': 90, 'lon0': -180, 'd': 1.0, 'enc': 'cloud % = v/255*100'},
            'gu': {'w': 720, 'h': 361, 'lat0': 90, 'lon0': -180, 'd': 0.5, 'enc': 'gust m/s = v/255*60', 'max': 60},
            'steps': steps}
    try:
        from fronts import fetch_fronts
        fr = fetch_fronts()
        if fr: json.dump(fr, open(f"{OUT}/fronts.json", 'w'), separators=(',', ':')); meta['fronts'] = {'issued': fr.get('issued'), 'coverage': 'North America (NOAA WPC)'}
    except Exception as e: print('fronts skipped:', e)
    json.dump(meta, open(f"{OUT}/meta.json", 'w'), separators=(',', ':'))

if __name__ == '__main__': main()
