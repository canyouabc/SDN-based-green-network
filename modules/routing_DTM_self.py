# -*- coding: utf-8 -*-

import re
import random
import logging
import os
import time
from .routing_base import RoutingBase

ENABLE_NEW_ALGO = True  # True：兩階段選路（2020過濾 → 權重圖選最佳）
CASCADE_DEEP_LOG = 10   # cascade 遞迴超過此深度時印 log

# ── [CD] debug log：只寫檔案，不輸出到 terminal ──────────────────
os.makedirs("log", exist_ok=True)
_cd_logger = logging.getLogger("cascade_debug")
_cd_logger.setLevel(logging.DEBUG)
_cd_logger.propagate = False   # 不往 root logger 傳（避免出現在 terminal）
if not _cd_logger.handlers:
    _cd_fh = logging.FileHandler("log/cascade_debug.log", mode="w")
    _cd_fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                          datefmt="%H:%M:%S"))
    _cd_logger.addHandler(_cd_fh)

def _cd_log(msg):
    _cd_logger.debug(msg)
# ─────────────────────────────────────────────────────────────────


class Routing_DTM_Self(RoutingBase):

    def __init__(self, app):
        self.app = app
        self.link_status = app.link_status
        self.k_short_paths = {}    # {(host_a, host_b): [[dpid, ...], ...]}
        self.k_short_dist  = {}    # {(host_a, host_b): {hop: [sw, ...]}}
        self.core_weight_map = {}    # {dpid: int} Layer 1 核心層：最短 hop flow 貢獻
        self.待檢查路徑 = set()      # {(host_a, host_b)}，防止同一 flow 重複進入 cascade
        self._cascade_depth = 0      # debug：cascade 巢狀深度計數器
        self._cascade_time_total = 0.0
        self._cascade_count = 0
        self._ns_only_mode = False   # True 時 cascade 只處理 NS flow（第二道 pass）
        self._cascade_changed = False  # 追蹤第一道 pass 是否有路徑變換
        self.非最短hop清單 = {}      # {(host_a, host_b): (best_hop, best_path)}，Phase1選出非全局最短hop的flow
        self.ns_weight_map = {}      # {dpid: int} Layer 2 NS層：非最短 hop flow 貢獻
        self.base_weight_map = {}    # {dpid: int}，拓撲天生偏好，啟動時從 k_short_dist 計算，靜態不變
        self.load_k_short_paths('data/k_short.txt')
        self.load_k_short_dist('data/k_short_dist.txt')
        self._build_base_weight_map()

    # =========================================================
    # core_weight_map 延遲初始化
    # =========================================================

    def _ensure_weight_map(self):
        for dpid in self.app.myswitches:
            if dpid not in self.core_weight_map:
                self.core_weight_map[dpid] = 0

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

    def _is_ns_path(self, host_a, host_b, path):
        """直接比較 path 長度與 global_min_hop，判斷是否為非最短路徑"""
        dist = self.k_short_dist.get((host_a, host_b), {})
        return bool(dist) and len(path) > min(dist.keys())

    def _decrement_weight(self, host_a, host_b, path):
        hop = len(path)
        dist_entry = self.k_short_dist.get((host_a, host_b), {})
        sw_set = dist_entry.get(hop, path)
        for sw in sw_set:
            self.core_weight_map[sw] = max(0, self.core_weight_map.get(sw, 0) - 1)

    def _log_snapshot(self):
        """目前完整狀態快照，供動畫直接讀取，不需自行推算。"""
        import json
        active = [[a, b, p] for a, b, p in self.app.get_active_flows()]
        ns     = [[a, b, h] for (a, b), (h, _) in self.非最短hop清單.items()]
        wmap   = {str(k): v for k, v in self.core_weight_map.items()}
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
                self.core_weight_map[sw] = self.core_weight_map.get(sw, 0) + 1

            # Step 2：對此 hop 群的路徑評分，排除含 OVERLOAD/DANGER 的路徑
            usable = []
            for path in paths:
                if len(path) != hop:
                    continue
                has_overload = False
                for i in range(len(path) - 1):
                    link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                    if all_link_status.get(link, {}).get('status') in ('OVERLOAD', 'DANGER'):
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
                self._cascade(host_a, host_b, selected)
                return selected

            # Step 2-1：無可用路徑，扣回暫時 +1，試下一個 hop
            for sw in switch_set:
                self.core_weight_map[sw] -= 1

        return None

    def _compute_path(self, host_a, host_b, remove_path=None, prefer_current=None):
        """兩階段選路：
        Phase 1（2020）：以最少 SN link 數、最短 hop 數排序，取最優候選集
        Phase 2（新算法）：對候選集套用 core_weight_map 評分，選最高者
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

        # Phase 1：計算每條路徑的 inactive switch 數與 switch 數，排除 OVERLOAD/DANGER
        # hop 以 len(path)（switch 數）計，與 k_short_dist 的 key 單位一致
        valid_paths = []
        for path in paths:
            has_overload = False
            for i in range(len(path) - 1):
                link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                status = all_link_status.get(link, {}).get('status', 'NORMAL')
                if status in ('OVERLOAD', 'DANGER'):
                    has_overload = True
                    break
            if not has_overload:
                inactive_counter = sum(1 for sw in path if sw not in active_switches)
                valid_paths.append((inactive_counter, len(path), path))

        # 第二輪：第一輪無結果時，把含 OVERLOAD/DANGER 的路徑也納入
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
            # NS 分支：Layer 2 唯讀評分，選後才 +1 Layer 2（不動 Layer 1）
            _cd_log(f"[CD][compute] {host_a}->{host_b} | NS分支 | best_hop={best_hop} global_min={global_min_hop} | prefer_current={prefer_current}")

            scored = sorted(
                ((sum(self.ns_weight_map.get(sw, 0) for sw in p), p) for p in candidates),
                key=lambda x: -x[0]
            )
            best_weight = scored[0][0]
            tied = [p for w, p in scored if w == best_weight]
            _cd_log(f"[CD][compute] {host_a}->{host_b} | NS候選={[p for _,p in scored]} | best_weight={best_weight} | tied={tied}")

            if len(tied) > 1:
                scored0 = sorted(
                    ((sum(self.base_weight_map.get(sw, 0) for sw in p), p) for p in tied),
                    key=lambda x: -x[0]
                )
                tied = [p for w, p in scored0 if w == scored0[0][0]]

            if prefer_current and prefer_current in tied:
                _cd_log(f"[CD][compute] {host_a}->{host_b} | prefer_current命中→return None（不換路）")
                return None

            selected = random.choice(tied)
            self.非最短hop清單[(host_a, host_b)] = (best_hop, selected)
            self._ns_increment(host_a, host_b)  # Layer 2 +1（選後才更新）
            print(f"[NonShortest] 新增: {host_a} -> {host_b}, hop={best_hop}, 路徑: {selected}")
            _cd_log(f"[CD][compute] {host_a}->{host_b} | NS寫入清單完成 | 清單={dict(self.非最短hop清單)}")
            self._cascade(host_a, host_b, selected)
            return selected

        # Phase 2：最短 hop，Layer 1 唯讀評分，平手再用 Layer 2 tiebreaker，選後才 +1 Layer 1
        scored = sorted(
            ((sum(self.core_weight_map.get(sw, 0) for sw in p), p) for p in candidates),
            key=lambda x: -x[0]
        )
        best_weight = scored[0][0]
        tied = [p for w, p in scored if w == best_weight]

        if len(tied) > 1:
            scored2 = sorted(
                ((sum(self.ns_weight_map.get(sw, 0) for sw in p), p) for p in tied),
                key=lambda x: -x[0]
            )
            tied = [p for w, p in scored2 if w == scored2[0][0]]

        if len(tied) > 1:
            scored0 = sorted(
                ((sum(self.base_weight_map.get(sw, 0) for sw in p), p) for p in tied),
                key=lambda x: -x[0]
            )
            tied = [p for w, p in scored0 if w == scored0[0][0]]

        if prefer_current and prefer_current in tied:
            return None

        selected = random.choice(tied)
        self._increment_weight(host_a, host_b, selected)  # Layer 1 +1（選後才更新）
        self._cascade(host_a, host_b, selected)
        return selected

    def admit_flow(self, host_a, host_b):
        if self._ns_only_mode:
            print(f"[CASCADE_WARN] admit_flow 進入時 _ns_only_mode=True，"
                  f"前次 cascade 可能異常中止未還原（{host_a}->{host_b}）")
        if self._cascade_depth != 0:
            print(f"[CASCADE_WARN] admit_flow 進入時 _cascade_depth={self._cascade_depth}，"
                  f"前次 cascade 可能異常中止未還原（{host_a}->{host_b}）")
        self.待檢查路徑.clear()  # 每次新流量開始一輪新的 cascade session
        path = self.select_path(host_a, host_b)
        if path:
            print(f"[FLOW_NEW] {host_a} -> {host_b}, path={path}")
            self.app.add_active_flow(host_a, host_b, path)
            self._log_snapshot()
            return path
        return None

    # =========================================================
    # Cascade 重路由
    # =========================================================

    def on_flow_removed(self, host_a, host_b, removed_path):
        """timeout 觸發的 flow 移除，以移除路徑的 hop 群做 cascade 檢查"""
        if self._ns_only_mode:
            print(f"[CASCADE_WARN] on_flow_removed 進入時 _ns_only_mode=True，"
                  f"前次 cascade 可能異常中止未還原（{host_a}->{host_b}）")
        if self._cascade_depth != 0:
            print(f"[CASCADE_WARN] on_flow_removed 進入時 _cascade_depth={self._cascade_depth}，"
                  f"前次 cascade 可能異常中止未還原（{host_a}->{host_b}）")
        if (host_a, host_b) in self.非最短hop清單:
            self._ns_decrement(host_a, host_b)             # Layer 2 -1
            self.非最短hop清單.pop((host_a, host_b), None)
        else:
            self._decrement_weight(host_a, host_b, removed_path)  # Layer 1 -1
        self._log_snapshot()
        self.待檢查路徑.clear()
        self._cascade(host_a, host_b, removed_path)

    def _cascade(self, host_a, host_b, selected_path):
        """兩道 pass 重算機制：
        第一道：全部 flow 重算（NS 優先），遞迴，追蹤是否有路徑變換
        第二道：若第一道有變換，只重算 NS flow，遞迴，讓 NS flow 反應新狀態
        """
        is_outermost = self._cascade_depth == 0
        if is_outermost:
            _t0 = time.time()
            if not self._ns_only_mode:
                self._cascade_changed = False  # 第一道 pass 開始時重置

        self._cascade_depth += 1

        if self._cascade_depth > CASCADE_DEEP_LOG:
            print(f"[CASCADE_DEEP] depth={self._cascade_depth} "
                  f"pass={'2nd-NS' if self._ns_only_mode else '1st'} "
                  f"trigger={host_a}->{host_b}")

        if self._cascade_depth > 50:
            print(f"[CASCADE_ABORT] depth={self._cascade_depth} 超過上限，強制中止 "
                  f"trigger={host_a}->{host_b} path={selected_path}")
            self._cascade_depth -= 1
            if is_outermost:
                print(f"[CASCADE_TIME] {time.time() - _t0:.4f}s")
            return

        # 收集需要重算的 flow：NS 優先；_ns_only_mode 時跳過最短 flow
        ns_flows = []
        shortest_flows = []
        for fa, fb, path in self.app.get_active_flows():
            if (fa, fb) in self.待檢查路徑:
                _cd_log(f"[CD][collect] {fa}->{fb} 跳過（已在待檢查路徑）")
                continue
            if (fa, fb) in self.非最短hop清單:
                _, ns_path = self.非最短hop清單[(fa, fb)]
                _cd_log(f"[CD][collect] {fa}->{fb} path={ns_path} is_ns=True 加入重算")
                ns_flows.append((fa, fb, ns_path, True))
            elif not self._ns_only_mode:
                _cd_log(f"[CD][collect] {fa}->{fb} path={path} is_ns=False 加入重算")
                shortest_flows.append((fa, fb, path, False))

        flows_to_check = ns_flows + shortest_flows

        _cd_log(f"[CD][cascade] depth={self._cascade_depth} "
              f"pass={'2nd-NS' if self._ns_only_mode else '1st'} "
              f"trigger={host_a}->{host_b} | 共{len(flows_to_check)}個flow待重算 "
              f"| 清單={dict(self.非最短hop清單)}")

        for fa, fb, _, _ in flows_to_check:
            self.待檢查路徑.add((fa, fb))

        for fa, fb, current_path, is_ns in flows_to_check:
            _cd_log(f"[CD][proc] ── 處理 {fa}->{fb} | current_path={current_path} is_ns={is_ns}")
            # 1. 扒乾淨自己的權重貢獻（影響哪層就扒哪層）
            if is_ns:
                self._ns_decrement(fa, fb)         # Layer 2 -1
                self.非最短hop清單.pop((fa, fb), None)
                print(f"[NonShortest] 移除: {fa} -> {fb}")
                _cd_log(f"[CD][proc] {fa}->{fb} | 扒乾淨NS權重完成 | 清單={dict(self.非最短hop清單)}")
            else:
                self._decrement_weight(fa, fb, current_path)  # Layer 1 -1
                _cd_log(f"[CD][proc] {fa}->{fb} | 扒乾淨一般權重完成")

            # 2. 當作新流量重算（prefer_current：若仍在最佳群就不換）
            _cd_log(f"[CD][proc] {fa}->{fb} | 呼叫_compute_path prefer_current={current_path}")
            new_path = self._compute_path(fa, fb, prefer_current=current_path)
            _cd_log(f"[CD][proc] {fa}->{fb} | _compute_path回傳={new_path} "
                  f"new_is_ns={self._is_ns_path(fa, fb, new_path) if new_path else 'N/A'}")

            # 3. None → 現有路徑仍是最佳，還原
            if new_path is None:
                _cd_log(f"[CD][proc] {fa}->{fb} | new_path=None→還原")
                if is_ns:
                    self._ns_increment(fa, fb)     # Layer 2 +1
                    self.非最短hop清單[(fa, fb)] = (len(current_path), current_path)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, "
                          f"hop={len(current_path)}, 路徑: {current_path}")
                    _cd_log(f"[CD][proc] {fa}->{fb} | 還原NS完成 | 清單={dict(self.非最短hop清單)}")
                else:
                    self._increment_weight(fa, fb, current_path)  # Layer 1 +1
                    _cd_log(f"[CD][proc] {fa}->{fb} | 還原一般權重完成")
                continue

            # 4. 換路
            old_pwp = self.app.build_path_with_ports(current_path, fa, fb)
            new_pwp = self.app.build_path_with_ports(new_path, fa, fb)
            _cd_log(f"[CD][proc] {fa}->{fb} | build_pwp: old={'OK' if old_pwp else 'None'} new={'OK' if new_pwp else 'None'}")
            if old_pwp is None or new_pwp is None:
                _cd_log(f"[CD][proc] {fa}->{fb} | pwp失敗→還原")
                if is_ns:
                    self._ns_increment(fa, fb)     # Layer 2 +1
                    self.非最短hop清單[(fa, fb)] = (len(current_path), current_path)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, "
                          f"hop={len(current_path)}, 路徑: {current_path}")
                    _cd_log(f"[CD][proc] {fa}->{fb} | pwp失敗還原NS | 清單={dict(self.非最短hop清單)}")
                else:
                    self._increment_weight(fa, fb, current_path)  # Layer 1 +1
                continue

            new_priority = self.app._get_next_flow_priority(fa, fb)
            self.app.install_flows_for_path(new_pwp, fa, fb, priority=new_priority, idle_timeout=5)
            # 舊路徑不主動刪，等 idle_timeout=5 自然過期
            self.app.remove_active_flow(fa, fb)
            self._cascade_changed = True  # 有路徑變換，標記供第二道 pass 判斷

            is_now_ns = (fa, fb) in self.非最短hop清單
            if is_now_ns:
                print(f"[FLOW_CASCADE_NS] {fa} -> {fb}, path={new_path}")
            else:
                print(f"[FLOW_CASCADE] {fa} -> {fb}, path={new_path}")
            _cd_log(f"[CD][proc] {fa}->{fb} | 換路完成 is_now_ns={is_now_ns} | 清單={dict(self.非最短hop清單)}")

            self.app.add_active_flow(fa, fb, new_path, is_reroute=True)
            self._log_snapshot()

        self._cascade_depth -= 1

        if is_outermost:
            # 第一道 pass 結束後，若有變換路徑且非第二道 pass，啟動第二道（NS only）
            if not self._ns_only_mode and self._cascade_changed:
                print(f"[CASCADE_2ND] 第一道pass有路徑變換，啟動NS second pass")
                self.待檢查路徑.clear()
                self._ns_only_mode = True
                self._cascade(host_a, host_b, selected_path)
                self._ns_only_mode = False

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
