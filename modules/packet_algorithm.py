# -*- coding: utf-8 -*-
"""
packet_algorithm.py - 未定義流量的演算法開關處理

從 DTM.py 抽出的 _apply_packet_algorithm 與 ICMP/IPv4/IPv6 三個 unknown packet
hook。這三種封包類型目前的處理策略都是 PACKET_ALGORITHM_ICMP/IPV4/IPV6= 'DROP'
（見 DTM.py 開頭設定），_apply_packet_algorithm 大部分分支還是空殼（FLOOD/
DYNAMIC_ROUTING 尚未實作）。TCP/UDP 的 unknown packet 處理邏輯跟路由演算法
（admit_flow 等）緊密綁在一起，仍留在 DTM.py，只有呼叫 _apply_packet_algorithm
那一行改呼叫這個模組。

使用方式：
    self.packet_algorithm = PacketAlgorithm(self, PACKET_ALGORITHM_ICMP,
                                             PACKET_ALGORITHM_IPV4, PACKET_ALGORITHM_IPV6)
    self.packet_algorithm.unknown_ICMP_packet(datapath, pkt)   # _packet_in_handler 呼叫
"""


class PacketAlgorithm:
    def __init__(self, app, algorithm_icmp, algorithm_ipv4, algorithm_ipv6):
        self.app = app
        self.algorithm_icmp = algorithm_icmp
        self.algorithm_ipv4 = algorithm_ipv4
        self.algorithm_ipv6 = algorithm_ipv6

    def _apply_packet_algorithm(self, algorithm, datapath, pkt, packet_type):
        """根據演算法類型執行相應的處理邏輯"""
        if algorithm == 'DROP':
            # 丟棄封包（不轉發）
            pass

        elif algorithm == 'FLOOD':
            # 轉發到所有埠（flooding）
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            # pkt 在這裡是 Packet 物件，需要從 _packet_in_handler 傳遞 msg

        elif algorithm == 'LOG_ONLY':
            # 只記錄，不轉發
            pass

        elif algorithm == 'DYNAMIC_ROUTING':
            # 使用動態路由（Dijkstra）
            # TODO: 在此實作動態路由邏輯
            pass

        else:
            pass

    def unknown_ICMP_packet(self, datapath, pkt_data):
        """處理未定義的 ICMP 流量 - 根據全域演算法開關觸發"""
        print(f"[UNKNOWN_ICMP] 收到未定義的 ICMP 封包，來自 switch {datapath.id}")
        self._apply_packet_algorithm(self.algorithm_icmp, datapath, pkt_data, 'ICMP')

    def unknown_IPv4_packet(self, datapath, pkt_data):
        """處理其他未定義的 IPv4 流量 - 根據全域演算法開關觸發"""
        print(f"[UNKNOWN_IPv4] 收到其他類型的未定義 IPv4 封包，來自 switch {datapath.id}")
        self._apply_packet_algorithm(self.algorithm_ipv4, datapath, pkt_data, 'IPv4')

    def unknown_IPv6_packet(self, datapath, pkt_data):
        """處理未定義的 IPv6 流量 - 根據全域演算法開關觸發"""
        self._apply_packet_algorithm(self.algorithm_ipv6, datapath, pkt_data, 'IPv6')
