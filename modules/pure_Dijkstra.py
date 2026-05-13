# -*- coding: utf-8 -*-
"""
routing.py - Dijkstra 最短路徑演算法模組

使用能耗和延遲作為權重進行最小成本路由計算
提供純粹的路由邏輯，所有依賴由呼叫者傳入
"""
import copy

class Pure_Dijkstra:
    def __init__(self, app):
        self.app = app

    def get_min_delay_path(self, src, dst, required_bw=0):
        
        first_port = self.app.host_macs[src][1]
        final_port = self.app.host_macs[dst][1]
        
        switches = copy.deepcopy(self.app.myswitches)
        adjacency = copy.deepcopy(self.app.adjacency)
        link_delay = copy.deepcopy(self.app.link_delay)
        link_energy = copy.deepcopy(self.app.link_energy)
        link_bw = copy.deepcopy(self.app.link_bw)
        link_used_bw = copy.deepcopy(self.app.link_used_bw)
        switch_energy = copy.deepcopy(self.app.switch_energy)
        """
        Dijkstra 演算法 - 計算最小成本路徑
        
        考慮因素：
        1. 能耗（交換機 + 鏈路）
        2. 剩餘頻寬（如果有要求）
        
        Args:
            src: 源 switch dpid
            dst: 目的地 switch dpid
            first_port: 源 switch 的入埠
            final_port: 目的地 switch 的出埠
            switches: 全部 switch dpid 列表
            adjacency: 鄰接表
            link_delay: 鏈路延遲字典
            link_energy: 鏈路能耗字典
            link_bw: 鏈路頻寬字典
            link_used_bw: 鏈路已用頻寬字典
            switch_energy: switch 能耗字典
            required_bw: 所需頻寬（Mbps）
        
        Returns:
            (路徑列表, switch 列表) 或 None if 無可用路徑
        """
        min_loss = {}
        previous = {}
        for dpid in switches:
            min_loss[dpid] = float('Inf')
            previous[dpid] = None
        min_loss[src] = 0
        
        Q = set(switches)
        
        while len(Q) > 0:
            u = min(Q, key=lambda node: min_loss[node])
            Q.remove(u)
            
            if u not in adjacency:
                continue
            for p in adjacency[u]:
                if adjacency[u][p] is not None:

                    # ← 檢查剩餘頻寬是否足夠
                        if required_bw > 0:
                            cap       = link_bw.get((u, p), 0)
                            key       = (min(u,p), max(u,p))
                            remaining = cap - link_used_bw.get(key, 0)
                            if remaining < required_bw:
                                continue   # 頻寬不足，跳過此 link

                        l_energy = link_energy.get((u, p), 99999)
                        s_energy = switch_energy.get(p, 99999)
                        Dij_weight = l_energy + s_energy
                        alt = min_loss[u] + Dij_weight
                        if alt < min_loss[p]:
                            min_loss[p] = alt
                            previous[p] = u
        
        # 檢查 dst 是否在 previous 中或可達
        if dst not in previous:
            print(f"*** DEBUG: dst {dst} 不在 previous 字典中！switches: {switches}")
            print(f"*** DEBUG: previous 的 key: {list(previous.keys())}")
            return None
        
        if min_loss[dst] == float('Inf'):
            print(f"*** DEBUG: 從 {src} 到 {dst} 距離為無窮大（無路徑）")
            return None
        
        # 回溯出從 dst 到 src 的最小成本路徑
        r = []
        p = dst
        r.append(p)
        q = previous[p]
        while q is not None:
            if q == src:
                r.append(q)
                break
            p = q
            r.append(p)
            q = previous[p]
        r.reverse()
        
        if src == dst:
            path = [src]
        else:
            path = r
        
        r = []
        in_port = first_port
        for s1, s2 in zip(path[:-1], path[1:]):
            out_port = adjacency[s1][s2]
            r.append((s1, in_port, out_port))
            in_port = adjacency[s2][s1]
        r.append((dst, in_port, final_port))
        
        # 將路徑上的 link 和 switch 的能耗歸零
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            link_energy[(u, v)] = 0
            link_energy[(v, u)] = 0
            switch_energy[v] = 0
        switch_energy[path[0]] = 0

        return r, path
