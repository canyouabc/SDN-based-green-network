import os
import pandas as pd
import matplotlib.pyplot as plt


def mean_after_warmup(g):
    """跳過開頭連續 100% 的暖機期，從第一次降到 100% 以下開始取平均"""
    g = g.reset_index(drop=True)
    mask = g["percent"] < 100.0
    if not mask.any():
        return float("nan")
    start = mask.idxmax()
    tail = g.loc[start:]
    return tail.loc[tail["percent"] < 100.0, "percent"].mean()


def analyze(csv_path="experiment.csv", output_dir=".", make_plots=True):
    """
    讀取 csv_path（parse_log.py 產出的格式），計算每個 batch 的能耗統計
    （含 AVERAGE 那一行），輸出圖表與 energy_saving_summary.csv 到 output_dir。
    回傳算好的 base DataFrame（供 sweep 腳本等外部程式直接使用）。
    """
    os.makedirs(output_dir, exist_ok=True)
    df = pd.read_csv(csv_path)

    if make_plots:
        for batch_id, group in df.groupby("batch"):
            group = group.reset_index(drop=True)
            group["time_s"] = group.index * 1  # x軸：每格 1s

            plt.figure(figsize=(12, 4))
            plt.plot(group["time_s"], group["percent"])
            plt.title(f"Batch {batch_id} - Energy Saving")
            plt.xlabel("Time (s)")
            plt.ylabel("Energy Saving (%)")
            plt.ylim(0, 100)
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, f"batch_{batch_id}.png"), dpi=150)
            plt.close()
            print(f"batch_{batch_id}.png 已儲存")

    # 過濾掉 100% 的值
    df_filtered = df[df["percent"] < 100.0]

    base = df_filtered.groupby("batch")["percent"].agg(
        count="count",
    ).round(2)

    base["mean_after_100"] = df.groupby("batch").apply(mean_after_warmup).round(2)

    col_map = {
        "history_avg_hops":         "history_avg_hops",
        "total_flows":              "total_flows",
        "reroute_link":             "re_link",
        "reroute_high_hop":         "re_high_hop",
        "reroute_low_share":        "re_low_share",
        "reroute_high_load":        "re_high_load",
        "shortest_ratio":           "shortest_ratio",
        "danger_unavoidable_count": "danger_unavoidable",
    }
    for src, dst in col_map.items():
        if src in df.columns:
            base[dst] = df.groupby("batch")[src].first()
        else:
            base[dst] = None

    avg_row = base.mean(numeric_only=True).round(2)
    avg_row.name = "AVERAGE"
    base = pd.concat([base, avg_row.to_frame().T])
    base.index.name = "batch"

    print(base.to_string())
    summary_path = os.path.join(output_dir, "energy_saving_summary.csv")
    base.to_csv(summary_path)
    print(f"\n已儲存 {summary_path}")
    return base


if __name__ == "__main__":
    analyze()
