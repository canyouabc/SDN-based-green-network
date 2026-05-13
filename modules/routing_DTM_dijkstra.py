# -*- coding: utf-8 -*-
"""
routing_DTM_dijkstra.py

與 routing_DTM_2020 邏輯完全相同（SN 懲罰、minimize sn_count 再 minimize hops、
兩輪選路），差別是以 runtime Dijkstra 取代預計算的 k_short.txt。

權重設計對應 2020 的 (sn_counter, hop_counter) 排序：
  Round 1: OVERLOAD → 排除, SN → 1000, LOW/NORMAL/HIGH → 1
  Round 2: SN → 1000, OVERLOAD/LOW/NORMAL/HIGH → 1
SN 權重 1000 >> 任何合理拓撲的最大跳數，確保「先最小化 SN 數，再最小化跳數」。
"""

from .routing_base import RoutingBase

SN_WEIGHT = 1000
NORMAL_WEIGHT = 1


class Routing_DTM_Dijkstra(RoutingBase):

    def __init__(self, app):
        super().__init__(app)
        self.link_status = app.link_status

    # =========================================================
    # 核心：Dijkstra（以 link 狀態為權重）
    # =========================================================

    def _dijkstra(self, src_dpid, dst_dpid, exclude_overload=True):
        """
        exclude_overload=True  → Round 1，OVERLOAD link 不可通
        exclude_overload=False → Round 2，所有 link 都考慮

        Returns: list of dpid，或 None
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

            for v in adjacency[u]:
                if adjacency[u][v] is None:
                    continue

                phy_key = (min(u, v), max(u, v))
                link_info = all_link_status.get(phy_key, {})
                status = link_info.get('status', 'SN')

                if exclude_overload and status == 'OVERLOAD':
                    continue

                weight = SN_WEIGHT if status == 'SN' else NORMAL_WEIGHT
                alt = dist[u] + weight
                if alt < dist[v]:
                    dist[v] = alt
                    prev[v] = u

        if dist[dst_dpid] == float('inf'):
            return None

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
    # 公開介面
    # =========================================================

    def find_reroute_path(self, host_a, host_b, remove_path=None, retrans_path=None):
        """
        _monitor_DTM 呼叫，尋找重路由路徑。
        remove_path:  保留參數，與 2020 介面相容（Dijkstra 不需要，OVERLOAD 已透過 exclude 自然避開）
        retrans_path: 若結果等於目前路徑，回傳 None（不換路）
        """
        if host_a not in self.app.host_macs or host_b not in self.app.host_macs:
            print(f"[DTM-Dijk] host_macs 中找不到: {host_a} or {host_b}")
            return None

        src_dpid = self.app.host_macs[host_a][0]
        dst_dpid = self.app.host_macs[host_b][0]

        # Round 1：排除 OVERLOAD
        path = self._dijkstra(src_dpid, dst_dpid, exclude_overload=True)

        # Round 2：放寬 OVERLOAD
        if path is None:
            path = self._dijkstra(src_dpid, dst_dpid, exclude_overload=False)

        if path is None:
            print(f"[DTM-Dijk] 無可用路徑: {host_a} -> {host_b}")
            return None

        if retrans_path is not None and path == retrans_path:
            return None

        return path

    def find_path_for_new_flow(self, host_a, host_b):
        """新流量進來時呼叫"""
        path = self.find_reroute_path(host_a, host_b)
        if path:
            self.app.add_active_flow(host_a, host_b, path)
            return path
        return None
