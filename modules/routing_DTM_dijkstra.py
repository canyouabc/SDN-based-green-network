# -*- coding: utf-8 -*-
"""
routing_DTM_dijkstra.py

兩種 Dijkstra 模式：
  energy  mode: SN=1000, 其他=1   → 先最小化 SN 數，再最小化 hop 數
  shortest mode: SN=101,  其他=100 → 先最小化 hop 數，再最小化 SN 數

兩輪選路（Round 1 排除 OVERLOAD，Round 2 放開），兩種模式各算一次後進比較區。

SHORTEST_CANDIDATE:
  'dijkstra' → 用 Dijkstra shortest mode 作為比較候選
  'kshort'   → 用 2020 k-short 選路邏輯作為比較候選
"""

import random
from .routing_base import RoutingBase

# ==================== energy mode 權重 ====================
SN_WEIGHT     = 1000
NORMAL_WEIGHT = 1

# ==================== shortest mode 權重 ====================
SHORTEST_HOP_WEIGHT = 100   # 非 SN link
SHORTEST_SN_WEIGHT  = 101   # SN link（同 hop 數時，SN 多的輸）

# ==================== 最短路徑比較開關 ====================
ENABLE_SHORTEST_PATH   = True       # True=啟用雙模式比較；False=僅使用 energy mode
SHORTEST_CANDIDATE     = 'kshort'   # 'dijkstra' 或 'kshort'
SHORTEST_HOP_TOLERANCE = 3          # energy hop 數 - candidate hop 數 >= N 時，選 candidate


class Routing_DTM_Dijkstra(RoutingBase):

    def __init__(self, app):
        super().__init__(app)
        self.link_status = app.link_status
        self.shortest_selected_count = 0
        self.total_path_selections   = 0
        self.k_short_paths = {}
        self.load_k_short_paths('data/k_short.txt')

    # =========================================================
    # 核心：Dijkstra（以 link 狀態為權重）
    # =========================================================

    def _dijkstra(self, src_dpid, dst_dpid, exclude_overload=True, mode='energy'):
        """
        mode='energy'  : SN=1000, 其他=1
        mode='shortest': SN=101,  其他=100
        exclude_overload=True → Round 1，OVERLOAD link 不可通
        """
        all_link_status = self.link_status.get_all_link_status()
        adjacency = self.app.adjacency
        switches  = list(self.app.myswitches)

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

                phy_key   = (min(u, v), max(u, v))
                link_info = all_link_status.get(phy_key, {})
                status    = link_info.get('status', 'SN')

                if exclude_overload and status == 'OVERLOAD':
                    continue

                if mode == 'energy':
                    weight = SN_WEIGHT if status == 'SN' else NORMAL_WEIGHT
                else:  # shortest
                    weight = SHORTEST_SN_WEIGHT if status == 'SN' else SHORTEST_HOP_WEIGHT

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
    # 比較區：energy vs shortest，決定最終路徑
    # =========================================================

    def _compare_paths(self, energy_path, shortest_path):
        """
        比較兩種模式的結果，回傳 (selected_path, used_shortest)。
        條件：shortest hop 數 <= energy hop 數 + SHORTEST_HOP_TOLERANCE → 選 shortest
        """
        if energy_path is None and shortest_path is None:
            return None, False
        if energy_path is None:
            return shortest_path, True
        if shortest_path is None:
            return energy_path, False

        energy_hops  = len(energy_path)  - 1
        shortest_hops = len(shortest_path) - 1

        if shortest_hops + SHORTEST_HOP_TOLERANCE <= energy_hops:
            return shortest_path, True
        return energy_path, False

    # =========================================================
    # 2020 k-short 選路邏輯
    # =========================================================

    def load_k_short_paths(self, filepath='data/k_short.txt'):
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    i = 0
                    while i + 4 < len(parts):
                        host_a = parts[i]
                        host_b = parts[i + 1]
                        path_str = parts[i + 4].strip('[]')
                        switch_path = [int(x) for x in path_str.split(',')]
                        key = (host_a, host_b)
                        if key not in self.k_short_paths:
                            self.k_short_paths[key] = []
                        self.k_short_paths[key].append(switch_path)
                        i += 5
            print(f"[k_short] 載入 {len(self.k_short_paths)} 個 host pair 的預算路徑")
        except FileNotFoundError:
            print(f"[k_short] 找不到 {filepath}，kshort 模式無法使用")

    def _find_kshort_path(self, host_a, host_b, exclude_overload=True):
        """2020 k-short 選路：(sn_counter, hop_counter) 排序，最小者優先"""
        paths = self.k_short_paths.get((host_a, host_b))
        if not paths:
            return None

        all_link_status = self.link_status.get_all_link_status()

        scored = []
        for path in paths:
            sn_count  = 0
            hop_count = 0
            has_overload = False
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                phy_key  = (min(u, v), max(u, v))
                status   = all_link_status.get(phy_key, {}).get('status', 'NORMAL')
                hop_count += 1
                if status == 'SN':
                    sn_count += 1
                elif status == 'OVERLOAD':
                    has_overload = True
                    break
            if exclude_overload and has_overload:
                continue
            scored.append((sn_count, hop_count, path))

        if not scored:
            return None

        scored.sort(key=lambda x: (x[0], x[1]))
        best_sn, best_hop = scored[0][0], scored[0][1]
        candidates = [p for sn, hop, p in scored if sn == best_sn and hop == best_hop]
        return random.choice(candidates)

    # =========================================================
    # 比較區入口
    # =========================================================

    def _find_best_path(self, src_dpid, dst_dpid, host_a=None, host_b=None, exclude_overload=True):
        """energy path 與候選 path 比較；ENABLE_SHORTEST_PATH=False 時僅跑 energy mode"""
        energy_path = self._dijkstra(src_dpid, dst_dpid, exclude_overload, mode='energy')
        if not ENABLE_SHORTEST_PATH:
            return energy_path, False

        if SHORTEST_CANDIDATE == 'kshort' and host_a and host_b:
            candidate = self._find_kshort_path(host_a, host_b, exclude_overload)
        else:
            candidate = self._dijkstra(src_dpid, dst_dpid, exclude_overload, mode='shortest')

        return self._compare_paths(energy_path, candidate)

    # =========================================================
    # 統計
    # =========================================================

    def get_shortest_ratio(self):
        if self.total_path_selections == 0:
            return 0.0
        return self.shortest_selected_count / self.total_path_selections

    # =========================================================
    # 公開介面
    # =========================================================

    def select_path(self, host_a, host_b, remove_path=None, retrans_path=None):
        if host_a not in self.app.host_macs or host_b not in self.app.host_macs:
            print(f"[DTM-Dijk] host_macs 中找不到: {host_a} or {host_b}")
            return None

        src_dpid = self.app.host_macs[host_a][0]
        dst_dpid = self.app.host_macs[host_b][0]

        # Round 1：排除 OVERLOAD
        path, used_shortest = self._find_best_path(src_dpid, dst_dpid, host_a, host_b, exclude_overload=True)

        # Round 2：放寬 OVERLOAD
        if path is None:
            path, used_shortest = self._find_best_path(src_dpid, dst_dpid, host_a, host_b, exclude_overload=False)

        if path is None:
            print(f"[DTM-Dijk] 無可用路徑: {host_a} -> {host_b}")
            return None

        if retrans_path is not None and path == retrans_path:
            return None

        self.total_path_selections += 1
        if used_shortest:
            self.shortest_selected_count += 1

        return path

    def admit_flow(self, host_a, host_b):
        path = self.select_path(host_a, host_b)
        if path:
            self.app.add_active_flow(host_a, host_b, path)
            return path
        return None
