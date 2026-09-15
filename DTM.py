# -*- coding: utf-8 -*-
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.lib.packet import icmp
from ryu.topology import event
from ryu.topology.api import get_switch, get_link
from collections import defaultdict
from ryu.lib import hub
import os
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

# 依序檢查各觸發條件，第一個成功觸發重路由就停（見 modules/reroute_policy.py）。
# LINK 沒有 ENABLE_* 開關（永遠檢查），其餘三個依對應的 ENABLE_REROUTE_* 決定
# 要不要檢查。想調整優先順序只要改這個 tuple，不用動邏輯。
REROUTE_TRIGGER_ORDER = ('LINK', 'HIGH_HOP', 'HIGH_LOAD', 'LOW_SHARE')
REROUTE_TRIGGER_CONFIG = {
    'HIGH_HOP':  {'enabled': ENABLE_REROUTE_HIGH_HOP,  'top_n': REROUTE_TOP_N_HOP,  'threshold': REROUTE_HOP_THRESHOLD},
    'HIGH_LOAD': {'enabled': ENABLE_REROUTE_HIGH_LOAD, 'top_n': REROUTE_TOP_N_LOAD, 'threshold': REROUTE_LOAD_THRESHOLD},
    'LOW_SHARE': {'enabled': ENABLE_REROUTE_LOW_SHARE, 'top_n': REROUTE_TOP_N_SHARE, 'threshold': REROUTE_SHARE_THRESHOLD},
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

# ==================== Packet-In 未知流量處理版本 ==========
# unknown_TCP/UDP/ICMP/IPv4/IPv6_packet 整批的完整邏輯打包成一個版本化模組
# （比照 ROUTING_ALGORITHM 的切換慣例）。DTM.py 的 _packet_in_handler 只依
# ethertype/協定分派（大方向），實際處理邏輯都在對應版本的檔案裡，改邏輯
# 就直接改那個檔案，或另開 v2 用這個常數切換，不動 v1。
# 選項: 'v1'（現行版本）
PACKET_HANDLER = 'v1'
# =========================================================

if PACKET_HANDLER == 'v1':
    from modules.packet_handler_v1 import PacketHandlerV1 as packet_handler_module
    print("*** 使用 Packet Handler v1（現行版本）")
else:
    print("*** PACKET_HANDLER 變數設定錯誤，請檢查程式碼")

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

from modules.arp_handler import ArpHandler
from modules.energy_data import EnergyData
from modules.flow_registry import FlowRegistry
from modules.flow_stats import FlowStats
from modules.history_reporter import HistoryReporter
from modules.host_discovery import HostDiscovery
from modules.legacy_algorithm_support import LegacyAlgorithmSupport
from modules.packet_throttle import PacketThrottle
from modules.packet_in_router import PacketInRouter
from modules.path_installer import PathInstaller
from modules.reroute_policy import ReroutePolicy
from modules.topology_readiness import TopologyReadiness
from modules.startup_requirements import check_dependencies, MonitorFlags, should_spawn_monitor


   




class ProjectController(app_manager.RyuApp):
    # implements modules.routing_host.RoutingHost + RoutingHostDelay（供 '2014'）
    # 改動 self.app 對 routing 模組露出的介面時，同步更新 modules/routing_host.py
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    def __init__(self, *args, **kwargs):
        super(ProjectController, self).__init__(*args, **kwargs)
        self.topology_api_app = self
        self.datapaths = {}
        # mac_to_port／ipv4_count／ipv6_count／lldp_count／vlan_count 已抽到
        # modules/packet_in_router.py；arp_count／temp_adjacency／temp_mymac
        # 已抽到 modules/legacy_algorithm_support.py（見下方模組實例化，
        # 這幾個原本就是零使用/只服務 2014／auto_k_short 的歷史狀態）
        self.link_delay = {}
        self.total_switch_lldp = 0
        self.total_switch_echo = 0
        self.last_tcp_processing_time = {}  # {pair: timestamp}
        self.last_udp_processing_time = {}  # {pair: timestamp}
        self.host_macs = {} # { mac: (dpid, port_no)}
        # dpid_to_mac／_topo_ready_logged／_link_ready_logged／_last_sw_count／
        # _last_link_count 已抽到 modules/topology_readiness.py（見下方模組實例化）
        self._flow_cookie_counter = 0

        # TCP/UDP 節流邏輯已抽到 modules/packet_throttle.py（見下方模組實例化）
        # ==================== 拓扑数据 ====================
        self.myswitches = []
        
        # ==================== 拓撲數據（續） ====================
        # adjacency map [sw1][sw2]->port from sw1 to sw2
        self.adjacency = defaultdict(lambda:defaultdict(lambda:None))
        # ==================== 能耗数据 ====================

        self.route_list = {}
        # 能耗/BW 設定檔讀取邏輯已抽到 modules/energy_data.py，switch_energy／
        # link_energy／link_bw 仍掛在 self 上（RoutingHost Protocol 屬性，
        # routing 模組直接讀 self.app.switch_energy 這種 dict）
        self.energy_data = EnergyData(self)
        self.switch_energy = self.energy_data.switch_energy
        self.link_energy   = self.energy_data.link_energy
        self.link_bw       = self.energy_data.link_bw

        self.link_used_bw = defaultdict(float)

        # ==================== Active Flow 管理 ====================
        # 記帳狀態（active_flows / flow_history_count / flow_history_hops /
        # flow priority 分配）已抽到 modules/flow_registry.py（見下方模組實例化）
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

        self.flow_registry = FlowRegistry(self, FLOW_BASE_PRIORITY, REROUTE_LOAD_WEIGHT)
        self.flow_stats = FlowStats(self)
        self.host_discovery = HostDiscovery(self)
        self.history_reporter = HistoryReporter(self)
        self.legacy_algorithm_support = LegacyAlgorithmSupport(self, ENABLE_DELAY_DETECTION, ROUTING_ALGORITHM)
        self.arp_handler = ArpHandler(self)
        self.path_installer = PathInstaller(self, FLOW_BASE_PRIORITY)
        self.packet_handler = packet_handler_module(
            self, ENABLE_ROUTING, ROUTING_ALGORITHM,
            PACKET_ALGORITHM_TCP, PACKET_ALGORITHM_UDP,
            PACKET_ALGORITHM_ICMP, PACKET_ALGORITHM_IPV4, PACKET_ALGORITHM_IPV6,
        )
        self.topology_readiness = TopologyReadiness(self)
        self.tcp_throttle = PacketThrottle(1000, 1.0, debug_log=False, label="TCP")
        self.udp_throttle = PacketThrottle(1000, 5.0, debug_log=True, label="UDP")
        self.reroute_policy = ReroutePolicy(self, REROUTE_TRIGGER_ORDER, REROUTE_TRIGGER_CONFIG)
        self.packet_in_router = PacketInRouter(self)

        if ENABLE_ROUTING:
            self.routing_module = routing_module(self)
            check_dependencies(self, ROUTING_ALGORITHM)
        else:
            self.routing_module = None

        # 沒有層級關係的話，會造成無法正確初始化

 
        
        # ==================== 執行緒啟動 ====================
        # 8 個背景執行緒該不該 spawn，統一由 modules/startup_requirements.py
        # 的 MONITOR_CONDITIONS 表決定（單一事實來源，見該檔案說明）。
        monitor_flags = MonitorFlags(ENABLE_ROUTING, ENABLE_DELAY_DETECTION, ENABLE_BANDWIDTH_MEASUREMENT, ROUTING_ALGORITHM)

        if should_spawn_monitor('monitor', monitor_flags):
            self.monitor_thread = hub.spawn(self._monitor)
        if should_spawn_monitor('link_ready_watcher', monitor_flags):
            self.link_ready_thread = hub.spawn(self.topology_readiness._link_ready_watcher)
        if should_spawn_monitor('legacy_detector', monitor_flags):
            self.measure_thread = hub.spawn(self.legacy_algorithm_support.detector)
        if should_spawn_monitor('legacy_dynamic_test', monitor_flags):
            self.dynamic_Dijkstra_test_thread = hub.spawn(self.legacy_algorithm_support.dynamic_test)
        if should_spawn_monitor('bandwidth_monitor', monitor_flags):
            self.bandwidth_monitor_thread = hub.spawn(self._bandwidth_monitor)
        if should_spawn_monitor('flow_stats_monitor', monitor_flags):
            self.flow_stats_monitor_thread = hub.spawn(self._flow_stats_monitor)
        if should_spawn_monitor('monitor_dtm', monitor_flags):
            self.dtm_monitor_thread = hub.spawn(self._monitor_DTM)
        if should_spawn_monitor('monitor_energy', monitor_flags):
            self.energy_monitor_thread = hub.spawn(self._monitor_energy)
            

    # =========================================
    # Active Flow 管理
    # =========================================
    # 以下皆為薄呼叫，實際記帳邏輯在 modules/flow_registry.py（FlowRegistry）。
    # 方法名稱維持不變，因為 routing 模組透過 self.app.X(...) 呼叫（見
    # modules/routing_host.py 的 RoutingHost Protocol），DTM.py 的其他方法
    # （_do_reroute／_monitor 等）也沿用 self.X(...) 呼叫，不用另外修改。
    def add_active_flow(self, host_a, host_b, path, is_reroute=False, priority=None):
        return self.flow_registry.add_active_flow(host_a, host_b, path, is_reroute, priority)

    def remove_active_flow(self, host_a, host_b, path=None, hard_timeout=None):
        return self.flow_registry.remove_active_flow(host_a, host_b, path, hard_timeout)

    def get_active_flows(self):
        return self.flow_registry.get_active_flows()

    def get_history_avg_hops(self):
        return self.flow_registry.get_history_avg_hops()

    def get_avg_hops(self):
        return self.flow_registry.get_avg_hops()

    def get_switch_flow_count(self):
        return self.flow_registry.get_switch_flow_count()

    def _get_next_flow_priority(self, src_mac, dst_mac):
        return self.flow_registry._get_next_flow_priority(src_mac, dst_mac)

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

    def get_path_switch_load(self, host_a, host_b):
        return self.flow_registry.get_path_switch_load(host_a, host_b)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not datapath.id in self.datapaths:
                #self.logger.debug('register datapath: %016x', datapath.id)
                print('register datapath:', datapath.id)
                self.datapaths[datapath.id] = datapath
                self.arp_handler.install_arp_to_controller(datapath)
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                #self.logger.debug('unregister datapath: %016x', datapath.id)
                print('unregister datapath:', datapath.id)
                del self.datapaths[datapath.id]

    def _monitor(self):
        hub.sleep(10)
        while True:
            self.topology_readiness.update_host_mac_table()
            self.history_reporter.maybe_log_history()
            hub.sleep(10)
            
    def _monitor_DTM(self):
        """定期偵測 link 狀態，每個週期只轉移一條流量。
        四個觸發條件的優先順序是資料（REROUTE_TRIGGER_ORDER），依序檢查的
        引擎在 modules/reroute_policy.py，調整順序只要改那份常數。"""
        hub.sleep(10) # 等待拓撲穩定
        while True:
            try:
                self.reroute_policy.attempt_rebalance()
            except Exception as e:
                import traceback
                print(f"[monitor_DTM] 發生錯誤: {e}")
                traceback.print_exc()
            self.energy_data.calculate_energy_saving_from_flows()
            hub.sleep(1)

    def _monitor_energy(self):
        """self 演算法專用：只負責定期輸出能耗統計"""
        hub.sleep(10)
        while True:
            self.energy_data.calculate_energy_saving_from_flows()
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
        """頻寬監控線程（每秒1次），實際計算邏輯在 bandwidth_measurement.py"""
        hub.sleep(10) # 等待拓撲穩定
        while True:
            try:
                self.bandwidth_measurement.run_monitor_tick(self.datapaths, self.adjacency, self.link_bw, self.link_status)
                if ROUTING_ALGORITHM in ('self', 'sorted') and self.routing_module:
                    self.routing_module.refresh_link_cache()
            except Exception as e:
                self.logger.error(f"Error in bandwidth monitor: {e}")
            hub.sleep(1)


    # _detector／dynamic_Dijkstra_test／_switch_to_switch_delay_count／
    # _request_stats 只服務 2014／auto_k_short（現行主線用不到），已打包搬到
    # modules/legacy_algorithm_support.py，功能不受影響（見上方模組實例化／
    # hub.spawn 呼叫點）。

    # build_path_with_ports／install_flows_for_path 的實際邏輯在
    # modules/path_installer.py（PathInstaller），這裡是 RoutingHost Protocol
    # 要求保留的同名 wrapper（routing 模組直接呼叫 self.app.X(...)）。
    def build_path_with_ports(self, switch_path, src_mac, dst_mac):
        return self.path_installer.build_path_with_ports(switch_path, src_mac, dst_mac)

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        self.legacy_algorithm_support.handle_echo_reply(ev.msg.datapath.id)

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
        
        
    # install_flows_for_path 的實際邏輯在 modules/path_installer.py，這裡是
    # RoutingHost Protocol 要求保留的同名 wrapper（routing 模組直接呼叫
    # self.app.install_flows_for_path(...)）。remove_flows_for_path 目前沒有
    # 任何呼叫者（搬過去前就已經是這樣），不留 wrapper，需要用時直接呼叫
    # self.path_installer.remove_flows_for_path(...)。
    def install_flows_for_path(self, path, src_mac, dst_mac, priority, hard_timeout=0, idle_timeout=0):
        return self.path_installer.install_flows_for_path(path, src_mac, dst_mac, priority, hard_timeout, idle_timeout)

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
                removed_path = (self.flow_registry.active_flows.get((src_mac, dst_mac)) or {}).get('path')
                self.remove_active_flow(src_mac, dst_mac, hard_timeout=msg.hard_timeout)
                if ROUTING_ALGORITHM in ('self', 'sorted') and removed_path and self.routing_module:
                    self.routing_module.on_flow_removed(src_mac, dst_mac, removed_path)
        elif msg.reason == ofp.OFPRR_IDLE_TIMEOUT:
            if src_mac and dst_mac:
                current_entry = self.flow_registry.active_flows.get((src_mac, dst_mac))
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
        self.packet_in_router.handle(ev)

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
        
