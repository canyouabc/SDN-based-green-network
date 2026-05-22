import random
import json
import argparse

HOSTS             = [f"h{i}" for i in range(1, 17)]
EXPERIMENT_DURATION = 150
FLOW_DURATION       = 15
LAMBDA              = 1 / 3

def gen_batch(rng):
    flows = []
    elapsed = 0.0

    # 第一條流立刻發
    src, dst = rng.sample(HOSTS, 2)
    bw = rng.uniform(3, 50)
    flows.append({"interval": 0.0, "src": src, "dst": dst, "bw_mbps": round(bw, 2)})

    while True:
        interval = rng.expovariate(LAMBDA)
        elapsed += interval
        if elapsed >= EXPERIMENT_DURATION:
            break
        src, dst = rng.sample(HOSTS, 2)
        bw = rng.uniform(3, 50)
        flows.append({"interval": round(elapsed, 4), "src": src, "dst": dst, "bw_mbps": round(bw, 2)})

    return flows

def gen_seed(seed, num_batches, output):
    rng = random.Random(seed)
    batches = []
    for i in range(1, num_batches + 1):
        batches.append({
            "batch_id": i,
            "flows": gen_batch(rng)
        })

    data = {
        "seed":                seed,
        "lambda":              LAMBDA,
        "flow_duration":       FLOW_DURATION,
        "experiment_duration": EXPERIMENT_DURATION,
        "batches":             batches
    }

    with open(output, "w") as f:
        json.dump(data, f, indent=2)

    total_flows = sum(len(b["flows"]) for b in batches)
    print(f"已生成 {output}：{num_batches} 批，共 {total_flows} 條流")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed",    type=int, required=True)
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--output",  type=str, default=None)
    args = parser.parse_args()

    output = args.output or f"seed_{args.seed}.json"
    gen_seed(args.seed, args.batches, output)
