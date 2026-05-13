# -*- coding: utf-8 -*-
"""
routing_DTM_dijkstra.py

邏輯與 routing_DTM_2020.py 相同（20%/80% 閾值、add/remove flow、SN優先節能），
差別是不依賴預計算的 k_short.txt，改為在 runtime 以 link 狀態為權重直接跑 Dijkstra。

link 狀態 → Dijkstra 權重對應：
  SN       → 100  （休眠 link，喚醒代價高，懲罰以節能）
  LOW      → 1    （已啟用，略低負載，優先使用）
  NORMAL   → 2    （健康，正常使用）
  HIGH     → 50   （discourage，不直接排除）
  OVERLOAD → inf  （第一輪排除，第二輪才考慮）

介面與 routing_DTM_2020 完全相容：
  select_path_for_new_flow(src_mac, dst_mac)
  k_short_path_status(host_a, host_b, retrans_path=None)
  add_active_flow / remove_active_flow / get_active_flows
"""

import time
import copy

STATUS_WEIGHTS = {
    'SN':       100,
    'LOW':      1,
    'NORMAL':   2,
    'HIGH':     50,
    'OVERLOAD': float('inf'),
}


class Routing_DTM_Dijkstra:
    def __init__(self, app):
        self.app = app
        self.link_status = app.link_status
        self.active_flows = {}   # {(host_a, host_b): {'path': [...], 'install_time': t}}

    # =========================================================
    # active_flows 管理（與 2020 版相同介面）
    # =========================================================

    def add_active_flow(self, host_a, host_b, path):
        self.active_flows[(host_a, host_b)] = {
            'path': path,
            'install_time': time.time()
        }
        print(f"[DTM-Dijk] 新增流量: {host_a} -> {host_b}, 路徑: {path}")

    def remove_active_flow(self, host_a, host_b, path=None, hard_timeout=None):
        entry = self.active_flows.get((host_a, host_b))
        if entry is None:
            return
        if hard_timeout is not None:
            if time.time() - entry['install_time'] < hard_timeout:
                print(f"[DTM-Dijk] 忽略舊 Flow Removed 事件: {host_a} -> {host_b}")
                return
        del self.active_flows[(host_a, host_b)]
        print(f"[DTM-Dijk] 移除流量: {host_a} -> {host_b}")

    def get_active_flows(self):
        return [(host_a, host_b, entry['path'])
                for (host_a, host_b), entry in self.active_flows.items()]

    # =========================================================
    # 核心：Dijkstra（以 link 狀態為權重）
    # =========================================================

    def _dijkstra(self, src_dpid, dst_dpid, exclude_overload=True):
        """
        在目前拓撲上跑 Dijkstra，以 link 狀態為邊的權重。
        exclude_overload=True  → 第一輪，OVERLOAD link 視為不可通
        exclude_overload=False → 第二輪，所有 link 都考慮

        Returns:
            list of dpid（switch 路徑），或 None
        """
        all_link_status = self.link_status.get_all_link_status()
        adjacency = self.app.adjacency
        switches = list(self.app.myswitches)

        if not switches:
            return None
        if src_dpid not in switches or dst_dpid not in switches:
            return None

        dist = {s: float('inf') for s in switches}
        prev = {s: None for s in switches}
        dist[src_dpid] = 0
        unvisited = set(switches)

        while unvisited:
            u = min(unvisited, key=lambda n: dist[n])
            if dist[u] == float('inf'):
                break
            unvisited.remove(u)

            if u not in adjacency:
                continue

            for v, port in adjacency[u].items():
                if port is None:
                    continue

                # link_status 的 key 是 (min, max)，需要標準化
                phy_key = (min(u, v), max(u, v))
                link_info = all_link_status.get(phy_key, {})
                status = link_info.get('status', 'SN')

                if exclude_overload and status == 'OVERLOAD':
                    continue

                weight = STATUS_WEIGHTS.get(status, 2)
                alt = dist[u] + weight
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u

        if dist[dst_dpid] == float('inf'):
            return None

        # 回溯路徑
        path = []
        node = dst_dpid
        while node is not None:
            path.append(node)
            node = prev[node]
        path.reverse()

        if not path or path[0] != src_dpid:
            return None

        return path

    # =========================================================
    # 路徑選擇（與 2020 的 k_short_path_status 對應）
    # =========================================================

    def k_short_path_status(self, host_a, host_b, remove_path=None, retrans_path=None):
        """
        與 routing_DTM_2020.k_short_path_status 介面相容。
        _monitor_DTM 呼叫此函式來進行重路由。

        retrans_path: 若 Dijkstra 算出的最佳路徑跟原路徑相同，回傳 None（不換路）
        remove_path:  保留參數，與 2020 介面相容，此版本不使用
        """
        if host_a not in self.app.host_macs or host_b not in self.app.host_macs:
            print(f"[DTM-Dijk] host_macs 中找不到: {host_a} or {host_b}")
            return None

        src_dpid = self.app.host_macs[host_a][0]
        dst_dpid = self.app.host_macs[host_b][0]

        # 第一輪：排除 OVERLOAD link
        path = self._dijkstra(src_dpid, dst_dpid, exclude_overload=True)

        # 第二輪：找不到時，放寬限制
        if path is None:
            path = self._dijkstra(src_dpid, dst_dpid, exclude_overload=False)

        if path is None:
            print(f"[DTM-Dijk] 無可用路徑: {host_a} -> {host_b}")
            return None

        # 若與原路徑相同，不換路（避免無謂抖動）
        if retrans_path is not None and path == retrans_path:
            return None

        return path

    # =========================================================
    # 新流量進來時呼叫（與 2020 介面相同）
    # =========================================================

    def select_path_for_new_flow(self, host_a, host_b):
        """由 unknown_TCP_packet / unknown_UDP_packet 呼叫"""
        path = self.k_short_path_status(host_a, host_b)
        if path:
            self.add_active_flow(host_a, host_b, path)
            return path
        return None
