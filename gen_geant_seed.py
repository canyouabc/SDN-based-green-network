# gen_geant_seed.py
# ─────────────────────────────────────────────────────────────────
# 把 GEANT 15-分鐘 demand matrix 時間序列（SNDlib native format）轉成
# sim.py 用的 seed json。
#
# 建模方式（詳見 CLAUDE.md 討論）：
#   每個 15 分鐘 snapshot = 一個獨立 batch（batch 之間互不延續狀態，
#   跟 sim.py 本來的架構一致）。snapshot 內每個非零 OD demand = 一條
#   聚合巨流（interval=0 同時進場，存活整個 900 秒視窗），因為原始資料
#   本身就是該視窗的平均聚合速率，視窗內個別 flow 的到達順序/起伏/
#   個別存活時間都不可考，不去憑空捏造。
#
# 分類規則（一般化，不寫死日期）：
#   EMPTY         : num_flows == 0                → 排除
#   ANOMALY_SPIKE : total_demand_mbps > 阈值        → 排除
#   NEAR_EMPTY / NORMAL：其餘                       → 保留
#
# 頻寬縮放：GEANT 真實鏈路容量均一 40000 Mbps，data/geant/link_bw.txt
# 縮小為 1000 Mbps（Mininet TCLink 上限），demand 數值同步除以 40，
# 維持原始相對壅塞比例。
#
# 使用方式：
#   python gen_geant_seed.py --input-dir <demand matrix 資料夾> \
#       --start 20050827-0000 --end 20050827-2345 \
#       --output data/geant_seed_20050827.json
# ─────────────────────────────────────────────────────────────────
import argparse
import json
import os
import re

NODE_NAMES = [
    'at1.at', 'be1.be', 'ch1.ch', 'cz1.cz', 'de1.de',
    'es1.es', 'fr1.fr', 'gr1.gr', 'hr1.hr', 'hu1.hu',
    'ie1.ie', 'il1.il', 'it1.it', 'lu1.lu', 'nl1.nl',
    'ny1.ny', 'pl1.pl', 'pt1.pt', 'se1.se', 'si1.si',
    'sk1.sk', 'uk1.uk',
]
NODE_TO_DPID = {name: i + 1 for i, name in enumerate(NODE_NAMES)}

BW_SCALE_FACTOR   = 1 / 40      # 真實鏈路 40000 Mbps → data/geant 縮放後 1000 Mbps
ANOMALY_THRESHOLD = 150000      # total_demand_mbps 超過此值視為 ANOMALY_SPIKE（見 CLAUDE.md 討論）
WINDOW_SECONDS    = 900         # 15 分鐘

TS_RE = re.compile(r"demandMatrix-geant-uhlig-15min-(\d{8}-\d{4})\.txt$")
DEMAND_LINE_RE = re.compile(
    r"^\s*\S+\s*\(\s*(\S+)\s+(\S+)\s*\)\s+\d+\s+([\d.]+)\s+UNLIMITED\s*$"
)


def parse_snapshot(path):
    """回傳 (flows, total_demand_mbps)；flows = [(src_node, dst_node, demand_mbps), ...]"""
    flows = []
    total = 0.0
    in_demands = False
    with open(path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s.startswith('DEMANDS ('):
                in_demands = True
                continue
            if in_demands:
                if s == ')':
                    break
                m = DEMAND_LINE_RE.match(line)
                if m:
                    src, dst, val = m.group(1), m.group(2), float(m.group(3))
                    flows.append((src, dst, val))
                    total += val
    return flows, total


def classify(num_flows, total_demand_mbps):
    if num_flows == 0:
        return 'EMPTY'
    if total_demand_mbps > ANOMALY_THRESHOLD:
        return 'ANOMALY_SPIKE'
    if num_flows < 100:
        return 'NEAR_EMPTY'
    return 'NORMAL'


def main():
    parser = argparse.ArgumentParser(description='GEANT demand matrix 時間序列 → sim.py seed json')
    parser.add_argument('--input-dir', required=True, help='demandMatrix-*.txt 所在資料夾')
    parser.add_argument('--start', default=None, help='起始 timestamp（含），格式 YYYYMMDD-HHMM，預設不限')
    parser.add_argument('--end',   default=None, help='結束 timestamp（含），格式 YYYYMMDD-HHMM，預設不限')
    parser.add_argument('--output', required=True, help='輸出 seed json 路徑')
    parser.add_argument('--report', default=None, help='分類報告 CSV 路徑（預設 <output>.report.csv）')
    args = parser.parse_args()

    report_path = args.report or os.path.splitext(args.output)[0] + '.report.csv'

    files = sorted(
        fn for fn in os.listdir(args.input_dir)
        if fn.startswith('demandMatrix-') and fn.endswith('.txt')
    )

    batches = []
    report_rows = []  # (timestamp, num_flows, total_demand_mbps, category, included)
    skipped_unknown_node = set()

    for fn in files:
        m = TS_RE.search(fn)
        if not m:
            continue
        ts = m.group(1)
        if args.start and ts < args.start:
            continue
        if args.end and ts > args.end:
            continue

        path = os.path.join(args.input_dir, fn)
        raw_flows, total_demand = parse_snapshot(path)
        num_flows = len(raw_flows)
        category = classify(num_flows, total_demand)
        included = category in ('NORMAL', 'NEAR_EMPTY')

        report_rows.append((ts, num_flows, round(total_demand, 3), category, included))

        if not included:
            continue

        flows = []
        for src, dst, val in raw_flows:
            if src not in NODE_TO_DPID or dst not in NODE_TO_DPID:
                skipped_unknown_node.add((src, dst))
                continue
            flows.append({
                'interval': 0.0,
                'src': f'h{NODE_TO_DPID[src]}',
                'dst': f'h{NODE_TO_DPID[dst]}',
                'bw_mbps': round(val * BW_SCALE_FACTOR, 4),
            })

        batches.append({
            'batch_id': len(batches) + 1,
            'timestamp': ts,
            'category': category,
            'flows': flows,
        })

    data = {
        'source':              'GEANT demandMatrix 15-min time series (SNDlib native format)',
        'bw_scale_factor':     BW_SCALE_FACTOR,
        'anomaly_threshold':   ANOMALY_THRESHOLD,
        'num_hosts':           len(NODE_NAMES),
        'experiment_duration': WINDOW_SECONDS,
        'flow_duration':       WINDOW_SECONDS,
        'num_batches':         len(batches),
        'batches':             batches,
    }

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('timestamp,num_flows,total_demand_mbps,category,included\n')
        for row in report_rows:
            f.write(','.join(str(x) for x in row) + '\n')

    total_scanned = len(report_rows)
    n_empty    = sum(1 for r in report_rows if r[3] == 'EMPTY')
    n_anomaly  = sum(1 for r in report_rows if r[3] == 'ANOMALY_SPIKE')
    n_near     = sum(1 for r in report_rows if r[3] == 'NEAR_EMPTY')
    n_normal   = sum(1 for r in report_rows if r[3] == 'NORMAL')

    print(f"[gen_geant_seed] 掃描 {total_scanned} 個 snapshot（範圍 {args.start or '不限'} ~ {args.end or '不限'}）")
    print(f"  EMPTY(排除)={n_empty}  ANOMALY_SPIKE(排除)={n_anomaly}  "
          f"NEAR_EMPTY(保留)={n_near}  NORMAL(保留)={n_normal}")
    print(f"  → 轉出 {len(batches)} 個 batch")
    if skipped_unknown_node:
        print(f"  [警告] 有 {len(skipped_unknown_node)} 個未知節點名稱被跳過: "
              f"{sorted(skipped_unknown_node)[:5]}...")
    print(f"[gen_geant_seed] 寫入 {args.output}")
    print(f"[gen_geant_seed] 分類報告 → {report_path}")


if __name__ == '__main__':
    main()
