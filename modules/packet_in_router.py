# -*- coding: utf-8 -*-
"""
packet_in_router.py - PacketIn 事件的完整處理內容

DTM.py 的 _packet_in_handler（Ryu 事件入口，@set_ev_cls 鎖死搬不走）現在只
剩一行：把 ev 轉交給這裡的 handle()。debug 計數、LLDP 解析、ARP/IPv4/IPv6
分派、最後的 OFPP_FLOOD fallback，全部原封不動搬過來，包含既有的註解說明
（例如 2026-09-11 的 ARP_REPLY 廣播風暴事故說明）跟原本就存在的死碼／註解
掉的舊邏輯——這次只是搬家，沒有解決、也沒有刪除任何懸而未決的問題。

已知但這次沒處理的問題（原封不動帶過來，CLAUDE.md 也有記錄）：
- OFPP_FLOOD fallback 該不該整個存在，還跟 vlan_count/lldp_count 統計混在
  一起，要拔得先盤點現在哪些流量類型還會走到這裡、每種原本在做什麼。
- 兩段註解掉的舊邏輯（try/except 測試碼、host learning 的手動實作）維持
  原樣保留在下面，不確定要不要保留就先不動它。

之後要處理這些問題，直接改這個檔案，不用動 DTM.py。

使用方式：
    self.packet_in_router = PacketInRouter(self)   # DTM.py __init__ 建立
    self.packet_in_router.handle(ev)                 # _packet_in_handler 呼叫
"""

from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import lldp
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4


class PacketInRouter:
    def __init__(self, app):
        self.app = app
        self.pkt_in_count = 0
        self.pkt_in_pair_counter = {}
        self.ipv4_count = 1
        self.ipv6_count = 1
        self.lldp_count = 1
        self.vlan_count = 1
        self.mac_to_port = {}

    def handle(self, ev):
      self.pkt_in_count += 1
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
          self.pkt_in_pair_counter[_pair] = self.pkt_in_pair_counter.get(_pair, 0) + 1

          if self.pkt_in_pair_counter[_pair] % 100 == 0:
              _udp_count = self.app.udp_throttle.pkt_counter.get(_pair, 0)
              _tcp_count = self.app.tcp_throttle.pkt_counter.get(_pair, 0)
              _has_flow  = _pair in self.app.flow_registry.active_flows
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
                          if (switch_a, switch_b) in self.app.link_delay_measurement.temp_lldp_link_delay:
                              self.app.link_delay_measurement.handle_lldp_reply(switch_a, switch_b)
                              #print(f"*** handle_lldp_reply called for ({switch_a}, {switch_b}), delay now: {temp_lldp_link_delay[(switch_a, switch_b)]}")
                          else:
                              self.app.logger.info("Delay_LLDP| %s -> %s not found", switch_a, switch_b)

                      break  # 找到自定義 LLDP 後跳出迴圈
          return
    # 繼續處理其他封包
      #print("eth.ethertype=", eth.ethertype)
      #avodi broadcast from LLDP
      if eth.ethertype == ether_types.ETH_TYPE_ARP:
        arp_pkt = pkt.get_protocol(arp.arp)
        if arp_pkt is not None:
          if arp_pkt.opcode == arp.ARP_REQUEST:
            self.app.arp_handler.handle_request(datapath, in_port, arp_pkt)
          # return 移出 REQUEST 判斷之外：ARP_REPLY（opcode != REQUEST）
          # 原本沒有 return，會落到本函式最後的 OFPP_FLOOD fallback，
          # 在有迴圈的拓撲（cap_topo.py 的 core mesh）會造成無防迴圈的
          # 永久廣播風暴（2026-09-11 實測，見 modules/host_discovery.py
          # 開頭註解）。這個架構下 controller 是純代理 ARP，正常運作時
          # host 本來就看不到彼此的原始 ARP 封包，ARP_REPLY 幾乎不會
          # 發生，補上 return 不影響任何現有功能。
          return

      # ← 檢測 TCP/UDP/ICMP 等傳輸層協議
      if eth.ethertype == ether_types.ETH_TYPE_IP:
        ipv4_pkt = pkt.get_protocol(ipv4.ipv4)
        if ipv4_pkt is not None:
          # 檢測 TCP
          if ipv4_pkt.proto == 6:  # TCP protocol number
            #tcp_pkt = pkt.get_protocol(tcp.tcp)
            #if tcp_pkt is not None:
            self.app.packet_handler.unknown_TCP_packet(datapath, pkt)
            return
          # 檢測 UDP
          elif ipv4_pkt.proto == 17:  # UDP protocol number
            #udp_pkt = pkt.get_protocol(udp.udp)
            #if udp_pkt is not None:
            #print("UDP packet detected")
            self.app.packet_handler.unknown_UDP_packet(datapath, pkt)
            return
          # 檢測 ICMP
          elif ipv4_pkt.proto == 1:  # ICMP protocol number
            #icmp_pkt = pkt.get_protocol(icmp.icmp)
            #if icmp_pkt is not None:
            self.app.packet_handler.unknown_ICMP_packet(datapath, pkt)
            return
          else:
            # 其他 IPv4 協議
            self.app.packet_handler.unknown_IPv4_packet(datapath, pkt)
            return

      # 檢測 IPv6
      if eth.ethertype == ether_types.ETH_TYPE_IPV6:
        self.app.packet_handler.unknown_IPv6_packet(datapath, pkt)
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
