import re
import csv

def parse_log(log_path, csv_path):
    batch_id = None
    rows = []
    history = {}       # {batch_id: {'avg_hops': float, 'total_flows': int}}
    danger_count = {}  # {batch_id: [DANGER_UNAVOIDABLE] 出現次數}

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # 偵測 BATCH marker
            m = re.match(r"=== BATCH (\d+) (START|END)(?:\s+[\d.]+)? ===", line)
            if m:
                batch_id = int(m.group(1))
                continue

            # 偵測 [DANGER_UNAVOIDABLE]
            if line.startswith("[DANGER_UNAVOIDABLE]") and batch_id is not None:
                danger_count[batch_id] = danger_count.get(batch_id, 0) + 1
                continue

            # 偵測 ENERGY 行
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) ENERGY saving=([\d.]+)W percent=([\d.]+)%", line)
            if m and batch_id is not None:
                rows.append({
                    "batch": batch_id,
                    "timestamp": m.group(1),
                    "saving_W": float(m.group(2)),
                    "percent": float(m.group(3)),
                    "history_avg_hops":  None,
                    "total_flows":       None,
                    "reroute_link":      None,
                    "reroute_high_hop":  None,
                    "reroute_low_share": None,
                    "reroute_high_load": None,
                    "shortest_ratio":    None,
                    "danger_unavoidable_count": None,
                })
                continue

            # 偵測 HISTORY 行
            m = re.match(
                r"\S+ \S+ HISTORY avg_hops=([\d.]+) total_flows=(\d+)"
                r"(?: reroute_link=(\d+) reroute_high_hop=(\d+) reroute_low_share=(\d+)"
                r"(?: reroute_high_load=(\d+)"
                r"(?: shortest_ratio=([\d.]+))?)?)?",
                line
            )
            if m and batch_id is not None:
                history[batch_id] = {
                    "avg_hops":           float(m.group(1)),
                    "total_flows":        int(m.group(2)),
                    "reroute_link":       int(m.group(3))   if m.group(3) else None,
                    "reroute_high_hop":   int(m.group(4))   if m.group(4) else None,
                    "reroute_low_share":  int(m.group(5))   if m.group(5) else None,
                    "reroute_high_load":  int(m.group(6))   if m.group(6) else None,
                    "shortest_ratio":     float(m.group(7)) if m.group(7) else None,
                }

    # 回填 history 值到對應 batch 的 ENERGY 行
    for row in rows:
        h = history.get(row["batch"])
        if h:
            row["history_avg_hops"]  = h["avg_hops"]
            row["total_flows"]       = h["total_flows"]
            row["reroute_link"]      = h["reroute_link"]
            row["reroute_high_hop"]  = h["reroute_high_hop"]
            row["reroute_low_share"] = h["reroute_low_share"]
            row["reroute_high_load"] = h["reroute_high_load"]
            row["shortest_ratio"]    = h["shortest_ratio"]
        row["danger_unavoidable_count"] = danger_count.get(row["batch"], 0)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "batch", "timestamp", "saving_W", "percent",
            "history_avg_hops", "total_flows",
            "reroute_link", "reroute_high_hop", "reroute_low_share", "reroute_high_load",
            "shortest_ratio", "danger_unavoidable_count",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"共 {len(rows)} 筆，寫入 {csv_path}")

if __name__ == "__main__":
    parse_log("experiment.log", "experiment.csv")
