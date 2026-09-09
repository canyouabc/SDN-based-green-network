# -*- coding: utf-8 -*-

import re
import random
import logging
import os
import time
from .routing_base import RoutingBase

NS_ACTIVE_SW_THRESHOLD = 0   # Phase 1 active_sw 切換門檻：NS flow 數 < 此值用 all_sw，否則用 shortest_sw

ENABLE_NEW_ALGO = True       # True：兩階段選路（2020過濾 → 權重圖選最佳）
ENABLE_LAYER2 = False        # True：Layer 2（ns_weight_map）作為 tiebreaker；False：跳過
ENABLE_LAYER3 = False        # True：Layer 3（base_weight_map）作為最終 tiebreaker；False：Layer 2 後直接 random
ENABLE_SNAPSHOT = False      # True：輸出 [SNAPSHOT] 供動畫使用；False：完全關閉（效能優先）
SNAPSHOT_PER_REROUTE = False # True：每個換路 flow 都照快照（動畫逐步模式）；False：cascade 結束後照一次（需 ENABLE_SNAPSHOT=True）
CD_DEBUG = False             # True：輸出 cascade debug log 至 log/cascade_debug.log

# ── [CD] debug log：只寫檔案，不輸出到 terminal ──────────────────
if CD_DEBUG:
    os.makedirs("log", exist_ok=True)
    _cd_logger = logging.getLogger("cascade_debug")
    _cd_logger.setLevel(logging.DEBUG)
    _cd_logger.propagate = False
    if not _cd_logger.handlers:
        _cd_fh = logging.FileHandler("log/cascade_debug.log", mode="w")
        _cd_fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                              datefmt="%H:%M:%S"))
        _cd_logger.addHandler(_cd_fh)

def _cd_log(msg):
    if CD_DEBUG:
        _cd_logger.debug(msg)
# ─────────────────────────────────────────────────────────────────


class Routing_DTM_Self(RoutingBase):

    def __init__(self, app):
        self.app = app
        self.link_status = app.link_status
        self.k_short_paths = {}         # {(host_a, host_b): [[dpid, ...], ...]}
        self.k_short_paths_by_hop = {}  # {(host_a, host_b): {hop: [paths...]}}，load 後預建
        self.k_short_hop_keys = {}      # {(host_a, host_b): [sorted hop values]}
        self.k_short_dist  = {}    # {(host_a, host_b): {hop: [sw, ...]}}
        self._global_min_hop = {}  # {(host_a, host_b): int}，load_k_short_dist 後預算，O(1) 查詢
        self._ns_sw_list = {}      # {(host_a, host_b): [sw, ...]}，global_min_hop 群的 switch 清單，靜態
        self.core_weight_map = {}    # {dpid: int} Layer 1 核心層：最短 hop flow 貢獻
        self._wmap_ready = False     # _ensure_weight_map 是否已完成初始化
        self.sw_count = {}           # {dpid: int} 非NS active flow 使用的 switch 計數，隨 add/remove_active_flow 連動
        self.all_sw_count = {}       # {dpid: int} 所有 active flow（含 NS）使用的 switch 計數
        self._overload_links = frozenset()  # monitor 每秒更新一次的 OVERLOAD/DANGER link 集合
        self.待檢查路徑 = set()      # {(host_a, host_b)}，防止同一 flow 重複進入 cascade
        self._cascade_time_total = 0.0
        self._cascade_count = 0
        self.非最短hop清單 = {}      # {(host_a, host_b): (best_hop, best_path)}，Phase1選出非全局最短hop的flow
        self.ns_weight_map = {}      # {dpid: int} Layer 2 NS層：非最短 hop flow 貢獻
        self.base_weight_map = {}    # {dpid: int}，拓撲天生偏好，啟動時從 k_short_dist 計算，靜態不變
        self.weight_map = {}         # {dpid: int}，動態：當前 active flows 的最短路徑 switch 集合疊加
        self.load_k_short_paths(getattr(app, 'k_short_path', 'data/k_short.txt'))
        self.load_k_short_dist(getattr(app, 'k_short_dist_path', 'data/k_short_dist.txt'))
        self._build_base_weight_map(getattr(app, 'base_weight_map_path', 'data/base_weight_map.txt'))

    # =========================================================
    # core_weight_map 延遲初始化
    # =========================================================

    def refresh_link_cache(self):
        """monitor 每秒呼叫一次，更新 OVERLOAD/DANGER link 快取。"""
        all_status = self.link_status.get_all_link_status()
        self._overload_links = frozenset(
            link for link, info in all_status.items()
            if info.get('status') in ('OVERLOAD', 'DANGER')
        )

    def _ensure_weight_map(self):
        if self._wmap_ready:
            return
        for dpid in self.app.myswitches:
            if dpid not in self.core_weight_map:
                self.core_weight_map[dpid] = 0
        self._wmap_ready = True

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

    def _build_weight_map(self):
        """根據當前 active flows 的最短路徑 switch 集合，計算動態權重圖。"""
        wmap = {}
        for fa, fb, _ in self.app.get_active_flows():
            hop_groups = self.k_short_dist.get((fa, fb), {})
            if not hop_groups:
                continue
            min_hop = min(hop_groups.keys())
            for sw in hop_groups[min_hop]:
                wmap[sw] = wmap.get(sw, 0) + 1
        self.weight_map = wmap

    def _ns_increment(self, host_a, host_b):
        """flow 進入非最短hop清單時，對其 global_min_hop switch 群做 +1"""
        for sw in self._ns_sw_list.get((host_a, host_b), []):
            self.ns_weight_map[sw] = self.ns_weight_map.get(sw, 0) + 1

    def _ns_decrement(self, host_a, host_b):
        """flow 離開非最短hop清單時，對其 global_min_hop switch 群做 -1"""
        for sw in self._ns_sw_list.get((host_a, host_b), []):
            self.ns_weight_map[sw] = max(0, self.ns_weight_map.get(sw, 0) - 1)

    def _is_ns_path(self, host_a, host_b, path):
        """直接比較 path 長度與 global_min_hop，判斷是否為非最短路徑"""
        global_min_hop = self._global_min_hop.get((host_a, host_b))
        return global_min_hop is not None and len(path) > global_min_hop

    def _decrement_weight(self, host_a, host_b, path):
        hop = len(path)
        dist_entry = self.k_short_dist.get((host_a, host_b), {})
        sw_set = dist_entry.get(hop, path)
        for sw in sw_set:
            self.core_weight_map[sw] = max(0, self.core_weight_map.get(sw, 0) - 1)

    def _log_snapshot(self):
        """目前完整狀態快照，供動畫直接讀取，不需自行推算。"""
        if not ENABLE_SNAPSHOT:
            return
        import json
        self._build_weight_map()
        active = [[a, b, p] for a, b, p in self.app.get_active_flows()]
        ns     = [[a, b, h] for (a, b), (h, _) in self.非最短hop清單.items()]
        wmap   = {str(k): v for k, v in self.weight_map.items()}
        print(f"[SNAPSHOT] {json.dumps({'active': active, 'ns': ns, 'wmap': wmap})}")

    def _increment_weight(self, host_a, host_b, path):
        hop = len(path)
        dist_entry = self.k_short_dist.get((host_a, host_b), {})
        sw_set = dist_entry.get(hop, path)
        for sw in sw_set:
            self.core_weight_map[sw] = self.core_weight_map.get(sw, 0) + 1

    # =========================================================
    # 核心選路
    # =========================================================

    def select_path(self, host_a, host_b, remove_path=None):
        self._ensure_weight_map()
        if ENABLE_NEW_ALGO:
            return self._compute_path(host_a, host_b, remove_path)

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
                self.core_weight_map[sw] = self.core_weight_map.get(sw, 0) + 1

            # Step 2：對此 hop 群的路徑評分，排除含 OVERLOAD/DANGER 的路徑
            usable = []
            for path in paths:
                if len(path) != hop:
                    continue
                has_overload = False
                for i in range(len(path) - 1):
                    link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                    if link in self._overload_links:
                        has_overload = True
                        break
                if has_overload:
                    continue
                weight = sum(self.core_weight_map.get(sw, 0) for sw in path)
                usable.append((weight, path))

            if usable:
                # Step 3：選權重最高的路徑，+1 確認保留，觸發 cascade
                usable.sort(key=lambda x: -x[0])
                best_weight = usable[0][0]
                candidates = [p for w, p in usable if w == best_weight]
                selected = random.choice(candidates)
                return selected

            # Step 2-1：無可用路徑，扣回暫時 +1，試下一個 hop
            for sw in switch_set:
                self.core_weight_map[sw] -= 1

        return None

    def _run_phase1(self, host_a, host_b, active_sw, remove_path):
        """以給定的 active_sw 執行一次 Phase 1 篩選。
        回傳 (candidates, best_hop, best_inactive)。
        - candidates: 路徑 list（均滿足 best_inactive 與 best_hop）
        - best_hop: candidates 的共同 hop 數
        - best_inactive: 路徑中不在 active_sw 的 switch 數（clean_zero 時為 0）
        若無任何可用路徑，回傳 (None, None, None)。
        """
        # 主路（clean_zero）：找最短 hop 群中 inactive=0 的路徑
        for hop in self.k_short_hop_keys[(host_a, host_b)]:
            clean_zero = []
            for path, links in self.k_short_paths_by_hop[(host_a, host_b)][hop]:
                if remove_path and path == remove_path:
                    continue
                if any(link in self._overload_links for link in links):
                    continue
                if all(sw in active_sw for sw in path):
                    clean_zero.append(path)
            if clean_zero:
                return clean_zero, hop, 0

        # Fallback：全量掃描，取 (inactive 最少, hop 最短) 的路徑集
        valid_paths = []
        fallback_paths = []
        for hop_key in self.k_short_hop_keys[(host_a, host_b)]:
            for path, links in self.k_short_paths_by_hop[(host_a, host_b)][hop_key]:
                if remove_path and path == remove_path:
                    continue
                has_overload = any(link in self._overload_links for link in links)
                inactive_counter = sum(1 for sw in path if sw not in active_sw)
                tup = (inactive_counter, len(path), path)
                if not has_overload:
                    valid_paths.append(tup)
                fallback_paths.append(tup)
        if not valid_paths:
            valid_paths = fallback_paths
        if not valid_paths:
            return None, None, None
        best_inactive = min(v[0] for v in valid_paths)
        best_hop = None
        candidates = []
        for inactive, hop, path in valid_paths:
            if inactive != best_inactive:
                continue
            if best_hop is None or hop < best_hop:
                best_hop = hop
                candidates = [path]
            elif hop == best_hop:
                candidates.append(path)
        return candidates, best_hop, best_inactive

    def _compute_path(self, host_a, host_b, remove_path=None, prefer_current=None,
                      exclude_path=None):
        """兩階段選路：
        Phase 1（2020）：以最少 SN link 數、最短 hop 數排序，取最優候選集
        Phase 2（新算法）：對候選集套用 core_weight_map 評分，選最高者
        """
        if (host_a, host_b) not in self.k_short_paths_by_hop:
            print(f"[DTM-Self] 沒有 k-short 路徑: {host_a} -> {host_b}")
            return None
        if (host_a, host_b) not in self.k_short_dist:
            print(f"[DTM-Self] 沒有 dist 資料: {host_a} -> {host_b}")
            return None

        # ── Layer 0：建立「已點亮 switch」集合 ───────────────────────────────
        # sw_count 只計入「最短 hop flow」使用的 switch（NS flow 不計）。
        # 因此 shortest_active_sw 的語意是：
        #   「目前至少被一條最短 hop flow 點亮、無需額外喚醒的 switch 集合」
        #
        # 注意：未來若建立涵蓋所有 flow（含 NS）的 active_switches，
        #   兩者會同時存在。Layer 0 目前使用 shortest_active_sw。
        #
        # exclude_path 用於 cascade 重算：將舊路徑的貢獻暫時扣除，
        # 避免自己的 sw_count 影響自己的重選結果。
        if exclude_path:
            excl = set(exclude_path)
            shortest_active_sw = {sw for sw, c in self.sw_count.items()
                                  if c - (1 if sw in excl else 0) > 0}
            active_sw = {sw for sw, c in self.all_sw_count.items()
                         if c - (1 if sw in excl else 0) > 0}
        else:
            shortest_active_sw = {sw for sw, c in self.sw_count.items() if c > 0}
            active_sw = {sw for sw, c in self.all_sw_count.items() if c > 0}
        # active_sw：所有 active flow（含 NS）點亮的 switch 集合，未來 Layer 0 可切換使用
        # ─────────────────────────────────────────────────────────────────────

        global_min_hop = self._global_min_hop[(host_a, host_b)]

        # ── Phase 1（Layer 0 應用）：以「是否需要喚醒新 switch」為第一優先 ──
        # NS flow 數量 < 3：使用 active_sw（全開 switch），讓選路空間更大
        # NS flow 數量 >= 3：使用 shortest_active_sw（最短 hop flow 點亮的 switch），收斂節能
        if len(self.非最短hop清單) < NS_ACTIVE_SW_THRESHOLD:
            phase1_sw = active_sw
        else:
            phase1_sw = shortest_active_sw
        candidates, best_hop, _ = self._run_phase1(
            host_a, host_b, phase1_sw, remove_path)

        if candidates is None:
            return None
        # ─────────────────────────────────────────────────────────────────────

        if best_hop > global_min_hop:
            # NS 分支：Layer 2 唯讀評分，選後才 +1 Layer 2（不動 Layer 1）
            _cd_log(f"[CD][compute] {host_a}->{host_b} | NS分支 | best_hop={best_hop} global_min={global_min_hop} | prefer_current={prefer_current}")

            if len(candidates) == 1:
                selected = candidates[0]
                if prefer_current and prefer_current == selected:
                    return None
                self.非最短hop清單[(host_a, host_b)] = (best_hop, selected)
                self._ns_increment(host_a, host_b)
                print(f"[NonShortest] 新增: {host_a} -> {host_b}, hop={best_hop}, 路徑: {selected}")
                return selected

            scores1 = [(sum(self.core_weight_map.get(sw, 0) for sw in p), p) for p in candidates]
            best_weight1 = max(s for s, _ in scores1)
            tied = [p for s, p in scores1 if s == best_weight1]

            if ENABLE_LAYER2 and len(tied) > 1:
                scores = [(sum(self.ns_weight_map.get(sw, 0) for sw in p), p) for p in tied]
                best_weight = max(s for s, _ in scores)
                tied = [p for s, p in scores if s == best_weight]

            if ENABLE_LAYER3 and len(tied) > 1:
                scores0 = [(sum(self.base_weight_map.get(sw, 0) for sw in p), p) for p in tied]
                best_weight0 = max(s for s, _ in scores0)
                tied = [p for s, p in scores0 if s == best_weight0]

            if prefer_current and prefer_current in tied:
                _cd_log(f"[CD][compute] {host_a}->{host_b} | prefer_current命中→return None（不換路）")
                return None

            selected = random.choice(tied)
            self.非最短hop清單[(host_a, host_b)] = (best_hop, selected)
            self._ns_increment(host_a, host_b)  # Layer 2 +1（選後才更新）
            print(f"[NonShortest] 新增: {host_a} -> {host_b}, hop={best_hop}, 路徑: {selected}")
            _cd_log(f"[CD][compute] {host_a}->{host_b} | NS寫入清單完成 | 清單={dict(self.非最短hop清單)}")
            return selected

        # Phase 2：最短 hop，Layer 1 唯讀評分，平手再用 Layer 2 tiebreaker，選後才 +1 Layer 1
        if len(candidates) == 1:
            selected = candidates[0]
            if prefer_current and prefer_current == selected:
                return None
            self._increment_weight(host_a, host_b, selected)
            return selected

        scores = [(sum(self.core_weight_map.get(sw, 0) for sw in p), p) for p in candidates]
        best_weight = max(s for s, _ in scores)
        tied = [p for s, p in scores if s == best_weight]

        if ENABLE_LAYER2 and len(tied) > 1:
            scores2 = [(sum(self.ns_weight_map.get(sw, 0) for sw in p), p) for p in tied]
            best_weight2 = max(s for s, _ in scores2)
            tied = [p for s, p in scores2 if s == best_weight2]

        if ENABLE_LAYER3 and len(tied) > 1:
            scores0 = [(sum(self.base_weight_map.get(sw, 0) for sw in p), p) for p in tied]
            best_weight0 = max(s for s, _ in scores0)
            tied = [p for s, p in scores0 if s == best_weight0]

        if prefer_current and prefer_current in tied:
            return None

        selected = random.choice(tied)
        self._increment_weight(host_a, host_b, selected)  # Layer 1 +1（選後才更新）
        return selected

    def admit_flow(self, host_a, host_b):
        self.待檢查路徑.clear()  # 每次新流量開始一輪新的 cascade session
        path = self.select_path(host_a, host_b)
        if path:
            print(f"[FLOW_NEW] {host_a} -> {host_b}, path={path}")
            self.app.add_active_flow(host_a, host_b, path)
            if (host_a, host_b) not in self.非最短hop清單:
                for sw in path:
                    self.sw_count[sw] = self.sw_count.get(sw, 0) + 1
            for sw in path:
                self.all_sw_count[sw] = self.all_sw_count.get(sw, 0) + 1
            self._build_weight_map()
            self._cascade(host_a, host_b, path)    # 觸發其他 flow 重算（_cascade 末尾已呼叫 _log_snapshot）
            return path
        return None

    # =========================================================
    # Cascade 重路由
    # =========================================================

    def on_flow_removed(self, host_a, host_b, removed_path):
        """timeout 觸發的 flow 移除，以移除路徑的 hop 群做 cascade 檢查"""
        if (host_a, host_b) in self.非最短hop清單:
            self._ns_decrement(host_a, host_b)             # Layer 2 -1
            self.非最短hop清單.pop((host_a, host_b), None)
        else:
            self._decrement_weight(host_a, host_b, removed_path)  # Layer 1 -1
            for sw in removed_path:
                self.sw_count[sw] = max(0, self.sw_count.get(sw, 0) - 1)
        for sw in removed_path:
            self.all_sw_count[sw] = max(0, self.all_sw_count.get(sw, 0) - 1)
        self._build_weight_map()
        self._log_snapshot()
        self.待檢查路徑.clear()
        self._cascade(host_a, host_b, removed_path)

    def _cascade(self, host_a, host_b, selected_path):
        """單道 pass：NS flow（最長路徑優先）→ 最短 hop flow，不遞歸。"""
        self._ensure_weight_map()
        _t0 = time.time()

        # 收集需要重算的 flow：NS 優先（最長路徑先）→ 最短 hop flow
        ns_flows = []
        shortest_flows = []
        for fa, fb, path in self.app.get_active_flows():
            if (fa, fb) in self.待檢查路徑:
                if CD_DEBUG: _cd_log(f"[CD][collect] {fa}->{fb} 跳過（已在待檢查路徑）")
                continue
            if (fa, fb) in self.非最短hop清單:
                _, ns_path = self.非最短hop清單[(fa, fb)]
                if CD_DEBUG: _cd_log(f"[CD][collect] {fa}->{fb} path={ns_path} is_ns=True 加入重算")
                ns_flows.append((fa, fb, ns_path, True))
            else:
                if CD_DEBUG: _cd_log(f"[CD][collect] {fa}->{fb} path={path} is_ns=False 加入重算")
                shortest_flows.append((fa, fb, path, False))

        ns_flows.sort(key=lambda x: -len(x[2]))  # 最長 NS 路徑優先
        flows_to_check = ns_flows + shortest_flows

        if CD_DEBUG: _cd_log(f"[CD][cascade] trigger={host_a}->{host_b} | 共{len(flows_to_check)}個flow待重算 "
                             f"| 清單={dict(self.非最短hop清單)}")

        for fa, fb, current_path, is_ns in flows_to_check:
            self.待檢查路徑.add((fa, fb))
            if CD_DEBUG: _cd_log(f"[CD][proc] ── 處理 {fa}->{fb} | current_path={current_path} is_ns={is_ns}")
            # 1. 扒乾淨自己的權重貢獻（影響哪層就扒哪層）
            if is_ns:
                self._ns_decrement(fa, fb)         # Layer 2 -1
                self.非最短hop清單.pop((fa, fb), None)
                print(f"[NonShortest] 移除: {fa} -> {fb}")
                if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | 扒乾淨NS權重完成 | 清單={dict(self.非最短hop清單)}")
            else:
                self._decrement_weight(fa, fb, current_path)  # Layer 1 -1
                if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | 扒乾淨一般權重完成")

            # 2. 當作新流量重算（prefer_current：若仍在最佳群就不換）
            if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | 呼叫_compute_path prefer_current={current_path}")
            exclude_path = current_path if not is_ns else None
            new_path = self._compute_path(fa, fb, prefer_current=current_path,
                                          exclude_path=exclude_path)
            if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | _compute_path回傳={new_path} "
                                 f"new_is_ns={self._is_ns_path(fa, fb, new_path) if new_path else 'N/A'}")

            # 3. None → 現有路徑仍是最佳，還原
            if new_path is None:
                if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | new_path=None→還原")
                if is_ns:
                    self._ns_increment(fa, fb)     # Layer 2 +1
                    self.非最短hop清單[(fa, fb)] = (len(current_path), current_path)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, "
                          f"hop={len(current_path)}, 路徑: {current_path}")
                    if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | 還原NS完成 | 清單={dict(self.非最短hop清單)}")
                else:
                    self._increment_weight(fa, fb, current_path)  # Layer 1 +1
                continue

            # 4. 換路
            old_pwp = self.app.build_path_with_ports(current_path, fa, fb)
            new_pwp = self.app.build_path_with_ports(new_path, fa, fb)
            if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | build_pwp: old={'OK' if old_pwp else 'None'} new={'OK' if new_pwp else 'None'}")
            if old_pwp is None or new_pwp is None:
                if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | pwp失敗→還原")
                if is_ns:
                    self._ns_increment(fa, fb)     # Layer 2 +1
                    self.非最短hop清單[(fa, fb)] = (len(current_path), current_path)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, "
                          f"hop={len(current_path)}, 路徑: {current_path}")
                else:
                    self._increment_weight(fa, fb, current_path)  # Layer 1 +1
                continue

            new_priority = self.app._get_next_flow_priority(fa, fb)
            self.app.install_flows_for_path(new_pwp, fa, fb, priority=new_priority, idle_timeout=5)
            # 舊路徑不主動刪，等 idle_timeout=5 自然過期
            self.app.remove_active_flow(fa, fb)
            if not is_ns:
                for sw in current_path:
                    self.sw_count[sw] = max(0, self.sw_count.get(sw, 0) - 1)
            for sw in current_path:
                self.all_sw_count[sw] = max(0, self.all_sw_count.get(sw, 0) - 1)

            is_now_ns = (fa, fb) in self.非最短hop清單
            if is_now_ns:
                print(f"[FLOW_CASCADE_NS] {fa} -> {fb}, path={new_path}")
            else:
                print(f"[FLOW_CASCADE] {fa} -> {fb}, path={new_path}")
            if CD_DEBUG: _cd_log(f"[CD][proc] {fa}->{fb} | 換路完成 is_now_ns={is_now_ns} | 清單={dict(self.非最短hop清單)}")

            self.app.add_active_flow(fa, fb, new_path, is_reroute=True, priority=new_priority)
            if not is_now_ns:
                for sw in new_path:
                    self.sw_count[sw] = self.sw_count.get(sw, 0) + 1
            for sw in new_path:
                self.all_sw_count[sw] = self.all_sw_count.get(sw, 0) + 1
            if SNAPSHOT_PER_REROUTE:
                self._log_snapshot()

        if not SNAPSHOT_PER_REROUTE:
            self._log_snapshot()
        elapsed = time.time() - _t0
        self._cascade_time_total += elapsed
        self._cascade_count += 1
        print(f"[CASCADE_TIME] {elapsed:.4f}s  avg={self._cascade_time_total/self._cascade_count:.4f}s")

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
            for key, path_list in self.k_short_paths.items():
                by_hop = {}
                for path in path_list:
                    links = tuple((min(path[i], path[i+1]), max(path[i], path[i+1]))
                                  for i in range(len(path) - 1))
                    by_hop.setdefault(len(path), []).append((path, links))
                self.k_short_paths_by_hop[key] = by_hop
                self.k_short_hop_keys[key] = sorted(by_hop.keys())
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
            self._global_min_hop = {k: min(v.keys()) for k, v in self.k_short_dist.items() if v}
            self._ns_sw_list = {k: v[self._global_min_hop[k]]
                                for k, v in self.k_short_dist.items()
                                if k in self._global_min_hop}
            print(f"[DTM-Self] 載入 {len(self.k_short_dist)} 個 host pair 的 dist 資料")
        except FileNotFoundError:
            print(f"[DTM-Self] 找不到 {filepath}")
        except Exception as e:
            print(f"[DTM-Self] 解析 k_short_dist.txt 時出錯: {e}")
