import random
import json
import argparse
from itertools import permutations

HOSTS             = [f"h{i}" for i in range(1, 55)]
EXPERIMENT_DURATION = 150
FLOW_DURATION       = 40
LAMBDA              = 1 / 1
NUM_BATCHES         = 3
BW_MIN              = 10
BW_MAX              = 40

# 這個拓撲理論上能同時存在的不同向 (src, dst) 流量上限：
# host 數為 n 時，ordered pair（h1→h2 跟 h2→h1 算不同組）共 n*(n-1) 組。
ALL_PAIRS = list(permutations(HOSTS, 2))

# 預估同時流量數（Little's law）：LAMBDA 是 expovariate 的到達率（每秒幾條新流），
# 乘上每條流量存活的 FLOW_DURATION，就是穩態下預期同時存在的流量數。
# 這個值若超過 ALL_PAIRS 的上限，代表目前設定注定會撞到 pick_pair 的 RuntimeError。
EXPECTED_CONCURRENT = LAMBDA * FLOW_DURATION

def gen_batch(rng):
    flows = []
    elapsed = 0.0
    active_until = {}  # {(src, dst): 該 pair 目前這條 flow 的結束時間}

    def pick_pair(t):
        """從所有 ordered pair 中，排除時間 t 仍在跑的那些，在真正空閒的裡面隨機挑一組。
        若當下所有 pair 都被佔用，代表目前流量設定（LAMBDA/FLOW_DURATION）已超出
        這個拓撲（host 數決定的 ordered pair 上限）能承受的並發流量，直接報錯中止，
        不再像過去那樣沿用碰撞結果。"""
        free = [p for p in ALL_PAIRS if active_until.get(p, -1) <= t]
        if not free:
            raise RuntimeError(
                f"[gen_seed] t={t:.2f}s：{len(HOSTS)} 台 host 共 {len(ALL_PAIRS)} 組 "
                f"ordered pair 全部仍在使用中，無法再產生不重複的新流。"
                f"目前 LAMBDA={LAMBDA}、FLOW_DURATION={FLOW_DURATION}"
                f"（預估同時流量數~{EXPECTED_CONCURRENT:.1f}，上限{len(ALL_PAIRS)}）："
                + (f"平均值已超出上限，注定會撞到。"
                   if EXPECTED_CONCURRENT > len(ALL_PAIRS) else
                   f"平均值雖未超出上限，但 Poisson 到達為隨機過程，瞬間並發數會在平均值上下波動，"
                   f"這次剛好在 t={t:.2f}s 波動到全部 pair 都被佔用。")
                + f"請調降流量強度、或改用 host 數更多的拓撲以取得更大的安全邊際。"
            )
        return rng.choice(free)

    # 第一條流立刻發
    src, dst = pick_pair(0.0)
    bw = rng.uniform(BW_MIN, BW_MAX)
    flows.append({"interval": 0.0, "src": src, "dst": dst, "bw_mbps": round(bw, 2)})
    active_until[(src, dst)] = FLOW_DURATION

    while True:
        interval = rng.expovariate(LAMBDA)
        elapsed += interval
        if elapsed >= EXPERIMENT_DURATION:
            break
        src, dst = pick_pair(elapsed)
        bw = rng.uniform(BW_MIN, BW_MAX)
        flows.append({"interval": round(elapsed, 4), "src": src, "dst": dst, "bw_mbps": round(bw, 2)})
        active_until[(src, dst)] = elapsed + FLOW_DURATION

    return flows

def gen_seed(seed, num_batches, output):
    if EXPECTED_CONCURRENT > len(ALL_PAIRS):
        risk_note = "（平均值已超出上限，注定會觸發 RuntimeError）"
    else:
        risk_note = "（平均值未超出上限，但 Poisson 到達仍可能隨機波動撞到上限，不保證不會觸發 RuntimeError）"
    print(f"[gen_seed] host數={len(HOSTS)}，可同時存在的不同向流量上限={len(ALL_PAIRS)} 組 pair，"
          f"目前設定預估同時流量數~{EXPECTED_CONCURRENT:.1f}{risk_note}")
    rng = random.Random(seed)
    batches = []
    for i in range(1, num_batches + 1):
        batches.append({
            "batch_id": i,
            "flows": gen_batch(rng)
        })

    data = {
        "seed":                seed,
        "num_hosts":           len(HOSTS),
        "experiment_duration": EXPERIMENT_DURATION,
        "flow_duration":       FLOW_DURATION,
        "lambda":              LAMBDA,
        "bw_min":              BW_MIN,
        "bw_max":              BW_MAX,
        "num_batches":         num_batches,
        "batches":             batches
    }

    with open(output, "w") as f:
        json.dump(data, f, indent=2)

    total_flows = sum(len(b["flows"]) for b in batches)
    print(f"已生成 {output}：{num_batches} 批，共 {total_flows} 條流")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed",    type=int, required=True)
    parser.add_argument("--batches", type=int, default=NUM_BATCHES)
    parser.add_argument("--output",  type=str, default=None)
    args = parser.parse_args()

    output = args.output or f"seed_{args.seed}.json"
    gen_seed(args.seed, args.batches, output)
