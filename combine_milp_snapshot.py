# combine_milp_snapshot.py
# ─────────────────────────────────────────────────────────────────
# 把 Gurobi（milp_transfer/milp_energy_saving.py --all-batches）對
# milp_transfer/seed_milpsnap_*.json 求出的結果 csv，依 json 裡的 segments
# 展開回逐秒節能率，再走跟 heuristic 完全相同的流程
#   ENERGY log → parse_log → matplotlib_DTM.analyze（mean_after_100）
# 得到每個原始 batch 的節能率，可直接跟 heuristic 快照結果對照。
#
# seed_milpsnap_*.json 的來源：論文用的 seed_000_*.json（動態流量），
# 逐秒切出 active flow 集合、相鄰相同合併成一段、同一份 seed 內相同集合去重。
#   batches  : 每個 batch = 一組同時存在的 flow（MILP 求解單位）
#   segments : {orig_batch, t_start, t_end, milp_batch_id}，
#              milp_batch_id=null 表示該段沒有 flow（節能率 100%）
#
# 用法：
#   python combine_milp_snapshot.py milp_transfer/seed_milpsnap_grid4x4_mid.json \
#       <seed_milpsnap_grid4x4_mid_results.csv> [out_dir] [--paths <paths.jsonl>]
#
# --paths：milp_energy_saving.py --paths-out 輸出的最優路徑檔。有給的話，另外在 out_dir
# 產出每個原始 batch 的 b{N}-snap.txt（snap_player.html 讀這個）。一個 segment = 一幀
# （event='milp_segment'），每幀都是獨立求解的最優解，相鄰兩幀同一條 flow 的路徑可能整條不同。
# ─────────────────────────────────────────────────────────────────
import os
import argparse
import csv
import json

import sim
from parse_log import parse_log
import matplotlib_DTM
from modules.link_status import Link_Status


def combine(snap_json, milp_csv, out_dir):
    snap = json.load(open(snap_json, encoding='utf-8'))

    res, status = {}, {}
    with open(milp_csv, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            res[int(row['batch'])] = float(row['energy_saving_percent'])
            status[row['status']] = status.get(row['status'], 0) + 1
    need = {s['milp_batch_id'] for s in snap['segments'] if s['milp_batch_id']}
    missing = sorted(need - set(res))
    if missing:
        raise ValueError(f"MILP 結果缺 {len(missing)} 個 batch，例如 {missing[:5]}")

    os.makedirs(out_dir, exist_ok=True)
    name = os.path.splitext(os.path.basename(snap_json))[0]
    log_path = os.path.join(out_dir, name + '.log')
    csv_path = os.path.join(out_dir, name + '.csv')
    exp = snap['experiment_duration']

    by_batch = {}
    for s in snap['segments']:
        by_batch.setdefault(s['orig_batch'], []).append(s)

    with open(log_path, 'w', encoding='utf-8') as log:
        for ob in sorted(by_batch):
            segs = sorted(by_batch[ob], key=lambda s: s['t_start'])
            assert segs[0]['t_start'] == 0 and segs[-1]['t_end'] == exp
            log.write(f"=== BATCH {ob} START ===\n")
            for s in segs:
                pct = 100.0 if s['milp_batch_id'] is None else res[s['milp_batch_id']]
                line = f"{sim._now_str()} ENERGY saving=0.00W percent={pct:.1f}%\n"
                log.write(line * (s['t_end'] - s['t_start'] + 1))
            log.write(f"=== BATCH {ob} END ===\n")

    parse_log(log_path, csv_path)
    base = matplotlib_DTM.analyze(csv_path, out_dir, make_plots=False)
    return base, status


def write_snaps(snap_json, paths_jsonl, out_dir):
    """依 segments 把 MILP 最優路徑展開成 snap_player.html 讀的 b{N}-snap.txt。"""
    snap = json.load(open(snap_json, encoding='utf-8'))
    paths = {}
    with open(paths_jsonl, encoding='utf-8') as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                paths[r['batch']] = r
    need = {s['milp_batch_id'] for s in snap['segments'] if s['milp_batch_id']}
    missing = sorted(need - set(paths))
    if missing:
        raise ValueError(f"路徑檔缺 {len(missing)} 個 batch，例如 {missing[:5]}")

    classify = Link_Status(None).get_link_status
    # 無解的題目 links 是 None，從有解的題目取 link 清單
    link_keys = next(r['links'] for r in paths.values() if r['links'] is not None).keys()
    os.makedirs(out_dir, exist_ok=True)

    by_batch = {}
    for s in snap['segments']:
        by_batch.setdefault(s['orig_batch'], []).append(s)
    for ob in sorted(by_batch):
        with open(os.path.join(out_dir, f'b{ob}-snap.txt'), 'w', encoding='utf-8') as out:
            for s in sorted(by_batch[ob], key=lambda s: s['t_start']):
                r = paths.get(s['milp_batch_id'])
                # 三種情況：這段沒有 flow（r=None）／無解（flows=None）／有解（OPTIMAL 或 TIME_LIMIT 次佳解）
                solved = r is not None and r['flows'] is not None
                usage = r['links'] if solved else dict.fromkeys(link_keys, 0.0)
                frame = {
                    'event':      'milp_segment',
                    'src':        None,
                    'dst':        None,
                    'path':       None,
                    't':          s['t_start'],
                    't_end':      s['t_end'],
                    'milp_batch': s['milp_batch_id'],
                    'status':     r['status'] if r else None,   # 無解時是 'no feasible solution found'
                    'active':     [[fl['src'], fl['dst'], fl['path']] for fl in r['flows']] if solved else [],
                    'bw':         [fl['bw_mbps'] for fl in r['flows']] if solved else [],
                    'ns':         [],
                    'links':      {k: {'s': classify(p), 'p': round(p, 1)} for k, p in usage.items()},
                    # 沒有 flow → 100%；無解 → None（播放器顯示「無解」，走勢圖在這段斷開）
                    'energy_pct': (round(r['energy_saving_percent'], 1) if solved else None) if r else 100.0,
                }
                out.write(f"[SIM_SNAPSHOT] {json.dumps(frame, ensure_ascii=False)}\n")
    return sorted(by_batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snap_json')
    parser.add_argument('milp_csv')
    parser.add_argument('out_dir', nargs='?', default=None)
    parser.add_argument('--paths', default=None,
                        help='milp_energy_saving.py --paths-out 的 .jsonl；有給就另外產出 b{N}-snap.txt')
    args = parser.parse_args()
    snap_json, milp_csv = args.snap_json, args.milp_csv
    out_dir = args.out_dir or os.path.join(
        'log', 'milpsnap-' + os.path.splitext(os.path.basename(snap_json))[0])
    base, status = combine(snap_json, milp_csv, out_dir)
    if args.paths:
        batches = write_snaps(snap_json, args.paths, out_dir)
        print(f"已產出 {len(batches)} 個 snap 檔到 {out_dir}")

    from run_meta import write_run_meta
    with open(milp_csv, encoding='utf-8') as f:
        milp_topo = next(csv.DictReader(f), {}).get('topo')   # 例如 grid_5x5_31
    snap = json.load(open(snap_json, encoding='utf-8'))
    write_run_meta(
        out_dir, 'milp', name=os.path.splitext(os.path.basename(snap_json))[0], series='milp',
        topo=milp_topo, data_dir=os.path.join(os.path.dirname(snap_json), 'data', milp_topo) if milp_topo else None,
        seed_data=snap, seed_path=snap_json, algorithm='MILP',
        # 快照 seed 的 batches 是 MILP 題目，不是原始 batch：num_batches 改記原始 batch 數，題數另記
        extra={'num_batches': len({s['orig_batch'] for s in snap['segments']}),
               'milp_problems': len(snap['batches']), 'num_flows': None,
               'milp_result_csv': os.path.basename(milp_csv), 'milp_status': status},
    )
    print(f"MILP 狀態統計：{status}")
    print(base[['mean_after_100']].to_string())
