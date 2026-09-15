# -*- coding: utf-8 -*-
"""
packet_throttle.py - 未知流量的節流計數

從 DTM.py 的 unknown_TCP_packet／unknown_UDP_packet 中間抽出的節流判斷邏輯：
同一個 (src,dst) pair 每 N 個封包只放行第 0、N、2N... 次進入真正的路由處理，
其餘直接跳過；閒置超過 reset_idle 秒後計數歸零（避免舊流量的計數殘留混進
下一次全新的流量）。

TCP／UDP 各自一個 instance（門檻值本來就不同：TCP N=1000／idle=1.0 秒，
UDP N=1000／idle=5.0 秒）。兩者行為有一處不對稱、刻意保留不統一：UDP 版本
在節流跳過時會印一行 debug log（原本就只有 UDP 有這行，TCP 沒有），用
debug_log 這個建構參數控制，不是搬家順便改掉的行為。

使用方式：
    self.tcp_throttle = PacketThrottle(1000, 1.0, debug_log=False, label="TCP")
    self.udp_throttle = PacketThrottle(1000, 5.0, debug_log=True, label="UDP")

    count = self.tcp_throttle.should_process(pair)   # unknown_TCP_packet 開頭呼叫
    if count is None:
        return   # 節流跳過
    # count 是這個 pair 目前累計到第幾個封包（給後續 debug log 用）
"""

import time


class PacketThrottle:
    def __init__(self, n, reset_idle, debug_log=False, label=""):
        self.n = n
        self.reset_idle = reset_idle
        self.debug_log = debug_log
        self.label = label
        self.pkt_counter = {}   # (src, dst) → 計數
        self.last_seen = {}     # (src, dst) → 最後一次看到的時間

    def should_process(self, pair):
        """回傳這個 pair 目前是第幾個封包（該放行處理），
        或 None（不是第 0/N/2N... 次，節流跳過）。"""
        now = time.time()

        # === 第二層：閒置超過 reset_idle 秒，重置計數器 ===
        if pair in self.last_seen:
            if now - self.last_seen[pair] > self.reset_idle:
                self.pkt_counter[pair] = 0  # 重置，下一個封包會是第 0 次

        # 更新時間戳
        self.last_seen[pair] = now

        # === 第一層：每 N 次只處理一次 ===
        count = self.pkt_counter.get(pair, 0)
        self.pkt_counter[pair] = count + 1

        if count % self.n != 0:
            if self.debug_log and (count <= 5 or count % 200 == 0):
                print(f"[{self.label} THROTTLE] pair={pair} count={count} N={self.n}")
            return None

        return count
