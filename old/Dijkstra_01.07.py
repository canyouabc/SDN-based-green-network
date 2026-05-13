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

# 本次是實作了 LLDP 延遲偵測功能
# 但 echo 的部分還尚未完成

#switches
myswitches = []



#mymac[srcmac]->(switch, port)
mymac={}

#adjacency map [sw1][sw2]->port from sw1 to sw2
adjacency=defaultdict(lambda:defaultdict(lambda:None))
datapath_list={}
loss_rate=defaultdict(lambda:defaultdict(lambda:None))


def get_min_loss_path(src, dst, first_port, final_port):
    global loss_rate
    print("Dijkstra's minimum loss rate path algorithm")
    print("src=", src, " dst=", dst, " first_port=", first_port, " final_port=", final_port)
    
    # 初始化每個節點的遺失率為正無窮
    min_loss = {}
    previous = {}
    for dpid in myswitches:
        min_loss[dpid] = float('Inf')
        previous[dpid] = None
    min_loss[src] = 0
    
    Q = set(myswitches)
    print("Q:", Q)
    
    while len(Q) > 0:
        # 選擇遺失率最小的節點
        u = min(Q, key=lambda node: min_loss[node])
        Q.remove(u)
        print("Q:", Q, "u:", u)
        
        # 更新鄰接節點的遺失率
        for p in myswitches:
          if adjacency[u][p] is not None:
            link_loss = loss_rate[str(u)][str(p)]
            if link_loss is None:
              link_loss = 0  # 預設值
            print("link_loss:", str(u), "->", str(p), ":", link_loss, "%")
            # 計算經過 u 的新遺失率
            alt = min_loss[u] + link_loss
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
  
def minimum_distance(distance, Q):
  #print("minimum_distance() is called", " distance=", distance, " Q=", Q)
  min = float('Inf')
  node = 0
  for v in Q:
    if distance[v] < min:
      min = distance[v]
      node = v
  return node
  
  
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
        self.echo_latency = {}
        self.measure_thread = hub.spawn(self._detector)
        self.lldp_send_time = 0
        self.lldp_reply_time = 0
        self.echo_a_to_b = 0
        self.echo_b_to_a = 0
        self.delay_temp = []

        global loss_rate
        try:
          fin = open("loss_rate.txt", "r")
          for line in fin:
            a=line.split()
            if a:
              loss_rate[str(a[0])][str(a[1])]=float(a[2])
              loss_rate[str(a[1])][str(a[0])]=float(a[2])
          fin.close()
        except IOError:
          print("make loss_rate.txt ready")
	   
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
            hub.sleep(3)
 
    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                del self.datapaths[datapath.id]

    """
    detector 是處理 echo request/reply 的執行緒
    1. 定期對所有 switch 發送 echo request
    2. 等待 echo reply
    """
    def _detector(self):
        while True:
            self.delay_temp = adjacency
            for switch_a in self.delay_temp:
                for switch_b in self.delay_temp[switch_a]:
                  self._sent_custom_lldp_request(switch_a, switch_b)
                  hub.sleep(0.5)
                  # self._send_echo_request()
                  # hub.sleep(0.05)

                  #delay = (self.lldp_send_time + self.lldp_reply_time - self.echo_a_to_b - self.echo_b_to_a) / 2
                  
                  print("lldp_delay:", switch_a, "<->", switch_b, ":", (self.lldp_reply_time - self.lldp_send_time)*1000, "ms")

            hub.sleep(4)
    
    # 這個自定義的 LLDP 封包，用來偵測延遲
    def _sent_custom_lldp_request(self, switch_a, switch_b):
      port_no = self.delay_temp[switch_a][switch_b]
      
      # 防呆檢查
      if port_no is None:
          self.logger.warning('Port is None for link %s -> %s', switch_a, switch_b)
          return
      
      # 在此儲存發送時間
      
      # LLDP 封包需要填寫的欄位
      lldp_pkt = lldp.lldp(tlvs=[
          lldp.ChassisID(subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
                        chassis_id=str(switch_a).encode('utf-8')),
          lldp.PortID(subtype=lldp.PortID.SUB_LOCALLY_ASSIGNED,
                      port_id=str(port_no).encode('utf-8')),
          lldp.TTL(ttl=120),
          # LLDP 自定義的欄位在這裡加入，AI說前兩者可以隨意，info最重要
          lldp.OrganizationallySpecific(oui=b'\xAA\xBB\xCC', subtype=99, 
                                        info=b'Delay_LLDP')
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
      self.lldp_send_time = time.time()



    def _send_echo_request(self):
        for datapath in self.datapaths.values():
            parser = datapath.ofproto_parser
            timestamp = ("%.12f" % time.time()).encode('utf-8')
            echo_req = parser.OFPEchoRequest(datapath, data=timestamp)
            datapath.send_msg(echo_req)
            hub.sleep(0.05)

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        try:
            latency = time.time() - float(ev.msg.data.decode('utf-8'))
            self.echo_latency[ev.msg.datapath.id] = latency
        except:
            pass

    def _calculate_delays(self):
        self.logger.info("\n=== Link Delays ===test")
        for (src, dst), lldp_delay in self.link_delay.items():
            src_latency = self.echo_latency.get(src, 0)
            dst_latency = self.echo_latency.get(dst, 0)
            self.logger.info("src_latency=", src_latency, " dst_latency=", dst_latency)
            self.logger.info("lldp_delay=", lldp_delay)
            # 沒通
            print("test")
            delay = (lldp_delay - src_latency - dst_latency) / 2
            self.logger.info(f"{src}<->{dst}: {max(delay, 0)*1000:.3f}ms")

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
		
    def install_path(self, p, ev, src_mac, dst_mac):
      print("install_path is called")
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
          datapath=datapath, match=match, idle_timeout=0, hard_timeout=0,
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
                  print("test2")
                  if  tlv.info == b'Delay_LLDP':
                      # print("test")
                      self.lldp_reply_time = time.time()
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
      #print("src=", src, " dst=", dst, " type=", hex(eth.ethertype))
      #print("adjacency=", adjacency)
      self.mac_to_port.setdefault(dpid, {})
      if src not in mymac.keys():
        mymac[src] = (dpid, in_port)
        #print("mymac=", mymac)
      if dst in mymac.keys():
        #print("get dst")
        p = get_min_loss_path(mymac[src][0], mymac[dst][0], mymac[src][1], mymac[dst][1])
        self.install_path(p, ev, src, dst)
        out_port = p[0][2]
      else:
        out_port = ofproto.OFPP_FLOOD
      actions = [parser.OFPActionOutput(out_port)]
      # install a flow to avoid packet_in next time
      if out_port != ofproto.OFPP_FLOOD:
        match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
      data = None
      if msg.buffer_id == ofproto.OFP_NO_BUFFER:
        data = msg.data
      if out_port == ofproto.OFPP_FLOOD:
        if eth.ethertype == 0x0806:
          self.arp_count += 1
          get_host(self.topology_api_app, None)
          #print("ARP", self.arp_count)          
          
          return

        elif eth.ethertype == 0x0800:
          self.ipv4_count += 1
          #print("IPv4", self.ipv4_count)

        elif eth.ethertype == 0x86DD:
          self.ipv6_count += 1
          #print("IPv6", self.ipv6_count)
          return

        elif eth.ethertype == 0x88CC:
          self.lldp_count += 1
          print("LLDP", self.lldp_count)

        elif eth.ethertype == 0x8100:
          self.vlan_count += 1
          print("VLAN", self.vlan_count)
        while len(actions) > 0:
          actions.pop()
        for i in range(1, 5):
          actions.append(parser.OFPActionOutput(i))
        #print "actions=", actions
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
        print("get_topology_data() is called")
        global myswitches, adjacency, datapath_list
        switch_list = get_switch(self.topology_api_app, None)
        myswitches=[switch.dp.id for switch in switch_list]
        for switch in switch_list:
          datapath_list[switch.dp.id]=switch.dp
        #print "datapath_list=", datapath_list
        print("myswitches=", myswitches)
        links_list = get_link(self.topology_api_app, None)
        #print "links_list=", links_list
        mylinks=[(link.src.dpid,link.dst.dpid,link.src.port_no,link.dst.port_no) for link in links_list]
        for s1,s2,port1,port2 in mylinks:
          #print "type(s1)=", type(s1), " type(port1)=", type(port1)
          adjacency[s1][s2]=port1
          adjacency[s2][s1]=port2
          # check用，先關掉
          # print(s1,":", port1, "<--->",s2,":",port2)
