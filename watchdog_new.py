# watchdog.py
import subprocess
import time
import random
import threading
import os
import json
import argparse

RYU_SESSION = "ryu"
MN_SESSION  = "mininet"

GENERATE_ANIMATION = True  # 是否產出動畫 HTML

HOSTS = [f"h{i}" for i in range(1, 17)]
EXPERIMENT_DURATION = 150  # seconds
FLOW_DURATION = 15         # seconds
LAMBDA = 1 / 3             # Poisson rate (期望間隔 3s)
IPERF_PORT = 5001

def cleanup_mininet():
    subprocess.run(["sudo", "mn", "-c"], capture_output=True)
    
def cleanup_tmux():
    subprocess.run(["tmux", "kill-session", "-t", RYU_SESSION],
                   capture_output=True)
    subprocess.run(["tmux", "kill-session", "-t", MN_SESSION],
                   capture_output=True)

def wait_for_tmux_session(session, timeout=15):
    """輪詢直到 tmux session 建立，或逾時"""
    start = time.time()
    while time.time() - start < timeout:
        result = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True
        )
        if result.returncode == 0:
            return True
        time.sleep(0.2)
    print(f"[watchdog] 警告：等待 tmux session '{session}' 逾時")
    return False

def wait_for_log(log_path, keyword, timeout=60):
    """輪詢 log 檔直到出現 keyword，或逾時"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with open(log_path, 'r') as f:
                if keyword in f.read():
                    return True
        except FileNotFoundError:
            pass
        time.sleep(0.5)
    print(f"[watchdog] 警告：等待 '{keyword}' 逾時（{log_path}）")
    return False

def wait_for_log_from(log_path, keyword, start=0, timeout=60):
    """只搜尋 start 位置之後的新內容"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(log_path, 'r') as f:
                f.seek(start)
                if keyword in f.read():
                    return True
        except FileNotFoundError:
            pass
        time.sleep(0.5)
    print(f"[watchdog] 警告：等待 '{keyword}' 逾時（{log_path}）")
    return False

def new_tmux(session, cmd, log_path=None):
    subprocess.Popen([
        "gnome-terminal", "--",
        "bash", "-c",
        f"tmux new-session -s {session} '{cmd}'; exec bash"
    ])
    if log_path:
        wait_for_tmux_session(session)  # 確認 session 建立後再 pipe-pane
        subprocess.run([
            "tmux", "pipe-pane", "-t", session,
            f"cat >> {log_path}"
        ])

def tmux_send(session, cmd):
    subprocess.run(["tmux", "send-keys", "-t", session, cmd, "Enter"])

def start_iperf_servers():
    """在所有 host 上啟動 iperf UDP server（背景執行）"""
    print("[watchdog] 啟動所有 host 的 iperf server...")
    for host in HOSTS:
        tmux_send(MN_SESSION, f"{host} iperf -s -u -p {IPERF_PORT} &")
        time.sleep(0.1)  # 避免 mininet CLI 來不及處理

def launch_flow(src, dst, bw_mbps):
    """送出單一條 iperf UDP 流"""
    ip_index = int(dst[1:])  # h3 -> 3
    dst_ip = f"10.0.0.{ip_index}"
    cmd = (
        f"{src} iperf -c {dst_ip} -u -b {bw_mbps}M "
        f"-t {FLOW_DURATION} -p {IPERF_PORT} &"
    )
    print(f"[flow] {src} -> {dst} ({bw_mbps:.1f} Mbps)")
    tmux_send(MN_SESSION, cmd)

def extract_activeflow_log(src_log, dst_log):
    """從 ryu log 抽出 [ActiveFlow] 新增/移除 與 [SNAPSHOT]，寫入 dst_log"""
    keywords = ("[ActiveFlow] 新增", "[ActiveFlow] 移除", "[SNAPSHOT]", "[NonShortest]",
                "[FLOW_NEW]", "[FLOW_CASCADE_NS]", "[FLOW_CASCADE]")
    try:
        with open(src_log, 'r') as fin, open(dst_log, 'w') as fout:
            for line in fin:
                if any(k in line for k in keywords):
                    fout.write(line)
    except FileNotFoundError:
        print(f"[watchdog] 找不到 {src_log}，略過 activeflow log 整理")

def run_experiment():
    """Poisson process 隨機產生流量"""
    flow_count = 0

    src, dst = random.sample(HOSTS, 2)
    bw_mbps = random.uniform(3, 50)
    launch_flow(src, dst, bw_mbps)
    flow_count += 1

    start_time = time.time()

    while True:
        interval = random.expovariate(LAMBDA)
        time.sleep(interval)

        if time.time() - start_time >= EXPERIMENT_DURATION:
            break

        src, dst = random.sample(HOSTS, 2)
        bw_mbps = random.uniform(3, 50)
        flow_count += 1
        launch_flow(src, dst, bw_mbps)

    print(f"[watchdog] 實驗結束，共產生 {flow_count} 條流")

def run_experiment_from_seed(flows):
    """依照種子檔的流量腳本執行"""
    if not flows:
        return

    first = flows[0]
    launch_flow(first["src"], first["dst"], first["bw_mbps"])
    start_time = time.time()

    for flow in flows[1:]:
        target = flow["interval"]
        wait = target - (time.time() - start_time)
        if wait > 0:
            time.sleep(wait)
        launch_flow(flow["src"], flow["dst"], flow["bw_mbps"])

    remaining = EXPERIMENT_DURATION - (time.time() - start_time)
    if remaining > 0:
        time.sleep(remaining)

    print(f"[watchdog] 實驗結束，共產生 {len(flows)} 條流")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=str, default=None,
                        help="種子檔路徑，例如 seed_42.json；不指定則隨機產生")
    args = parser.parse_args()

    seed_data = None
    if args.seed:
        with open(args.seed) as f:
            seed_data = json.load(f)
        batches_plan = seed_data["batches"]
        print(f"[watchdog] 使用種子檔 {args.seed}，共 {len(batches_plan)} 批")
    else:
        batches_plan = [{"batch_id": i} for i in range(1, 6)]
        print("[watchdog] 隨機模式，共 5 批")

    os.makedirs("log", exist_ok=True)
    run_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    experiment_log = f"log/experiment-{run_timestamp}.log"

    for batch in batches_plan:
        batch_id = batch["batch_id"]
        print(f"\n=== BATCH {batch_id} START ===")

        cleanup_tmux()
        cleanup_mininet()  # 確保上一批殘留的 mininet 清乾淨
        time.sleep(2)

        with open(experiment_log, "a") as f:
            f.write(f"=== BATCH {batch_id} START {time.time():.3f} ===\n")
        with open("experiment.log", "a") as f:
            f.write(f"=== BATCH {batch_id} START ===\n")

        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        ryu_log = f"log/DTM-2026-{timestamp}.txt"
        mn_log  = f"log/mininet-2026-{timestamp}.txt"

        print("[watchdog] 啟動 Ryu...")
        new_tmux(RYU_SESSION, "ryu-manager DTM.py --observe-links", ryu_log)

        print("[watchdog] 啟動 Mininet...")
        new_tmux(MN_SESSION, "sudo python grid_topo.py", mn_log)

        print("[watchdog] 等待 Mininet CLI 就緒...")
        wait_for_log(mn_log, "*** Starting CLI:", timeout=60)
        time.sleep(0.5)

        tmux_send(MN_SESSION, "sendarp")

        print("[watchdog] 等待 ARP 完成...")
        wait_for_log(mn_log, "[*] ARP 全部發送完畢！", timeout=120)
        time.sleep(0.5)

        start_iperf_servers()
        time.sleep(3)

        print("[watchdog] 等待 Ryu link status 就緒...")
        wait_for_log(ryu_log, "SN:", timeout=120)

        print(f"[watchdog] Batch {batch_id} 實驗開始（150s）...")
        if seed_data:
            run_experiment_from_seed(batch["flows"])
        else:
            run_experiment()

        print(f"[watchdog] 等待控制器回傳歷史統計...")
        _log_pos = os.path.getsize("experiment.log") if os.path.exists("experiment.log") else 0
        open("stats_request.flag", "w").close()
        if not wait_for_log_from("experiment.log", "HISTORY avg_hops=", start=_log_pos, timeout=30):
            print("[watchdog] 警告：等待 HISTORY 統計逾時，跳過")
            try:
                os.remove("stats_request.flag")
            except FileNotFoundError:
                pass

        activeflow_log = ryu_log.replace("DTM-", "activeflow-")
        extract_activeflow_log(ryu_log, activeflow_log)
        print(f"[watchdog] ActiveFlow log 已整理至 {activeflow_log}")

        with open(experiment_log, "a") as f:
            f.write(f"=== BATCH {batch_id} END {time.time():.3f} ===\n")
        with open("experiment.log", "a") as f:
            f.write(f"=== BATCH {batch_id} END ===\n")

        print(f"=== BATCH {batch_id} END ===")

        # 先關閉 session，再產出動畫，避免動畫阻塞期間延長 mininet 存活時間
        cleanup_tmux()
        time.sleep(3)
        cleanup_mininet()
        time.sleep(5)  # 等 mininet 完全釋放資源

        if GENERATE_ANIMATION:
            anim_path = activeflow_log.replace("activeflow-", "anim-").replace(".txt", ".html")
            anim_log  = anim_path.replace(".html", ".log")
            with open(anim_log, "w") as flog:
                subprocess.Popen(
                    ["python3", "animate_activeflow.py", activeflow_log,
                     "--save", anim_path, "--interval", "800"],
                    stdout=flog, stderr=flog,
                    start_new_session=True,
                )
            print(f"[watchdog] 動畫背景產出中 → {anim_path}")