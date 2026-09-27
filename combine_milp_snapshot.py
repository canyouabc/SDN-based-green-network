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
#       <seed_milpsnap_grid4x4_mid_results.csv> [out_dir]
# ─────────────────────────────────────────────────────────────────
import os
import sys
import csv
import json

import sim
from parse_log import parse_log
import matplotlib_DTM


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


if __name__ == '__main__':
    snap_json, milp_csv = sys.argv[1], sys.argv[2]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        'log', 'milpsnap-' + os.path.splitext(os.path.basename(snap_json))[0])
    base, status = combine(snap_json, milp_csv, out_dir)
    print(f"MILP 狀態統計：{status}")
    print(base[['mean_after_100']].to_string())
