# -*- coding: utf-8 -*-
"""
routing.py - Dijkstra 最短路徑演算法模組

使用能耗和延遲作為權重進行最小成本路由計算
提供純粹的路由邏輯，所有依賴由呼叫者傳入
"""
import copy
import heapq
import os

class Auto_routing_k_short:
    def __init__(self, app):
        self.app = app
    def _calculate_path_cost(self, switch_path, link_energy, switch_energy):
        """
        計算路徑的總成本（能耗和）
        
        Args:
            switch_path: switch dpid 列表 [s1, s2, ..., sn]
            link_energy: 鏈路能耗字典
            switch_energy: switch 能耗字典
        
        Returns:
            總成本（浮點數）
        """
        total_cost = 0.0
        
        # 計算鏈路成本
        for i in range(len(switch_path) - 1):
            u, v = switch_path[i], switch_path[i + 1]
            total_cost += link_energy.get((u, v), 0)
        
        # 計算 switch 成本（除了源和目的地 switch）
        for i in range(1, len(switch_path) - 1):
            total_cost += switch_energy.get(switch_path[i], 0)
        
        return total_cost


    def yens_k_shortest_paths(self, k, src, dst, required_bw=0):
        first_port = self.app.host_macs[src][1]
        final_port = self.app.host_macs[dst][1]
        src_dpid = self.app.host_macs[src][0]   # 加這行
        dst_dpid = self.app.host_macs[dst][0]   # 加這行
        myswitches = copy.deepcopy(self.app.myswitches)
        adjacency = copy.deepcopy(self.app.adjacency)
        link_delay = copy.deepcopy(self.app.link_delay)
        link_energy = copy.deepcopy(self.app.link_energy)
        link_bw = copy.deepcopy(self.app.link_bw)
        link_used_bw = copy.deepcopy(self.app.link_used_bw)
        switch_energy = copy.deepcopy(self.app.switch_energy)

        """
        Yen's K-Shortest Paths 演算法
        
        使用能耗作為權重，計算 k 條最短路徑（可有邊重疊）
        """
        
        if k <= 0:
            return []
        
        # ========== 保存原始能耗（用於計算最終成本） ==========
        original_link_energy = copy.deepcopy(link_energy)
        original_switch_energy = copy.deepcopy(switch_energy)
        
        # ========== 第 1 條路徑：直接 Dijkstra ==========
        temp_link_energy = copy.deepcopy(original_link_energy)
        temp_switch_energy = copy.deepcopy(original_switch_energy)
        
        result = self.get_min_delay_path(
            src_dpid, dst_dpid, first_port, final_port,
            myswitches, adjacency, temp_link_energy, link_bw,
            link_used_bw, temp_switch_energy, 
            required_bw=required_bw
        )
        
        if result is None:
            return []
        
        path_list_1, switch_path_1 = result
        A = [(switch_path_1, path_list_1)]  # A 儲存已找到的路徑
        found_paths = {tuple(switch_path_1)}  # 已加入 A 的路徑（去重用）
        
        print(f"      [YING's] 路徑 1: {switch_path_1}, 成本={self._calculate_path_cost(switch_path_1, original_link_energy, original_switch_energy)}")
        
        # ========== 對第 1 條路徑進行一輪：生成初始候選 ==========
        B = []  # 候選路徑優先隊列
        candidate_count = 0
        for i in range(len(switch_path_1) - 1):
            # ← 建立臨時圖：刪除前 i 段的邊 + 已找到路中此前綴點之後的邊
            temp_adjacency = copy.deepcopy(adjacency)
            temp_link_energy = copy.deepcopy(original_link_energy)
            temp_switch_energy = copy.deepcopy(original_switch_energy)
            
            print(f"        [i={i}] 禁用前綴段數")
            # 刪除路徑的前 i 段邊
            for j in range(i):
                u, v = switch_path_1[j], switch_path_1[j + 1]
                print(f"          刪除邊: ({u}, {v})")
                if u in temp_adjacency and v in temp_adjacency[u]:
                    del temp_adjacency[u][v]
                if v in temp_adjacency and u in temp_adjacency[v]:
                    del temp_adjacency[v][u]
            
            # 額外：禁用所有已找到路中，從此 spur_src 的下一條邊
            spur_src = switch_path_1[i]
            for path_in_A in A:
                path_nodes = path_in_A[0]  # switch_path
                if path_nodes[:i+1] == switch_path_1[:i+1]: # ← 前綴比對
                    idx = i # 位置就是 i，不需要再搜尋
                    # 只禁用 (spur_src → next_node) 這一條邊
                    if idx < len(path_nodes) - 1:
                        next_node = path_nodes[idx + 1]
                        if spur_src in temp_adjacency and next_node in temp_adjacency[spur_src]:
                            print(f"          禁用已找路邊: ({spur_src}, {next_node})")
                            del temp_adjacency[spur_src][next_node]
                        if next_node in temp_adjacency and spur_src in temp_adjacency[next_node]:
                            del temp_adjacency[next_node][spur_src]

            # 移除前綴節點（除 spur_src），防止 spur path 繞回前綴產生 loop
            root_nodes = set(switch_path_1[:i])
            temp_switches = [s for s in myswitches if s not in root_nodes]

            # ← 從前綴終點到目標計算 spur path
            spur_first_port = 0
            print(f"          計算 spur: {spur_src} → {dst_dpid}")

            result = self.get_min_delay_path(
                spur_src, dst_dpid, spur_first_port, final_port,
                temp_switches, temp_adjacency, temp_link_energy, link_bw,
                link_used_bw, temp_switch_energy,
                required_bw=required_bw
            )
            
            if result is None:
                print(f"          spur 返回 None")
                continue
            
            spur_path_list, spur_switch_path = result
            print(f"          spur_path: {spur_switch_path}")
            
            # ← 拼接：前綴 + spur path
            prefix = switch_path_1[0:i+1]
            suffix = spur_switch_path[1:]
            new_switch_path = prefix + suffix
            new_path_list = path_list_1[0:i+1] + spur_path_list[1:]
            print(f"          拼接: [{prefix}] + [{suffix}] = {new_switch_path}")
            
            # ← 去重檢查
            new_tuple = tuple(new_switch_path)
            if new_tuple in found_paths:
                print(f"          ✗ 已存在於 found_paths，舍棄")
                continue
            
            # ← 計算成本並加入 B
            new_cost = self._calculate_path_cost(new_switch_path, original_link_energy, original_switch_energy)
            heapq.heappush(B, (new_cost, new_switch_path, new_path_list))
            found_paths.add(new_tuple)
            candidate_count += 1
            print(f"          ✓ 加入 B，成本={new_cost}")
        
        print(f"      [YING's] 第1輪生成，B 隊列大小={len(B)}, 總候選數={candidate_count}")
        
        # ========== 流程控制迴圈：第 2~k 條路徑 ==========
        for k_idx in range(1, k):
            if not B:
                # B 為空表示無法再找到新路徑
                break
            
            # ← 從 B 彈出成本最低的候選作為第 k 條路徑
            _, candidate_switch_path, candidate_path_list = heapq.heappop(B)
            A.append((candidate_switch_path, candidate_path_list))
            
            print(f"        [YING's] 路徑 {k_idx+1}: {candidate_switch_path}, 成本={self._calculate_path_cost(candidate_switch_path, original_link_energy, original_switch_energy)}")
            
            # ========== 對此路徑進行一輪：生成新候選 ==========
            # 對前一條路徑的每個前綴位置進行嘗試
            for i in range(len(candidate_switch_path) - 1):
                # ========== 前綴約束迭代 ==========
                # 對於路徑的每個前綴位置 i (0, 1, 2, ..., len-2)，嘗試從位置 i 插入不同的後繼
                # 目的：生成長度不同、前綴相同但後續不同的新路徑候選
                
                # ========== 第1步：建立臨時圖副本 ==========
                temp_adjacency = copy.deepcopy(adjacency)
                temp_link_energy = copy.deepcopy(original_link_energy)
                temp_switch_energy = copy.deepcopy(original_switch_energy)
                # 深拷貝原始網路圖和成本資訊（link_energy、switch_energy）
                # 原因：接下來會刪除邊和修改成本，必須在副本上操作以避免污染原始圖
                
                # ========== 第2步：禁用前 i 段邊（前綴約束）==========
                # Yen's 演算法的核心機制之一：強制 spur path 必須從位置 i 開始分岔
                for j in range(i):
                    u, v = candidate_switch_path[j], candidate_switch_path[j + 1]
                    # 獲取路徑中第 j 到第 j+1 段的邊
                    
                    if u in temp_adjacency and v in temp_adjacency[u]:
                        del temp_adjacency[u][v]
                    # 刪除正向邊 (u → v)，防止 spur path 沿著原路徑的前 i 段走
                    
                    if v in temp_adjacency and u in temp_adjacency[v]:
                        del temp_adjacency[v][u]
                    # 刪除反向邊（假設圖是無向的），同時禁用反向通行
                
                # ========== 第3步：計算 spur 起點 ==========
                spur_src = candidate_switch_path[i]
                # spur_src 是前綴的終點：路徑上第 i 個位置的交換機
                # 新的 spur path 將從這裡開始計算，必須不同於已有路徑的後續
                
                # ========== 第4步：禁用已找路徑的後繼邊（關鍵：防止重複）==========
                # Yen's 演算法的核心機制之二：比較 A 集合（已找到的路徑）
                # 對每一條已找到的路徑，檢查是否有相同的前綴
                for path_in_A in A:
                    path_nodes = path_in_A[0]  # 提取路徑的 switch 節點列表
                    
                    # =========== 前綴比對：防止生成相同的路徑 ===========
                    if path_nodes[:i+1] == candidate_switch_path[:i+1]:
                        # 檢查：已找路徑的前 i+1 個節點 == 候選路徑的前 i+1 個節點？
                        # 如果相同，表示兩條路徑有相同的前綴
                        # 若不禁用後繼邊，新生成的 spur path 會與已找路徑重複
                        # 因此必須禁用已找路徑的下一條邊，強制 spur path 選擇不同的後繼
                        
                        idx = i  # 前綴終點的索引（已知是 i，無需搜尋）
                        
                        # =========== 禁用已找路徑的下一條邊 ===========
                        if idx < len(path_nodes) - 1:
                            # 檢查：已找路徑是否還有後續節點（不是路徑終點）
                            
                            next_node = path_nodes[idx + 1]
                            # 獲取已找路徑在 spur_src 之後的下一個節點
                            
                            if spur_src in temp_adjacency and next_node in temp_adjacency[spur_src]:
                                del temp_adjacency[spur_src][next_node]
                            # 刪除邊 (spur_src → next_node)
                            # 效果：迫使 Dijkstra 不能沿著已找路徑的方式繼續，必須選擇替代路由
                            
                            if next_node in temp_adjacency and spur_src in temp_adjacency[next_node]:
                                del temp_adjacency[next_node][spur_src]
                            # 刪除反向邊（無向圖），確保 Dijkstra 無法雙向使用此邊
                
                # 移除前綴節點（除 spur_src），防止 spur path 繞回前綴產生 loop
                root_nodes = set(candidate_switch_path[:i])
                temp_switches = [s for s in myswitches if s not in root_nodes]

                # ← 從前綴終點到目標計算 spur path
                # 重要：不要綁定 spur_src 的入埠，允許它通過任何入埠到達
                spur_first_port = 0

                result = self.get_min_delay_path(
                    spur_src, dst_dpid, spur_first_port, final_port,
                    temp_switches, temp_adjacency, temp_link_energy, link_bw,
                    link_used_bw, temp_switch_energy,
                    required_bw=required_bw
                )
                
                if result is None:
                    continue
                
                spur_path_list, spur_switch_path = result
                
                # ← 拼接：前綴 + spur path
                new_switch_path = candidate_switch_path[0:i+1] + spur_switch_path[1:]
                new_path_list = candidate_path_list[0:i+1] + spur_path_list[1:]
                
                # ← 去重檢查
                new_tuple = tuple(new_switch_path)
                if new_tuple in found_paths:
                    continue
                
                # ← 計算成本並加入 B
                new_cost = self._calculate_path_cost(new_switch_path, original_link_energy, original_switch_energy)
                heapq.heappush(B, (new_cost, new_switch_path, new_path_list))
                found_paths.add(new_tuple)
                candidate_count += 1
                print(f"        [YING's]   i={i}: 生成候選 {new_switch_path}, 成本={new_cost}")
        
        # ========== 返回結果 ==========
        return [(path_list, switch_path) for switch_path, path_list in A]


    def compute_all_k_shortest_paths_once(
        self, k, output_filepath='data/k_short.txt', host_range=(46, 72)):
        myswitches = copy.deepcopy(self.app.myswitches)
        adjacency = copy.deepcopy(self.app.adjacency)
        link_delay = copy.deepcopy(self.app.link_delay)
        link_energy = copy.deepcopy(self.app.link_energy)
        link_bw = copy.deepcopy(self.app.link_bw)
        link_used_bw = copy.deepcopy(self.app.link_used_bw)
        switch_energy = copy.deepcopy(self.app.switch_energy)
        """
        一次性計算所有 host pair 的 k-shortest paths 並保存結果
        
        只需呼叫一次，即從底層完整執行到檔案輸出
        
        Args:
            k: 每個 pair 的路徑數
            output_filepath: 輸出檔案
            myswitches, adjacency, link_delay, link_energy, 
            link_bw, link_used_bw, switch_energy : 拓撲參數
            host_range: (start, end) host 編號範圍，包含 end
        
        Returns:
            計算結果數（路徑總數）
        """
        import os
        
        # 建立反向對應
        #host_to_switch = {v: k for k, v in switch_to_host.items()}
        results = []
        
        all_macs = list(self.app.host_macs.keys())

        
        print(f"\n{'='*70}")
        print(f"*** [K-SHORTEST] 開始計算所有 host pair 的 {k} 條最短路徑")
        print(f"*** Host 範圍: {all_macs[0]}~{all_macs[-1]}, 共 {len(all_macs) * (len(all_macs) - 1)} 對")
        print(f"{'='*70}\n")
        
        pair_idx = 0
        for src_mac in all_macs:
            for dst_mac in all_macs:
                if src_mac == dst_mac:
                    continue
                
                pair_idx += 1
                
                # 檢查 host 配置
                '''
                if src_host not in host_to_switch or dst_host not in host_to_switch:
                    print(f"[{pair_idx:4d}/{total_pairs}] h{src_host}→h{dst_host}: 主機未配置 ✗")
                    continue
                '''

                
                try:
                    # 為每個 pair 建立 link_energy 和 switch_energy 的乾淨副本
                    # 防止 get_min_delay_path 的修改污染全局變數
                    clean_link_energy = copy.deepcopy(link_energy)
                    clean_switch_energy = copy.deepcopy(switch_energy)
                    
                    # 呼叫 Yen's 演算法（內部自動深拷貝以避免修改全域變數）
                    paths = self.yens_k_shortest_paths(
                        k=k, src=src_mac, dst=dst_mac,required_bw=0)
                    
                    print(f" 找到 {len(paths):2d} 條 ✓")
                    
                    # 儲存結果
                    for path_idx, (path_list, switch_path) in enumerate(paths):
                        cost = self._calculate_path_cost(
                            switch_path, link_energy, switch_energy
                        )
                        results.append({
                            'src_host': src_mac,
                            'dst_host': dst_mac,
                            'path_index': path_idx,
                            'switch_path': switch_path,
                            'path_list': path_list,
                            'cost': cost
                        })
                
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f" ERROR: {e}")
        
        # 寫入檔案
        self._write_k_shortest_results(results, output_filepath)
        
        print(f"\n{'='*70}")
        print(f"*** [K-SHORTEST] 完成！計算結果 {len(results)} 條路徑")
        print(f"*** 儲存至: {output_filepath}")
        print(f"{'='*70}\n")
        
        return len(results)


    def _write_k_shortest_results(self, results, filepath):
        """將 k-shortest paths 結果寫入文本檔案"""
        dirpath = os.path.dirname(filepath)
        if dirpath and not os.path.exists(dirpath):
            os.makedirs(dirpath)
        
        with open(filepath, 'w') as f:
            f.write("# K-Shortest Paths Results\n")
            f.write("# Format: src_host dst_host path_index cost switch_path port_details\n")
            f.write("# " + "="*66 + "\n\n")
            
            current_pair = None
            for result in results:
                src, dst = result['src_host'], result['dst_host']
                idx, cost = result['path_index'], result['cost']
                switch_path = result['switch_path']
                path_list = result['path_list']
                
                if current_pair != (src, dst):
                    if current_pair is not None:
                        f.write("\n")
                    f.write(f"# h{src} -> h{dst}\n")
                    current_pair = (src, dst)
                
                switch_str = ",".join(str(s) for s in switch_path)
                port_details = ";".join(f"{s}:{p_in}→{p_out}"
                                    for s, p_in, p_out in path_list)
                
                f.write(f"{src:>20} {dst:>20} {idx} {cost:6.0f}  [{switch_str}]  "
)

    def get_min_delay_path(self, src, dst, first_port, final_port,
                        switches, adjacency, link_energy, link_bw, 
                        link_used_bw, switch_energy, 
                        required_bw=0):
        


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
