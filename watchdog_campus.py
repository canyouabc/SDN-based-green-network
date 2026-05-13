# watchdog_campus.py — 校園網路拓撲版本
import subprocess
import time
import random
import threading
import os

RYU_SESSION = "ryu"
MN_SESSION  = "mininet"

HOSTS = [f"h{i}" for i in range(1, 28)]
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

def run_experiment():
    """Poisson process 產生流量，持續 150 秒"""
    flow_count = 0

    # 第一條流立刻發，然後才開始計時
    src, dst = random.sample(HOSTS, 2)
    bw_mbps = random.uniform(3, 50)
    launch_flow(src, dst, bw_mbps)
    flow_count += 1

    start_time = time.time()  # 第一條流發出後才開始計時

    while True:
        elapsed = time.time() - start_time
        if elapsed >= EXPERIMENT_DURATION:
            break

        interval = random.expovariate(LAMBDA)

        remaining = EXPERIMENT_DURATION - (time.time() - start_time)
        if interval > remaining:
            time.sleep(remaining)
            break

        time.sleep(interval)

        src, dst = random.sample(HOSTS, 2)
        bw_mbps = random.uniform(3, 50)

        flow_count += 1
        launch_flow(src, dst, bw_mbps)

    print(f"[watchdog] 實驗結束，共產生 {flow_count} 條流")

if __name__ == "__main__":
    os.makedirs("log", exist_ok=True)
    run_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    experiment_log = f"log/experiment-{run_timestamp}.log"

    for batch_id in range(1, 6):
        print(f"\n=== BATCH {batch_id} START ===")

        cleanup_tmux()
        cleanup_mininet()  # 確保上一批殘留的 mininet 清乾淨
        time.sleep(2)

        with open(experiment_log, "a") as f:
            f.write(f"=== BATCH {batch_id} START {time.time():.3f} ===\n")

        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        ryu_log = f"log/DTM-2026-{timestamp}.txt"
        mn_log  = f"log/mininet-2026-{timestamp}.txt"

        print("[watchdog] 啟動 Ryu...")
        new_tmux(RYU_SESSION, "ryu-manager DTM.py --observe-links", ryu_log)

        print("[watchdog] 啟動 Mininet...")
        new_tmux(MN_SESSION, "sudo python new_topo.py", mn_log)

        print("[watchdog] 等待 Mininet CLI 就緒...")
        wait_for_log(mn_log, "*** Starting CLI:", timeout=60)
        time.sleep(0.5)

        tmux_send(MN_SESSION, "sendarp")

        print("[watchdog] 等待 ARP 完成...")
        wait_for_log(mn_log, "[*] ARP 全部發送完畢！", timeout=120)
        time.sleep(0.5)

        start_iperf_servers()
        time.sleep(3)

        print(f"[watchdog] Batch {batch_id} 實驗開始（150s）...")
        run_experiment()

        with open(experiment_log, "a") as f:
            f.write(f"=== BATCH {batch_id} END {time.time():.3f} ===\n")

        print(f"=== BATCH {batch_id} END ===")

        # 關閉這批的 session
        cleanup_tmux()
        time.sleep(3)
        cleanup_mininet()
        time.sleep(5)  # 等 mininet 完全釋放資源
