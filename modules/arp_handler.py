# -*- coding: utf-8 -*-
"""
arp_handler.py - Controller 代理 ARP 請求

從 DTM.py 抽出的 _handle_arp_request / _send_arp_reply：收到 ARP_REQUEST 時，
controller 直接查 Ryu topology 的 get_host() 找出目標 host，用 OFPPacketOut
組一個 ARP_REPLY 直接送回去（繞過 flow table，不需要目標 host 真的在場回覆）。

使用方式：
    self.arp_handler = ArpHandler(self)   # DTM.py __init__ 建立
    self.arp_handler.handle_request(datapath, in_port, arp_pkt)   # _packet_in_handler 呼叫
"""

from ryu.topology.api import get_host
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp


class ArpHandler:
    def __init__(self, app):
        self.app = app
        self.host_list = {}

    def handle_request(self, datapath, in_port, arp_pkt):
        """Controller直接回應ARP請求"""
        self.host_list = get_host(self.app.topology_api_app, None)

        _pair = (arp_pkt.src_mac, arp_pkt.dst_mac)
        _count = getattr(self.app, 'pkt_in_pair_counter', {}).get(_pair, 0)
        if _count > 100:
            _known_ips = {ip: h.mac for h in self.host_list for ip in h.ipv4}
            print(f"[ARP DEBUG] src={arp_pkt.src_ip} dst={arp_pkt.dst_ip} "
                  f"pair_count={_count} get_host_ips={list(_known_ips.keys())}")

        for host in self.host_list:
            if arp_pkt.dst_ip in host.ipv4:
                self.send_reply(
                    datapath, in_port,
                    host.mac, arp_pkt.dst_ip,
                    arp_pkt.src_mac, arp_pkt.src_ip
                )
                return

    def send_reply(self, datapath, in_port, src_mac, src_ip, dst_mac, dst_ip):
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
