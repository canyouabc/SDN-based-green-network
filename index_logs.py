# index_logs.py
# ─────────────────────────────────────────────────────────────────
# 掃描 log/ 底下所有實驗資料夾（遞迴，不依賴實體分類方式），產生 log/index.json，
# 給 log_browser.html 做「多種讀取方式」（依任意屬性分組／篩選／排序）。
#
# 每筆實驗的屬性來源（前面的優先，後面只補缺的欄位）：
#   1. 資料夾裡的 meta.json（run_meta.py 寫的，2026-10-06 之後的實驗都有）
#   2. log_series.json 的 name_regex（從 combo 名稱拆屬性）與 attrs（整個系列共用）
#   3. 舊資料夾的簡單推測：資料夾名稱、結果 CSV、時間最接近的 sweep-summary 旗標
# 輸出兩份相同內容：log/index.json，以及給 log_viewer.html 自動載入用的 log/index.js
# 取不到的欄位就不寫——只是不能用那個條件搜到。
#
# 用法：python index_logs.py      （跑完會印出各欄位的覆蓋率）
# ─────────────────────────────────────────────────────────────────
import csv
import json
import os
import re
from collections import Counter
from datetime import datetime

from run_meta import _result_fields, _topo_fields

LOG_DIR = 'log'
SERIES_FILE = 'log_series.json'
OUT = os.path.join(LOG_DIR, 'index.json')
OUT_JS = os.path.join(LOG_DIR, 'index.js')
TS_RE = re.compile(r'-(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})$')
RUN_PREFIX = re.compile(r'^(sweep|sim|real|geant|milpsnap)')


def _topo_data_dir(topo):
    for d in (os.path.join('data', topo), os.path.join('milp_transfer', 'data', topo)):
        if os.path.isdir(d):
            return d
    return None


def _merge_missing(meta, extra):
    """只補 meta 沒有的欄位；flags 逐個旗標補。"""
    for k, v in extra.items():
        if k == 'flags':
            meta.setdefault('flags', {})
            for fk, fv in v.items():
                meta['flags'].setdefault(fk, fv)
        elif k not in meta:
            meta[k] = v


def _with_topo(attrs):
    """attrs 有 topo 時順便推出 topo_family／topo_size／energy_ratio 等。"""
    if 'topo' in attrs:
        return dict(_topo_fields(attrs['topo'], _topo_data_dir(attrs['topo'])), **attrs)
    return attrs


def _infer_basic(folder):
    """舊資料夾（沒有 meta.json）：只從資料夾名稱推最基本的屬性。"""
    m = {'inferred': True}
    ts = TS_RE.search(folder)
    if ts:
        m['time'] = datetime.strptime(ts.group(1), '%Y-%m-%d_%H-%M-%S').strftime('%Y-%m-%d %H:%M:%S')
    core = TS_RE.sub('', folder)
    if folder.startswith('sweep-summary-'):
        m.update(kind='sweep_summary', name='summary', series='summary')
    elif folder.startswith('sweep-'):
        name = core[len('sweep-'):]
        m.update(kind='sweep', name=name, series=name.split('_')[0])
    elif folder.startswith('sim-'):
        m.update(kind='sim', series='sim', name=core[len('sim-'):])
        # sim-{topo}-{seed stem}-{algorithm}；topo 本身不含 '-'
        sm = re.match(r'^sim-([^-]+)-(.+)-([a-z0-9_]+)$', core)
        if sm:
            m['topo'], seed, m['algorithm'] = sm.groups()
            if seed != 'noseed':
                m['seed_file'] = seed + '.json'
                lv = re.search(r'_(xxlow|xlow|low|mid|high)(?=[_.]|$)', seed)
                if lv:
                    m['traffic_level'] = lv.group(1)
    elif folder.startswith('real-'):
        m.update(kind='mininet', series='mininet', name=folder)
    elif folder.startswith('geant-'):
        m.update(kind='geant', series='geant', name=folder)
    elif folder.startswith('milpsnap'):
        m.update(kind='milp', series=folder.split('-')[0], name=folder)
    else:
        m.update(kind='other', name=folder)
    return m


def _load_summaries(runs):
    """sweep-summary 資料夾：{時間: {combo 名稱: flags}}，給舊 sweep 對應旗標。"""
    out = []
    for path, folder in runs:
        if not folder.startswith('sweep-summary-'):
            continue
        ts = TS_RE.search(folder)
        f = os.path.join(path, 'sweep_comparison.csv')
        if not ts or not os.path.isfile(f):
            continue
        flags = {}
        with open(f, encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                cols = list(row)
                flag_cols = cols[1:cols.index('batch')] if 'batch' in cols else []
                flags.setdefault(row['name'], {c: row[c] for c in flag_cols})
        out.append((datetime.strptime(ts.group(1), '%Y-%m-%d_%H-%M-%S'), flags))
    return sorted(out, key=lambda x: x[0])


def _summary_flags(summaries, name, time_str):
    """時間在該實驗之後、最接近、且含同名 combo 的那份 summary。"""
    t = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
    for st, flags in summaries:
        if st >= t and name in flags:
            return {k: _parse_scalar(v) for k, v in flags[name].items()}
    return None


def _parse_scalar(v):
    return {'True': True, 'False': False, 'None': None, '': None}.get(v, v)


def _apply_series(meta, series):
    s = series.get(meta.get('series')) or {}
    if not s:
        return
    if s.get('desc'):
        meta.setdefault('series_desc', s['desc'])
    if s.get('name_regex') and meta.get('name'):
        mm = re.match(s['name_regex'], meta['name'])
        if mm:
            got = {}
            for k, v in mm.groupdict().items():
                if v is None:
                    continue
                v = _parse_scalar(v)
                if isinstance(v, str) and v.isdigit():
                    v = int(v)
                if k.startswith('flag_'):
                    got.setdefault('flags', {})[k[5:]] = v
                else:
                    got[k] = v
            _merge_missing(meta, _with_topo(got))
    if s.get('attrs'):
        _merge_missing(meta, _with_topo(dict(s['attrs'])))


def find_runs():
    """log/ 底下的實驗資料夾（遞迴）：有 meta.json，或名稱是已知 runner 前綴。"""
    runs = []
    for root, dirs, files in os.walk(LOG_DIR):
        if root == LOG_DIR:
            continue
        folder = os.path.basename(root)
        if 'meta.json' in files or RUN_PREFIX.match(folder):
            runs.append((root, folder))
            dirs[:] = []          # 實驗資料夾底下不再往下找
    return runs


def build_index():
    series = {k: v for k, v in json.load(open(SERIES_FILE, encoding='utf-8')).items() if not k.startswith('_')} \
        if os.path.isfile(SERIES_FILE) else {}
    runs = find_runs()
    summaries = _load_summaries(runs)
    entries = []
    for path, folder in runs:
        mp = os.path.join(path, 'meta.json')
        if os.path.isfile(mp):
            meta = json.load(open(mp, encoding='utf-8'))
        else:
            meta = _infer_basic(folder)
            if meta.get('topo'):
                _merge_missing(meta, _with_topo({'topo': meta['topo']}))
            if meta['kind'] == 'sweep' and meta.get('time'):
                fl = _summary_flags(summaries, meta['name'], meta['time'])
                if fl:
                    meta['flags'] = fl
            _merge_missing(meta, _result_fields(path))
        _apply_series(meta, series)
        meta['path'] = os.path.relpath(path, LOG_DIR).replace(os.sep, '/')
        meta['snaps'] = sorted(f for f in os.listdir(path) if f.endswith('-snap.txt'))
        entries.append(meta)
    entries.sort(key=lambda m: m.get('time', ''), reverse=True)
    data = json.dumps({'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'count': len(entries),
                       'runs': entries}, ensure_ascii=False)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(data)
    # 同一份內容包成 JS：log_viewer.html 用 <script src="log/index.js"> 載入，
    # 雙擊開頁就有列表，不用選資料夾（瀏覽器不讓網頁直接讀本機 json，但允許載入同資料夾的 script）
    with open(OUT_JS, 'w', encoding='utf-8') as f:
        f.write('window.LOG_INDEX = ' + data + ';\n')
    return entries


if __name__ == '__main__':
    entries = build_index()
    print(f'已寫入 {OUT}：{len(entries)} 筆')
    cov = Counter(k for m in entries for k in m)
    for k in ('kind', 'series', 'time', 'topo', 'energy_ratio', 'traffic_level', 'seed_file', 'seed_rng',
              'algorithm', 'flags', 'avg_energy_saving', 'has_snap'):
        print(f'  {k:18} {cov[k]:5d} / {len(entries)}')
