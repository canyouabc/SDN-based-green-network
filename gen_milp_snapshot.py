# gen_milp_snapshot.py
# ─────────────────────────────────────────────────────────────────
# 把 sim.py 用的動態流量 seed（gen_seed.py 產生）切成 Gurobi 用的靜態快照 seed，
# 格式與 combine_milp_snapshot.py 對應（milp_transfer/seed_milpsnap_*.json）：
#   batches  : 每個 batch = 一組同時存在的 flow（MILP 求解單位，interval 一律 0）
#   segments : {orig_batch, t_start, t_end, milp_batch_id}，逐秒對應；
#              milp_batch_id=null 表示該段沒有 flow（節能率 100%）
#
# 「第 t 秒 active」與 sim.py 的逐秒記錄一致：記錄第 t 秒之前會先處理所有時間 <= t 的
# admit／depart 事件，所以 active(t) = { f : interval <= t < interval + flow_duration }。
# 相鄰秒 active 集合相同就合併成一段；同一份 seed 內相同集合只出一題（去重）。
#
# 用法：
#   python gen_milp_snapshot.py <動態 seed.json> <輸出.json> --sim-topo grid --milp-topo grid_5x5
# ─────────────────────────────────────────────────────────────────
import argparse
import json
import os


def build(seed_path, sim_topo, milp_topo):
    src = json.load(open(seed_path, encoding='utf-8'))
    D = src['flow_duration']
    exp = src['experiment_duration']
    batches, segments, index = [], [], {}

    for b in src['batches']:
        flows = b['flows']
        prev_key, seg = None, None
        for t in range(exp + 1):
            active = [f for f in flows if f['interval'] <= t < f['interval'] + D]
            key = tuple((f['src'], f['dst'], f['bw_mbps']) for f in active)
            if seg is not None and key == prev_key:
                seg['t_end'] = t
                continue
            if not active:
                mid = None
            elif key in index:
                mid = index[key]
            else:
                mid = len(batches) + 1
                index[key] = mid
                batches.append({'batch_id': mid,
                                'flows': [{'src': s, 'dst': d, 'bw_mbps': bw, 'interval': 0} for s, d, bw in key]})
            seg = {'orig_batch': b['batch_id'], 't_start': t, 't_end': t, 'milp_batch_id': mid}
            segments.append(seg)
            prev_key = key

    return {
        'source_seed': os.path.basename(seed_path),
        'sim_topo': sim_topo,
        'milp_topo': milp_topo,
        'flow_duration': D,
        'experiment_duration': exp,
        'note': '每個 batch = 一組同時存在的 flow（靜態快照）；segments 記錄逐秒對應，milp_batch_id=null 表示該段沒有 flow（節能率 100%）。',
        'batches': batches,
        'segments': segments,
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('seed')
    ap.add_argument('output')
    ap.add_argument('--sim-topo', required=True)
    ap.add_argument('--milp-topo', required=True)
    a = ap.parse_args()
    data = build(a.seed, a.sim_topo, a.milp_topo)
    with open(a.output, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"已生成 {a.output}：{len(data['batches'])} 題，{len(data['segments'])} 段")
