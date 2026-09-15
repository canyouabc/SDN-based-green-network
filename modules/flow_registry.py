# -*- coding: utf-8 -*-
"""
flow_registry.py - Active Flow 記帳模組

從 DTM.py（ProjectController）抽出的「# Active Flow 管理」區塊：管理
active_flows 記帳狀態（路徑、priority、安裝時間）、累計統計（flow 數、hop 數）、
flow priority 分配，以及供 _monitor_DTM reroute 觸發用的排序/篩選查詢。

這些邏輯本來就不依賴 Ryu datapath/ofproto，只是巧合放在 controller 裡，
抽出來符合系統性回顧的 MockApp 可測試判準。

DTM.py 保留同名的 wrapper method（add_active_flow 等），維持 routing 模組
透過 self.app.X(...) 呼叫的既有契約（見 modules/routing_host.py 的
RoutingHost Protocol）。

使用方式：
    # DTM.py __init__ 建立（REROUTE_LOAD_WEIGHT 為模組層級常數，建構子傳入避免循環 import）
    self.flow_registry = FlowRegistry(self, FLOW_BASE_PRIORITY, REROUTE_LOAD_WEIGHT)
    self.flow_registry.add_active_flow(host_a, host_b, path)
    self.flow_registry.active_flows                                # 直接讀取記帳 dict
"""

import time


class FlowRegistry:
    def __init__(self, app, base_priority, reroute_load_weight):
        self.app = app
        self.base_priority = base_priority
        # DTM.py 模組層級的 REROUTE_LOAD_WEIGHT 常數，建構子傳入避免
        # flow_registry.py 要 import DTM 造成循環 import
        self.reroute_load_weight = reroute_load_weight

        # {(host_a, host_b): {'path': [dpid, ...], 'priority': int, 'install_time': t}}
        self.active_flows = {}
        self.flow_history_count = 0   # 累計產生的流數（含 reroute）
        self.flow_history_hops = 0    # 累計 hop 數

        # {(src_mac, dst_mac): {'priority': int, 'last_time': float}}
        self.flow_priority = {}

    # =========================================
    # Active Flow 管理
    # =========================================
    def add_active_flow(self, host_a, host_b, path, is_reroute=False, priority=None):
        self.active_flows[(host_a, host_b)] = {
            'path': path,
            'priority': priority,
            'install_time': time.time()
        }
        if not is_reroute:
            self.flow_history_count += 1
            self.flow_history_hops += len(path) - 1
        self.app.flow_stats.assign(host_a, host_b, path)
        print(f"[ActiveFlow] 新增: {host_a} -> {host_b}, 路徑: {path}")

    def remove_active_flow(self, host_a, host_b, path=None, hard_timeout=None):
        entry = self.active_flows.get((host_a, host_b))
        if entry is None:
            return
        if hard_timeout is not None:
            if time.time() - entry['install_time'] < hard_timeout:
                print(f"[ActiveFlow] 忽略舊 Flow Removed 事件: {host_a} -> {host_b}")
                return
        del self.active_flows[(host_a, host_b)]
        self.app.flow_stats.unassign(host_a, host_b)
        print(f"[ActiveFlow] 移除: {host_a} -> {host_b}")

    def get_active_flows(self):
        return [(host_a, host_b, entry['path'])
                for (host_a, host_b), entry in self.active_flows.items()]

    def get_history_avg_hops(self):
        """啟動後累計的平均 hop 數（含 reroute）"""
        if self.flow_history_count == 0:
            return 0.0
        return self.flow_history_hops / self.flow_history_count

    def get_avg_hops(self):
        paths = [e['path'] for e in self.active_flows.values()]
        if not paths:
            return 0.0
        return sum(len(p) - 1 for p in paths) / len(paths)

    def get_switch_flow_count(self):
        """每個 switch 被幾條活躍流量通過"""
        count = {}
        for entry in self.active_flows.values():
            for dpid in entry['path']:
                count[dpid] = count.get(dpid, 0) + 1
        return count

    def _get_next_flow_priority(self, src_mac, dst_mac):
        """每次安裝新路徑就 +1，確保新規則優先度永遠高於舊規則，
        使 OFPFC_ADD 能立即生效而不被舊規則蓋過。
        舊規則靠 idle_timeout=5 自然過期，不主動刪除。

        ⚠️  暴力解：priority 只增不減，上限 65534 後循環回 base_priority。
            若同一 pair 在短時間內大量重算（cascade 風暴），priority 會快速累積。
            根本解法應為追蹤並主動刪除舊規則，但目前以簡化實作為優先。
        """
        key = (src_mac, dst_mac)
        entry = self.flow_priority.get(key)

        if entry is None:
            new_priority = self.base_priority
        else:
            new_priority = entry['priority'] + 1
            if new_priority > 65534:
                new_priority = self.base_priority   # 循環，極少發生

        self.flow_priority[key] = {'priority': new_priority, 'last_time': time.time()}
        return new_priority

    def _get_high_hop_flows(self, top_n=1, threshold=None):
        flows = sorted(self.get_active_flows(), key=lambda x: len(x[2]) - 1, reverse=True)
        if threshold is not None:
            flows = [f for f in flows if len(f[2]) - 1 >= threshold]
        return flows[:top_n]

    def _get_low_share_flows(self, top_n=1, threshold=None):
        switch_count = self.get_switch_flow_count()
        def ratio(f):
            path = f[2]
            hops = len(path) - 1
            if hops == 0:
                return float('inf')
            return sum(switch_count.get(d, 0) for d in path) / hops
        flows = sorted(self.get_active_flows(), key=ratio)
        if threshold is not None:
            flows = [f for f in flows if ratio(f) <= threshold]
        return flows[:top_n]

    def _get_high_load_flows(self, top_n=1, threshold=None):
        all_link_status = self.app.link_status.get_all_link_status()
        scored = []
        for f in self.get_active_flows():
            path = f[2]
            score = 0
            skip = False
            for i in range(len(path) - 1):
                key = (min(path[i], path[i+1]), max(path[i], path[i+1]))
                status = all_link_status.get(key, {}).get('status', 'NORMAL')
                w = self.reroute_load_weight.get(status, 1)
                if w == -999:
                    skip = True
                    break
                score += w
            if not skip:
                scored.append((score, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        if threshold is not None:
            scored = [(s, f) for s, f in scored if s >= threshold]
        return [f for _, f in scored[:top_n]]

    def get_path_switch_load(self, host_a, host_b):
        """指定路徑上，每個 switch 的總流量通過數（來自所有活躍流）"""
        entry = self.active_flows.get((host_a, host_b))
        if entry is None:
            return None
        switch_count = self.get_switch_flow_count()
        return {dpid: switch_count.get(dpid, 0) for dpid in entry['path']}
