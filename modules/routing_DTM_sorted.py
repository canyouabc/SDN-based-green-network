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
LINK_WEIGHT = False  # False（現行）：Phase1 成本 = 要新開幾台 switch（inactive_counter），不看 link。
                     # True：Phase1 成本 = 新開 switch 能耗 + 新開 link 能耗（讀 app.switch_energy／app.link_energy，
                     # 權重與能耗等比例）；「不用新開任何東西」的 clean zero 也要求 link 已開啟。目前只有 sim.py 的 MockApp 有這兩個屬性。
PATH_INIT = 'SGH'   # 'SGH'（現行）：Phase1/Phase2 照 SGH 選路。
                    # 'SHORTEST'：每條 flow 從全局最短 hop 的 k-short 候選中隨機挑一條（「純 NSP」的初始路徑，
                    # 對應 Assefa & Ozkasap 2017 Alg.1；不做 OVERLOAD／DANGER 篩選）。
LINK_PRUNE = None   # None（現行）：不做選路後處理。
                    # 'NSP_COUNT'：NSP 變種（以 flow 數取代頻寬使用率）。每輪選路完成後，已開啟的 link 依
                    # 「經過的 flow 數」由少到多排序一次（同數隨機），逐條嘗試：在兩端 switch 間找只走其他已開啟
                    # link 的最短替代路徑（同長隨機；頻寬需 <= PRUNE_U_MAX），成功就把該 link 上的 flow 全部改走
                    # 替代路徑並關閉它。只走已開啟 link -> 每次成功必淨省一條 link、不會多開任何元件。
PRUNE_U_MAX = 0.95  # LINK_PRUNE 替代路徑上各 link 的頻寬使用率上限（論文 U_max）
WEIGHT_SCORE_NEW_ONLY = False  # False（現行）：Phase2 打分加總候選路徑上所有 switch 的 weight_map。
                                # True：只加總「尚未開啟」（不在 active_sw）的 switch，排除已開啟 switch
                                # 的權重（反正已經開著，跟本次要不要多開一個新 switch 的決策無關）。
CD_DEBUG = False

# k_short.txt 解析結果快取（見 load_k_short_paths 的說明）：
# {filepath: (k_short_paths, k_short_paths_by_hop, k_short_hop_keys)}
# 這是跨 Simulator/process 生命週期共用的模組級快取，同一個拓樸的檔案
# 只會真的讀取+parse一次；換拓樸（不同 filepath）會各自快取一份，不衝突。
_K_SHORT_CACHE = {}


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


class _ActiveElements(set):
    """LINK_WEIGHT 專用的 active_sw：update(path) 時另外記下路徑上的 link。
    本模組內 active_sw.update() 一律只傳一條 path。"""
    def __init__(self):
        super().__init__()
        self.links = set()

    def update(self, path):
        super().update(path)
        self.links.update((min(a, b), max(a, b)) for a, b in zip(path, path[1:]))


def _new_active_sw():
    """LINK_WEIGHT 關閉時用原本的 set()，預設模式不多任何開銷。"""
    return _ActiveElements() if LINK_WEIGHT else set()


class Routing_DTM_Sorted(RoutingBase):
    # 用 admit_flow 當下的 cascade 選路，需要 on_flow_removed 通知／
    # refresh_link_cache 維持內部 link 快取更新（見 modules/startup_requirements.py）。
    REROUTE_STYLE = 'cascade'
    REQUIRED_APP_FEATURES = {'link_status'}

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
        if PATH_INIT == 'SHORTEST':   # 純 NSP 初始路徑：全局最短 hop 候選全數交給 Phase2（隨機挑）
            hop = self.k_short_hop_keys[(host_a, host_b)][0]
            paths = [p for p, _ in self.k_short_paths_by_hop[(host_a, host_b)][hop] if p != remove_path]
            return (paths, hop, 0) if paths else (None, None, None)
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
                if all(sw in active_sw for sw in path) and (
                        not LINK_WEIGHT or all(link in active_sw.links for link in links)):
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
                if LINK_WEIGHT:
                    inactive_counter = self._new_energy_cost(path, links, active_sw)
                else:
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

    def _new_energy_cost(self, path, links, active_sw):
        """LINK_WEIGHT 專用：這條路徑要新開的 switch 能耗 + link 能耗（W）。
        round 避免同樣的能耗組合因加總順序不同產生浮點誤差，導致平手判斷失準。"""
        switch_energy = getattr(self.app, 'switch_energy', None)
        link_energy = getattr(self.app, 'link_energy', None)
        if switch_energy is None or link_energy is None:
            raise RuntimeError("LINK_WEIGHT=True 需要 app.switch_energy／app.link_energy（目前只有 sim.py 提供）")
        cost = sum(switch_energy.get(sw, 0) for sw in path if sw not in active_sw)
        cost += sum(link_energy.get(link, 0) for link in links if link not in active_sw.links)
        return round(cost, 6)

    def _run_phase2(self, candidates, active_sw):
        """
        Phase 2：用 weight_map 打分，回傳 (selected, scores)。
        scores = [(path, weight), ...]，weight 為路徑上 switch 的 weight 總和
        （WEIGHT_SCORE_NEW_ONLY=True 時只計入尚未開啟的 switch）。
        無論候選數量，一律回傳 scores（供 trace 使用）。
        """
        if not candidates:
            return None, []

        if WEIGHT_SCORE_NEW_ONLY:
            scores = [(p, sum(self.weight_map.get(sw, 0) for sw in p if sw not in active_sw))
                      for p in candidates]
        else:
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
            active_sw = _new_active_sw()

        candidates, _, _ = self._run_phase1(host_a, host_b, active_sw, remove_path)
        if candidates is None:
            return None

        selected, _ = self._run_phase2(candidates, active_sw)
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

        active_sw = _new_active_sw()
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
            selected, scores = self._run_phase2(candidates, active_sw)

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

            self.app.add_active_flow(fa, fb, selected, is_reroute=True, priority=new_priority)
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

        if LINK_PRUNE:
            self._prune_links()
            new_flow_path = next((p for a, b, p in self.app.get_active_flows()
                                  if (a, b) == (host_a, host_b)), new_flow_path)

        elapsed = time.time() - _t0
        print(f"[SORTED_TIME] flows={len(all_flows)-1} elapsed={elapsed:.4f}s")
        return new_flow_path

    # =========================================================
    # admit_flows_batch：靜態快照專用——只排序一次、逐一放置一次，
    # 沒有 cascade（不會回頭重放已經放好的flow）。
    #
    # 只適合「這批flow邏輯上同時存在、到達順序沒有意義」的情境
    # （例如 sim.py 的靜態快照MILP對照實驗）。DTM.py／真實 Mininet
    # 這種flow真的隨時間各自抵達的情境，必須用 admit_flow() 逐條
    # 處理，不能用這個——這裡刻意不留任何相容/降級路徑，用錯就是
    # 用錯，不要悄悄算出一個看似合理但少考慮cascade的結果。
    # =========================================================

    def admit_flows_batch(self, flow_list):
        """
        flow_list: [(host_a, host_b), ...]
        回傳: {(host_a, host_b): path}，只包含成功選到路徑的flow。

        前提：呼叫時這個 Simulator 必須還沒有任何 active flow（乾淨狀態）。
        """
        if list(self.app.get_active_flows()):
            raise RuntimeError(
                "admit_flows_batch() 只能用在全新、還沒有任何 active flow 的情境——"
                "這個函式假設所有 flow 邏輯上同時抵達，如果已經有 flow 在跑，"
                "代表你要的是真實情境，該用 admit_flow() 逐條處理。"
            )

        self.refresh_link_cache()
        _t0 = time.time()

        all_flows = []
        for host_a, host_b in flow_list:
            if (host_a, host_b) not in self.k_short_paths_by_hop:
                print(f"[DTM-Sorted] 沒有 k-short 路徑: {host_a} -> {host_b}")
                continue
            all_flows.append((host_a, host_b, None))

        self._build_weight_map(all_flows)
        if LOAD_CHECK_MODE == 'INCREMENTAL':
            self._build_link_load(all_flows)
        self._sort_flows(all_flows)

        active_sw = _new_active_sw()
        if PRESEED_ENDPOINTS:
            self._preseed_endpoints(active_sw, all_flows)

        results = {}
        for fa, fb, _ in all_flows:
            global_min_hop = self._global_min_hop.get((fa, fb))
            candidates, _, best_inactive = self._run_phase1(fa, fb, active_sw, remove_path=None)
            if candidates is None:
                continue

            selected, scores = self._run_phase2(candidates, active_sw)
            is_ns = (global_min_hop is not None and len(selected) > global_min_hop)
            if is_ns:
                self.非最短hop清單[(fa, fb)] = len(selected)

            self.app.add_active_flow(fa, fb, selected)
            active_sw.update(selected)
            results[(fa, fb)] = selected
            if LOAD_CHECK_MODE == 'INCREMENTAL':
                self._add_link_load(selected, self._get_flow_bw(fa, fb))

        elapsed = time.time() - _t0
        print(f"[SORTED_BATCH_TIME] flows={len(all_flows)} elapsed={elapsed:.4f}s")
        return results

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

        active_sw = _new_active_sw()
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
            selected, scores = self._run_phase2(candidates, active_sw)

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

            self.app.add_active_flow(fa, fb, selected, is_reroute=True, priority=new_priority)
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

        if LINK_PRUNE:
            self._prune_links()

        elapsed = time.time() - _t0
        print(f"[CASCADE_TIME] {elapsed:.4f}s")

    # =========================================================
    # LINK_PRUNE='NSP_COUNT'：選路後處理（NSP 變種，以 flow 數排序）
    # =========================================================

    @staticmethod
    def _path_links(path):
        return [(min(u, v), max(u, v)) for u, v in zip(path, path[1:])]

    @staticmethod
    def _remove_loops(path):
        """替代路徑讓 flow 重複經過同一台 switch 時，剪掉中間那段迴圈（保留第一次出現）。"""
        out, pos = [], {}
        for node in path:
            if node in pos:
                cut = pos[node]
                for dropped in out[cut + 1:]:
                    del pos[dropped]
                out = out[:cut + 1]
            else:
                pos[node] = len(out)
                out.append(node)
        return out

    def _find_detour(self, link, on_link, load, moved_bw):
        """在 link 兩端之間找只走其他已開啟 link 的替代路徑：由短到長，頻寬需 <= PRUNE_U_MAX，同長隨機。"""
        i, j = link
        adj = {}
        for (u, v), ks in on_link.items():
            if ks and (u, v) != link:
                adj.setdefault(u, []).append(v)
                adj.setdefault(v, []).append(u)
        if i not in adj or j not in adj:
            return None

        def feasible(path):
            for x in self._path_links(path):
                cap = self.app.link_bw.get(x, 0)
                if cap > 0 and (load.get(x, 0.0) + moved_bw) / cap > PRUNE_U_MAX:
                    return False
            return True

        # 依節點數逐層列舉簡單路徑（DFS 限長），每層收集可行者後隨機挑一條
        for n_nodes in range(3, len(adj) + 1):
            found = []
            stack = [(i, [i])]
            while stack:
                node, path = stack.pop()
                if len(path) == n_nodes:
                    if node == j and feasible(path):
                        found.append(path)
                    continue
                for nxt in adj.get(node, ()):
                    if nxt not in path and (nxt != j or len(path) + 1 == n_nodes):
                        stack.append((nxt, path + [nxt]))
            if found:
                return random.choice(found)
        return None

    def _prune_links(self):
        flows = {(a, b): list(p) for a, b, p in self.app.get_active_flows()}
        if not flows:
            return
        original = dict(flows)
        bw = {k: self._get_flow_bw(*k) for k in flows}
        on_link, load = {}, {}
        for k, p in flows.items():
            for x in self._path_links(p):
                on_link.setdefault(x, set()).add(k)
                load[x] = load.get(x, 0.0) + bw[k]

        order = list(on_link)
        random.shuffle(order)                        # 同 flow 數時隨機
        order.sort(key=lambda x: len(on_link[x]))    # 只在一開始排序一次（flow 數由少到多）
        for link in order:
            movers = list(on_link.get(link, ()))
            if not movers:
                continue
            detour = self._find_detour(link, on_link, load, sum(bw[k] for k in movers))
            if detour is None:
                continue
            for k in movers:
                path = flows[k]
                for t in range(len(path) - 1):
                    if (min(path[t], path[t + 1]), max(path[t], path[t + 1])) == link:
                        seg = detour if path[t] == detour[0] else detour[::-1]
                        new_path = self._remove_loops(path[:t] + seg + path[t + 2:])
                        break
                for x in self._path_links(path):
                    on_link[x].discard(k)
                    load[x] -= bw[k]
                for x in self._path_links(new_path):
                    on_link.setdefault(x, set()).add(k)
                    load[x] = load.get(x, 0.0) + bw[k]
                flows[k] = new_path

        for (fa, fb), new_path in flows.items():
            if new_path != original[(fa, fb)]:
                self._apply_prune_reroute(fa, fb, original[(fa, fb)], new_path)

    def _apply_prune_reroute(self, fa, fb, old_path, new_path):
        """比照 cascade 換路：裝新規則、更新 active_flows／非最短 hop 清單／link_load。"""
        new_pwp = self.app.build_path_with_ports(new_path, fa, fb)
        if new_pwp is None:
            return
        new_priority = self.app._get_next_flow_priority(fa, fb)
        self.app.install_flows_for_path(new_pwp, fa, fb, priority=new_priority, idle_timeout=5)
        self.app.remove_active_flow(fa, fb)
        global_min_hop = self._global_min_hop.get((fa, fb))
        self.非最短hop清單.pop((fa, fb), None)
        if global_min_hop is not None and len(new_path) > global_min_hop:
            self.非最短hop清單[(fa, fb)] = len(new_path)
        self.app.add_active_flow(fa, fb, new_path, is_reroute=True, priority=new_priority)
        print(f"[FLOW_PRUNE] {fa} -> {fb}, path={new_path}")
        if LOAD_CHECK_MODE == 'INCREMENTAL':
            flow_bw = self._get_flow_bw(fa, fb)
            self._remove_link_load(old_path, flow_bw)
            self._add_link_load(new_path, flow_bw)

    # =========================================================
    # 載入 k_short.txt
    # =========================================================

    def load_k_short_paths(self, filepath='data/k_short.txt'):
        # k_short.txt 解析後就是唯讀資料，載入後從沒被改過（見上面幾個
        # self.k_short_paths[...]／k_short_paths_by_hop[...]／k_short_hop_keys[...]
        # 的賦值，全部只在這個函式裡發生）——用同一份拓樸重複建立多個
        # Simulator（例如批次跑很多個snapshot）時，直接共用同一份已解析
        # 好的資料，不用每次都重新開檔、重新parse一次（大拓樸的k_short.txt
        # 可能好幾MB，重複parse是明顯的效能瓶頸）。
        cached = _K_SHORT_CACHE.get(filepath)
        if cached is not None:
            self.k_short_paths, self.k_short_paths_by_hop, self.k_short_hop_keys = cached
            print(f"[DTM-Sorted] 沿用快取的 k-short 路徑（{len(self.k_short_paths)} 個 host pair）: {filepath}")
            return
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
            _K_SHORT_CACHE[filepath] = (self.k_short_paths, self.k_short_paths_by_hop, self.k_short_hop_keys)
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
