# -*- coding: utf-8 -*-
"""
flow_oracle.py - Oracle 模式：controller 的 active flow 完全由外部（watchdog）告知（驗證用）

前提：比照多數論文的假設，controller 能事先得知每條 flow 的起訖、頻寬與結束時間。
這個模組讓 Mininet 的 controller 邏輯狀態與 sim.py 一致：
  - start：watchdog 啟動 flow 前寫 "start src_mac dst_mac bw_mbps"，controller 收到後
    比照 sim.py Simulator.admit()：先把 bw 寫進 app._flow_sizes，再呼叫 admit_flow
    選路並主動安裝規則（proactive，不等 packet-in）。
  - end：flow 理論到期時寫 "end src_mac dst_mac"，controller 從 active_flows 移除、
    觸發 on_flow_removed（cascade 風格）、刪除 _flow_sizes（比照 Simulator.depart()）。
    switch 上的規則不動，照舊靠 idle_timeout 自然過期。

oracle 模式開啟時，DTM.py／packet_handler_v1 另有兩處配合：
  - flow_removed_handler 不再影響 active_flows（規則過期與 flow 存活脫鉤）
  - 不在 active_flows 的 TCP/UDP packet-in 不 admit（例如 iperf server 回傳的報告封包）

預設關閉（DTM.py 的 ENABLE_FLOW_ORACLE）。真實網路需要端點或編排系統配合才能提供這些資訊。

使用方式：
    self.flow_oracle = FlowOracle(self, idle_timeout=5)   # DTM.py __init__（旗標開才建立）
    self.flow_oracle.poll()                               # 監聽執行緒每 0.05 秒呼叫
"""

import os
import time

FLOW_ORACLE_QUEUE = "flow_oracle.queue"


class FlowOracle:
    def __init__(self, app, idle_timeout, path=FLOW_ORACLE_QUEUE):
        self.app = app
        self.idle_timeout = idle_timeout
        self.path = path
        if not hasattr(app, '_flow_sizes'):
            app._flow_sizes = {}   # 與 sim.py MockApp 同名，routing_DTM_sorted._get_flow_bw 會讀
        # 從目前檔尾開始讀，忽略啟動前殘留的舊內容
        self._offset = os.path.getsize(path) if os.path.exists(path) else 0

    def poll(self):
        try:
            with open(self.path, 'r') as f:
                f.seek(self._offset)
                data = f.read()
        except FileNotFoundError:
            return
        if not data:
            return
        # 只處理完整的行，半行留到下一輪
        end = data.rfind('\n') + 1
        self._offset += len(data[:end].encode('utf-8'))
        for line in data[:end].splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == 'start':
                self.start_flow(parts[1], parts[2], float(parts[3]))
            elif len(parts) == 3 and parts[0] == 'end':
                self.end_flow(parts[1], parts[2])

    def start_flow(self, src_mac, dst_mac, bw_mbps):
        """比照 packet_handler_v1 的 UDP admit 流程，只是觸發來源從 packet-in 換成 oracle。"""
        if src_mac not in self.app.host_macs or dst_mac not in self.app.host_macs:
            print(f"[ORACLE_START] {time.time():.3f} {src_mac} -> {dst_mac} host 尚未發現，略過")
            return
        self.app._flow_sizes[(src_mac, dst_mac)] = bw_mbps
        switch_path = self.app.routing_module.admit_flow(src_mac, dst_mac)
        if not switch_path:
            print(f"[ORACLE_START] {time.time():.3f} {src_mac} -> {dst_mac} 找不到路徑")
            return
        path = self.app.build_path_with_ports(switch_path, src_mac, dst_mac)
        if not path:
            print(f"[ORACLE_START] {time.time():.3f} {src_mac} -> {dst_mac} 無法轉換路徑信息: {switch_path}")
            return
        prio = self.app._get_next_flow_priority(src_mac, dst_mac)
        self.app.install_flows_for_path(path, src_mac, dst_mac, priority=prio, idle_timeout=self.idle_timeout)
        if (src_mac, dst_mac) in self.app.flow_registry.active_flows:
            self.app.flow_registry.active_flows[(src_mac, dst_mac)]['priority'] = prio
        print(f"[ORACLE_START] {time.time():.3f} {src_mac} -> {dst_mac} bw={bw_mbps} path={switch_path} priority={prio}")

    def end_flow(self, src_mac, dst_mac):
        self.app._flow_sizes.pop((src_mac, dst_mac), None)
        entry = self.app.flow_registry.active_flows.get((src_mac, dst_mac))
        if entry is None:
            print(f"[ORACLE_END] {time.time():.3f} {src_mac} -> {dst_mac} 不在 active_flows，略過")
            return
        removed_path = entry['path']
        self.app.remove_active_flow(src_mac, dst_mac)
        if self.app.routing_module.REROUTE_STYLE == 'cascade':
            self.app.routing_module.on_flow_removed(src_mac, dst_mac, removed_path)
        print(f"[ORACLE_END] {time.time():.3f} {src_mac} -> {dst_mac} path={removed_path}")
