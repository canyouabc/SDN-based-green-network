# -*- coding: utf-8 -*-

import re
import random
import logging
import os
import time
from .routing_base import RoutingBase

ENABLE_NEW_ALGO = True
ENABLE_WEIGHT_MAP = True    # True：Phase 2 用 base_weight_map 打分；False：並列時直接 random
SORT_MODE = 'SPF'    # 'LPF'：依理論最短 hop 由大到小（現行）
                      # 'DENSITY'：依最小路徑集合在 weight_map 上的平均權重由大到小
                      # 'SPF'：依理論最短 hop 由小到大（最短路徑優先）
                      # 'HDF'：依 flow 已知頻寬由大到小（最高流量優先）
                      # 'SDF'：依 flow 已知頻寬由小到大（最低流量優先）
                      # SPF/HDF/SDF 對應 SGH 論文的 Shortest Path First / High(est) Demand First / Smallest Demand First
WEIGHT_MODE = 'STATIC'   # 'STATIC'：weight_map 整輪處理期間固定不變（現行）
                         # 'DECAY'：每條 flow 選路完成後，扣除該 flow 最小路徑集合對 weight_map 的貢獻
LOAD_CHECK_MODE = 'INCREMENTAL'  # DANGER 前瞻檢查用的 link 負載來源
                                 # 'INCREMENTAL'：自己維護 link_load，隨每條 flow 的選路結果即時增減（預設）
                                 # 'LIVE'：每次檢查都重新掃一次 active_flows 現算，較簡單但較耗運算
PRESEED_ENDPOINTS = False  # True：處理每一輪 flow 前，先把這輪所有 flow 的起訖點 switch
                           # （同一 host pair 不管選哪條 k-short 候選路徑都固定相同）預先標記為 active，
                           # 不讓 clean_zero／inactive_counter 把「反正一定要開」的 switch 誤判成選路的代價。
                           # False（現行／預設）：active_sw 從空集合開始，起訖點也要等流量真的選定路徑才算 active。
CD_DEBUG = False


if CD_DEBUG:
    os.makedirs("log", exist_ok=True)
    _cd_logger = logging.getLogger("cascade_debug_sorted")
    _cd_logger.setLevel(logging.DEBUG)
    _cd_logger.propagate = False
    if not _cd_logger.handlers:
        _cd_fh = logging.FileHandler("log/cascade_debug_sorted.log", mode="w")
        _cd_fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                              datefmt="%H:%M:%S"))
        _cd_logger.addHandler(_cd_fh)

def _cd_log(msg):
    if CD_DEBUG:
        _cd_logger.debug(msg)


class Routing_DTM_Sorted(RoutingBase):

    def __init__(self, app):
        self.app = app
        self.link_status = app.link_status
        self.k_short_paths = {}
        self.k_short_paths_by_hop = {}
        self.k_short_hop_keys = {}
        self.k_short_dist = {}
        self._global_min_hop = {}
        self.weight_map = {}   # 動態：當前 active flows 的最短路徑 switch 集合疊加
        self.link_load = {}    # {(u,v): Mbps}，LOAD_CHECK_MODE='INCREMENTAL' 專用，即時追蹤各 link 實際負載
        self._overload_links = frozenset()
        self.非最短hop清單 = {}
        self._step_cb = None   # trace mode callback，None 表示停用
        self.load_k_short_paths(getattr(app, 'k_short_path', 'data/k_short.txt'))
        self.load_k_short_dist(getattr(app, 'k_short_dist_path', 'data/k_short_dist.txt'))

    # =========================================================
    # 工具方法（與 DTM-Self 相同）
    # =========================================================

    def refresh_link_cache(self):
        all_status = self.link_status.get_all_link_status()
        self._overload_links = frozenset(
            link for link, info in all_status.items()
            if info.get('status') in ('OVERLOAD', 'DANGER')
        )

    def _build_weight_map(self, flows):
        """根據當前 active flows 的最短路徑 switch 集合，計算動態權重圖。
        每條 flow 的最短 hop switch 集合（k_short_dist）貢獻 +1。"""
        wmap = {}
        for fa, fb, _ in flows:
            hop_groups = self.k_short_dist.get((fa, fb), {})
            if not hop_groups:
                continue
            min_hop = min(hop_groups.keys())
            for sw in hop_groups[min_hop]:
                wmap[sw] = wmap.get(sw, 0) + 1
        self.weight_map = wmap

    def _decrement_weight_map(self, host_a, host_b):
        """WEIGHT_MODE='DECAY' 專用：扣除該 flow 最小路徑集合對 weight_map 的貢獻。
        跟 _build_weight_map 的加法對稱，用同一個 global_min_hop 群，
        不管這條 flow 最後選中的是不是這個群裡的路徑。
        Phase 1 找不到候選路徑時一樣呼叫（該 flow 沒有實際佔用這些 switch）。"""
        hop_groups = self.k_short_dist.get((host_a, host_b), {})
        if not hop_groups:
            return
        min_hop = min(hop_groups.keys())
        for sw in hop_groups[min_hop]:
            if sw in self.weight_map:
                self.weight_map[sw] -= 1

    def _density_score(self, host_a, host_b):
        """該 flow 最小路徑集合在 weight_map 上的平均權重（集合擁擠密度）。
        呼叫前必須先跑過 _build_weight_map，確保 self.weight_map 是最新的。"""
        hop_groups = self.k_short_dist.get((host_a, host_b), {})
        if not hop_groups:
            return 0.0
        min_hop = min(hop_groups.keys())
        switches = hop_groups[min_hop]
        if not switches:
            return 0.0
        return sum(self.weight_map.get(sw, 0) for sw in switches) / len(switches)

    def _get_flow_bw(self, host_a, host_b):
        """取得該 flow 的已知頻寬需求（Mbps）。
        真實 Mininet（DTM.py）沒有這個資訊，getattr 保底回傳 0，
        等同不啟用前瞻檢查，行為與改動前一致。"""
        return getattr(self.app, '_flow_sizes', {}).get((host_a, host_b), 0.0)

    def _get_endpoints(self, host_a, host_b):
        """回傳 (起點 switch, 終點 switch)。同一個 host pair 底下，
        不管選中哪一條 k-short 候選路徑，頭尾 switch 都固定相同
        （由 host 實體連接的 switch 決定，跟選路無關），任取一條候選路徑即可。"""
        paths = self.k_short_paths.get((host_a, host_b))
        if not paths:
            return None, None
        first = paths[0]
        return first[0], first[-1]

    def _preseed_endpoints(self, active_sw, flows):
        """PRESEED_ENDPOINTS 專用：把這輪所有 flow 的起訖點 switch 預先標記為 active。"""
        for fa, fb, _ in flows:
            src, dst = self._get_endpoints(fa, fb)
            if src is not None:
                active_sw.add(src)
            if dst is not None:
                active_sw.add(dst)

    def _build_link_load(self, flows):
        """LOAD_CHECK_MODE='INCREMENTAL' 專用：從目前所有 flow 的實際路徑 × 已知 BW，
        建立即時 link 負載表（Mbps）。呼叫時機與 _build_weight_map 相同（整輪處理開始前）。"""
        load = {}
        for fa, fb, path in flows:
            if not path:
                continue
            bw = self._get_flow_bw(fa, fb)
            if bw <= 0:
                continue
            for i in range(len(path) - 1):
                link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                load[link] = load.get(link, 0.0) + bw
        self.link_load = load

    def _add_link_load(self, path, bw):
        """flow 新裝上某路徑後，把負載加回 link_load。"""
        if bw <= 0 or not path:
            return
        for i in range(len(path) - 1):
            link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
            self.link_load[link] = self.link_load.get(link, 0.0) + bw

    def _remove_link_load(self, path, bw):
        """flow 離開某路徑（換路或移除）後，把負載從 link_load 扣掉。"""
        if bw <= 0 or not path:
            return
        for i in range(len(path) - 1):
            link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
            if link in self.link_load:
                self.link_load[link] -= bw

    def _compute_current_load_live(self, link):
        """LOAD_CHECK_MODE='LIVE' 專用：即時掃過 active_flows 算出這條 link 目前的實際負載（Mbps）。"""
        total = 0.0
        for fa, fb, path in self.app.get_active_flows():
            bw = self._get_flow_bw(fa, fb)
            if bw <= 0:
                continue
            for i in range(len(path) - 1):
                if (min(path[i], path[i + 1]), max(path[i], path[i + 1])) == link:
                    total += bw
                    break
        return total

    def _would_exceed_danger(self, links, flow_bw):
        """前瞻檢查：加入 flow_bw 後，路徑上是否有 link 會超過 100%（DANGER）。
        flow_bw <= 0（未知）時直接視為不會超過，不影響現有行為。
        負載來源依 LOAD_CHECK_MODE 決定，不依賴 link_status 快照的更新時機。"""
        if flow_bw <= 0:
            return False
        for link in links:
            capacity = self.app.link_bw.get(link, 0)
            if capacity <= 0:
                continue
            if LOAD_CHECK_MODE == 'LIVE':
                current_load = self._compute_current_load_live(link)
            else:  # 'INCREMENTAL'
                current_load = self.link_load.get(link, 0.0)
            if (current_load + flow_bw) / capacity * 100.0 >= 100.0:
                return True
        return False

    def _sort_flows(self, all_flows):
        """依 SORT_MODE 排序所有 flow（優先度最高排最前面）。
        呼叫前必須先跑過 _build_weight_map。"""
        if SORT_MODE == 'DENSITY':
            all_flows.sort(
                key=lambda f: self._density_score(f[0], f[1]),
                reverse=True
            )
        elif SORT_MODE == 'SPF':
            all_flows.sort(
                key=lambda f: self._global_min_hop.get((f[0], f[1]), 999)
            )
        elif SORT_MODE == 'HDF':
            all_flows.sort(
                key=lambda f: self._get_flow_bw(f[0], f[1]),
                reverse=True
            )
        elif SORT_MODE == 'SDF':
            all_flows.sort(
                key=lambda f: self._get_flow_bw(f[0], f[1])
            )
        else:  # 'LPF'
            all_flows.sort(
                key=lambda f: self._global_min_hop.get((f[0], f[1]), 999),
                reverse=True
            )

    # =========================================================
    # 核心選路：簡化版本，只用 core_weight_map
    # =========================================================

    def select_path(self, host_a, host_b, remove_path=None):
        """廢棄。使用 _compute_path 替代。"""
        return None

    def _run_phase1(self, host_a, host_b, active_sw, remove_path):
        """Phase 1：優先找「所有 switch 都已在 active_sw 中」的路徑"""
        flow_bw = self._get_flow_bw(host_a, host_b)
        for hop in self.k_short_hop_keys[(host_a, host_b)]:
            clean_zero = []
            for path, links in self.k_short_paths_by_hop[(host_a, host_b)][hop]:
                if remove_path and path == remove_path:
                    continue
                if any(link in self._overload_links for link in links):
                    continue
                if self._would_exceed_danger(links, flow_bw):
                    continue
                if all(sw in active_sw for sw in path):
                    clean_zero.append(path)
            if clean_zero:
                return clean_zero, hop, 0

        # 無「clean zero」，尋找「非現有 switch 最少」的候選
        valid_paths = []
        fallback_paths = []
        for hop_key in self.k_short_hop_keys[(host_a, host_b)]:
            for path, links in self.k_short_paths_by_hop[(host_a, host_b)][hop_key]:
                if remove_path and path == remove_path:
                    continue
                has_overload = (
                    any(link in self._overload_links for link in links)
                    or self._would_exceed_danger(links, flow_bw)
                )
                inactive_counter = sum(1 for sw in path if sw not in active_sw)
                tup = (inactive_counter, len(path), path)
                if not has_overload:
                    valid_paths.append(tup)
                fallback_paths.append(tup)
        if not valid_paths:
            if flow_bw > 0 and fallback_paths:
                all_would_danger = all(
                    self._would_exceed_danger(
                        tuple((min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                              for i in range(len(path) - 1)),
                        flow_bw
                    )
                    for _, _, path in fallback_paths
                )
                if all_would_danger:
                    print(f"[DANGER_UNAVOIDABLE] {host_a} -> {host_b}: "
                          f"所有候選路徑皆會使某段 link 超過 100%（DANGER），已無可避免，強制選路")
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

    def _run_phase2(self, candidates):
        """
        Phase 2：用 weight_map 打分，回傳 (selected, scores)。
        scores = [(path, weight), ...]，weight 為路徑上所有 switch 的 weight 總和。
        無論候選數量，一律回傳 scores（供 trace 使用）。
        """
        if not candidates:
            return None, []

        scores = [(p, sum(self.weight_map.get(sw, 0) for sw in p)) for p in candidates]

        if len(candidates) == 1:
            return candidates[0], scores

        if not ENABLE_WEIGHT_MAP:
            return random.choice(candidates), scores

        best_weight = max(s for _, s in scores)
        top = [p for p, s in scores if s == best_weight]
        return random.choice(top), scores

    def _compute_path(self, host_a, host_b, remove_path=None, active_sw=None):
        """
        選路核心邏輯：
        - Phase 1：優先找「所有 switch 都已在 active_sw 中」的路徑
        - Phase 2：同 hop 下，用 weight_map 加權選擇
        """
        if (host_a, host_b) not in self.k_short_paths_by_hop:
            print(f"[DTM-Sorted] 沒有 k-short 路徑: {host_a} -> {host_b}")
            return None

        if active_sw is None:
            active_sw = set()

        candidates, _, _ = self._run_phase1(host_a, host_b, active_sw, remove_path)
        if candidates is None:
            return None

        selected, _ = self._run_phase2(candidates)
        return selected

    # =========================================================
    # admit_flow：排序所有 flow（按理論最短 hop），逐個選路
    # =========================================================

    def admit_flow(self, host_a, host_b):
        """
        新 flow 加入。所有 flow 依 SORT_MODE 排序後，逐個選路安裝。
        被選到「非最短 hop」的路徑會被被動紀錄到非最短hop清單，但不影響後續 flow 的選路優先度。
        """
        self.refresh_link_cache()

        if (host_a, host_b) not in self.k_short_paths_by_hop:
            print(f"[DTM-Sorted] 沒有 k-short 路徑: {host_a} -> {host_b}")
            return None

        _t0 = time.time()

        # 現有 flow + 新 flow
        all_flows = list(self.app.get_active_flows())
        all_flows.append((host_a, host_b, None))

        # 動態 weight_map：基於當前所有 flow 的最短路徑 switch 集合
        self._build_weight_map(all_flows)
        if LOAD_CHECK_MODE == 'INCREMENTAL':
            self._build_link_load(all_flows)

        # 排序：依 SORT_MODE 決定優先度
        self._sort_flows(all_flows)

        active_sw = set()
        if PRESEED_ENDPOINTS:
            self._preseed_endpoints(active_sw, all_flows)
        new_flow_path = None
        _order = [(f[0], f[1], self._global_min_hop.get((f[0], f[1]), 0)) for f in all_flows]

        for fa, fb, current_path in all_flows:
            is_new = (current_path is None)
            global_min_hop = self._global_min_hop.get((fa, fb))

            # ── Trace: sort ──────────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_sort', fa, fb, {
                    'order': _order, 'current': [fa, fb]
                })

            # Phase 1
            candidates, _, best_inactive = self._run_phase1(fa, fb, active_sw, remove_path=None)

            # ── Trace: phase1 ────────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_phase1', fa, fb, {
                    'candidates': candidates or [],
                    'best_inactive': best_inactive,
                })

            if candidates is None:
                if not is_new:
                    active_sw.update(current_path)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                continue

            # Phase 2
            selected, scores = self._run_phase2(candidates)

            # ── Trace: phase2 ────────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_phase2', fa, fb, {
                    'scores': [[list(p), s] for p, s in scores],
                    'selected': selected,
                })

            # 檢查是否非最短 hop
            is_ns = (global_min_hop is not None and len(selected) > global_min_hop)

            if is_new:
                # 新 flow：紀錄並返回給 DTM.py 安裝
                if is_ns:
                    self.非最短hop清單[(fa, fb)] = len(selected)
                    print(f"[NonShortest] 新增: {fa} -> {fb}, hop={len(selected)}")
                self.app.add_active_flow(fa, fb, selected)
                print(f"[FLOW_NEW] {fa} -> {fb}, path={selected}")
                new_flow_path = selected
                active_sw.update(selected)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                if LOAD_CHECK_MODE == 'INCREMENTAL':
                    self._add_link_load(selected, self._get_flow_bw(fa, fb))
                # ── Trace: decided ───────────────────────────────
                if self._step_cb:
                    self._step_cb('trace_decided', fa, fb, {
                        'old_path': None, 'new_path': selected, 'changed': True
                    })
                continue

            # 現有 flow：路徑沒變就跳過
            if selected == current_path:
                active_sw.update(current_path)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                # ── Trace: decided ───────────────────────────────
                if self._step_cb:
                    self._step_cb('trace_decided', fa, fb, {
                        'old_path': current_path, 'new_path': selected, 'changed': False
                    })
                continue

            # 換路：解舊、裝新
            new_pwp = self.app.build_path_with_ports(selected, fa, fb)
            if new_pwp is None:
                active_sw.update(current_path)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                continue

            new_priority = self.app._get_next_flow_priority(fa, fb)
            self.app.install_flows_for_path(new_pwp, fa, fb, priority=new_priority, idle_timeout=5)
            self.app.remove_active_flow(fa, fb)

            # NS 清單更新
            self.非最短hop清單.pop((fa, fb), None)
            if is_ns:
                self.非最短hop清單[(fa, fb)] = len(selected)
                print(f"[NonShortest] 新增: {fa} -> {fb}, hop={len(selected)}")

            self.app.add_active_flow(fa, fb, selected, is_reroute=True)
            print(f"[FLOW_CASCADE] {fa} -> {fb}, path={selected}")
            active_sw.update(selected)
            if WEIGHT_MODE == 'DECAY':
                self._decrement_weight_map(fa, fb)
            if LOAD_CHECK_MODE == 'INCREMENTAL':
                flow_bw = self._get_flow_bw(fa, fb)
                self._remove_link_load(current_path, flow_bw)
                self._add_link_load(selected, flow_bw)
            # ── Trace: decided ───────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_decided', fa, fb, {
                    'old_path': current_path, 'new_path': selected, 'changed': True
                })

        elapsed = time.time() - _t0
        print(f"[SORTED_TIME] flows={len(all_flows)-1} elapsed={elapsed:.4f}s")
        return new_flow_path

    # =========================================================
    # on_flow_removed + _cascade
    # =========================================================

    def on_flow_removed(self, host_a, host_b, removed_path):
        """flow 移除時觸發 cascade。"""
        self.非最短hop清單.pop((host_a, host_b), None)
        self._cascade()

    def _cascade(self):
        """
        Cascade：所有 flow 依 SORT_MODE 排序，逐個重選路。
        """
        self.refresh_link_cache()
        _t0 = time.time()

        all_flows = list(self.app.get_active_flows())
        if not all_flows:
            return

        # 動態 weight_map：基於當前所有 flow 的最短路徑 switch 集合
        self._build_weight_map(all_flows)
        if LOAD_CHECK_MODE == 'INCREMENTAL':
            self._build_link_load(all_flows)

        # 排序：依 SORT_MODE 決定優先度
        self._sort_flows(all_flows)

        active_sw = set()
        if PRESEED_ENDPOINTS:
            self._preseed_endpoints(active_sw, all_flows)
        _order = [(f[0], f[1], self._global_min_hop.get((f[0], f[1]), 0)) for f in all_flows]

        for fa, fb, current_path in all_flows:
            global_min_hop = self._global_min_hop.get((fa, fb))

            # ── Trace: sort ──────────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_sort', fa, fb, {
                    'order': _order, 'current': [fa, fb]
                })

            # Phase 1
            candidates, _, best_inactive = self._run_phase1(fa, fb, active_sw, remove_path=None)

            # ── Trace: phase1 ────────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_phase1', fa, fb, {
                    'candidates': candidates or [],
                    'best_inactive': best_inactive,
                })

            if candidates is None:
                active_sw.update(current_path)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                continue

            # Phase 2
            selected, scores = self._run_phase2(candidates)

            # ── Trace: phase2 ────────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_phase2', fa, fb, {
                    'scores': [[list(p), s] for p, s in scores],
                    'selected': selected,
                })

            if selected is None or selected == current_path:
                active_sw.update(current_path)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                # ── Trace: decided ───────────────────────────────
                if self._step_cb:
                    self._step_cb('trace_decided', fa, fb, {
                        'old_path': current_path, 'new_path': selected, 'changed': False
                    })
                continue

            # 路徑有變，安裝新規則
            new_pwp = self.app.build_path_with_ports(selected, fa, fb)
            if new_pwp is None:
                active_sw.update(current_path)
                if WEIGHT_MODE == 'DECAY':
                    self._decrement_weight_map(fa, fb)
                continue

            new_priority = self.app._get_next_flow_priority(fa, fb)
            self.app.install_flows_for_path(new_pwp, fa, fb, priority=new_priority, idle_timeout=5)
            self.app.remove_active_flow(fa, fb)

            # NS 清單更新
            self.非最短hop清單.pop((fa, fb), None)
            is_ns = (global_min_hop is not None and len(selected) > global_min_hop)
            if is_ns:
                self.非最短hop清單[(fa, fb)] = len(selected)
                print(f"[NonShortest] 新增: {fa} -> {fb}, hop={len(selected)}")

            self.app.add_active_flow(fa, fb, selected, is_reroute=True)
            print(f"[FLOW_CASCADE] {fa} -> {fb}, path={selected}")
            active_sw.update(selected)
            if WEIGHT_MODE == 'DECAY':
                self._decrement_weight_map(fa, fb)
            if LOAD_CHECK_MODE == 'INCREMENTAL':
                flow_bw = self._get_flow_bw(fa, fb)
                self._remove_link_load(current_path, flow_bw)
                self._add_link_load(selected, flow_bw)
            # ── Trace: decided ───────────────────────────────────
            if self._step_cb:
                self._step_cb('trace_decided', fa, fb, {
                    'old_path': current_path, 'new_path': selected, 'changed': True
                })

        elapsed = time.time() - _t0
        print(f"[CASCADE_TIME] {elapsed:.4f}s")

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
            print(f"[DTM-Sorted] 載入 {len(self.k_short_paths)} 個 host pair 的 k-short 路徑")
        except FileNotFoundError:
            print(f"[DTM-Sorted] 找不到 {filepath}")
        except Exception as e:
            print(f"[DTM-Sorted] 解析 k_short.txt 時出錯: {e}")

    # =========================================================
    # 載入 k_short_dist.txt（計算理論最短 hop）
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
            print(f"[DTM-Sorted] 載入 {len(self.k_short_dist)} 個 host pair 的 dist 資料")
        except FileNotFoundError:
            print(f"[DTM-Sorted] 找不到 {filepath}")
        except Exception as e:
            print(f"[DTM-Sorted] 解析 k_short_dist.txt 時出錯: {e}")
