# sim.py
# ─────────────────────────────────────────────────────────────────
# 純路由模擬器：不依賴 Ryu / Mininet
#
# 只需要三個輸入：來源、目的、流量大小(Mbps)
# Link status 由 active flow × 流量大小 × 路徑直接計算，不量測
#
# 使用方式：
#   sim = Simulator(algorithm='self')
#   sim.admit('h1', 'h16', 100)    # src, dst, Mbps
#   sim.depart('h1', 'h16')
#   sim.status()
#
# 從 seed 檔執行：
#   python3 sim.py --seed seed_1.json --algorithm self
# ─────────────────────────────────────────────────────────────────

import sys
import time
from collections import defaultdict
from datetime import datetime


class _Tee:
    """將 stdout 同時輸出到 terminal 和檔案（不修改任何模組即可捕捉所有 print）"""
    def __init__(self, filepath):
        self._file   = open(filepath, 'w', encoding='utf-8')
        self._stdout = sys.stdout
    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)
    def flush(self):
        self._stdout.flush()
        self._file.flush()
    def close(self):
        sys.stdout = self._stdout
        self._file.close()


class _SnapLogger:
    """將 [SIM_SNAPSHOT] JSON 行寫入獨立的 snap 檔（不影響 terminal / run log）"""
    def __init__(self, filepath):
        self._file = open(filepath, 'w', encoding='utf-8')

    def write_snap(self, data: str):
        self._file.write(f"[SIM_SNAPSHOT] {data}\n")
        self._file.flush()

    def close(self):
        self._file.close()

# ── 設定 ────────────────────────────────────────────────────────
ROUTING_ALGORITHM  = 'sorted'       # 'self' | '2020' | 'dijkstra' | 'sorted'
TOPO               = 'grid_2x2'       # 'grid'(5x5) | 'cap' | 'grid_2x2' | 'grid_3x3' | 'grid_4x4' | 'grid_6x6' | 'grid_7x7'
EXPERIMENT_LOG     = 'experiment.log'
LINK_LOAD_UPDATE   = 'periodic'   # 'realtime'（每次 add/remove 即時更新）
                                  # 'periodic' （每 N 秒更新一次）
LINK_LOAD_INTERVAL = 1            # N：LINK_LOAD_UPDATE='periodic' 時有效
TRACE_MODE         = False        # True：逐步追蹤模式（每條 flow 產生 4 幀）；False：現有模式

# 各拓撲對應的資料檔（依 TOPO 分別指向 data/grid/ 或 data/cap/）
_TOPO_FILES = {
    'grid': {
        'link_bw':         'data/grid/link_bw.txt',
        'link_energy':     'data/grid/link_energy.txt',
        'switch_energy':   'data/grid/switch_energy.txt',
        'k_short':         'data/grid/k_short.txt',
        'k_short_dist':    'data/grid/k_short_dist.txt',
        'base_weight_map': 'data/grid/base_weight_map.txt',
    },
    'cap': {
        'link_bw':         'data/cap/link_bw.txt',
        'link_energy':     'data/cap/link_energy.txt',
        'switch_energy':   'data/cap/switch_energy.txt',
        'k_short':         'data/cap/k_short.txt',
        'k_short_dist':    'data/cap/k_short_dist.txt',
        'base_weight_map': 'data/cap/base_weight_map.txt',
    },
    'grid_2x2': {
        'link_bw':         'data/grid_2x2/link_bw.txt',
        'link_energy':     'data/grid_2x2/link_energy.txt',
        'switch_energy':   'data/grid_2x2/switch_energy.txt',
        'k_short':         'data/grid_2x2/k_short.txt',
        'k_short_dist':    'data/grid_2x2/k_short_dist.txt',
        'base_weight_map': 'data/grid_2x2/base_weight_map.txt',
    },
    'grid_3x3': {
        'link_bw':         'data/grid_3x3/link_bw.txt',
        'link_energy':     'data/grid_3x3/link_energy.txt',
        'switch_energy':   'data/grid_3x3/switch_energy.txt',
        'k_short':         'data/grid_3x3/k_short.txt',
        'k_short_dist':    'data/grid_3x3/k_short_dist.txt',
        'base_weight_map': 'data/grid_3x3/base_weight_map.txt',
    },
    'grid_4x4': {
        'link_bw':         'data/grid_4x4/link_bw.txt',
        'link_energy':     'data/grid_4x4/link_energy.txt',
        'switch_energy':   'data/grid_4x4/switch_energy.txt',
        'k_short':         'data/grid_4x4/k_short.txt',
        'k_short_dist':    'data/grid_4x4/k_short_dist.txt',
        'base_weight_map': 'data/grid_4x4/base_weight_map.txt',
    },
    'grid_6x6': {
        'link_bw':         'data/grid_6x6/link_bw.txt',
        'link_energy':     'data/grid_6x6/link_energy.txt',
        'switch_energy':   'data/grid_6x6/switch_energy.txt',
        'k_short':         'data/grid_6x6/k_short.txt',
        'k_short_dist':    'data/grid_6x6/k_short_dist.txt',
        'base_weight_map': 'data/grid_6x6/base_weight_map.txt',
    },
    'grid_7x7': {
        'link_bw':         'data/grid_7x7/link_bw.txt',
        'link_energy':     'data/grid_7x7/link_energy.txt',
        'switch_energy':   'data/grid_7x7/switch_energy.txt',
        'k_short':         'data/grid_7x7/k_short.txt',
        'k_short_dist':    'data/grid_7x7/k_short_dist.txt',
        'base_weight_map': 'data/grid_7x7/base_weight_map.txt',
    },
    'geant': {
        'link_bw':         'data/geant/link_bw.txt',
        'link_energy':     'data/geant/link_energy.txt',
        'switch_energy':   'data/geant/switch_energy.txt',
        'k_short':         'data/geant/k_short.txt',
        'k_short_dist':    'data/geant/k_short_dist.txt',
        'base_weight_map': 'data/geant/base_weight_map.txt',
    },
    # switch:link 能耗比例改為 3:1（比照論文 Section III 的節能公式假設，
    # 而非專案既有的 146W/0.18W ≈ 811:1）。k_short 系列檔案跟 data/geant 完全共用
    # ——兩個 flat 常數版本下，Dijkstra 選路只看 hop 數排序，不受 switch:link 絕對比例影響，
    # 詳見與使用者的討論。
    'geant_31': {
        'link_bw':         'data/geant_31/link_bw.txt',
        'link_energy':     'data/geant_31/link_energy.txt',
        'switch_energy':   'data/geant_31/switch_energy.txt',
        'k_short':         'data/geant_31/k_short.txt',
        'k_short_dist':    'data/geant_31/k_short_dist.txt',
        'base_weight_map': 'data/geant_31/base_weight_map.txt',
    },
}

def _topo_file(key: str) -> str:
    files = _TOPO_FILES.get(TOPO)
    if files is None:
        raise ValueError(f"未知拓撲: {TOPO}，可用選項: {', '.join(_TOPO_FILES.keys())}")
    return files[key]


def _now_str() -> str:
    """回傳與 experiment.log 相同格式的時間戳記：YYYY-MM-DD HH:MM:SS.mmm"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]


def host_to_mac(name: str) -> str:
    """
    將 Mininet 主機名稱轉換為 MAC 位址。
    routing 模組（以及 k_short.txt）使用 MAC 作為 flow key。

    規則：h{n} → 00:00:00:00:00:{n:02x}
      h1  → 00:00:00:00:00:01
      h10 → 00:00:00:00:00:0a
      h16 → 00:00:00:00:00:10
    """
    n = int(name[1:])
    return f'00:00:00:00:00:{n:02x}'


def mac_to_host(mac: str) -> str:
    """00:00:00:00:00:0a → h10"""
    return f'h{int(mac.split(":")[-1], 16)}'


# ─────────────────────────────────────────────────────────────────
# Stub：模擬 FlowStats 的 assign/unassign（不需要 Ryu datapath）
# ─────────────────────────────────────────────────────────────────

class _SimFlowStats:
    def __init__(self):
        self._assignment  = {}
        self._sw_to_flows = defaultdict(set)

    def assign(self, src, dst, path):
        self.unassign(src, dst)
        if path:
            dpid = path[0]
            self._assignment[(src, dst)] = dpid
            self._sw_to_flows[dpid].add((src, dst))

    def unassign(self, src, dst):
        dpid = self._assignment.pop((src, dst), None)
        if dpid is not None:
            self._sw_to_flows[dpid].discard((src, dst))
            if not self._sw_to_flows[dpid]:
                del self._sw_to_flows[dpid]


# ─────────────────────────────────────────────────────────────────
# MockApp：提供路由模組所需的全部介面
# ─────────────────────────────────────────────────────────────────

class MockApp:
    """
    模擬 DTM.py ProjectController，供路由模組直接 import。

    implements modules.routing_host.RoutingHost（完整成員清單與型別見該檔）。
    額外提供 `_flow_sizes`（sim 專用合成流量大小）；不提供 RoutingHostDelay
    的 link_delay / link_used_bw / get_link_delay_func → routing_2014 無法在 sim 跑。
    改動這裡對 routing 模組露出的介面時，同步更新 modules/routing_host.py。
    """

    def __init__(self):
        from modules.link_status import Link_Status

        self.myswitches    = []
        self.adjacency     = defaultdict(lambda: defaultdict(lambda: None))
        self.link_bw       = {}
        self.host_macs     = {}   # {mac: (dpid, port)}，dijkstra 模組使用
        self._realtime_load = False  # 由 Simulator 依設定覆寫

        # 路由模組讀取 k_short 系列檔案時依此路徑（依 TOPO 分流，見 _TOPO_FILES）
        self.k_short_path         = _topo_file('k_short')
        self.k_short_dist_path    = _topo_file('k_short_dist')
        self.base_weight_map_path = _topo_file('base_weight_map')

        self._load_link_bw(_topo_file('link_bw'))

        # 能耗資料（與 DTM.py 相同，用於 calculate_energy_saving）
        self.switch_energy         = self._load_switch_energy(_topo_file('switch_energy'))
        self.link_energy           = self._load_link_txt(_topo_file('link_energy'))
        self.initial_switch_energy = dict(self.switch_energy)
        self.initial_link_energy   = dict(self.link_energy)

        self.link_status = Link_Status(self)
        self.flow_stats  = _SimFlowStats()

        # active flow 管理（與 DTM.py 相同結構）
        self.active_flows     = {}   # {(src, dst): {'path': [...], 'install_time': t}}
        self._flow_sizes      = {}   # {(src, dst): Mbps}，模擬器專用

        # 統計（與 DTM.py 相同，供 HISTORY 行使用）
        self.flow_history_count   = 0
        self.flow_history_hops    = 0
        self.reroute_count_link      = 0
        self.reroute_count_high_hop  = 0
        self.reroute_count_low_share = 0
        self.reroute_count_high_load = 0

        # 所有 link 初始為 0%（SN）
        for (u, v) in self.link_bw:
            self.link_status.update_link_status(u, v, 0.0)

    # ── 資料載入 ─────────────────────────────────────────────────

    def _load_link_bw(self, filepath):
        try:
            with open(filepath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    u, v, bw = int(parts[0]), int(parts[1]), float(parts[2])
                    self.link_bw[(u, v)] = bw
                    self.link_bw[(v, u)] = bw
                    # port 用鄰居 dpid 當 dummy 值（路由模組只檢查 None / 非 None）
                    self.adjacency[u][v] = v
                    self.adjacency[v][u] = u
                    for sw in (u, v):
                        if sw not in self.myswitches:
                            self.myswitches.append(sw)
        except FileNotFoundError:
            print(f"[Sim] 找不到 {filepath}")

    def _load_switch_energy(self, filepath):
        """格式：dpid  type  energy_W"""
        data = {}
        try:
            with open(filepath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    data[int(parts[0])] = float(parts[2])
        except FileNotFoundError:
            print(f"[Sim] 找不到 {filepath}，能耗計算將為 0")
        return data

    def _load_link_txt(self, filepath):
        """格式：src  dst  value（雙向）"""
        data = {}
        try:
            with open(filepath, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    u, v, val = int(parts[0]), int(parts[1]), float(parts[2])
                    data[(u, v)] = val
                    data[(v, u)] = val
        except FileNotFoundError:
            print(f"[Sim] 找不到 {filepath}，能耗計算將為 0")
        return data

    def register_host(self, mac, dpid, port=1):
        """dijkstra 模組需要的 host→switch 對應，手動註冊"""
        self.host_macs[mac] = (dpid, port)

    # ── Active Flow 管理（與 DTM.py 介面一致）────────────────────

    def add_active_flow(self, host_a, host_b, path, is_reroute=False, priority=None):
        self.active_flows[(host_a, host_b)] = {
            'path': path,
            'install_time': time.time()
        }
        if not is_reroute:
            self.flow_history_count += 1
            self.flow_history_hops  += len(path) - 1
        self.flow_stats.assign(host_a, host_b, path)
        print(f"[ActiveFlow] 新增: {host_a} -> {host_b}, 路徑: {path}")
        if self._realtime_load:
            self._recompute_link_load()

    def remove_active_flow(self, host_a, host_b, path=None, hard_timeout=None):
        if (host_a, host_b) not in self.active_flows:
            return
        del self.active_flows[(host_a, host_b)]
        self.flow_stats.unassign(host_a, host_b)
        print(f"[ActiveFlow] 移除: {host_a} -> {host_b}")
        if self._realtime_load:
            self._recompute_link_load()

    def get_active_flows(self):
        """回傳 [(src, dst, path), ...]，供 cascade 迭代使用"""
        return [(a, b, e['path']) for (a, b), e in self.active_flows.items()]

    def get_history_avg_hops(self):
        if self.flow_history_count == 0:
            return 0.0
        return self.flow_history_hops / self.flow_history_count

    # ── cascade 需要的三個 DTM.py stub ──────────────────────────

    def build_path_with_ports(self, switch_path, src_mac, dst_mac):
        """
        真實版本查 adjacency port 資訊，回傳 [(dpid, in_port, out_port), ...]。
        模擬器不需要 port，只要回傳非 None（cascade 只檢查 None/非 None）。
        """
        return switch_path

    def _get_next_flow_priority(self, src_mac, dst_mac):
        """模擬器不裝 flow rule，priority 無意義，回傳固定值。"""
        return 1

    def install_flows_for_path(self, path, src_mac, dst_mac, priority=1,
                               hard_timeout=0, idle_timeout=0):
        """模擬器不需要下發 OpenFlow rule，no-op。"""
        pass

    # ── Link Load 計算 ───────────────────────────────────────────

    def _recompute_link_load(self):
        """
        從 active_flows × flow_sizes × 路徑，算出每條 link 的使用率，
        直接更新 link_status（取代 bandwidth_measurement 的角色）。
        """
        load = defaultdict(float)

        for (src, dst), entry in self.active_flows.items():
            size = self._flow_sizes.get((src, dst), 0.0)
            path = entry['path']
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                load[(u, v)] += size
                load[(v, u)] += size

        for (u, v), bw in self.link_bw.items():
            usage = (load.get((u, v), 0.0) / bw * 100.0) if bw > 0 else 0.0
            self.link_status.update_link_status(u, v, usage)

    # ── 能耗計算（與 DTM.py 的 calculate_energy_saving_from_flows 相同）──

    def calculate_energy_saving(self):
        """
        從 active_flows 推導出使用中的 switch 與 link，
        計算目前節省的能耗（W）與百分比。
        """
        active_switches = set()
        active_links    = set()
        for _, _, path in self.get_active_flows():
            for dpid in path:
                active_switches.add(dpid)
            for i in range(len(path) - 1):
                active_links.add((path[i], path[i + 1]))

        # initial_link_energy 裡每條實體連線存了 (u,v) 跟 (v,u) 兩筆（方便雙向查詢），
        # 加總前要先去重成唯一的無向連線 (min(u,v), max(u,v))，否則每條連線的能耗會被算兩次。
        unique_links = {(min(u, v), max(u, v)) for (u, v) in self.initial_link_energy}
        total_energy = (
            sum(self.initial_switch_energy.values()) +
            sum(self.initial_link_energy[link] for link in unique_links)
        )
        if total_energy == 0:
            return 0.0, 0.0

        used_sw = sum(self.initial_switch_energy.get(n, 0) for n in active_switches)
        unique_active_links = {(min(u, v), max(u, v)) for (u, v) in active_links}
        used_link = sum(self.initial_link_energy.get(link, 0)
                        for link in unique_active_links)
        current  = used_sw + used_link
        saving   = total_energy - current
        percent  = saving / total_energy * 100
        return saving, percent


# ─────────────────────────────────────────────────────────────────
# Simulator：事件驅動介面
# ─────────────────────────────────────────────────────────────────

class Simulator:

    def __init__(self, algorithm=ROUTING_ALGORITHM, log_path=EXPERIMENT_LOG,
                 link_load_update=LINK_LOAD_UPDATE,
                 link_load_interval=LINK_LOAD_INTERVAL,
                 trace_mode=TRACE_MODE):
        self.app      = MockApp()
        self.routing  = self._load_routing(algorithm)
        self.log_path = log_path
        self._sim_time = 0.0   # 目前模擬時間（秒）

        # 對應 DTM.py：'2020'/'dijkstra' 才跑 _monitor_DTM（LINK 觸發重路由）
        # 'self'/'sorted' 只跑 _monitor_energy（純計算，不重路由）
        self._enable_link_monitor = algorithm in ('2020', 'dijkstra')

        # Link load 更新模式
        self._link_load_update   = link_load_update    # 'realtime' | 'periodic'
        self._link_load_interval = max(1, int(link_load_interval))
        self.app._realtime_load  = (link_load_update == 'realtime')
        self._snap_logger: '_SnapLogger | None' = None   # 由外部設定，None 表示不記錄

        self.set_trace_mode(trace_mode)

    def set_trace_mode(self, enabled: bool):
        """開啟或關閉逐步追蹤模式。可在執行中隨時切換。"""
        if hasattr(self.routing, '_step_cb'):
            self.routing._step_cb = self._on_trace if enabled else None

    def _on_trace(self, event: str, fa, fb, data: dict):
        """
        trace callback：由路由模組在每個演算步驟呼叫。
        組出與 _snap 相同基底格式的快照，額外帶入 trace 專屬欄位。
        """
        import json
        if self._snap_logger is None:
            return

        active = [[mac_to_host(a), mac_to_host(b), entry['path']]
                  for (a, b), entry in self.app.active_flows.items()]

        ns = []
        if hasattr(self.routing, '非最短hop清單'):
            for (a, b), val in self.routing.非最短hop清單.items():
                hop = val[0] if isinstance(val, (tuple, list)) else val
                ns.append([mac_to_host(a), mac_to_host(b), hop])

        links = {}
        for (u, v), info in self.app.link_status.get_all_link_status().items():
            key = f"{min(u,v)},{max(u,v)}"
            links[key] = {
                's': info.get('status', 'SN'),
                'p': round(info.get('usage_percent', 0.0), 1),
            }

        wmap = {str(k): v for k, v in
                getattr(self.routing, 'weight_map', {}).items()}

        _, energy_pct = self.app.calculate_energy_saving()

        # 轉換 data 中含 MAC 的欄位
        converted = dict(data)
        if 'current' in converted:
            converted['current'] = [mac_to_host(x) for x in converted['current']]
        if 'order' in converted:
            converted['order'] = [[mac_to_host(a), mac_to_host(b), hop]
                                   for a, b, hop in converted['order']]

        snap = {
            'event':      event,
            'src':        mac_to_host(fa),
            'dst':        mac_to_host(fb),
            't':          round(self._sim_time, 1),
            'active':     active,
            'ns':         ns,
            'links':      links,
            'wmap':       wmap,
            'energy_pct': round(energy_pct, 1),
        }
        snap.update(converted)
        self._snap_logger.write_snap(json.dumps(snap, ensure_ascii=False))

    def _load_routing(self, algorithm):
        if algorithm == 'self':
            from modules.routing_DTM_self import Routing_DTM_Self
            return Routing_DTM_Self(self.app)
        elif algorithm == '2020':
            from modules.routing_DTM_2020 import Routing_DTM_2020
            return Routing_DTM_2020(self.app)
        elif algorithm == 'dijkstra':
            from modules.routing_DTM_dijkstra import Routing_DTM_Dijkstra
            return Routing_DTM_Dijkstra(self.app)
        elif algorithm == 'sorted':
            from modules.routing_DTM_sorted import Routing_DTM_Sorted
            return Routing_DTM_Sorted(self.app)
        elif algorithm == 'sorted_link':
            from modules.routing_DTM_sorted_link import Routing_DTM_Sorted_Link
            return Routing_DTM_Sorted_Link(self.app)
        else:
            raise ValueError(f"未知演算法: {algorithm}")

    # ── 日誌輸出 ─────────────────────────────────────────────────

    def _log(self, line: str):
        """追加一行到 experiment.log"""
        with open(self.log_path, 'a') as f:
            f.write(line + '\n')

    def _log_energy(self):
        """計算並寫入一筆 ENERGY 行"""
        saving, percent = self.app.calculate_energy_saving()
        line = f"{_now_str()} ENERGY saving={saving:.2f}W percent={percent:.1f}%"
        self._log(line)

    def _log_energy_second(self, t):
        """每模擬秒觸發：依模式決定是否重算 link load，然後記錄能耗。"""
        if self._link_load_update == 'periodic' and t % self._link_load_interval == 0:
            self.app._recompute_link_load()
        saving, percent = self.app.calculate_energy_saving()
        line = f"{_now_str()} ENERGY saving={saving:.2f}W percent={percent:.1f}%"
        self._log(line)
        print(f"[t={t:>4}s]  saving={saving:.2f}W  ({percent:.1f}%)")

    def _log_history(self):
        """寫入一筆 HISTORY 行（批次結尾呼叫）"""
        avg_hops = self.app.get_history_avg_hops()
        shortest_ratio = (
            self.routing.get_shortest_ratio()
            if hasattr(self.routing, 'get_shortest_ratio') else 0.0
        )
        line = (
            f"{_now_str()} HISTORY"
            f" avg_hops={avg_hops:.4f}"
            f" total_flows={self.app.flow_history_count}"
            f" reroute_link={self.app.reroute_count_link}"
            f" reroute_high_hop={self.app.reroute_count_high_hop}"
            f" reroute_low_share={self.app.reroute_count_low_share}"
            f" reroute_high_load={self.app.reroute_count_high_load}"
            f" shortest_ratio={shortest_ratio:.4f}"
        )
        self._log(line)

    # ── 動畫快照 ────────────────────────────────────────────────

    def _snap(self, event: str, src, dst, path=None):
        """
        寫入一幀 JSON 快照到 snap 檔（animate_sim.py 動畫來源）。
        src/dst 可為 'h1' 格式或 MAC 位址。
        """
        import json
        if self._snap_logger is None:
            return

        def _to_host(x):
            if x is None:
                return None
            if isinstance(x, str) and x.startswith('h'):
                return x
            try:
                return mac_to_host(x)
            except Exception:
                return str(x)

        active = [[mac_to_host(a), mac_to_host(b), entry['path']]
                  for (a, b), entry in self.app.active_flows.items()]

        ns = []
        if hasattr(self.routing, '非最短hop清單'):
            for (a, b), val in self.routing.非最短hop清單.items():
                hop = val[0] if isinstance(val, (tuple, list)) else val
                ns.append([mac_to_host(a), mac_to_host(b), hop])

        links = {}
        for (u, v), info in self.app.link_status.get_all_link_status().items():
            key = f"{min(u,v)},{max(u,v)}"
            links[key] = {
                's': info.get('status', 'SN'),
                'p': round(info.get('usage_percent', 0.0), 1),
            }

        _, energy_pct = self.app.calculate_energy_saving()

        snap = {
            'event':      event,
            'src':        _to_host(src),
            'dst':        _to_host(dst),
            'path':       path,
            't':          round(self._sim_time, 1),
            'active':     active,
            'ns':         ns,
            'links':      links,
            'energy_pct': round(energy_pct, 1),
        }
        self._snap_logger.write_snap(json.dumps(snap, ensure_ascii=False))

    # ── 路由後狀態顯示 ──────────────────────────────────────────

    def _print_routing_status(self):
        """每次 admit / depart 後顯示：已開啟的 switch 與 link 狀態"""
        # ── Switch 狀態 ───────────────────────────────────────────
        active_sw = set()
        for _, _, path in self.app.get_active_flows():
            active_sw.update(path)
        all_sw   = set(self.app.myswitches)
        sleeping = sorted(all_sw - active_sw)
        active   = sorted(active_sw)
        total    = len(all_sw)
        print(f"[Sim] Switch  active={len(active)}/{total}  "
              f"sleeping={len(sleeping)}  → {active}")
        if sleeping:
            print(f"[Sim]         sleeping → {sleeping}")

        # ── Link 狀態 ─────────────────────────────────────────────
        counts = self.app.link_status.count_links_by_status()
        sn = counts.get('SN', 0)
        low = counts.get('LOW', 0)
        norm = counts.get('NORMAL', 0)
        high = counts.get('HIGH', 0)
        over = counts.get('OVERLOAD', 0)
        dang = counts.get('DANGER', 0)
        print(f"[Sim] Links   SN={sn}  LOW={low}  NORMAL={norm}  "
              f"HIGH={high}  OVERLOAD={over}  DANGER={dang}")
        # 非 SN link 的詳細資訊（按使用率降序）
        all_link_st = self.app.link_status.get_all_link_status()
        non_sn = sorted(
            [(u, v, info) for (u, v), info in all_link_st.items()
             if info['status'] != 'SN' and u < v],
            key=lambda x: x[2]['usage_percent'], reverse=True
        )
        for u, v, info in non_sn:
            print(f"[Sim]         ({u:>2},{v:>2})  "
                  f"{info['status']:>8}  {info['usage_percent']:.1f}%")

    # ── 流量事件 ─────────────────────────────────────────────────

    def admit(self, src, dst, size_mbps, sim_t=None):
        """
        新增一條流量。
        src/dst 接受主機名稱（'h5'）或 MAC（'00:00:00:00:00:05'）。
        sim_t: 模擬時間（秒），由主迴圈傳入；未傳則沿用 _sim_time。
        """
        if sim_t is not None:
            self._sim_time = sim_t
        mac_src = host_to_mac(src) if src.startswith('h') else src
        mac_dst = host_to_mac(dst) if dst.startswith('h') else dst
        print(f"\n[t={self._sim_time:>6.1f}s] ▶ admit  {src} → {dst}  ({size_mbps} Mbps)")
        self.app._flow_sizes[(mac_src, mac_dst)] = size_mbps
        self._snap('trigger_admit', src, dst)
        path = self.routing.admit_flow(mac_src, mac_dst)
        if hasattr(self.routing, 'refresh_link_cache'):
            self.routing.refresh_link_cache()
        if self._enable_link_monitor:
            self._run_monitor()
        self._print_routing_status()
        self._snap('admit', src, dst, path)
        return path

    def depart(self, src, dst, sim_t=None):
        """
        結束一條流量。
        順序與 DTM.py flow_removed_handler 相同：
          1. remove_active_flow（清資料）
          2. on_flow_removed（觸發 cascade / 權重更新）
        sim_t: 模擬時間（秒），由主迴圈傳入；未傳則沿用 _sim_time。
        """
        if sim_t is not None:
            self._sim_time = sim_t
        mac_src = host_to_mac(src) if src.startswith('h') else src
        mac_dst = host_to_mac(dst) if dst.startswith('h') else dst
        print(f"\n[t={self._sim_time:>6.1f}s] ■ depart  {src} → {dst}")
        entry = self.app.active_flows.get((mac_src, mac_dst))
        if entry is None:
            print(f"[Sim]   找不到 active flow: {src} -> {dst}")
            return
        removed_path = entry['path']
        self.app._flow_sizes.pop((mac_src, mac_dst), None)
        self.app.remove_active_flow(mac_src, mac_dst)
        self._snap('trigger_depart', src, dst, removed_path)
        if hasattr(self.routing, 'on_flow_removed'):
            self.routing.on_flow_removed(mac_src, mac_dst, removed_path)
        if hasattr(self.routing, 'refresh_link_cache'):
            self.routing.refresh_link_cache()
        if self._enable_link_monitor:
            self._run_monitor()
        self._print_routing_status()
        self._snap('depart', src, dst, removed_path)

    # ── Monitor（對應 DTM.py 的 _monitor_DTM）───────────────────

    def _run_monitor(self):
        """
        模擬 DTM.py 的 _monitor_DTM LINK 觸發。

        OVERLOAD / DANGER（壅塞）：
            迴圈直到沒有壅塞或所有 flow 都已評估過。
            每條 flow 最多被重路由一次（already_rerouted），避免無限迴圈。

        LOW（能源節省）：
            只跑一輪。LOW 路由是「模組計算結果」，完成後不應再觸發下一輪，
            否則 A→B（B 也 LOW）→ A→B 振盪。
            同一 flow 在一輪中只查詢一次（checked），減少 select_path side effect。
        """
        # ── Pass 1: OVERLOAD / DANGER ─────────────────────────────
        already_rerouted = set()   # 本次呼叫中已重路由的 flow，不再重路由
        while True:
            rebalanced = False
            all_status = self.app.link_status.get_all_link_status()
            for (dpid_a, dpid_b), info in all_status.items():
                if rebalanced:
                    break
                if info.get('status') not in ('OVERLOAD', 'DANGER'):
                    continue
                for host_a, host_b, path in self.app.get_active_flows():
                    if (host_a, host_b) in already_rerouted:
                        continue
                    has_link = any(
                        (min(path[i], path[i+1]), max(path[i], path[i+1]))
                        == (min(dpid_a, dpid_b), max(dpid_a, dpid_b))
                        for i in range(len(path) - 1)
                    )
                    if not has_link:
                        continue
                    new_path = self.routing.select_path(host_a, host_b)
                    already_rerouted.add((host_a, host_b))
                    if new_path is None or new_path == path:
                        continue
                    self._snap('reroute_rem', host_a, host_b, path)
                    self.app.remove_active_flow(host_a, host_b)
                    self.app.add_active_flow(host_a, host_b, new_path, is_reroute=True)
                    self.app.reroute_count_link += 1
                    print(f"[Reroute:OVERLOAD] {host_a}->{host_b}: {path} → {new_path}")
                    self._snap('reroute_add', host_a, host_b, new_path)
                    rebalanced = True
                    break
            if not rebalanced:
                break

        # ── Pass 2: LOW（只跑一輪）───────────────────────────────
        checked    = set()   # 本輪已評估過的 flow，避免重複呼叫 select_path
        all_status = self.app.link_status.get_all_link_status()
        for (dpid_a, dpid_b), info in all_status.items():
            if info.get('status') != 'LOW':
                continue
            for host_a, host_b, path in self.app.get_active_flows():
                if (host_a, host_b) in checked:
                    continue
                has_link = any(
                    (min(path[i], path[i+1]), max(path[i], path[i+1]))
                    == (min(dpid_a, dpid_b), max(dpid_a, dpid_b))
                    for i in range(len(path) - 1)
                )
                if not has_link:
                    continue
                new_path = self.routing.select_path(host_a, host_b)
                checked.add((host_a, host_b))
                if new_path is None or new_path == path:
                    continue
                self._snap('reroute_rem', host_a, host_b, path)
                self.app.remove_active_flow(host_a, host_b)
                self.app.add_active_flow(host_a, host_b, new_path, is_reroute=True)
                self.app.reroute_count_link += 1
                print(f"[Reroute:LOW] {host_a}->{host_b}: {path} → {new_path}")
                self._snap('reroute_add', host_a, host_b, new_path)
                break   # 繼續下一條 link

        if hasattr(self.routing, 'refresh_link_cache'):
            self.routing.refresh_link_cache()

    def status(self):
        """顯示目前 active flows 與非 SN 的 link 狀態"""
        counts = self.app.link_status.count_links_by_status()
        flows  = self.app.get_active_flows()
        print(f"\n[Sim] ── Status ──────────────────────────────────────────")
        print(f"  Active flows : {len(flows)}")
        print(f"  Link counts  : {counts}")
        non_sn = {
            (u, v): info
            for (u, v), info in self.app.link_status.get_all_link_status().items()
            if info['status'] != 'SN' and u < v
        }
        if non_sn:
            print("  Non-SN links :")
            for (u, v), info in sorted(non_sn.items()):
                print(f"    ({u:>2},{v:>2})  {info['status']:>8}  {info['usage_percent']:.1f}%")
        else:
            print("  (all links SN)")
        for a, b, path in sorted(flows):
            sz = self.app._flow_sizes.get((a, b), 0.0)
            print(f"  flow {a}→{b}  {sz} Mbps  path={path}")
        print(f"[Sim] ────────────────────────────────────────────────────")


# ─────────────────────────────────────────────────────────────────
# Seed 檔讀取：把 interval-based 事件展開成 (admit, depart) 序列
# ─────────────────────────────────────────────────────────────────

def load_seed_events(batch, flow_duration):
    """
    將 seed 檔的單一 batch 展開成排好序的事件列表。

    每條 flow 產生兩個事件：
        (interval,                  'admit',  src, dst, bw_mbps)
        (interval + flow_duration,  'depart', src, dst, None   )

    注意：同一 (src, dst) 在上一條還沒 depart 前又 admit，後者會覆蓋
    active_flows 中的路徑紀錄（與 DTM.py 的 key 設計相同）。
    """
    events = []
    for flow in batch['flows']:
        t   = flow['interval']
        src = flow['src']
        dst = flow['dst']
        bw  = flow['bw_mbps']
        events.append((t,                 'admit',  src, dst, bw))
        events.append((t + flow_duration, 'depart', src, dst, None))
    events.sort(key=lambda e: e[0])
    return events


# ─────────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import json, argparse, os

    parser = argparse.ArgumentParser(description='路由模擬器')
    parser.add_argument('--seed',      type=str, default=None,
                        help='種子檔路徑，例如 seed_1.json')
    parser.add_argument('--batch',     type=int, default=None,
                        help='指定 batch_id（不指定則跑全部）')
    parser.add_argument('--algorithm', type=str, default=ROUTING_ALGORITHM,
                        choices=['self', '2020', 'dijkstra', 'sorted', 'sorted_link'],
                        help='路由演算法（預設依檔案頂部設定）')
    parser.add_argument('--topo',      type=str, default=None,
                        choices=list(_TOPO_FILES.keys()),
                        help='拓撲（預設依檔案頂部 TOPO 設定）')
    parser.add_argument('--log',         type=str, default=EXPERIMENT_LOG,
                        help=f'experiment log 路徑（預設 {EXPERIMENT_LOG}）')
    parser.add_argument('--link-update', type=str, default=None,
                        help='link load 更新模式：realtime 或整數秒數（例如 1、5）'
                             '（預設依檔案頂部 LINK_LOAD_UPDATE / LINK_LOAD_INTERVAL）')
    parser.add_argument('--trace', action='store_true', default=False,
                        help='開啟逐步追蹤模式（每條 flow 產生 4 幀快照）')
    args = parser.parse_args()

    # 解析 --link-update
    _ll_update   = LINK_LOAD_UPDATE
    _ll_interval = LINK_LOAD_INTERVAL
    if args.link_update is not None:
        if args.link_update.lower() == 'realtime':
            _ll_update = 'realtime'
        else:
            _ll_update   = 'periodic'
            _ll_interval = int(args.link_update)

    # CLI --topo 覆蓋檔案頂部設定
    if args.topo:
        TOPO = args.topo

    # ── 本次執行的資料夾：log/sim-{topo}-{seed}-{algorithm}-{timestamp}/ ──
    _timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    _seed_stem = (
        os.path.splitext(os.path.basename(args.seed))[0]   # 'seed_1.json' → 'seed_1'
        if args.seed else 'noseed'
    )
    _run_dir = f"log/sim-{TOPO}-{_seed_stem}-{args.algorithm}-{_timestamp}"
    os.makedirs(_run_dir, exist_ok=True)
    _run_log_path = f"{_run_dir}/run.log"
    _tee = _Tee(_run_log_path)
    sys.stdout = _tee
    _lu_label = 'realtime' if _ll_update == 'realtime' else f'periodic/{_ll_interval}s'
    print(f"[Sim] topo={TOPO}  seed={_seed_stem}  algorithm={args.algorithm}"
          f"  link-update={_lu_label}")
    print(f"[Sim] run log  → {_run_log_path}")
    print(f"[Sim] exp log  → {args.log}")

    if args.seed:
        with open(args.seed) as f:
            seed_data = json.load(f)

        flow_duration = seed_data.get('flow_duration', 40)
        batches       = seed_data['batches']

        for batch in batches:
            bid = batch['batch_id']
            if args.batch is not None and bid != args.batch:
                continue

            print(f"\n{'='*60}")
            print(f"  BATCH {bid}  (topo={TOPO}  algorithm={args.algorithm})")
            print(f"{'='*60}")

            sim = Simulator(algorithm=args.algorithm, log_path=args.log,
                            link_load_update=_ll_update,
                            link_load_interval=_ll_interval,
                            trace_mode=(TRACE_MODE or args.trace))

            # snap logger（動畫來源）
            _snap_path = f"{_run_dir}/b{bid}-snap.txt"
            _snap_logger = _SnapLogger(_snap_path)
            sim._snap_logger = _snap_logger

            sim._log(f"=== BATCH {bid} START ===")

            events      = load_seed_events(batch, flow_duration)
            exp_dur     = seed_data.get('experiment_duration', 150)
            event_idx   = 0
            n_events    = len(events)

            # 逐秒推進：每整數秒記一次能耗，事件在其確切時間點插入
            for sec in range(0, exp_dur + 1):
                # 處理所有落在 (上一秒, 本秒] 區間內的事件
                while event_idx < n_events and events[event_idx][0] <= sec:
                    sim_t, kind, src_h, dst_h, bw = events[event_idx]
                    if kind == 'admit':
                        sim.admit(src_h, dst_h, bw, sim_t=sim_t)
                    else:
                        sim.depart(src_h, dst_h, sim_t=sim_t)
                    event_idx += 1
                # 整數秒能耗快照
                sim._log_energy_second(sec)

            sim._log_history()
            sim._log(f"=== BATCH {bid} END ===")
            _snap_logger.close()

            # 背景產出動畫（不阻塞 terminal）
            _anim_path = f"{_run_dir}/b{bid}-anim.html"
            import subprocess as _sp
            _sp.Popen([sys.executable, 'animate_sim.py', _snap_path,
                       '--topo', TOPO, '--save', _anim_path],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            print(f"[Sim] 動畫產出中（背景）→ {_anim_path}")

            print(f"\n[Sim] Batch {bid} 結束")
            sim.status()

    else:
        # seed 未指定：跑個簡單範例（3 條流，30 秒）
        sim = Simulator(algorithm=args.algorithm, log_path=args.log,
                        link_load_update=_ll_update,
                        link_load_interval=_ll_interval,
                        trace_mode=(TRACE_MODE or args.trace))
        _snap_path = f"{_run_dir}/b0-snap.txt"
        _snap_logger = _SnapLogger(_snap_path)
        sim._snap_logger = _snap_logger

        sim._log("=== BATCH 0 START ===")
        # 手動事件序列：(sim_t, kind, src, dst, bw)
        demo_events = [
            (0,  'admit',  'h1', 'h16', 100),
            (2,  'admit',  'h2', 'h15',  80),
            (5,  'admit',  'h3', 'h14',  60),
            (15, 'depart', 'h1', 'h16', None),
            (20, 'depart', 'h2', 'h15', None),
            (25, 'depart', 'h3', 'h14', None),
        ]
        event_idx = 0
        n_events  = len(demo_events)
        for sec in range(0, 31):
            while event_idx < n_events and demo_events[event_idx][0] <= sec:
                sim_t, kind, src_h, dst_h, bw = demo_events[event_idx]
                if kind == 'admit':
                    sim.admit(src_h, dst_h, bw, sim_t=sim_t)
                else:
                    sim.depart(src_h, dst_h, sim_t=sim_t)
                event_idx += 1
            sim._log_energy_second(sec)
        sim._log_history()
        sim._log("=== BATCH 0 END ===")
        _snap_logger.close()

        # 背景產出動畫
        _anim_path = f"{_run_dir}/b0-anim.html"
        import subprocess as _sp
        _sp.Popen([sys.executable, 'animate_sim.py', _snap_path,
                   '--topo', TOPO, '--save', _anim_path],
                  stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        print(f"[Sim] 動畫產出中（背景）→ {_anim_path}")

    _tee.close()
