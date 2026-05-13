# -*- coding: utf-8 -*-
"""
delay_detection.py - 延遲偵測模組

提供鏈路延遲量測的所有相關功能，包括：
- LLDP 探測封包發送
- Echo Request 發送
- 拓撲掃描和隊列生成
"""
import time
from ryu.lib.packet import packet, ethernet, lldp
from .link_delay_measurement import Link_Delay_Measurement

class Delay_Detection:
    '''
    delay_detection.py - 延遲偵測模組

    提供鏈路延遲量測的所有相關功能，包括：
    - LLDP 探測封包發送
    - Echo Request 發送
    - 拓撲掃描和隊列生成    
    '''
    
    def __init__(self,app):
        self.app = app
        
        self.link_delay_measurement = app.link_delay_measurement
        # 直接從 app 取得 link_delay_measurement 模組的引用，避免重複初始化

    def build_detection_queue(self, adjacency):
        """
        根據拓撲圖生成延遲檢測隊列
        
        Args:
            adjacency: 鄰接表
        
        Returns:
            list: [(switch_a, switch_b), ...] 的列表，只包含 switch_a < switch_b 的配對
        """
        queue = []
        
        for switch_a in list(adjacency.keys()):
            for switch_b in list(adjacency[switch_a].keys()):
                if switch_a >= switch_b:
                    continue  # 只記錄單向，避免重複
                queue.append((switch_a, switch_b))
        
        return queue


    def send_lldp_for_delay_detection(self, switch_a, switch_b, adjacency, datapaths):
        """
        發送自定義 LLDP 封包用於延遲偵測
        
        Args:
            switch_a: 源 switch dpid
            switch_b: 目標 switch dpid
            adjacency: 鄰接表，用於查詢埠號
            datapaths: datapath 字典，用於取得 datapath 物件
        
        Returns:
            bool: 是否成功發送
        """
        # 檢查埠號是否有效
        port_no = adjacency[switch_a][switch_b]
        if port_no is None:
            print(f"[LLDP] Port is None for link {switch_a} -> {switch_b}")
            return False
        
        # 檢查 datapath 是否存在
        if switch_a not in datapaths:
            print(f"[LLDP] Datapath not found for switch {switch_a}")
            return False
        
        try:
            # 構造自定義 LLDP 信息
            switch_to_switch_info = f"Delay_LLDP|{switch_a}|{switch_b}".encode('utf-8')
            
            # 建立 LLDP 封包
            lldp_pkt = lldp.lldp(tlvs=[
                lldp.ChassisID(subtype=lldp.ChassisID.SUB_LOCALLY_ASSIGNED,
                            chassis_id=str(switch_a).encode('utf-8')),
                lldp.PortID(subtype=lldp.PortID.SUB_LOCALLY_ASSIGNED,
                            port_id=str(port_no).encode('utf-8')),
                lldp.TTL(ttl=120),
                lldp.OrganizationallySpecific(oui=b'\xAA\xBB\xCC', subtype=99, 
                                            info=switch_to_switch_info)
            ])
            
            # 構造以太網層
            pkt = packet.Packet()
            pkt.add_protocol(ethernet.ethernet(dst=lldp.LLDP_MAC_NEAREST_BRIDGE,
                                            src='00:00:00:00:00:99',
                                            ethertype=0x88CC))
            pkt.add_protocol(lldp_pkt)
            pkt.serialize()
            
            # 發送封包
            datapath = datapaths[switch_a]
            ofproto = datapath.ofproto
            ofproto_parser = datapath.ofproto_parser
            
            actions = [ofproto_parser.OFPActionOutput(port_no)]
            out = ofproto_parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=ofproto.OFP_NO_BUFFER,
                in_port=ofproto.OFPP_CONTROLLER,
                actions=actions,
                data=pkt.data
            )
            datapath.send_msg(out)
            
            # ← 在發送後立即記錄時間戳（負值），與 Dijkstra_02_26.py 一致
            self.link_delay_measurement.temp_lldp_link_delay[(switch_a, switch_b)] = 0 - (time.time() * 1000)
            
            return True
            
        except Exception as e:
            print(f"[LLDP] Error sending LLDP packet: {e}")
            return False


    def send_echo_for_delay_detection(self, switch_a, switch_b, datapaths):
        """
        發送 Echo Request 用於延遲偵測，並記錄發送時間戳
        
        Args:
            switch_a: 源 switch dpid
            switch_b: 目標 switch dpid
            datapaths: datapath 字典，用於取得 datapath 物件
        
        Returns:
            bool: 是否成功發送
        """
        if switch_a not in datapaths:
            print(f"[Echo] Datapath not found for switch {switch_a}")
            return False
        
        try:
            datapath = datapaths[switch_a]
            ofp_parser = datapath.ofproto_parser
            echo_req = ofp_parser.OFPEchoRequest(datapath, data=None)
            datapath.send_msg(echo_req)
            
            # 在發送後立即記錄發送時間戳（記為負值）
            self.link_delay_measurement.temp_echo_link_delay[(switch_a, switch_b)] = 0 - (time.time() * 1000)
            
            return True
            
        except Exception as e:
            print(f"[Echo] Error sending Echo Request: {e}")
            return False


    def handle_echo_reply_event(self, dpid):
        """
        處理 Echo Reply 事件（當 switch 回覆 Echo时調用）
        
        Args:
            dpid: 發送 Echo Reply 的 switch DPID
        """
        self.link_delay_measurement.handle_echo_reply(dpid)
