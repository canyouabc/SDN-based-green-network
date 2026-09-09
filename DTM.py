# -*- coding: utf-8 -*-
from ryu.base import app_manager
from ryu.controller import mac_to_port
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp
from ryu.lib.packet import lldp
from ryu.lib.packet import ipv4
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.lib.packet import icmp
from ryu.base.app_manager import lookup_service_brick
from ryu.lib import mac
from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link, get_host
from ryu.app.wsgi import ControllerBase
from collections import defaultdict
from ryu.lib import hub
from operator import attrgetter
import os
import time
import logging


# ==================== Logger ======================
energy_logger = logging.getLogger("energy")
energy_logger.setLevel(logging.INFO)
energy_logger.propagate = False  # 加這行，不往 root logger 傳

_fh = logging.FileHandler("experiment.log", mode="a")
_fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                    datefmt="%Y-%m-%d %H:%M:%S"))
energy_logger.addHandler(_fh)

import os as _os
_os.makedirs("log", exist_ok=True)
_bw_logger = logging.getLogger("bw")
_bw_logger.setLevel(logging.INFO)
_bw_logger.propagate = False
_bw_fh = logging.FileHandler("log/bw.log", mode="w")
_bw_fh.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                       datefmt="%H:%M:%S"))
_bw_logger.addHandler(_bw_fh)
# ==================== Feature Flags ======================
ENABLE_DELAY_DETECTION = False
ENABLE_ROUTING = True
ENABLE_BANDWIDTH_MEASUREMENT = True
# =========================================================

# ==================== 路由演算法選擇 ====================
# 選項: '2014' (Routing_2014) 或 '2020' (Routing_DTM_2020)
# 選項: 'auto_k_short'
# 選項: 'dijkstra' (Routing_DTM_Dijkstra) — 同 2020 邏輯，不依賴 k_short.txt
# 選項: 'self' (Routing_DTM_Self) — 2020 延伸，加入 active flow 重疊度排序
# 選項: 'sorted' (Routing_DTM_Sorted) — 全 flow 依 hop 排序後逐一選路
ROUTING_ALGORITHM = 'sorted'
# ======================================================

# ==================== Reroute 觸發條件設定 ====================
ENABLE_REROUTE_HIGH_HOP  = False
REROUTE_TOP_N_HOP        = 3     # 取 hop 數最高的前 N 條
REROUTE_HOP_THRESHOLD    = None  # None=不設閾值；否則填最小觸發 hop 數（含）

ENABLE_REROUTE_LOW_SHARE  = False
REROUTE_TOP_N_SHARE       = 3     # 取自用比最高（ratio 最低）的前 N 條
REROUTE_SHARE_THRESHOLD   = None  # None=不設閾值；否則填最大 ratio 上限（含）

ENABLE_REROUTE_HIGH_LOAD  = False
REROUTE_TOP_N_LOAD        = 3     # 取路徑負載分數最高的前 N 條
REROUTE_LOAD_THRESHOLD    = None  # None=不設閾值；否則填最小觸發分數（含）
REROUTE_LOAD_WEIGHT = {        # 各 link 狀態的負載分數
    'SN':      0,
    'LOW':     0,
    'NORMAL':  1,
    'HIGH':    3,
    'OVERLOAD': -999,          # OVERLOAD 已由 LINK 觸發處理，此觸發不選
    'DANGER':   -999,          # DANGER 已由 LINK 觸發處理，此觸發不選
}
# ============================================================

# ==================== Flow Priority Counter ==================
FLOW_BASE_PRIORITY = 2      # 路由流量的基礎優先度
FLOW_PRIORITY_IDLE = 10.0   # 超過此秒數未觸發，計數重置（假設 idle_timeout=5 已清除舊流）
# ============================================================

# ==================== PacketIn 封包處理演算法開關 =========
# TCP/UDP/ICMP/IPv4/IPv6 封包的處理策略
# FLOOD 還沒有實做，請不要使用 FLOOD 選項
PACKET_ALGORITHM_TCP = 'DROP'       # 選項: FLOOD, DROP, LOG_ONLY, DYNAMIC_ROUTING
PACKET_ALGORITHM_UDP = 'DROP'       # 選項: FLOOD, DROP, LOG_ONLY, DYNAMIC_ROUTING
PACKET_ALGORITHM_ICMP = 'DROP'      # 選項: FLOOD, DROP, LOG_ONLY, DYNAMIC_ROUTING
PACKET_ALGORITHM_IPV4 = 'DROP'      # 選項: FLOOD, DROP, LOG_ONLY, DYNAMIC_ROUTING
PACKET_ALGORITHM_IPV6 = 'DROP'       # 選項: FLOOD, DROP, LOG_ONLY, DYNAMIC_ROUTING
# =========================================================

# ← 條件引入延遲計算與偵測模組
if ENABLE_DELAY_DETECTION:
    from modules.link_delay_measurement import Link_Delay_Measurement
    from modules.delay_detection import Delay_Detection

# ← 條件引入路由模組
if ENABLE_ROUTING:
    if ROUTING_ALGORITHM == '2014':
        from modules.routing_2014 import Routing_2014 as routing_module
        print("*** 使用 2014 路由演算法（Routing_2014）")
    elif ROUTING_ALGORITHM == '2020':
        from modules.routing_DTM_2020 import Routing_DTM_2020 as routing_module
        print("*** 使用 2020 路由演算法（Routing_DTM_2020）")
    elif ROUTING_ALGORITHM == 'auto_k_short':
        from modules.routing_auto_k_short import Auto_routing_k_short as routing_module
        print("*** 使用 Auto Yen's K-Shortest Paths 演算法")
    elif ROUTING_ALGORITHM == 'dijkstra':
        from modules.routing_DTM_dijkstra import Routing_DTM_Dijkstra as routing_module
        print("*** 使用 DTM-Dijkstra 演算法（即時狀態權重，不依賴 k_short.txt）")
    elif ROUTING_ALGORITHM == 'self':
        from modules.routing_DTM_self import Routing_DTM_Self as routing_module
        print("*** 使用 DTM-Self 演算法（2020 延伸，active flow 重疊度排序）")
    elif ROUTING_ALGORITHM == 'sorted':
        from modules.routing_DTM_sorted import Routing_DTM_Sorted as routing_module
        print("*** 使用 DTM-Sorted 演算法（全 flow 依 hop 排序後逐一選路）")
    else:
        print("*** ROUTING_ALGORITHM 變數設定錯誤，請檢查程式碼")

# ← 條件引入頻寬量測模組
if ENABLE_BANDWIDTH_MEASUREMENT:
    from modules.bandwidth_measurement import Bandwidth_Measurement
    from modules.link_status import Link_Status

from modules.flow_stats import FlowStats


   




class ProjectController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    def __init__(self, *args, **kwargs):
        super(ProjectController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.topology_api_app = self
        self.datapaths = {}
        self.arp_count = 1
        self.ipv4_count = 1
        self.ipv6_count = 1
        self.lldp_count = 1
        self.vlan_count = 1
        self.host_list =  {}
        self.link_delay = {}
        self.total_switch_lldp = 0
        self.total_switch_echo = 0
        self.temp_adjacency = {}
        self.temp_mymac = {}
        self.last_tcp_processing_time = {}  # {pair: timestamp}
        self.last_udp_processing_time = {}  # {pair: timestamp}
        self.host_macs = {} # { mac: (dpid, port_no)}
        self.dpid_to_mac = {}            # {dpid: mac}
        self._topo_ready_logged = False  # [TOPO_READY] 只發一次
        self._link_ready_logged = False  # [LINK_READY] 只發一次
        self._last_sw_count     = 0
        self._last_link_count   = 0
        self._flow_cookie_counter = 0
        self._flow_priority = {}     # {(src_mac, dst_mac): {'priority': int, 'last_time': float}}
        
        # ← TCP 節流属性
        self.tcp_pkt_counter = {}        # (src, dst) → 計數
        self.tcp_last_seen = {}          # (src, dst) → 最後一次看到的時間
        self.TCP_THROTTLE_N = 1000        # 每 N 次觸發一次
        self.TCP_RESET_IDLE = 1.0        # 閒置幾秒後重置計數器
        
        # ← UDP 節流属性
        self.udp_pkt_counter = {}        # (src, dst) → 計數
        self.udp_last_seen = {}          # (src, dst) → 最後一次看到的時間
        self.UDP_THROTTLE_N = 1000     # 每 N 次觸發一次
        self.UDP_RESET_IDLE = 5.0        # 閒置幾秒後重置計數器
        # ==================== 拓扑数据 ====================
        self.myswitches = []
        
        # ==================== 拓撲數據（續） ====================
        # adjacency map [sw1][sw2]->port from sw1 to sw2
        self.adjacency = defaultdict(lambda:defaultdict(lambda:None))
        # ==================== 能耗数据 ====================

        self.route_list = {}               
        self.switch_energy = self.load_switch_energy('data/switch_energy.txt')
        # link_energy 與 link_bw 的 key 是 (src_dpid, dst_dpid)，value 分別是能耗與帯寶
        # 因為相同格式，所以共用同一個載入函數 load_link_txt
        self.link_energy   = self.load_link_txt('data/link_energy.txt')
        self.link_bw       = self.load_link_txt('data/link_bw.txt')

        self.initial_switch_energy = dict(self.switch_energy)
        self.initial_link_energy   = dict(self.link_energy)
        
        self.link_used_bw = defaultdict(float)

        # ==================== Active Flow 管理 ====================
        # {(host_a, host_b): {'path': [dpid, ...], 'install_time': t}}
        self.active_flows = {}
        self.flow_history_count = 0   # 累計產生的流數（含 reroute）
        self.flow_history_hops  = 0   # 累計 hop 數
        self.reroute_count_link      = 0
        self.reroute_count_high_hop  = 0
        self.reroute_count_low_share = 0
        self.reroute_count_high_load = 0
        # =========================================================

        #===將 controller 的 args 傳給各模組===
        
        # 第一層：沒有依賴其他模組的，先建
        if ENABLE_DELAY_DETECTION:
            self.link_delay_measurement = Link_Delay_Measurement(self)
            self.delay_detection = Delay_Detection(self)
        else:
            self.link_delay_measurement = None
            self.delay_detection = None

        if ENABLE_BANDWIDTH_MEASUREMENT:
            self.bandwidth_measurement = Bandwidth_Measurement(self)
            self.link_status = Link_Status(self)
        else:
            self.bandwidth_measurement = None
            self.link_status = None

        self.flow_stats = FlowStats(self)

        if ENABLE_ROUTING:
            self.routing_module = routing_module(self)
        else:
            self.routing_module = None

        # 沒有層級關係的話，會造成無法正確初始化

 
        
        # ==================== 執行緒啟動 ====================
        # ← 條件啟動延遲偵測線程
        self.monitor_thread = hub.spawn(self._monitor)
        self.link_ready_thread = hub.spawn(self._link_ready_watcher)

        if ENABLE_DELAY_DETECTION:
            # 經過檢查，問題不在這
            self.measure_thread = hub.spawn(self._detector)
                    
        # ← 條件啟動動態路由線程
        if ENABLE_ROUTING:
            # 經過檢查，問題不在這
            self.dynamic_Dijkstra_test_thread = hub.spawn(self.dynamic_Dijkstra_test)
                    
        # ← 條件啟動頻寬監控線程（每秒1次）
        if ENABLE_BANDWIDTH_MEASUREMENT:
            # 經過檢查，問題不在這
            self.bandwidth_monitor_thread = hub.spawn(self._bandwidth_monitor)
        self.flow_stats_monitor_thread = hub.spawn(self._flow_stats_monitor)
        if ROUTING_ALGORITHM in ('2020', 'dijkstra'):
            self.dtm_monitor_thread = hub.spawn(self._monitor_DTM)
        if ROUTING_ALGORITHM in ('self', 'sorted'):
            self.energy_monitor_thread = hub.spawn(self._monitor_energy)
            

    # =========================================
    # Active Flow 管理
    # =========================================
    def add_active_flow(self, host_a, host_b, path, is_reroute=False, priority=None):
        self.active_flows[(host_a, host_b)] = {
            'path': path,
            'priority': priority,
            'install_time': time.time()
        }
        if not is_reroute:
            self.flow_history_count += 1
            self.flow_history_hops  += len(path) - 1
        self.flow_stats.assign(host_a, host_b, path)
        print(f"[ActiveFlow] 新增: {host_a} -> {host_b}, 路徑: {path}")

    def remove_active_flow(self, host_a, host_b, path=None, hard_timeout=None):
        entry = self.active_flows.get((host_a, host_b))
        if entry is None:
            return
        if hard_timeout is not None:
            if time.time() - entry['install_time'] < hard_timeout:
                print(f"[ActiveFlow] 忽略舊 Flow Removed 事件: {host_a} -> {host_b}")
                return
        del self.active_flows[(host_a, host_b)]
        self.flow_stats.unassign(host_a, host_b)
        print(f"[ActiveFlow] 移除: {host_a} -> {host_b}")

    def get_active_flows(self):
        return [(host_a, host_b, entry['path'])
                for (host_a, host_b), entry in self.active_flows.items()]

    def get_history_avg_hops(self):
        """啟動後累計的平均 hop 數（含 reroute）"""
        if self.flow_history_count == 0:
            return 0.0
        return self.flow_history_hops / self.flow_history_count

    def get_avg_hops(self):
        paths = [e['path'] for e in self.active_flows.values()]
        if not paths:
            return 0.0
        return sum(len(p) - 1 for p in paths) / len(paths)

    def get_switch_flow_count(self):
        """每個 switch 被幾條活躍流量通過"""
        count = {}
        for entry in self.active_flows.values():
            for dpid in entry['path']:
                count[dpid] = count.get(dpid, 0) + 1
        return count

    def _get_next_flow_priority(self, src_mac, dst_mac):
        """每次安裝新路徑就 +1，確保新規則優先度永遠高於舊規則，
        使 OFPFC_ADD 能立即生效而不被舊規則蓋過。
        舊規則靠 idle_timeout=5 自然過期，不主動刪除。

        ⚠️  暴力解：priority 只增不減，上限 65534 後循環回 FLOW_BASE_PRIORITY。
            若同一 pair 在短時間內大量重算（cascade 風暴），priority 會快速累積。
            根本解法應為追蹤並主動刪除舊規則，但目前以簡化實作為優先。
        """
        key = (src_mac, dst_mac)
        entry = self._flow_priority.get(key)

        if entry is None:
            new_priority = FLOW_BASE_PRIORITY
        else:
            new_priority = entry['priority'] + 1
            if new_priority > 65534:
                new_priority = FLOW_BASE_PRIORITY   # 循環，極少發生

        self._flow_priority[key] = {'priority': new_priority, 'last_time': time.time()}
        return new_priority

    def _do_reroute(self, host_a, host_b, path, reason=""):
        new_path = self.routing_module.select_path(host_a, host_b, retrans_path=path)
        if new_path is None or new_path == path:
            return False
        new_pwp = self.build_path_with_ports(new_path, host_a, host_b)
        if new_pwp is None:
            print(f"[Reroute:{reason}] 無法建立新路徑 port 資訊，跳過: {host_a} -> {host_b}")
            return False
        new_priority = self._get_next_flow_priority(host_a, host_b)
        self.install_flows_for_path(new_pwp, host_a, host_b, priority=new_priority, idle_timeout=5)
        # 舊路徑不主動刪，等 idle_timeout=5 自然過期
        self.remove_active_flow(host_a, host_b, path)
        self.add_active_flow(host_a, host_b, new_path, priority=new_priority)
        print(f"[Reroute:{reason}] {host_a}->{host_b}: {path} → {new_path}")
        if reason == "LINK":
            self.reroute_count_link += 1
        elif reason == "HIGH_HOP":
            self.reroute_count_high_hop += 1
        elif reason == "LOW_SHARE":
            self.reroute_count_low_share += 1
        elif reason == "HIGH_LOAD":
            self.reroute_count_high_load += 1
        return True

    def _get_high_hop_flows(self, top_n=1, threshold=None):
        flows = sorted(self.get_active_flows(), key=lambda x: len(x[2]) - 1, reverse=True)
        if threshold is not None:
            flows = [f for f in flows if len(f[2]) - 1 >= threshold]
        return flows[:top_n]

    def _get_low_share_flows(self, top_n=1, threshold=None):
        switch_count = self.get_switch_flow_count()
        def ratio(f):
            path = f[2]
            hops = len(path) - 1
            if hops == 0:
                return float('inf')
            return sum(switch_count.get(d, 0) for d in path) / hops
        flows = sorted(self.get_active_flows(), key=ratio)
        if threshold is not None:
            flows = [f for f in flows if ratio(f) <= threshold]
        return flows[:top_n]

    def _get_high_load_flows(self, top_n=1, threshold=None):
        all_link_status = self.link_status.get_all_link_status()
        scored = []
        for f in self.get_active_flows():
            path = f[2]
            score = 0
            skip = False
            for i in range(len(path) - 1):
                key = (min(path[i], path[i+1]), max(path[i], path[i+1]))
                status = all_link_status.get(key, {}).get('status', 'NORMAL')
                w = REROUTE_LOAD_WEIGHT.get(status, 1)
                if w == -999:
                    skip = True
                    break
                score += w
            if not skip:
                scored.append((score, f))
        scored.sort(key=lambda x: x[0], reverse=True)
        if threshold is not None:
            scored = [(s, f) for s, f in scored if s >= threshold]
        return [f for _, f in scored[:top_n]]

    def get_path_switch_load(self, host_a, host_b):
        """指定路徑上，每個 switch 的總流量通過數（來自所有活躍流）"""
        entry = self.active_flows.get((host_a, host_b))
        if entry is None:
            return None
        switch_count = self.get_switch_flow_count()
        return {dpid: switch_count.get(dpid, 0) for dpid in entry['path']}

    # =========================================
    # 讀取能耗與 BW 設定檔
    # =========================================
    def load_switch_energy(self, filepath='data/switch_energy.txt'):
        data = {}
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    dpid   = int(parts[0])
                    energy = int(parts[2])  
                    data[dpid] = energy
            print(f"*** Switch 能耗設定載入成功，共 {len(data)} 個 switch")
        except FileNotFoundError:
            print(f"*** 找不到 {filepath}")
        return data

    def load_link_txt(self, filepath):
        # filepath 應該是完整路徑，例如 'data/link_energy.txt'
        data = {}
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    src = int(parts[0])
                    dst = int(parts[1])
                    val = float(parts[2])
                    data[(src, dst)] = val
                    data[(dst, src)] = val   # ← 補上雙向
        except FileNotFoundError:
            print(f"[警告] 找不到 {filepath}")
        return data

    def calculate_energy_saving_from_flows(self):

        active_flows = self.get_active_flows()
        
        # 從 active_flows 推導出 active_switches 和 active_links
        active_switches = set()
        active_links = set()
        
        for host_a, host_b, path in active_flows:
            for dpid in path:
                active_switches.add(dpid)
            for i in range(len(path) - 1):
                active_links.add((path[i], path[i+1]))
        
        # 以下跟原本一樣
        # initial_link_energy 裡每條實體連線存了 (u,v) 跟 (v,u) 兩筆（方便雙向查詢），
        # 加總前要先去重成唯一的無向連線 (min(u,v), max(u,v))，否則每條連線的能耗會被算兩次。
        unique_links = {(min(u, v), max(u, v)) for (u, v) in self.initial_link_energy}
        total_energy = sum(self.initial_switch_energy.values()) + \
                    sum(self.initial_link_energy[link] for link in unique_links)

        used_sw_energy   = sum(self.initial_switch_energy.get(n, 0)
                            for n in active_switches)
        unique_active_links = {(min(u, v), max(u, v)) for (u, v) in active_links}
        used_link_energy = sum(self.initial_link_energy.get(link, 0)
                            for link in unique_active_links)
        current_energy   = used_sw_energy + used_link_energy

        saving  = total_energy - current_energy
        percent = saving / total_energy * 100

        print(f"===== 能耗統計 ===== 節省能耗：{saving:.2f} W ({percent:.1f}%)")
        energy_logger.info(f"ENERGY saving={saving:.2f}W percent={percent:.1f}%")
        
        return saving, percent     
	   
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not datapath.id in self.datapaths:
                #self.logger.debug('register datapath: %016x', datapath.id)
                print('register datapath:', datapath.id)
                self.datapaths[datapath.id] = datapath
                self._install_arp_to_controller(datapath)
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                #self.logger.debug('unregister datapath: %016x', datapath.id)
                print('unregister datapath:', datapath.id)
                del self.datapaths[datapath.id]
    def _install_arp_to_controller(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_ARP)
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 128)]  # ARP 最多 42 bytes，128 足夠
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath, priority=10,
            match=match, instructions=inst
        )
        datapath.send_msg(mod)

    def _monitor(self):
        hub.sleep(10)
        while True:
            self.update_host_mac_table()
            if os.path.exists("stats_request.flag"):
                avg_hops = self.get_history_avg_hops()
                shortest_ratio = (
                    self.routing_module.get_shortest_ratio()
                    if hasattr(self.routing_module, 'get_shortest_ratio') else 0.0
                )
                energy_logger.info(
                    f"HISTORY avg_hops={avg_hops:.4f} total_flows={self.flow_history_count} "
                    f"reroute_link={self.reroute_count_link} "
                    f"reroute_high_hop={self.reroute_count_high_hop} "
                    f"reroute_low_share={self.reroute_count_low_share} "
                    f"reroute_high_load={self.reroute_count_high_load} "
                    f"shortest_ratio={shortest_ratio:.4f}"
                )
                os.remove("stats_request.flag")
            hub.sleep(10)
            
    def _monitor_DTM(self):
        """定期偵測 link 狀態，每個週期只轉移一條流量"""
        hub.sleep(10) # 等待拓撲穩定
        while True:
            try:
                rebalanced = False

                # ① LINK 觸發：LOW / OVERLOAD
                all_link_status = self.link_status.get_all_link_status()
                for (dpid_a, dpid_b), link_info in all_link_status.items():
                    if rebalanced:
                        break
                    status = link_info.get('status', 'NORMAL')
                    if status not in ('LOW', 'OVERLOAD', 'DANGER'):
                        continue
                    for host_a, host_b, path in self.get_active_flows():
                        has_link = any(
                            (min(path[i], path[i+1]), max(path[i], path[i+1])) == (dpid_a, dpid_b)
                            for i in range(len(path) - 1)
                        )
                        if not has_link:
                            continue
                        if self._do_reroute(host_a, host_b, path, reason="LINK"):
                            rebalanced = True
                            break

                # ② HIGH_HOP 觸發
                if not rebalanced and ENABLE_REROUTE_HIGH_HOP:
                    for host_a, host_b, path in self._get_high_hop_flows(
                            REROUTE_TOP_N_HOP, REROUTE_HOP_THRESHOLD):
                        if self._do_reroute(host_a, host_b, path, reason="HIGH_HOP"):
                            rebalanced = True
                            break

                # ③ HIGH_LOAD 觸發
                if not rebalanced and ENABLE_REROUTE_HIGH_LOAD:
                    for host_a, host_b, path in self._get_high_load_flows(
                            REROUTE_TOP_N_LOAD, REROUTE_LOAD_THRESHOLD):
                        if self._do_reroute(host_a, host_b, path, reason="HIGH_LOAD"):
                            rebalanced = True
                            break

                # ④ LOW_SHARE 觸發
                if not rebalanced and ENABLE_REROUTE_LOW_SHARE:
                    for host_a, host_b, path in self._get_low_share_flows(
                            REROUTE_TOP_N_SHARE, REROUTE_SHARE_THRESHOLD):
                        if self._do_reroute(host_a, host_b, path, reason="LOW_SHARE"):
                            rebalanced = True
                            break

            except Exception as e:
                import traceback
                print(f"[monitor_DTM] 發生錯誤: {e}")
                traceback.print_exc()
            self.calculate_energy_saving_from_flows()
            hub.sleep(1)

    def _monitor_energy(self):
        """self 演算法專用：只負責定期輸出能耗統計"""
        hub.sleep(10)
        while True:
            self.calculate_energy_saving_from_flows()
            hub.sleep(1)

    def _flow_stats_monitor(self):
        """Flow stats 輪詢線程（每秒 1 次）
        只向有 assigned flow 的 switch 發送 OFPFlowStatsRequest。
        Reply 由 flow_stats_reply_handler 非同步接收。
        """
        hub.sleep(10)  # 等待拓撲穩定
        while True:
            self.flow_stats.request_assigned()
            hub.sleep(1)           # reply 在這段時間非同步抵達
            self.flow_stats.log_summary()

    def _bandwidth_monitor(self):
        """
        頻寬監控線程（每秒1次）
        定期檢查各 link 的頻寬使用率
        """
        hub.sleep(10) # 等待拓撲穩定
        
        # ← 過濾背景流量的閾值（Mbps）
        BW_THRESHOLD_MBPS = 0.1
        
        while True:
            try:
                # 發送 PortStats Request 到所有 switch
                for dp in self.datapaths.values():
                    self.bandwidth_measurement.send_port_stats_request(dp)
                
                # 等待回覆並計算（在 port_stats_reply_handler 中進行）
                # 這裡只需定期發送請求即可
                
                # 列印當前的頻寬使用率
                all_stats = self.bandwidth_measurement.get_all_bandwidth_usage()
                
                # ← 收集本輪的雙向流量（用於計算物理 link 的負載）
                physical_link_traffic = {}  # {(min_dpid, max_dpid): {'traffic_bps': bps, 'capacity_bps': capacity}}
                
                # 格式化輸出（顯示所有有流量的方向）
                for (dpid, port_no), stats in all_stats.items():
                    throughput_bps = stats.get('throughput_bps', 0)
                    throughput_mbps = throughput_bps / 1e6
                    
                    # ← 過濾背景流量，只顯示超過閾值的流量
                    if throughput_mbps < BW_THRESHOLD_MBPS:
                        continue
                    
                    # 尋找該埠連結的目標 switch
                    for neighbor, port in self.adjacency[dpid].items():
                        if port == port_no:
                            # 查詢該 link 的容量
                            capacity_bps = 0
                            link_key_bw = (dpid, neighbor)
                            if link_key_bw in self.link_bw:
                                capacity_bps = self.link_bw[link_key_bw] * 1e6  # 轉成 bps
                            else:
                                # ← 如果反向 link 存在
                                link_key_bw_rev = (neighbor, dpid)
                                if link_key_bw_rev in self.link_bw:
                                    capacity_bps = self.link_bw[link_key_bw_rev] * 1e6  # 轉成 bps
                            
                            if capacity_bps > 0:
                                throughput_gbps = throughput_bps / 1e9
                                capacity_gbps = capacity_bps / 1e9
                                usage_percent_single = (throughput_bps / capacity_bps) * 100
                                
                                # ← 列印所有方向的日誌（PortStats 統計的）
                                _bw_logger.info(f"[BW] Link {dpid} -> {neighbor}: {throughput_gbps:.3f} Gbps / {capacity_gbps:.3f} Gbps ({usage_percent_single:.1f}%)")
                                
                                # ← 累積到物理 link（用於雙向負載計算）
                                phy_link = (min(dpid, neighbor), max(dpid, neighbor))
                                if phy_link not in physical_link_traffic:
                                    physical_link_traffic[phy_link] = {
                                        'traffic_bps': 0,
                                        'capacity_bps': capacity_bps
                                    }
                                physical_link_traffic[phy_link]['traffic_bps'] += throughput_bps
                            
                            break
                
                # ← 根據雙向合併的流量來判斷物理 link 的狀態
                for (src_dpid, dst_dpid), link_info in physical_link_traffic.items():
                    total_usage_percent = (link_info['traffic_bps'] / link_info['capacity_bps']) * 100
                    self.link_status.update_link_status(src_dpid, dst_dpid, total_usage_percent)
                
                # ← 對於沒有流量的 link，重置為低負載 (0%)
                all_links_set = set()
                for dpid in self.adjacency:
                    for neighbor in self.adjacency[dpid]:
                        phy_link = (min(dpid, neighbor), max(dpid, neighbor))
                        all_links_set.add(phy_link)
                
                for phy_link in all_links_set:
                    if phy_link not in physical_link_traffic:
                        src_dpid, dst_dpid = phy_link
                        self.link_status.update_link_status(src_dpid, dst_dpid, 0)

                if ROUTING_ALGORITHM in ('self', 'sorted') and self.routing_module:
                    self.routing_module.refresh_link_cache()
                
                # ← 在每輪結束時，列印 link 狀態統計
                status_counts = self.link_status.count_links_by_status()
                print(f"SN: {status_counts['SN']}, LOW: {status_counts['LOW']}, NORMAL: {status_counts['NORMAL']}, HIGH: {status_counts['HIGH']}, OVERLOAD: {status_counts['OVERLOAD']}, DANGER: {status_counts['DANGER']}")
                
            except Exception as e:
                self.logger.error(f"Error in bandwidth monitor: {e}")
            
            # 每秒檢查一次
            hub.sleep(1)


    def _detector(self):
        """
        detector 是處理延遲偵測的執行緒
        定期掃描拓撲，將所有 link 對加入檢測隊列
        """
        hub.sleep(10)  # 等待拓撲穩定    
        while True:
            self.temp_adjacency = dict(self.adjacency)
            detection_queue = self.delay_detection.build_detection_queue(self.temp_adjacency)
            print(f"[DETECTOR] 開始測量，共 {len(detection_queue)} 對", flush=True)
            for switch_a, switch_b in detection_queue:
                self._switch_to_switch_delay_count(switch_a, switch_b)
                hub.sleep(0)  # ← 先加這個測試
            print(f"[DETECTOR] 測量完成", flush=True)
            hub.sleep(30)
    '''
    這段用來測試 Dijkstra 動態更新路徑的功能
    '''
    def dynamic_Dijkstra_test(self):
        
        # ← 等待 10 秒，確保拓撲和主機表完全建立
        hub.sleep(10)
        
        # ← 2014 版本是被動式（packet_in 觸發），不需要長期線程
        if ROUTING_ALGORITHM == '2014':
            print("*** 2014 被動式路由已啟用 - 路由計算將在 packet_in 事件時觸發")
            return
        
        if ROUTING_ALGORITHM == 'auto_k_short':
            print("*** k-shortest paths 計算模組已啟用 - 等待 sendarp 完成...")
            # 清掉可能殘留的舊旗標（例如上一輪實驗中途中斷），避免這次一啟動
            # 就誤判成「sendarp 已完成」而跳過等待
            if os.path.exists('arp_done.flag'):
                os.remove('arp_done.flag')
            # 先等 send_arp_all() 送完 ARP 後寫出的旗標檔，避免在使用者於 Mininet
            # CLI 真正打 sendarp 之前，host_macs 就因為背景流量短暫持平而誤判穩定
            while not os.path.exists('arp_done.flag'):
                hub.sleep(1)
            os.remove('arp_done.flag')
            print("*** 偵測到 sendarp 已完成，開始等待 host_macs 穩定...")
            # 輪詢 host_macs 數量直到穩定（連續 3 次不再增加）才開始算，
            # sendarp 送出後 packet-in 仍需時間陸續抵達 controller，這裡當作最後一道緩衝
            last_count = -1
            stable_ticks = 0
            while stable_ticks < 3:
                hub.sleep(2)
                cur_count = len(self.host_macs)
                if cur_count > 0 and cur_count == last_count:
                    stable_ticks += 1
                else:
                    stable_ticks = 0
                last_count = cur_count
            print(f"\n*** host_macs 已穩定（共 {last_count} 個 host），開始計算 K-Shortest Paths...")
            self.routing_module.compute_all_k_shortest_paths_once(
                k=16,
                output_filepath='data/k_short.txt',
                host_range=(1, 16)
            )
            return

        
            
    def _check_link_ready(self):
        """檢查 switch 和 link 數量是否穩定，穩定則發出 [LINK_READY]"""
        sw_count   = len(get_switch(self.topology_api_app, None))
        link_count = len(get_link(self.topology_api_app, None))
        if (sw_count > 0 and link_count > 0
                and sw_count   == self._last_sw_count
                and link_count == self._last_link_count
                and not self._link_ready_logged):
            self._link_ready_logged = True
            print(f"[LINK_READY] 共 {sw_count} 個 switch，{link_count} 條 link")
        self._last_sw_count   = sw_count
        self._last_link_count = link_count

    def _link_ready_watcher(self):
        """快速輪詢直到 [LINK_READY] 確認，之後結束"""
        hub.sleep(3)
        while not self._link_ready_logged:
            self._check_link_ready()
            hub.sleep(2)

    def update_host_mac_table(self):
        """从拓扑信息更新主机MAC表"""
        hosts = get_host(self.topology_api_app, None)
        new_added = 0

        for host in hosts:
            mac = host.mac
            dpid = host.port.dpid
            port_no = host.port.port_no

            if mac not in self.host_macs:
                self.host_macs[mac] = (dpid, port_no)
                self.dpid_to_mac[dpid] = mac
                print(f"Added host: {mac} at switch {dpid}, port {port_no}")
                new_added += 1

        # 這輪沒有新增 host，且已有資料 → 拓撲穩定，發一次 [TOPO_READY]
        if new_added == 0 and self.host_macs and not self._topo_ready_logged:
            self._topo_ready_logged = True
            print(f"[TOPO_READY] 所有 host 已學習完成，共 {len(self.host_macs)} 個")            

    def _switch_to_switch_delay_count(self, switch_a, switch_b):
        if not ENABLE_DELAY_DETECTION:
            return
            
        # ← 直接傳遞 delay_detection 的模組函式作為回調
        self.link_delay_measurement.measure_pair_delay(
            switch_a, switch_b,
            lambda sa, sb: self.delay_detection.send_lldp_for_delay_detection(sa, sb, self.temp_adjacency, self.datapaths),
            lambda s, ps: self.delay_detection.send_echo_for_delay_detection(s, ps, self.datapaths),
            hub.sleep
        )
    def build_path_with_ports(self, switch_path, src_mac, dst_mac):
        """將 switch_path (dpid序列) 轉換成帶有 port 資訊的 path"""
        path = []

        if len(switch_path) == 1:
            first_sw = switch_path[0]
            host_in_port = self.host_macs[src_mac][1]
            host_out_port = self.host_macs[dst_mac][1]
            path.append((first_sw, host_in_port, host_out_port))
        else:
            # 第一個 switch
            first_sw = switch_path[0]
            host_in_port = self.host_macs[src_mac][1]
            out_port = self.adjacency[first_sw][switch_path[1]]
            if out_port is None:
                return None
            path.append((first_sw, host_in_port, out_port))

            # 中間的 switch
            for i in range(1, len(switch_path) - 1):
                sw_dpid = switch_path[i]
                in_port = self.adjacency[sw_dpid][switch_path[i-1]]
                out_port = self.adjacency[sw_dpid][switch_path[i+1]]
                if in_port is None or out_port is None:
                    return None
                path.append((sw_dpid, in_port, out_port))

            # 最後一個 switch
            last_sw = switch_path[-1]
            in_port = self.adjacency[last_sw][switch_path[-2]]
            if in_port is None:
                return None
            host_out_port = self.host_macs[dst_mac][1]
            path.append((last_sw, in_port, host_out_port))

        return path
        
    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        if not ENABLE_DELAY_DETECTION:
            return
            
        datapath = ev.msg.datapath
        dpid = datapath.id
        
        # ← 使用 delay_detection module 處理 Echo Reply
        self.delay_detection.handle_echo_reply_event(dpid)

    def _request_stats(self, datapath):
        #self.logger.debug('send stats request: %016x', datapath.id)
        #print 'send stats request:', datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
    
    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_reply_handler(self, ev):
        """處理 FlowStats Reply，交給 flow_stats 模組解析"""
        self.flow_stats.handle_reply(ev)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        """處理 PortStats Reply（頻寬量測）"""
        if not ENABLE_BANDWIDTH_MEASUREMENT:
            return
        
        try:
            msg = ev.msg
            datapath = msg.datapath
            dpid = datapath.id
            port_stats = msg.body

            # ← 呼叫頻寬量測模組處理 PortStats Reply
            self.bandwidth_measurement.handle_port_stats_reply(dpid, port_stats, self.link_bw)
            
        except Exception as e:
            self.logger.error(f"Error handling PortStats Reply: {e}")
        
        
    # 主动安装流表，不依赖packet_in事件，但感覺可以寫得更彈性一些
    def install_flows_for_path(self, path, src_mac, dst_mac, priority, hard_timeout=0,idle_timeout=0):
        """主动安装流表，不依赖packet_in事件"""
        #print(f"Installing flows for path: {src_mac} -> {dst_mac}")
        
        for sw_dpid, in_port, out_port in path:
            if sw_dpid not in self.datapaths:
                print(f"Warning: Switch {sw_dpid} not found")
                continue
                
            datapath = self.datapaths[sw_dpid]
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            
            # 安装正向流表
            match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
            actions = [parser.OFPActionOutput(out_port)]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            
            mod = parser.OFPFlowMod(
                datapath=datapath,
                match=match,
                idle_timeout=idle_timeout,
                hard_timeout=hard_timeout,
                priority=priority,
                flags=ofproto.OFPFF_SEND_FLOW_REM,
                instructions=inst
            )
            datapath.send_msg(mod)
            
            # 安装反向流表
            
            match_rev = parser.OFPMatch(in_port=out_port, eth_src=dst_mac, eth_dst=src_mac)
            actions_rev = [parser.OFPActionOutput(in_port)]
            inst_rev = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_rev)]
            mod_rev = parser.OFPFlowMod(
                datapath=datapath, match=match_rev,
                idle_timeout=idle_timeout, hard_timeout=hard_timeout,
                priority=priority, flags=ofproto.OFPFF_SEND_FLOW_REM,
                instructions=inst_rev
            )
            datapath.send_msg(mod_rev)
    def remove_flows_for_path(self, path, src_mac, dst_mac, priority=FLOW_BASE_PRIORITY):
        """主動刪除流表。OFPFC_DELETE_STRICT 需指定 priority 才能精確比對。"""
        for sw_dpid, in_port, out_port in path:
            if sw_dpid not in self.datapaths:
                print(f"Warning: Switch {sw_dpid} not found")
                continue

            datapath = self.datapaths[sw_dpid]
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser

            # 刪除正向流表
            match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
            mod = parser.OFPFlowMod(
                datapath=datapath,
                match=match,
                priority=priority,
                command=ofproto.OFPFC_DELETE_STRICT,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
            )
            datapath.send_msg(mod)

            # 刪除反向流表
            match_rev = parser.OFPMatch(in_port=out_port, eth_src=dst_mac, eth_dst=src_mac)
            mod_rev = parser.OFPFlowMod(
                datapath=datapath,
                match=match_rev,
                priority=priority,
                command=ofproto.OFPFC_DELETE_STRICT,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
            )
            datapath.send_msg(mod_rev)

    def _handle_arp_request(self, datapath, in_port, arp_pkt):
        """Controller直接回應ARP請求"""
        self.host_list = get_host(self.topology_api_app, None)

        _pair = (arp_pkt.src_mac, arp_pkt.dst_mac)
        _count = getattr(self, 'pkt_in_pair_counter', {}).get(_pair, 0)
        if _count > 100:
            _known_ips = {ip: h.mac for h in self.host_list for ip in h.ipv4}
            print(f"[ARP DEBUG] src={arp_pkt.src_ip} dst={arp_pkt.dst_ip} "
                  f"pair_count={_count} get_host_ips={list(_known_ips.keys())}")

        for host in self.host_list:
            if arp_pkt.dst_ip in host.ipv4:
                self._send_arp_reply(
                    datapath, in_port,
                    host.mac, arp_pkt.dst_ip,
                    arp_pkt.src_mac, arp_pkt.src_ip
                )
                return
            
    def _send_arp_reply(self, datapath, in_port, src_mac, src_ip, dst_mac, dst_ip):
        """建立並發送ARP回應封包"""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # 建立封包
        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(
            dst=dst_mac,
            src=src_mac,
            ethertype=ether_types.ETH_TYPE_ARP
        ))
        pkt.add_protocol(arp.arp(
            opcode=arp.ARP_REPLY,
            src_mac=src_mac,
            src_ip=src_ip,
            dst_mac=dst_mac,
            dst_ip=dst_ip
        ))
        
        # 序列化並發送
        pkt.serialize()
        actions = [parser.OFPActionOutput(port=in_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=pkt.data
        )
        datapath.send_msg(out)

    # ============================================
    # 演算法處理方法
    # ============================================
    def _apply_packet_algorithm(self, algorithm, datapath, pkt, packet_type):
        """根據演算法類型執行相應的處理邏輯"""
        if algorithm == 'DROP':
            # 丟棄封包（不轉發）
            #print(f"[{packet_type}] DROP from {datapath.id}")
            pass
        
        elif algorithm == 'FLOOD':
            # 轉發到所有埠（flooding）
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            # pkt 在這裡是 Packet 物件，需要從 _packet_in_handler 傳遞 msg
            #print(f"[{packet_type}] FLOOD from {datapath.id}")
        
        elif algorithm == 'LOG_ONLY':
            # 只記錄，不轉發
            #print(f"[{packet_type}] LOG_ONLY from {datapath.id}")
            pass
        
        elif algorithm == 'DYNAMIC_ROUTING':
            # 使用動態路由（Dijkstra）
            #print(f"[{packet_type}] DYNAMIC_ROUTING from {datapath.id} (未實作)")
            # TODO: 在此實作動態路由邏輯
            pass
        
        else:
            #print(f"[{packet_type}] Unknown algorithm: {algorithm}")
            pass
    
    # ============================================
    # 未定義流量的 Hook 處理（可擴展設計）
    # ============================================
    def unknown_TCP_packet(self, datapath, pkt_data):
        eth = pkt_data.get_protocol(ethernet.ethernet)
        if not eth:
            return

        pair = (eth.src, eth.dst)
        now = time.time()

        # === 第二層：閒置超過 5 秒，重置計數器 ===
        if pair in self.tcp_last_seen:
            if now - self.tcp_last_seen[pair] > self.TCP_RESET_IDLE:
                self.tcp_pkt_counter[pair] = 0  # 重置，下一個封包會是第 0 次

        # 更新時間戳
        self.tcp_last_seen[pair] = now

        # === 第一層：每 N 次只處理一次 ===
        count = self.tcp_pkt_counter.get(pair, 0)
        self.tcp_pkt_counter[pair] = count + 1

        if count % self.TCP_THROTTLE_N != 0:
            return  # 不是第 0, 20, 40... 次，直接跳過

        # ★ 已有 active flow，不重複計算
        if pair in self.active_flows:
            return

        # === 以下才是真正的處理邏輯 ===
        self.logger.debug(f"[UNKNOWN_TCP] switch {datapath.id}, pair {pair}, count {count}")

        if ENABLE_ROUTING and ROUTING_ALGORITHM == '2014':
            try:
                parser = datapath.ofproto_parser

                match = parser.OFPMatch(eth_src=eth.src, eth_dst=eth.dst)
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=2,
                    idle_timeout=5,
                    hard_timeout=5,
                    match=match,
                    instructions=[]
                )
                datapath.send_msg(mod)

                self.routing_module.calculate_and_install_path(
                    src_mac=eth.src,
                    dst_mac=eth.dst,
                )
            except Exception as e:
                self.logger.error(f"[UNKNOWN_TCP] 路由計算失敗: {e}")
        elif ROUTING_ALGORITHM in ('2020', 'dijkstra', 'self', 'sorted'):
            # 2020 / dijkstra 版本的路由計算邏輯
            try:
                parser = datapath.ofproto_parser
                match = parser.OFPMatch(eth_src=eth.src, eth_dst=eth.dst)
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=1,        # 臨時 DROP，防止選路期間重複 PacketIn
                    idle_timeout=3,
                    hard_timeout=5,
                    match=match,
                    instructions=[]    # DROP
                )
                datapath.send_msg(mod)

                src_mac = eth.src
                dst_mac = eth.dst

                if src_mac not in self.host_macs or dst_mac not in self.host_macs:
                    return

                if src_mac and dst_mac:
                    switch_path = self.routing_module.admit_flow(src_mac, dst_mac)

                    if switch_path and len(switch_path) >= 1:
                        path = self.build_path_with_ports(switch_path, src_mac, dst_mac)

                        if path:
                            _prio = self._get_next_flow_priority(src_mac, dst_mac)
                            self.install_flows_for_path(path, src_mac, dst_mac, priority=_prio, idle_timeout=5)
                            if (src_mac, dst_mac) in self.active_flows:
                                self.active_flows[(src_mac, dst_mac)]['priority'] = _prio
                            _first_sw, _first_in, _first_out = path[0]
                            print(f"[{ROUTING_ALGORITHM} Routing TCP] {src_mac} -> {dst_mac}: path {switch_path} | sw={_first_sw} in_port={_first_in} out_port={_first_out} priority={_prio}")
                        else:
                            print(f"[{ROUTING_ALGORITHM} Routing TCP] 無法轉換路徑信息: {switch_path}")
                    else:
                        print(f"[{ROUTING_ALGORITHM} Routing TCP] 無法為 {src_mac} -> {dst_mac} 找到路徑")
                else:
                    print(f"[{ROUTING_ALGORITHM} Routing TCP] 無法轉換 MAC: {src_mac} -> {dst_mac}")

            except Exception as e:
                self.logger.error(f"[{ROUTING_ALGORITHM} Routing TCP] 路由計算失敗: {e}")
            
        else:
            self._apply_packet_algorithm(PACKET_ALGORITHM_TCP, datapath, pkt_data, 'TCP')

    def unknown_UDP_packet(self, datapath, pkt_data):
        eth = pkt_data.get_protocol(ethernet.ethernet)
        if not eth:
            return

        pair = (eth.src, eth.dst)
        now = time.time()

        # === 第二層：閒置超過 5 秒，重置計數器 ===
        if pair in self.udp_last_seen:
            if now - self.udp_last_seen[pair] > self.UDP_RESET_IDLE:
                self.udp_pkt_counter[pair] = 0  # 重置，下一個封包會是第 0 次

        # 更新時間戳
        self.udp_last_seen[pair] = now

        # === 第一層：每 N 次只處理一次 ===
        count = self.udp_pkt_counter.get(pair, 0)
        self.udp_pkt_counter[pair] = count + 1

        if count % self.UDP_THROTTLE_N != 0:
            if count <= 5 or count % 200 == 0:
                print(f"[UDP THROTTLE] pair={pair} count={count} N={self.UDP_THROTTLE_N}")
            return

        # ★ 已有 active flow，不重複計算
        if pair in self.active_flows:
            return

        # === 以下才是真正的處理邏輯 ===
        print(f"[UNKNOWN_UDP] switch {datapath.id}, pair {pair}, count {count}")
        self.logger.debug(f"[UNKNOWN_UDP] switch {datapath.id}, pair {pair}, count {count}")

        if ENABLE_ROUTING and ROUTING_ALGORITHM == '2014':
            try:
                parser = datapath.ofproto_parser

                match = parser.OFPMatch(eth_src=eth.src, eth_dst=eth.dst)
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=1,
                    idle_timeout=5,
                    hard_timeout=5,
                    match=match,
                    instructions=[]
                )
                datapath.send_msg(mod)

                self.routing_module.calculate_and_install_path(
                    src_mac=eth.src,
                    dst_mac=eth.dst,
                )
            except Exception as e:
                self.logger.error(f"[UNKNOWN_UDP] 路由計算失敗: {e}")
        elif ROUTING_ALGORITHM in ('2020', 'dijkstra', 'self', 'sorted'):
            # 2020 / dijkstra 版本的路由計算邏輯
            try:
                parser = datapath.ofproto_parser
                match = parser.OFPMatch(eth_src=eth.src, eth_dst=eth.dst)
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=1,        # 臨時 DROP，防止選路期間重複 PacketIn
                    idle_timeout=3,
                    hard_timeout=5,
                    match=match,
                    instructions=[]    # DROP
                )
                datapath.send_msg(mod)

                src_mac = eth.src
                dst_mac = eth.dst

                if src_mac not in self.host_macs or dst_mac not in self.host_macs:
                    return

                if src_mac and dst_mac:
                    # 呼叫 DTM 模組選擇路徑
                    switch_path = self.routing_module.admit_flow(src_mac, dst_mac)
                    
                    if switch_path and len(switch_path) >= 1:
                            path = self.build_path_with_ports(switch_path, src_mac, dst_mac)

                            if path:
                                _prio = self._get_next_flow_priority(src_mac, dst_mac)
                                self.install_flows_for_path(path, src_mac, dst_mac, priority=_prio, idle_timeout=5)
                                if (src_mac, dst_mac) in self.active_flows:
                                    self.active_flows[(src_mac, dst_mac)]['priority'] = _prio
                                _first_sw, _first_in, _first_out = path[0]
                                print(f"[{ROUTING_ALGORITHM} Routing UDP] {src_mac} -> {dst_mac}: path {switch_path} | sw={_first_sw} in_port={_first_in} out_port={_first_out} priority={_prio}")
                            else:
                                print(f"[{ROUTING_ALGORITHM} Routing UDP] 無法轉換路徑信息: {switch_path}")
                    else:
                        print(f"[{ROUTING_ALGORITHM} Routing UDP] 無法為 {src_mac} -> {dst_mac} 找到路徑")
                else:
                    print(f"[{ROUTING_ALGORITHM} Routing UDP] 無法轉換 MAC: {src_mac} -> {dst_mac}")

            except Exception as e:
                import traceback
                print(f"[{ROUTING_ALGORITHM} Routing UDP] 路由計算失敗: {e}")
                traceback.print_exc()
        else:
            self._apply_packet_algorithm(PACKET_ALGORITHM_UDP, datapath, pkt_data, 'UDP')
        
    def unknown_ICMP_packet(self, datapath, pkt_data):
        """處理未定義的 ICMP 流量 - 根據全域演算法開關觸發"""
        print(f"[UNKNOWN_ICMP] 收到未定義的 ICMP 封包，來自 switch {datapath.id}")
        self._apply_packet_algorithm(PACKET_ALGORITHM_ICMP, datapath, pkt_data, 'ICMP')

    def unknown_IPv4_packet(self, datapath, pkt_data):
        """處理其他未定義的 IPv4 流量 - 根據全域演算法開關觸發"""
        print(f"[UNKNOWN_IPv4] 收到其他類型的未定義 IPv4 封包，來自 switch {datapath.id}")
        self._apply_packet_algorithm(PACKET_ALGORITHM_IPV4, datapath, pkt_data, 'IPv4')

    def unknown_IPv6_packet(self, datapath, pkt_data):
        """處理未定義的 IPv6 流量 - 根據全域演算法開關觸發"""
        #print(f"[UNKNOWN_IPv6] 收到未定義的 IPv6 封包，來自 switch {datapath.id}")
        self._apply_packet_algorithm(PACKET_ALGORITHM_IPV6, datapath, pkt_data, 'IPv6')
	
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures , CONFIG_DISPATCHER)
    def switch_features_handler(self , ev):

         print("switch_features_handler is called")
         datapath = ev.msg.datapath
         ofproto = datapath.ofproto
         parser = datapath.ofproto_parser
         match = parser.OFPMatch()
         actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, 128)]  # 只送前 128 bytes，夠解析 header 即可
         inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS , actions)]
         mod = datapath.ofproto_parser.OFPFlowMod(
         datapath=datapath, match=match, cookie=0,
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=0, instructions=inst)
         datapath.send_msg(mod)


    @set_ev_cls(ofp_event.EventOFPFlowRemoved, MAIN_DISPATCHER)
    def flow_removed_handler(self, ev):
        if ROUTING_ALGORITHM not in ('2020', 'dijkstra', 'self', 'sorted'):
            return

        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto

        if msg.priority < FLOW_BASE_PRIORITY:
            return

        match = msg.match
        src_mac = match.get('eth_src')
        dst_mac = match.get('eth_dst')

        if msg.reason == ofp.OFPRR_HARD_TIMEOUT:
            if src_mac and dst_mac:
                removed_path = (self.active_flows.get((src_mac, dst_mac)) or {}).get('path')
                self.remove_active_flow(src_mac, dst_mac, hard_timeout=msg.hard_timeout)
                if ROUTING_ALGORITHM in ('self', 'sorted') and removed_path and self.routing_module:
                    self.routing_module.on_flow_removed(src_mac, dst_mac, removed_path)
        elif msg.reason == ofp.OFPRR_IDLE_TIMEOUT:
            if src_mac and dst_mac:
                current_entry = self.active_flows.get((src_mac, dst_mac))
                if current_entry is None:
                    return
                current_priority = current_entry.get('priority')
                if current_priority is not None and msg.priority < current_priority:
                    # 舊路徑的 rule 自然過期（cascade 後留下的舊 rule），忽略
                    return
                removed_path = current_entry.get('path')
                self.remove_active_flow(src_mac, dst_mac)
                if ROUTING_ALGORITHM in ('self', 'sorted') and removed_path and self.routing_module:
                    self.routing_module.on_flow_removed(src_mac, dst_mac, removed_path)
                    
		 
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
      self.pkt_in_count = getattr(self, 'pkt_in_count', 0) + 1
      if self.pkt_in_count % 100 == 0:
          print(f"[PKT-IN COUNT] {self.pkt_in_count}")

      '''
      try:
          print("test0", flush=True)
          ...
      except Exception as e:
          import traceback
          print(f"### EXCEPTION ###: {e}", flush=True)
          traceback.print_exc()
      '''

      msg = ev.msg
      datapath = msg.datapath
      ofproto = datapath.ofproto
      parser = datapath.ofproto_parser
      in_port = msg.match['in_port']
      pkt = packet.Packet(msg.data)
      eth = pkt.get_protocol(ethernet.ethernet)

      if eth:
          _pair = (eth.src, eth.dst)
          self.pkt_in_pair_counter = getattr(self, 'pkt_in_pair_counter', {})
          self.pkt_in_pair_counter[_pair] = self.pkt_in_pair_counter.get(_pair, 0) + 1

          if self.pkt_in_pair_counter[_pair] % 100 == 0:
              _udp_count = self.udp_pkt_counter.get(_pair, 0)
              _tcp_count = self.tcp_pkt_counter.get(_pair, 0)
              _has_flow  = _pair in self.active_flows
              print(f"[PKT-IN PAIR] {_pair[0]} -> {_pair[1]} "
                    f"total={self.pkt_in_pair_counter[_pair]} "
                    f"sw={datapath.id} port={in_port} "
                    f"udp={_udp_count} tcp={_tcp_count} "
                    f"active_flow={_has_flow}")

      # 處理 LLDP 封包
      #if eth.ethertype != 0x88CC:
          #print("test")
      if eth.ethertype == 0x88CC:
          #print("LLDP packet received")
          lldp_pkt = pkt.get_protocol(lldp.lldp)
          if not lldp_pkt:
            return  # 非 LLDP 封包，忽略
          
          # ← 只在啟用延遲偵測時處理自定義 LLDP
          # if ENABLE_DELAY_DETECTION:  ← 原始版本沒有此判斷，直接處理
          for tlv in lldp_pkt.tlvs:
              if isinstance(tlv, lldp.OrganizationallySpecific):
                  info_str = tlv.info.decode('utf-8')
                  if info_str.startswith("Delay_LLDP|"):
                      parts = info_str.split("|")
                      if len(parts) == 3:
                          switch_a = int(parts[1])
                          switch_b = int(parts[2])
                                                  
                          # ← 改為呼叫新模組的 LLDP 回覆處理
                          if (switch_a, switch_b) in self.link_delay_measurement.temp_lldp_link_delay:
                              self.link_delay_measurement.handle_lldp_reply(switch_a, switch_b)
                              #print(f"*** handle_lldp_reply called for ({switch_a}, {switch_b}), delay now: {temp_lldp_link_delay[(switch_a, switch_b)]}")
                          else:
                              self.logger.info("Delay_LLDP| %s -> %s not found", switch_a, switch_b)
                          
                      break  # 找到自定義 LLDP 後跳出迴圈
          return  
    # 繼續處理其他封包
      #print("eth.ethertype=", eth.ethertype)
      #avodi broadcast from LLDP
      if eth.ethertype == ether_types.ETH_TYPE_ARP:
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is not None:
          if arp_pkt.opcode == arp.ARP_REQUEST:
            self._handle_arp_request(datapath, in_port, arp_pkt)
            return  
      
      # ← 檢測 TCP/UDP/ICMP 等傳輸層協議
      if eth.ethertype == ether_types.ETH_TYPE_IP:
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
        if ipv4_pkt is not None:
          # 檢測 TCP
          if ipv4_pkt.proto == 6:  # TCP protocol number
            #tcp_pkt = pkt.get_protocol(tcp.tcp)
            #if tcp_pkt is not None:
            self.unknown_TCP_packet(datapath, pkt)
            return
          # 檢測 UDP
          elif ipv4_pkt.proto == 17:  # UDP protocol number
            #udp_pkt = pkt.get_protocol(udp.udp)
            #if udp_pkt is not None:
            #print("UDP packet detected")
            self.unknown_UDP_packet(datapath, pkt)
            return
          # 檢測 ICMP
          elif ipv4_pkt.proto == 1:  # ICMP protocol number
            #icmp_pkt = pkt.get_protocol(icmp.icmp)
            #if icmp_pkt is not None:
            self.unknown_ICMP_packet(datapath, pkt)
            return
          else:
            # 其他 IPv4 協議
            self.unknown_IPv4_packet(datapath, pkt)
            return
      
      # 檢測 IPv6
      if eth.ethertype == ether_types.ETH_TYPE_IPV6:
        self.unknown_IPv6_packet(datapath, pkt)
        return
      
      if eth.ethertype == 35020:
        return
      dst = eth.dst
      src = eth.src
      dpid = datapath.id
      self.mac_to_port.setdefault(dpid, {})
      
      # 學習 host 的 MAC 位址與連接埠
      # hosts = get_host(self.topology_api_app, None)
      # host_macs = [host.mac for host in hosts]
      # if src in host_macs and src not in mymac.keys():
      #  mymac[src] = (dpid, in_port)
      #if dst in mymac.keys():
        #print("get dst")
      #  p = get_min_delay_path(mymac[src][0], mymac[dst][0], mymac[src][1], mymac[dst][1])
      #  route_list[(src, dst)] = p
      #  self.install_path(p, ev, src, dst)
      #  out_port = p[0][2]
      #else:
      out_port = ofproto.OFPP_FLOOD
      actions = [parser.OFPActionOutput(out_port)]
      # install a flow to avoid packet_in next time
      if out_port != ofproto.OFPP_FLOOD:
        match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
      data = None
      if msg.buffer_id == ofproto.OFP_NO_BUFFER:
        data = msg.data
      if out_port == ofproto.OFPP_FLOOD:
        if eth.ethertype == 0x0800:
            self.ipv4_count += 1
        elif eth.ethertype == 0x86DD:
            self.ipv6_count += 1
            return
        elif eth.ethertype == 0x88CC:
            self.lldp_count += 1
            print("LLDP", self.lldp_count)
        elif eth.ethertype == 0x8100:
            self.vlan_count += 1
            print("VLAN", self.vlan_count)

        actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                      in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
      else:
        print ("unicast")
        out = parser.OFPPacketOut(
          datapath=datapath, buffer_id=msg.buffer_id, in_port=in_port,
          actions=actions, data=data)
        datapath.send_msg(out)
        
    events = [event.EventSwitchEnter,
         event.EventSwitchLeave, event.EventPortAdd,
          event.EventPortDelete, event.EventPortModify,
          event.EventLinkAdd, event.EventLinkDelete]			  
    @set_ev_cls(events)
    def get_topology_data(self, ev):
        #print("get_topology_data() is called")
        switch_list = get_switch(self.topology_api_app, None)
        self.myswitches=[switch.dp.id for switch in switch_list]
        #print("switches=", self.myswitches)
        links_list = get_link(self.topology_api_app, None)
        mylinks=[(link.src.dpid,link.dst.dpid,link.src.port_no,link.dst.port_no) for link in links_list]
        for s1,s2,port1,port2 in mylinks:
          self.adjacency[s1][s2]=port1
          self.adjacency[s2][s1]=port2
        
