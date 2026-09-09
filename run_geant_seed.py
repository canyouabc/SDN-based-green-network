# run_geant_seed.py
# ─────────────────────────────────────────────────────────────────
# 極簡模式：跑一份 seed（例如 gen_geant_seed.py 產出的 GEANT seed json）
# 的全部 batch，只產出 experiment.csv + energy_saving_summary.csv，
# 不留 snapshot/動畫、預設也不留 experiment.log（純數據）。
#
# 做法比照 sweep_sorted.py 的 run_one_combo：直接 instantiate
# sim.Simulator 逐 batch 跑，不經過 sim.py 的 CLI（那條路徑才會
# 產生 snapshot 檔跟背景動畫），只是這裡只跑單一設定，不做多組
# COMBOS 比較。
#
# 使用方式：
#   編輯下方 SEED_PATH / TOPO / ALGORITHM 後：
#   python run_geant_seed.py
# ─────────────────────────────────────────────────────────────────
import os
import sys
import time
import json
from datetime import datetime

import sim
from parse_log import parse_log
import matplotlib_DTM

# ── 設定 ────────────────────────────────────────────────────────
SEED_PATH    = 'data/geant_seed_full.json'
TOPO         = 'geant'
ALGORITHM    = 'sorted'
KEEP_RAW_LOG = False   # False：parse_log 轉完 csv 後刪掉中繼 experiment.log，只留 csv
PROGRESS_EVERY = 50    # 每跑幾個 batch 印一次進度


def main():
    with open(SEED_PATH, encoding='utf-8') as f:
        seed_data = json.load(f)

    sim.TOPO = TOPO
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    run_dir = f"log/geant-{timestamp}"
    os.makedirs(run_dir, exist_ok=True)
    log_path = f"{run_dir}/experiment.log"

    flow_duration = seed_data.get('flow_duration', 900)
    exp_dur       = seed_data.get('experiment_duration', 900)
    batches       = seed_data['batches']
    n             = len(batches)

    print(f"[run_geant_seed] topo={TOPO} algorithm={ALGORITHM} "
          f"seed={SEED_PATH}（{n} 個 batch）")
    print(f"[run_geant_seed] 輸出目錄 → {run_dir}")

    real_stdout = sys.stdout
    devnull = open(os.devnull, 'w', encoding='utf-8', errors='replace')

    t_start = time.time()
    for i, batch in enumerate(batches, 1):
        # 靜音 routing 模組的逐事件 print()（不動任何專案原始碼，只是
        # 這裡不想看到；experiment.log 該有的 BATCH/ENERGY/HISTORY 行
        # 是靠 s._log() 直接寫檔，不受這裡影響）
        sys.stdout = devnull
        try:
            s = sim.Simulator(algorithm=ALGORITHM, log_path=log_path)
            bid = batch['batch_id']
            events = sim.load_seed_events(batch, flow_duration)
            event_idx, n_events = 0, len(events)

            s._log(f"=== BATCH {bid} START ===")
            for sec in range(0, exp_dur + 1):
                while event_idx < n_events and events[event_idx][0] <= sec:
                    sim_t, kind, src, dst, bw = events[event_idx]
                    if kind == 'admit':
                        s.admit(src, dst, bw, sim_t=sim_t)
                    else:
                        s.depart(src, dst, sim_t=sim_t)
                    event_idx += 1
                s._log_energy_second(sec)
            s._log_history()
            s._log(f"=== BATCH {bid} END ===")
        finally:
            sys.stdout = real_stdout

        if i % PROGRESS_EVERY == 0 or i == n:
            elapsed = time.time() - t_start
            eta = elapsed / i * (n - i)
            print(f"[run_geant_seed] {i}/{n} batch 完成，"
                  f"已耗時 {elapsed/60:.1f} 分鐘，預估剩餘 {eta/60:.1f} 分鐘")

    csv_path = f"{run_dir}/experiment.csv"
    parse_log(log_path, csv_path)
    matplotlib_DTM.analyze(csv_path, run_dir, make_plots=False)

    if not KEEP_RAW_LOG:
        os.remove(log_path)
        print(f"[run_geant_seed] 已刪除中繼 log：{log_path}")

    print(f"[run_geant_seed] 完成 → {run_dir}/experiment.csv, "
          f"{run_dir}/energy_saving_summary.csv")


if __name__ == '__main__':
    main()
