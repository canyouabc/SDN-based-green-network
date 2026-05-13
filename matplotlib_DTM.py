import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("experiment.csv")

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
    plt.savefig(f"batch_{batch_id}.png", dpi=150)
    plt.close()
    print(f"batch_{batch_id}.png 已儲存")
    
# 過濾掉 100% 的值
df_filtered = df[df["percent"] < 100.0]

base = df_filtered.groupby("batch")["percent"].agg(
    count="count",
).round(2)

trimmed = df_filtered.groupby("batch")["percent"].apply(
    lambda g: g.iloc[20:]
).reset_index(level=0)
base["mean-20"] = trimmed.groupby("batch")["percent"].mean().round(2)

col_map = {
    "history_avg_hops":  "history_avg_hops",
    "total_flows":       "total_flows",
    "reroute_link":      "re_link",
    "reroute_high_hop":  "re_high_hop",
    "reroute_low_share": "re_low_share",
    "reroute_high_load": "re_high_load",
}
for src, dst in col_map.items():
    if src in df.columns:
        base[dst] = df.groupby("batch")[src].first()
    else:
        base[dst] = None

print(base.to_string())
base.to_csv("energy_saving_summary.csv")
print("\n已儲存 energy_saving_summary.csv")