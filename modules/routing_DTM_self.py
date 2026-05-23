# -*- coding: utf-8 -*-

import re
import random
from .routing_base import RoutingBase

ENABLE_NEW_ALGO = True  # True：兩階段選路（2020過濾 → 權重圖選最佳）


class Routing_DTM_Self(RoutingBase):

    def __init__(self, app):
        self.app = app
        self.link_status = app.link_status
        self.k_short_paths = {}    # {(host_a, host_b): [[dpid, ...], ...]}
        self.k_short_dist  = {}    # {(host_a, host_b): {hop: [sw, ...]}}
        self.switch_weight_map = {}  # {dpid: int}，從 topo 延遲初始化
        self.待檢查路徑 = set()      # {(host_a, host_b)}，防止同一 flow 重複進入 cascade
        self._cascade_depth = 0      # debug：cascade 巢狀深度計數器
        self.非最短hop清單 = {}      # {(host_a, host_b): (best_hop, best_path)}，Phase1選出非全局最短hop的flow
        self.ns_weight_map = {}      # {dpid: int}，非最短hop flow 以其最低hop群計算的第二層權重圖
        self.base_weight_map = {}    # {dpid: int}，拓撲天生偏好，啟動時從 k_short_dist 計算，靜態不變
        self.load_k_short_paths('data/k_short.txt')
        self.load_k_short_dist('data/k_short_dist.txt')
        self._build_base_weight_map()

    # =========================================================
    # switch_weight_map 延遲初始化
    # =========================================================

    def _ensure_weight_map(self):
        for dpid in self.app.myswitches:
            if dpid not in self.switch_weight_map:
                self.switch_weight_map[dpid] = 0

    def _build_base_weight_map(self, filepath='data/base_weight_map.txt'):
        """載入或計算拓撲天生偏好的基底權重圖。
        有快取檔案直接讀；沒有則從 k_short_dist 計算後存檔，下次直接使用。
        """
        try:
            self.base_weight_map = {}
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    dpid, weight = line.split()
                    self.base_weight_map[int(dpid)] = int(weight)
            print(f"[DTM-Self] base_weight_map 載入完成，共 {len(self.base_weight_map)} 個 switch")
        except FileNotFoundError:
            self.base_weight_map = {}
            for (host_a, host_b), hop_groups in self.k_short_dist.items():
                if not hop_groups:
                    continue
                global_min_hop = min(hop_groups.keys())
                for sw in hop_groups.get(global_min_hop, []):
                    self.base_weight_map[sw] = self.base_weight_map.get(sw, 0) + 1
            with open(filepath, 'w') as f:
                f.write('# dpid weight\n')
                for dpid, weight in sorted(self.base_weight_map.items()):
                    f.write(f"{dpid} {weight}\n")
            print(f"[DTM-Self] base_weight_map 計算並儲存至 {filepath}，共 {len(self.base_weight_map)} 個 switch")

    def _ns_increment(self, host_a, host_b):
        """flow 進入非最短hop清單時，對其 global_min_hop switch 群做 +1"""
        dist = self.k_short_dist.get((host_a, host_b), {})
        if not dist:
            return
        global_min_hop = min(dist.keys())
        for sw in dist.get(global_min_hop, []):
            self.ns_weight_map[sw] = self.ns_weight_map.get(sw, 0) + 1

    def _ns_decrement(self, host_a, host_b):
        """flow 離開非最短hop清單時，對其 global_min_hop switch 群做 -1"""
        dist = self.k_short_dist.get((host_a, host_b), {})
        if not dist:
            return
        global_min_hop = min(dist.keys())
        for sw in dist.get(global_min_hop, []):
            self.ns_weight_map[sw] = max(0, self.ns_weight_map.get(sw, 0) - 1)

    def _build_active_switches(self, exclude_pair=None):
        """從 active_flows 建立目前使用中的 switch 集合。
        exclude_pair: reroute 時傳入 (host_a, host_b)，排除自身舊路徑。
        非最短hop清單 中的 flow 一律排除（隔離設計）。
        """
        active_switches = set()
        for fa, fb, path in self.app.get_active_flows():
            if exclude_pair and (fa, fb) == exclude_pair:
                continue
            if (fa, fb) in self.非最短hop清單:
                continue
            for sw in path:
                active_switches.add(sw)
        return active_switches

    def _decrement_weight(self, host_a, host_b, path):
        hop = len(path)
        dist_entry = self.k_short_dist.get((host_a, host_b), {})
        sw_set = dist_entry.get(hop, path)
        for sw in sw_set:
            self.switch_weight_map[sw] = max(0, self.switch_weight_map.get(sw, 0) - 1)

    def _increment_weight(self, host_a, host_b, path):
        hop = len(path)
        dist_entry = self.k_short_dist.get((host_a, host_b), {})
        sw_set = dist_entry.get(hop, path)
        for sw in sw_set:
            self.switch_weight_map[sw] = self.switch_weight_map.get(sw, 0) + 1

    # =========================================================
    # 核心選路
    # =========================================================

    def select_path(self, host_a, host_b, remove_path=None):
        if ENABLE_NEW_ALGO:
            return self._compute_path(host_a, host_b, remove_path)

        self._ensure_weight_map()
        all_link_status = self.link_status.get_all_link_status()

        if (host_a, host_b) not in self.k_short_paths:
            print(f"[DTM-Self] 沒有 k-short 路徑: {host_a} -> {host_b}")
            return None
        if (host_a, host_b) not in self.k_short_dist:
            print(f"[DTM-Self] 沒有 dist 資料: {host_a} -> {host_b}")
            return None

        paths = self.k_short_paths[(host_a, host_b)]
        if remove_path:
            paths = [p for p in paths if p != remove_path]

        dist = self.k_short_dist[(host_a, host_b)]

        for hop in sorted(dist.keys()):
            switch_set = dist[hop]

            # Step 0：暫時將此 hop 群的所有 switch 權重 +1
            for sw in switch_set:
                self.switch_weight_map[sw] = self.switch_weight_map.get(sw, 0) + 1

            # Step 2：對此 hop 群的路徑評分，排除含 OVERLOAD 的路徑
            usable = []
            for path in paths:
                if len(path) != hop:
                    continue
                has_overload = False
                for i in range(len(path) - 1):
                    link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                    if all_link_status.get(link, {}).get('status') == 'OVERLOAD':
                        has_overload = True
                        break
                if has_overload:
                    continue
                weight = sum(self.switch_weight_map.get(sw, 0) for sw in path)
                usable.append((weight, path))

            if usable:
                # Step 3：選權重最高的路徑，+1 確認保留，觸發 cascade
                usable.sort(key=lambda x: -x[0])
                best_weight = usable[0][0]
                candidates = [p for w, p in usable if w == best_weight]
                selected = random.choice(candidates)
                self._cascade(host_a, host_b, selected)
                return selected

            # Step 2-1：無可用路徑，扣回暫時 +1，試下一個 hop
            for sw in switch_set:
                self.switch_weight_map[sw] -= 1

        return None

    def _compute_path(self, host_a, host_b, remove_path=None, prefer_current=None):
        """兩階段選路：
        Phase 1（2020）：以最少 SN link 數、最短 hop 數排序，取最優候選集
        Phase 2（新算法）：對候選集套用 switch_weight_map 評分，選最高者
        """
        self._ensure_weight_map()
        all_link_status = self.link_status.get_all_link_status()

        if (host_a, host_b) not in self.k_short_paths:
            print(f"[DTM-Self] 沒有 k-short 路徑: {host_a} -> {host_b}")
            return None
        if (host_a, host_b) not in self.k_short_dist:
            print(f"[DTM-Self] 沒有 dist 資料: {host_a} -> {host_b}")
            return None

        paths = self.k_short_paths[(host_a, host_b)]
        if remove_path:
            paths = [p for p in paths if p != remove_path]

        dist = self.k_short_dist[(host_a, host_b)]

        active_switches = self._build_active_switches(exclude_pair=(host_a, host_b))

        # Phase 1：計算每條路徑的 inactive switch 數與 switch 數，排除 OVERLOAD
        # hop 以 len(path)（switch 數）計，與 k_short_dist 的 key 單位一致
        valid_paths = []
        for path in paths:
            has_overload = False
            for i in range(len(path) - 1):
                link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                status = all_link_status.get(link, {}).get('status', 'NORMAL')
                if status == 'OVERLOAD':
                    has_overload = True
                    break
            if not has_overload:
                inactive_counter = sum(1 for sw in path if sw not in active_switches)
                valid_paths.append((inactive_counter, len(path), path))

        # 第二輪：第一輪無結果時，把含 OVERLOAD 的路徑也納入
        if not valid_paths:
            for path in paths:
                inactive_counter = sum(1 for sw in path if sw not in active_switches)
                valid_paths.append((inactive_counter, len(path), path))

        if not valid_paths:
            return None

        # Step 1：留下 inactive 最少的路徑
        best_inactive = min(v[0] for v in valid_paths)
        step1 = [(hop, path) for inactive, hop, path in valid_paths
                 if inactive == best_inactive]

        # Step 2：留下 hop 最少的路徑
        best_hop = min(hop for hop, path in step1)
        candidates = [path for hop, path in step1 if hop == best_hop]

        global_min_hop = min(dist.keys())

        if best_hop > global_min_hop:
            # 非最短 hop：不 +1，不觸發 cascade
            scored = sorted(
                ((sum(self.switch_weight_map.get(sw, 0) for sw in p), p) for p in candidates),
                key=lambda x: -x[0]
            )
            best_weight = scored[0][0]
            tied = [p for w, p in scored if w == best_weight]

            if prefer_current and prefer_current in tied:
                return None  # 現有路徑仍是最佳群，不換

            selected = random.choice(tied)
            self.非最短hop清單[(host_a, host_b)] = (best_hop, selected)
            self._ns_increment(host_a, host_b)
            print(f"[NonShortest] 新增: {host_a} -> {host_b}, hop={best_hop}, 路徑: {selected}")
            return selected

        # Phase 2：最短 hop，+1，觸發 cascade
        switch_set = dist.get(len(candidates[0]), candidates[0])
        for sw in switch_set:
            self.switch_weight_map[sw] = self.switch_weight_map.get(sw, 0) + 1

        scored = sorted(
            ((sum(self.switch_weight_map.get(sw, 0) for sw in p), p) for p in candidates),
            key=lambda x: -x[0]
        )
        best_weight = scored[0][0]
        tied = [p for w, p in scored if w == best_weight]

        if prefer_current and prefer_current in tied:
            # 退回 +1，現有路徑仍是最佳群，不換
            for sw in switch_set:
                self.switch_weight_map[sw] -= 1
            return None

        selected = random.choice(tied)
        self._cascade(host_a, host_b, selected)
        return selected

    def admit_flow(self, host_a, host_b):
        self.待檢查路徑.clear()  # 每次新流量開始一輪新的 cascade session
        path = self.select_path(host_a, host_b)
        if path:
            print(f"[FLOW_NEW] {host_a} -> {host_b}, path={path}")
            self.app.add_active_flow(host_a, host_b, path)
            print(f"[WeightMap] {dict(self.switch_weight_map)}")
            return path
        return None

    # =========================================================
    # Cascade 重路由
    # =========================================================

    def on_flow_removed(self, host_a, host_b, removed_path):
        """timeout 觸發的 flow 移除，以移除路徑的 hop 群做 cascade 檢查"""
        if (host_a, host_b) in self.非最短hop清單:
            self._ns_decrement(host_a, host_b)
            del self.非最短hop清單[(host_a, host_b)]
        else:
            self._decrement_weight(host_a, host_b, removed_path)
            print(f"[WeightMap] {dict(self.switch_weight_map)}")
        self.待檢查路徑.clear()
        self._cascade(host_a, host_b, removed_path)

    def _debug_draw_cascade(self, host_a, host_b, selected_path):
        """cascade 深度超過 50 時，畫出當前 active flow 狀態並存檔"""
        try:
            import matplotlib.pyplot as plt
            N = 5
            fig, ax = plt.subplots(figsize=(8, 8))
            ax.set_facecolor('#f8f8f8')
            ax.set_xlim(-0.7, N - 0.3)
            ax.set_ylim(-0.7, N - 0.3)
            ax.set_aspect('equal')
            ax.axis('off')

            # 畫邊
            for sw in range(1, N * N + 1):
                r, c = (sw - 1) // N, (sw - 1) % N
                x, y = c, N - 1 - r
                if c < N - 1:
                    ax.plot([x, x + 1], [y, y], color='#cccccc', lw=0.8)
                if r < N - 1:
                    ax.plot([x, x], [y, y - 1], color='#cccccc', lw=0.8)

            # 畫 active flows
            colors = plt.cm.tab10.colors
            active = list(self.app.get_active_flows())
            for i, (fa, fb, path) in enumerate(active):
                color = colors[i % len(colors)]
                is_ns = (fa, fb) in self.非最短hop清單
                for j in range(len(path) - 1):
                    u, v = path[j], path[j + 1]
                    x0, y0 = (u-1) % N, N - 1 - (u-1) // N
                    x1, y1 = (v-1) % N, N - 1 - (v-1) // N
                    ax.plot([x0, x1], [y0, y1], color=color,
                            lw=2.5, ls='--' if is_ns else '-', alpha=0.8)

            # 畫 switch 節點
            for sw in range(1, N * N + 1):
                x, y = (sw-1) % N, N - 1 - (sw-1) // N
                w = self.switch_weight_map.get(sw, 0)
                ax.plot(x, y, 'o', color='#ffffcc', markersize=22,
                        markeredgecolor='#333333', lw=0.8)
                ax.text(x, y + 0.08, str(sw), ha='center', va='center',
                        fontsize=7.5, fontweight='bold')
                if w > 0:
                    ax.text(x, y - 0.22, f'w={w}', ha='center', va='top',
                            fontsize=6, color='#555555')

            tag = host_a.split(':')[-1] + '_' + host_b.split(':')[-1]
            ax.set_title(
                f'[DEBUG] cascade depth > 50\n'
                f'{host_a} → {host_b}  path={selected_path}\n'
                f'active flows={len(active)}  depth={self._cascade_depth}',
                fontsize=8)
            fname = f'debug_cascade_{tag}.png'
            plt.tight_layout()
            plt.savefig(fname, dpi=120)
            plt.close()
            print(f"[DEBUG] cascade depth={self._cascade_depth} > 50，圖已儲存: {fname}")
        except Exception as e:
            print(f"[DEBUG] 畫圖失敗: {e}")

    def _cascade(self, host_a, host_b, selected_path):
        """依 selected_path 的 hop 數，查 dist 取得同 hop 群的所有 switch，找出經過的 flow 嘗試重算"""
        self._cascade_depth += 1
        if self._cascade_depth > 50:
            self._debug_draw_cascade(host_a, host_b, selected_path)
            self._cascade_depth -= 1
            return
        hop = len(selected_path)
        dist_entry = self.k_short_dist.get((host_a, host_b), {})
        path_switches = set(dist_entry.get(hop, selected_path))

        # 收集需要重算的 flow
        # NS flow 無論路徑有無交集都重算（weight map 變動可能影響它們的選路）
        # 一般 flow 只收集路徑有交集的
        flows_to_check = []  # [(fa, fb, current_path, is_ns)]
        for fa, fb, path in self.app.get_active_flows():
            if (fa, fb) in self.待檢查路徑:
                continue
            if (fa, fb) in self.非最短hop清單:
                _, ns_path = self.非最短hop清單[(fa, fb)]
                flows_to_check.append((fa, fb, ns_path, True))
            elif any(sw in path_switches for sw in path):
                flows_to_check.append((fa, fb, path, False))

        for fa, fb, _, _ in flows_to_check:
            self.待檢查路徑.add((fa, fb))

        for fa, fb, current_path, is_ns in flows_to_check:
            # 1. 扒乾淨自己的權重貢獻（NS flow 先印移除，順序必須在 新增 之前）
            if is_ns:
                self._ns_decrement(fa, fb)
                del self.非最短hop清單[(fa, fb)]
                print(f"[NonShortest] 移除: {fa} -> {fb}")
            else:
                self._decrement_weight(fa, fb, current_path)

            # 2. 當作新流量重算（prefer_current：若仍在最佳群就不換）
            new_path = self._compute_path(fa, fb, prefer_current=current_path)

            # 3. None → 現有路徑仍是最佳，還原
            if new_path is None:
                if is_ns:
                    self._ns_increment(fa, fb)
                    self.非最短hop清單[(fa, fb)] = (len(current_path), current_path)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, "
                          f"hop={len(current_path)}, 路徑: {current_path}")
                else:
                    self._increment_weight(fa, fb, current_path)
                continue

            # 4. 換路
            old_pwp = self.app.build_path_with_ports(current_path, fa, fb)
            new_pwp = self.app.build_path_with_ports(new_path, fa, fb)
            if old_pwp is None or new_pwp is None:
                if is_ns:
                    self._ns_increment(fa, fb)
                    self.非最短hop清單[(fa, fb)] = (len(current_path), current_path)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, "
                          f"hop={len(current_path)}, 路徑: {current_path}")
                else:
                    self._increment_weight(fa, fb, current_path)
                continue

            self.app.remove_flows_for_path(old_pwp, fa, fb)
            self.app.install_flows_for_path(new_pwp, fa, fb, priority=2, idle_timeout=5)
            self.app.remove_active_flow(fa, fb)

            is_now_ns = (fa, fb) in self.非最短hop清單
            print(f"[WeightMap] {dict(self.switch_weight_map)}")
            if is_now_ns:
                print(f"[FLOW_CASCADE_NS] {fa} -> {fb}, path={new_path}")
            else:
                print(f"[FLOW_CASCADE] {fa} -> {fb}, path={new_path}")

            self.app.add_active_flow(fa, fb, new_path, is_reroute=True)
            print(f"[WeightMap] {dict(self.switch_weight_map)}")

        self._cascade_depth -= 1

    # =========================================================
    # 載入 k_short.txt
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
                        host_a   = parts[i]
                        host_b   = parts[i + 1]
                        path_str = parts[i + 4].strip('[]')
                        switch_path = [int(x) for x in path_str.split(',')]
                        key = (host_a, host_b)
                        if key not in self.k_short_paths:
                            self.k_short_paths[key] = []
                        self.k_short_paths[key].append(switch_path)
                        i += 5
            print(f"[DTM-Self] 載入 {len(self.k_short_paths)} 個 host pair 的 k-short 路徑")
        except FileNotFoundError:
            print(f"[DTM-Self] 找不到 {filepath}")
        except Exception as e:
            print(f"[DTM-Self] 解析 k_short.txt 時出錯: {e}")

    # =========================================================
    # 載入 k_short_dist.txt
    # =========================================================

    def load_k_short_dist(self, filepath='data/k_short_dist.txt'):
        pattern = re.compile(r'(\d+)\[([^\]]+)\]')
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split(None, 2)
                    if len(parts) < 3:
                        continue
                    host_a, host_b = parts[0], parts[1]
                    hop_groups = {}
                    for match in pattern.finditer(parts[2]):
                        hop      = int(match.group(1))
                        switches = [int(s) for s in match.group(2).split(',')]
                        hop_groups[hop] = switches
                    self.k_short_dist[(host_a, host_b)] = hop_groups
            print(f"[DTM-Self] 載入 {len(self.k_short_dist)} 個 host pair 的 dist 資料")
        except FileNotFoundError:
            print(f"[DTM-Self] 找不到 {filepath}")
        except Exception as e:
            print(f"[DTM-Self] 解析 k_short_dist.txt 時出錯: {e}")
