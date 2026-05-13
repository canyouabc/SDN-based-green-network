import re
import csv

def parse_log(log_path, csv_path):
    batch_id = None
    rows = []

    with open(log_path, "r") as f:
        for line in f:
            line = line.strip()

            # 偵測 BATCH marker
            m = re.match(r"=== BATCH (\d+) (START|END) ([\d.]+) ===", line)
            if m:
                batch_id = int(m.group(1))
                continue

            # 偵測 ENERGY 行
            m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) ENERGY saving=([\d.]+)W percent=([\d.]+)%", line)
            if m and batch_id is not None:
                rows.append({
                    "batch": batch_id,
                    "timestamp": m.group(1),
                    "saving_W": float(m.group(2)),
                    "percent": float(m.group(3)),
                })

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["batch", "timestamp", "saving_W", "percent"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"共 {len(rows)} 筆，寫入 {csv_path}")

parse_log("experiment.log", "experiment.csv")