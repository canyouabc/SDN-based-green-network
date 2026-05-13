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
    mean="mean",
).round(2)

for n in [10, 15, 20]:
    trimmed = df_filtered.groupby("batch")["percent"].apply(
        lambda g: g.iloc[n:]
    ).reset_index(level=0)
    base[f"mean-{n}"] = trimmed.groupby("batch")["percent"].mean().round(2)

print(base)
base.to_csv("energy_saving_summary.csv")
print("\n已儲存 energy_saving_summary.csv")