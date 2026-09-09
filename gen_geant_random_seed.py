# gen_geant_random_seed.py
# ─────────────────────────────────────────────────────────────────
# 產生 GEANT 拓撲用的隨機流量 seed json，跟 gen_geant_seed.py 轉出來的
# 真實資料格式相容（同樣是「一個 batch = 一組同時進場、撐滿整個視窗的
# 聚合流量」），可以直接餵給 sim.py / sweep_sorted.py。
#
# 跟 gen_seed.py（Poisson 到達模型）不同：這裡每個 batch 是固定數量的
# flow，全部在 interval=0 同時進場，沒有到達時間分佈，單純測試「N 條
# 隨機 host pair、隨機頻寬」這個情境本身。
#
# 使用方式：
#   python gen_geant_random_seed.py --num-flows 90 --num-batches 10 \
#       --output data/geant_random_90.json
# ─────────────────────────────────────────────────────────────────
import argparse
import json
import random
from itertools import permutations

NUM_HOSTS = 22
ALL_PAIRS = list(permutations([f'h{i}' for i in range(1, NUM_HOSTS + 1)], 2))  # 462 組


def gen_batch(rng, num_flows, bw_min, bw_max):
    pairs = rng.sample(ALL_PAIRS, num_flows)  # 不重複，同一批不會有同一個 (src,dst) 出現兩次
    flows = []
    for src, dst in pairs:
        bw = rng.uniform(bw_min, bw_max)
        flows.append({'interval': 0.0, 'src': src, 'dst': dst, 'bw_mbps': round(bw, 4)})
    return flows


def main():
    parser = argparse.ArgumentParser(description='GEANT 隨機流量 seed 產生器')
    parser.add_argument('--seed',        type=int, default=42)
    parser.add_argument('--num-flows',   type=int, required=True, help='每個 batch 幾條 flow')
    parser.add_argument('--num-batches', type=int, required=True)
    parser.add_argument('--bw-min',      type=float, default=0.1, help='每條 flow 頻寬下限 (Mbps)')
    parser.add_argument('--bw-max',      type=float, default=20.0, help='每條 flow 頻寬上限 (Mbps)')
    parser.add_argument('--output',      type=str, required=True)
    args = parser.parse_args()

    if args.num_flows > len(ALL_PAIRS):
        raise ValueError(f'--num-flows={args.num_flows} 超過 22 節點最多可用的 {len(ALL_PAIRS)} 組不重複 pair')

    rng = random.Random(args.seed)
    batches = []
    for i in range(1, args.num_batches + 1):
        batches.append({
            'batch_id': i,
            'flows': gen_batch(rng, args.num_flows, args.bw_min, args.bw_max),
        })

    data = {
        'source':              f'隨機產生（seed={args.seed}），每 batch {args.num_flows} 條不重複 host pair，'
                                f'頻寬均勻分布於 [{args.bw_min}, {args.bw_max}] Mbps',
        'num_hosts':           NUM_HOSTS,
        'experiment_duration': 900,
        'flow_duration':       900,
        'num_batches':         len(batches),
        'batches':             batches,
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

    print(f'[gen_geant_random_seed] 產生 {len(batches)} 個 batch，每個 {args.num_flows} 條 flow，'
          f'頻寬 [{args.bw_min}, {args.bw_max}] Mbps → {args.output}')


if __name__ == '__main__':
    main()
