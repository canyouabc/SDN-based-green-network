# run_meta.py
# ─────────────────────────────────────────────────────────────────
# 每次實驗在自己的 log 資料夾寫一份 meta.json，記錄這次跑的條件與結果摘要，
# 給 index_logs.py／log_browser.html 當索引用。
#
# 原則：每個欄位都是選填。取不到（或無法確定）的欄位直接不寫，
# 索引端遇到缺欄位只是「不能用這個條件搜到」，不會出錯。
#
# ⚠️ watchdog_new.py（Mininet VM，Python 3.8.10）也會 import 這支，必須維持 3.8 相容。
# ─────────────────────────────────────────────────────────────────
import csv
import glob
import json
import os
import re
from datetime import datetime

TRAFFIC_LEVELS = ('xxlow', 'xlow', 'low', 'mid', 'high')


def _read_energy(path):
    """switch_energy.txt（dpid type W）／link_energy.txt（src dst W [備註]）：能耗都在第 3 欄。"""
    vals = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and not line.lstrip().startswith('#'):
                    try:
                        vals.append(float(parts[2]))
                    except ValueError:
                        pass
    except OSError:
        return None
    return vals or None


def _topo_fields(topo, data_dir):
    m = {'topo': topo}
    fam = re.match(r'(grid|cap|geant|fattree)', topo or '')
    if fam:
        m['topo_family'] = fam.group(1)
    size = re.search(r'(\d+x\d+)', topo or '')
    if size:
        m['topo_size'] = size.group(1)
    elif m.get('topo_family') == 'grid':
        m['topo_size'] = '5x5'          # 'grid'／'grid_31' 沿用舊命名，是 5x5
    k = re.search(r'_k(\d+)', topo or '')
    if m.get('topo_family') == 'fattree' and k:
        m['topo_size'] = 'k' + k.group(1)
    if 'allhosts' in (topo or ''):
        m['topo_variant'] = 'allhosts'
    if data_dir:
        sw = _read_energy(os.path.join(data_dir, 'switch_energy.txt'))
        ln = _read_energy(os.path.join(data_dir, 'link_energy.txt'))
        if sw:
            m['n_switches'] = len(sw)
            m['switch_energy_w'] = round(sum(sw) / len(sw), 4)
        if ln:
            m['n_links'] = len(ln)
            m['link_energy_w'] = round(sum(ln) / len(ln), 4)
        if sw and ln and m['link_energy_w'] > 0:
            r = m['switch_energy_w'] / m['link_energy_w']
            m['energy_ratio'] = f'{round(r)}:1' if r >= 10 else f'{round(r, 1):g}:1'
    return m


def _seed_fields(seed_data, seed_path):
    """seed 參數一律取自實際傳進來的 seed_data；seed 檔名只在確認內容一致時才記錄
    （有些腳本直接傳 seed_data 進 run_one_combo、沒有設 SEED_PATH，不能盲目相信檔名）。"""
    m = {}
    if seed_data:
        for src, dst in (('seed', 'seed_rng'), ('lambda', 'lambda'), ('bw_min', 'bw_min'), ('bw_max', 'bw_max'),
                         ('flow_duration', 'flow_duration'), ('experiment_duration', 'experiment_duration'),
                         ('num_hosts', 'num_hosts')):
            if src in seed_data:
                m[dst] = seed_data[src]
        if 'batches' in seed_data:
            m['num_batches'] = len(seed_data['batches'])
            m['num_flows'] = sum(len(b.get('flows', [])) for b in seed_data['batches'])
        if 'source_seed' in seed_data:       # gen_milp_snapshot.py 的快照 seed
            m['source_seed'] = seed_data['source_seed']
    name = None
    if seed_path and os.path.isfile(seed_path):
        if seed_data is None:
            name = os.path.basename(seed_path)
        else:
            try:
                with open(seed_path, encoding='utf-8') as f:
                    if json.load(f) == seed_data:
                        name = os.path.basename(seed_path)
            except (OSError, ValueError):
                pass
    if name:
        m['seed_file'] = name
    level_src = name or m.get('source_seed') or ''
    lv = re.search(r'_(%s)(?=[_.]|$)' % '|'.join(TRAFFIC_LEVELS), level_src)
    if lv:
        m['traffic_level'] = lv.group(1)        # 檔名推測（seed 表頭沒有這個欄位）
    return m


def _result_fields(run_dir):
    m = {}
    summary = os.path.join(run_dir, 'energy_saving_summary.csv')
    if os.path.isfile(summary):
        with open(summary, encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        avg = [r for r in rows if r.get('batch') == 'AVERAGE']
        if avg and avg[0].get('mean_after_100') not in (None, '', 'nan'):
            m['avg_energy_saving'] = float(avg[0]['mean_after_100'])
        m['batches_done'] = sum(1 for r in rows if r.get('batch') != 'AVERAGE')
    m['has_snap'] = bool(glob.glob(os.path.join(run_dir, '*-snap.txt')))
    return m


def read_module_flags(path):
    """讀路由模組頂部的大寫常數（例如 SORT_MODE = 'SPF'），只收 literal 值。
    給 Mininet（watchdog_new.py）用：它不 import 路由模組，只能從原始碼讀設定。"""
    import ast
    flags = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                m = re.match(r'^([A-Z][A-Z0-9_]*)\s*=\s*(.+?)\s*(#.*)?$', line)
                if m:
                    try:
                        flags[m.group(1)] = ast.literal_eval(m.group(2))
                    except (ValueError, SyntaxError):
                        pass
    except OSError:
        pass
    return flags


def write_run_meta(run_dir, kind, name=None, series=None, time=None, topo=None, data_dir=None,
                   seed_data=None, seed_path=None, algorithm=None, flags=None, extra=None):
    """寫 {run_dir}/meta.json。time 可傳 datetime 或 'YYYY-MM-DD_HH-MM-SS' 字串。"""
    meta = {'kind': kind}
    if name:
        meta['name'] = name
        meta['series'] = series or name.split('_')[0]
    elif series:
        meta['series'] = series
    if isinstance(time, str):
        try:
            time = datetime.strptime(time, '%Y-%m-%d_%H-%M-%S')
        except ValueError:
            time = None
    if time is not None:
        meta['time'] = time.strftime('%Y-%m-%d %H:%M:%S')
    if topo:
        meta.update(_topo_fields(topo, data_dir))
    meta.update(_seed_fields(seed_data, seed_path))
    if algorithm:
        meta['algorithm'] = algorithm
    if flags:
        meta['flags'] = dict(flags)    # None 也保留（例如 LINK_PRUNE=None 是有意義的設定值）
    for k, v in (extra or {}).items():   # extra 可覆蓋前面算出的欄位；值為 None 代表「不要這個欄位」
        if v is None:
            meta.pop(k, None)
        else:
            meta[k] = v
    meta.update(_result_fields(run_dir))
    with open(os.path.join(run_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    # 順便重建 log/index.json（約 1 秒），log_viewer.html 按「重新讀取」就看得到這次實驗。
    # 失敗不影響實驗本身，只印提醒；之後手動 python index_logs.py 即可。
    try:
        import index_logs   # 放這裡 import：index_logs 也 import run_meta，避免循環
        index_logs.build_index()
    except Exception as e:
        print(f'[run_meta] 重建 log/index.json 失敗（不影響實驗結果，可手動 python index_logs.py）：{e}')
    return meta
