# -*- coding: utf-8 -*-
from scapy.all import *
import threading
import time
import sys
import os

# ── 讀取 demands.txt ──────────────────────────────────────────────────────────

def load_demands(filepath):
    demands = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            src  = int(parts[0])   # host 編號 (46~72)
            dst  = int(parts[1])   # host 編號 (46~72)
            gbps = float(parts[2]) # Gbit/s
            demands.append((src, dst, gbps))
    return demands

# ── 編號轉換 ──────────────────────────────────────────────────────────────────

def host_to_ip(host_id):
    """host 編號 → IP，例如 46 → 10.0.0.1"""
    real_id = host_id - 45         # 46→1, 47→2, ...
    return f"10.0.0.{real_id}"

def host_to_iface(host_id):
    """host 編號 → 網卡名稱，例如 46 → h1-eth0"""
    real_id = host_id - 45
    return f"h{real_id}-eth0"

# ── 流量發送 ──────────────────────────────────────────────────────────────────

def send_traffic(src_id, dst_id, gbps, duration=30):
    """
    從 src 發送流量到 dst
    gbps     : 目標流量 (Gbit/s)
    duration : 發送持續秒數
    """
    dst_ip  = host_to_ip(dst_id)
    iface   = host_to_iface(src_id)
    src_ip  = host_to_ip(src_id)

    # 計算每秒需要發送的封包數
    pkt_size  = 1400          # bytes（接近 MTU）
    bps       = gbps * 1e9    # 轉成 bps
    pkt_per_s = bps / (pkt_size * 8)
    interval  = 1.0 / pkt_per_s  # 每個封包間隔

    pkt = (IP(src=src_ip, dst=dst_ip) /
           UDP(sport=5000, dport=5001) /
           Raw(load='X' * pkt_size))

    print(f"[發送] h{src_id-45}({src_ip}) → h{dst_id-45}({dst_ip}) "
          f"{gbps*1000:.2f} Mbps | 封包間隔={interval*1000:.3f} ms")

    end_time = time.time() + duration
    while time.time() < end_time:
        sendp(pkt, iface=iface, verbose=0)
        time.sleep(interval)

    print(f"[完成] h{src_id-45} → h{dst_id-45} 發送結束")

# ── 主程式 ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    filepath = sys.argv[1] if len(sys.argv) >= 2 else "demands.txt"
    duration = int(sys.argv[2]) if len(sys.argv) >= 3 else 30

    demands = load_demands(filepath)
    print(f"[讀取] {len(demands)} 筆需求，持續發送 {duration} 秒\n")

    # 每條需求開一條 thread 同時發送
    threads = []
    for src, dst, gbps in demands:
        t = threading.Thread(
            target=send_traffic,
            args=(src, dst, gbps, duration)
        )
        threads.append(t)

    # 同時啟動所有 thread
    for t in threads:
        t.start()

    # 等待所有 thread 結束
    for t in threads:
        t.join()

    print("\n[結束] 所有流量發送完畢")