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
from ryu.base.app_manager import lookup_service_brick
from ryu.lib import mac
from ryu.topology import event, switches
from ryu.topology.api import get_switch, get_link, get_host
from ryu.app.wsgi import ControllerBase
from collections import defaultdict
from ryu.lib import hub
from operator import attrgetter
import time


# 這個版本是為了更大的 topo 而改良的
# 改良的內容主要是： thread 寫法重製


#switches
myswitches = []

link_delay = {}
temp_lldp_link_delay = {}
temp_echo_link_delay = {}
# 這是用來儲存臨時的鏈路延遲值，在每次測量期間使用
temp_link_delay = {}

route_list = {}
def update_link_delay(switch_a, switch_b, delay):
    
    link_delay[(switch_a, switch_b)] = (float(delay))

def get_link_delay(switch_a, switch_b):
    return link_delay[(switch_a, switch_b)]
  
def update_temp_link_delay(switch_a, switch_b, delay):
    temp_link_delay[(switch_a, switch_b)] = (float(delay))

def get_temp_link_delay(switch_a, switch_b):
    return temp_link_delay[(switch_a, switch_b)]
#mymac[srcmac]->(switch, port)
mymac={}

#adjacency map [sw1][sw2]->port from sw1 to sw2
adjacency=defaultdict(lambda:defaultdict(lambda:None))
datapath_list={}


def get_min_delay_path(src, dst, first_port, final_port, green_adjacency=None):
    #print("Dijkstra's minimum loss rate path algorithm")
    #print("src=", src, " dst=", dst, " first_port=", first_port, " final_port=", final_port)
    
    # 初始化每個節點的遺失率為正無窮
    min_loss = {}
    previous = {}
    for dpid in myswitches:
        min_loss[dpid] = float('Inf')
        previous[dpid] = None
    min_loss[src] = 0
    
    Q = set(myswitches)
    #print("Q:", Q)
    
    while len(Q) > 0:
        # 選擇遺失率最小的節點
        u = min(Q, key=lambda node: min_loss[node])
        Q.remove(u)
        #print("Q:", Q, "u:", u)
        
        # 更新鄰接節點的遺失率
        if green_adjacency is not None:
            if u not in green_adjacency:
                continue
            for p in green_adjacency[u]:
                if green_adjacency[u][p] is not None:
                    if (u, p) not in link_delay:
                        #print("No delay info for link:", str(u), "->", str(p))
                        Dij_link_delay = 1000  # 假設一個很大的遺失率
                    else:
                        Dij_link_delay = get_link_delay(u, p)
                    #print("Dij_link_delay:", str(u), "->", str(p), ":", Dij_link_delay, "ms")
                    # 計算經過 u 的新遺失率
                    alt = min_loss[u] + Dij_link_delay
                    if alt < min_loss[p]:
                        min_loss[p] = alt
                        previous[p] = u
            
        else:  # ← 加上 else
            if u not in adjacency:
                continue
            for p in adjacency[u]:
                if adjacency[u][p] is not None:
                    if (u, p) not in link_delay:
                        Dij_link_delay = 1000  # 假設一個很大的遺失率
                    else:
                        Dij_link_delay = get_link_delay(u, p)
                    #print("Dij_link_delay:", str(u), "->", str(p), ":", Dij_link_delay, "ms")
                    # 計算經過 u 的新遺失率
                    alt = min_loss[u] + Dij_link_delay
                    if alt < min_loss[p]:
                        min_loss[p] = alt
                        previous[p] = u
        
    # 回溯出從 dst 到 src 的最小遺失率路徑
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
    
    # 如果 src 和 dst 是同一個節點，返回單節點路徑
    if src == dst:
        path = [src]
    else:
        path = r
    
    # 加入每段路徑的輸入和輸出port
    r = []
    in_port = first_port
    for s1, s2 in zip(path[:-1], path[1:]):
        out_port = adjacency[s1][s2]
        r.append((s1, in_port, out_port))
        in_port = adjacency[s2][s1]
    r.append((dst, in_port, final_port))
    return r
  
class ProjectController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
	
    def __init__(self, *args, **kwargs):
        super(ProjectController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.topology_api_app = self
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        self.arp_count = 1
        self.ipv4_count = 1
        self.ipv6_count = 1
        self.lldp_count = 1
        self.vlan_count = 1
        self.host_list =  {}
        self.link_delay = {}
        self.measure_thread = hub.spawn(self._detector)
        self.total_switch_lldp = 0
        self.total_switch_echo = 0
        self.temp_adjacency = []
        self.temp_mymac = {}
        self.dynamic_Dijkstra_test = hub.spawn(self.dynamic_Dijkstra_test)
        
        self.work_queue = hub.Queue()
        for _ in range(3):
            hub.spawn(self._worker)

	   
    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if not datapath.id in self.datapaths:
                #self.logger.debug('register datapath: %016x', datapath.id)
                print('register datapath:', datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                #self.logger.debug('unregister datapath: %016x', datapath.id)
                print('unregister datapath:', datapath.id)
                del self.datapaths[datapath.id]
    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)            
            hub.sleep(15)
 
#    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
#    def _state_change_handler(self, ev):
#        datapath = ev.datapath
#        if ev.state == MAIN_DISPATCHER:
#            self.datapaths[datapath.id] = datapath
#        elif ev.state == DEAD_DISPATCHER:
#            if datapath.id in self.datapaths:
#                del self.datapaths[datapath.id]
    def _worker(self):
        """長駐 worker，從 queue 取工作，沒工作就等待"""
        while True:
            switch_a, switch_b = self.work_queue.get()
            self._switch_to_switch_delay_count(switch_a, switch_b)

    """
    detector 是處理 echo request/reply 的執行緒
    1. 定期對所有 switch 發送 echo request
    2. 等待 echo reply
    """
    def _detector(self):
        while True:
            self.temp_adjacency = dict(adjacency)
            for switch_a in list(self.temp_adjacency.keys()):
                for switch_b in list(self.temp_adjacency[switch_a].keys()):
                    if switch_a >= switch_b:
                        # 把工作丟進 queue，worker 自己去取
                        self.work_queue.put((switch_a, switch_b))

            print("----- Delay Measurement Cycle Complete -----")
            
            # 保證前一次的 worker 都已經完成了任務，才進行下一輪的測量
            hub.sleep(10)
    
    '''
    這段用來測試 Dijkstra 動態更新路徑的功能
    '''
    def dynamic_Dijkstra_test(self):
        hub.sleep(15)  # 等待網路拓撲穩定
        while True:
            
            green_Dijkstra = "disable"  # "enable" 或 "disable"，到時候可以設定開關，現在測試而已，先寫死
            
            if green_Dijkstra == "enable":
                # 只是暫時模擬關閉某些 switch 的功能
                
                green_adjacency = {}
                
                # 直接指定關閉 switch 5，簡易實驗
                for u in adjacency:
                    if u == 5:
                        continue
                    
                    # 初始化第一層，沒有初始化會報錯
                    green_adjacency[u] = {}
                    
                    for p in adjacency[u]:
                        if p !=5:
                            green_adjacency[u][p] = adjacency[u][p]            

            self.update_host_mac_table()
                
            self.temp_mymac = dict(mymac)
                
            host_list = list(self.temp_mymac.keys())
            for host_a in host_list:
                for host_b in host_list:
                    if host_a != host_b:
                        
                        temp_route = dict(route_list)
                        
                        if green_Dijkstra == "enable":
                            p = get_min_delay_path(self.temp_mymac[host_a][0], self.temp_mymac[host_b][0], 
                                                    self.temp_mymac[host_a][1], self.temp_mymac[host_b][1],
                                                    green_adjacency)
                        else:
                            p = get_min_delay_path(self.temp_mymac[host_a][0], self.temp_mymac[host_b][0], 
                                                    self.temp_mymac[host_a][1], self.temp_mymac[host_b][1])
                        #print(p)
                            
                        # 检查是否已有这条路径的记录
                        # 演算法有需要更新
                        if (host_a, host_b) in temp_route:
                            if p == temp_route[(host_a, host_b)]:
                                self.install_flows_for_path(p, host_a, host_b, 1, 60)
                            else:
                                #print(f"Path change detected for {host_a} -> {host_b}")
                                self.install_flows_for_path(p, host_a, host_b, 2, 24)
                                route_list[(host_a, host_b)] = p
                        else:
                            # 如果route_list中没有这条路径记录，当作新路径处理
                            #print(f"New path for {host_a} -> {host_b}")
                            self.install_flows_for_path(p, host_a, host_b, 1, 60)
                            route_list[(host_a, host_b)] = p
            hub.sleep(20)
    def update_host_mac_table(self):
        """从拓扑信息更新主机MAC表"""
        hosts = get_host(self.topology_api_app, None)
        
        for host in hosts:
            mac = host.mac
            dpid = host.port.dpid
            port_no = host.port.port_no
            
            if mac not in mymac:
                mymac[mac] = (dpid, port_no)
                print(f"Added host: {mac} at switch {dpid}, port {port_no}")            

    def _switch_to_switch_delay_count(self, switch_a, switch_b):
        MAX_RETRY = 3
        
        for retry in range(MAX_RETRY):  # ← 改成迴圈取代遞迴
            delay = 0
            for i in range(3):
                sleep_time = 0
                temp_lldp_link_delay[(switch_a, switch_b)] = 0
                temp_lldp_link_delay[(switch_b, switch_a)] = 0
                temp_echo_link_delay[(switch_a, switch_b)] = 0
                temp_echo_link_delay[(switch_b, switch_a)] = 0

                self._sent_custom_lldp_request(switch_a, switch_b)
                self._sent_custom_lldp_request(switch_b, switch_a)
                self._send_echo_request(switch_a, switch_b)
                self._send_echo_request(switch_b, switch_a)

                hub.sleep(0.5)
                while (temp_lldp_link_delay[(switch_a, switch_b)] <= 0 or
                       temp_echo_link_delay[(switch_a, switch_b)] <= 0 or
                       temp_lldp_link_delay[(switch_b, switch_a)] <= 0 or
                       temp_echo_link_delay[(switch_b, switch_a)] <= 0):
                    hub.sleep(0.1)
                    sleep_time += 0.1
                    if sleep_time >= 1:
                        if i >= 2:
                            print(f"*** Timeout: {switch_a} <-> {switch_b}")
                            break
                        else:
                            print(f"*** Retry measure: {switch_a} <-> {switch_b}")
                            break
                if sleep_time >= 1:
                    hub.sleep(0.5)
                    continue

                delay = (temp_lldp_link_delay[(switch_a, switch_b)]
                        + temp_lldp_link_delay[(switch_b, switch_a)]
                        - temp_echo_link_delay[(switch_a, switch_b)]
                        - temp_echo_link_delay[(switch_b, switch_a)]) / 2

            if delay > 0:
                break  # ← delay 正常，跳出 retry 迴圈
            else:
                print(f"*** delay <= 0 ({delay:.2f}) {switch_a} <-> {switch_b}，重試第 {retry+1} 次")
                hub.sleep(0.5)

        if delay > 0:
            update_link_delay(switch_a, switch_b, delay)
            update_link_delay(switch_b, switch_a, delay)
            print(f"Measured delay {switch_a} <-> {switch_b}: {delay:.2f} ms")
        else:
            print(f"*** 重試 {MAX_RETRY} 次後仍失敗，保留上一次的值")

    # 這個自定義的 LLDP 封包，用來偵測延遲
    def _sent_custom_lldp_request(self, switch_a, switch_b):
      
      port_no = self.temp_adjacency[switch_a][switch_b]
      
      # 防呆檢查
      if port_no is None:
          self.logger.warning('Port is None for link %s -> %s', switch_a, switch_b)
          return
      
      # 在此儲存發送時間
      
      switch_to_switch_info = f"Delay_LLDP|{switch_a}|{switch_b}".encode('utf-8')
      
      # LLDP 封包需要填寫的欄位
      lldp_pkt = lldp.lldp(tlvs=[
          lldp.ChassisID(subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
                        chassis_id=str(switch_a).encode('utf-8')),
          lldp.PortID(subtype=lldp.PortID.SUB_LOCALLY_ASSIGNED,
                      port_id=str(port_no).encode('utf-8')),
          lldp.TTL(ttl=120),
          # LLDP 自定義的欄位在這裡加入，AI說前兩者可以隨意，info最重要
          lldp.OrganizationallySpecific(oui=b'\xAA\xBB\xCC', subtype=99, 
                                        info=switch_to_switch_info)
      ])
      
      pkt = packet.Packet()
      # 這只是用來偵測時間的，來源不重要，目的地之所以是廣播，是因為 LLDP 不能指定 MAC，本質上是廣播封包
      pkt.add_protocol(ethernet.ethernet(dst=lldp.LLDP_MAC_NEAREST_BRIDGE,
                                         src='00:00:00:00:00:99',
                                         ethertype=0x88CC))
      pkt.add_protocol(lldp_pkt)
      pkt.serialize()
      
      datapath = self.datapaths[switch_a]
      actions = [datapath.ofproto_parser.OFPActionOutput(port_no)]
      out = datapath.ofproto_parser.OFPPacketOut(
          datapath=datapath,
          buffer_id=datapath.ofproto.OFP_NO_BUFFER,
          in_port=datapath.ofproto.OFPP_CONTROLLER,
          actions=actions,
          data=pkt.data
      )
      datapath.send_msg(out)
      
      temp_lldp_link_delay[(switch_a, switch_b)] = temp_lldp_link_delay[(switch_a, switch_b)] - (time.time() * 1000)


    def _send_echo_request(self, switch, pair_switch):  # ← 新增 pair_switch 參數
        if switch not in self.datapaths:
            return

        datapath = self.datapaths[switch]
        ofp_parser = datapath.ofproto_parser
        echo_req = ofp_parser.OFPEchoRequest(datapath, data=None)
        datapath.send_msg(echo_req)

        # ↓ 改成以 pair 為 key
        temp_echo_link_delay[(switch, pair_switch)] = temp_echo_link_delay[(switch, pair_switch)] - (time.time() * 1000)
        
    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        datapath = ev.msg.datapath
        dpid = datapath.id
        
        # ↓ 更新所有包含此 switch 的 pair
        for key in list(temp_echo_link_delay.keys()):
            if key[0] == dpid and temp_echo_link_delay[key] < 0:
                temp_echo_link_delay[key] = temp_echo_link_delay[key] + (time.time() * 1000)

    def _request_stats(self, datapath):
        #self.logger.debug('send stats request: %016x', datapath.id)
        #print 'send stats request:', datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)
        
    def ls(self,obj):
        print("\n".join([x for x in dir(obj) if x[0] != "_"]))
		
    def add_flow(self, datapath, in_port, dst, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser    
        match = datapath.ofproto_parser.OFPMatch(
            in_port=in_port, eth_dst=dst)
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath, match=match, cookie=0,
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=ofproto.OFP_DEFAULT_PRIORITY, instructions=inst)
        datapath.send_msg(mod)
        
        
    # 主动安装流表，不依赖packet_in事件，但感覺可以寫得更彈性一些
    def install_flows_for_path(self, path, src_mac, dst_mac,proirity,hard_timeout):
        """主动安装流表，不依赖packet_in事件"""
        #print(f"Installing flows for path: {src_mac} -> {dst_mac}")
        
        for sw_dpid, in_port, out_port in path:
            if sw_dpid not in datapath_list:
                print(f"Warning: Switch {sw_dpid} not found")
                continue
                
            datapath = datapath_list[sw_dpid]
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            
            # 安装正向流表
            match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
            actions = [parser.OFPActionOutput(out_port)]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            
            mod = parser.OFPFlowMod(
                datapath=datapath,
                match=match,
                idle_timeout=0,
                hard_timeout=hard_timeout,
                priority=proirity,
                instructions=inst
            )
            datapath.send_msg(mod)
            #print(f"Flow installed on switch {sw_dpid}: {in_port} -> {out_port}")
    def install_path(self, p, ev, src_mac, dst_mac):
      #print("install_path is called")
      #print "p=", p, " src_mac=", src_mac, " dst_mac=", dst_mac
      msg = ev.msg
      datapath = msg.datapath
      ofproto = datapath.ofproto
      parser = datapath.ofproto_parser
      for sw, in_port, out_port in p:
        print(src_mac, "->", dst_mac, "via ", sw, " in_port=", in_port, " out_port=", out_port)
        match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
        actions = [parser.OFPActionOutput(out_port)]
        datapath = datapath_list[sw]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(
          datapath=datapath, match=match, idle_timeout=0, hard_timeout=20,
          priority=1, instructions=inst)
        datapath.send_msg(mod)

    def _handle_arp_request(self, datapath, in_port, arp_pkt):
        """Controller直接回應ARP請求"""
        self.host_list = get_host(self.topology_api_app, None)
        
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
	
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures , CONFIG_DISPATCHER)
    def switch_features_handler(self , ev):

         print("switch_features_handler is called")
         datapath = ev.msg.datapath
         ofproto = datapath.ofproto
         parser = datapath.ofproto_parser
         match = parser.OFPMatch()
         actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
         inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS , actions)]
         mod = datapath.ofproto_parser.OFPFlowMod(
         datapath=datapath, match=match, cookie=0,
            command=ofproto.OFPFC_ADD, idle_timeout=0, hard_timeout=0,
            priority=0, instructions=inst)
         datapath.send_msg(mod)
		 
    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
      global target_srcmac, target_dstmac
      #print "packet_in event:", ev.msg.datapath.id, " in_port:", ev.msg.match['in_port']
      msg = ev.msg
      datapath = msg.datapath
      ofproto = datapath.ofproto
      parser = datapath.ofproto_parser
      in_port = msg.match['in_port']
      pkt = packet.Packet(msg.data)
      eth = pkt.get_protocol(ethernet.ethernet)
      # 處理 LLDP 封包
      
      if eth.ethertype == 0x88CC:
          #print("LLDP packet received")
          lldp_pkt = pkt.get_protocol(lldp.lldp)
          if not lldp_pkt:
            return  # 非 LLDP 封包，忽略
          
          for tlv in lldp_pkt.tlvs:
              if  isinstance(tlv, lldp.OrganizationallySpecific):
                  info_str = tlv.info.decode('utf-8')
                  if info_str.startswith("Delay_LLDP|"):
                      parts = info_str.split("|")
                      if len(parts) == 3:
                          switch_a = int(parts[1])
                          switch_b = int(parts[2])
                          
                          if (switch_a, switch_b) not in temp_lldp_link_delay:
                            self.logger.info("Delay_LLDP| %s -> %s not found", switch_a, switch_b)
                          else:
                            temp_lldp_link_delay[(switch_a, switch_b)] = temp_lldp_link_delay[(switch_a, switch_b)] + (time.time() * 1000)
                  else:
                      return  # 忽略非自定義 LLDP 封包
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
        global myswitches, adjacency, datapath_list
        switch_list = get_switch(self.topology_api_app, None)
        myswitches=[switch.dp.id for switch in switch_list]
        for switch in switch_list:
          datapath_list[switch.dp.id]=switch.dp
        #print("myswitches=", myswitches)
        links_list = get_link(self.topology_api_app, None)
        mylinks=[(link.src.dpid,link.dst.dpid,link.src.port_no,link.dst.port_no) for link in links_list]
        for s1,s2,port1,port2 in mylinks:
          adjacency[s1][s2]=port1
          adjacency[s2][s1]=port2
