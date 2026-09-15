# -*- coding: utf-8 -*-
"""
packet_handler_v1.py - Packet-In 未知流量處理（v1，現行版本）

把 DTM.py 的 unknown_TCP_packet／unknown_UDP_packet／_apply_packet_algorithm／
unknown_ICMP_packet／unknown_IPv4_packet／unknown_IPv6_packet 整批打包成一個
版本化的模組，對應 DTM.py 既有的 ROUTING_ALGORITHM 切換慣例：DTM.py 開頭的
PACKET_HANDLER 常數決定要 import 哪個版本，DTM.py 的 _packet_in_handler 只
負責依 ethertype/協定分派給正確的方法（大方向），實際「收到 TCP/UDP/ICMP/
IPv4/IPv6 封包該怎麼處理」的完整邏輯都在這個檔案裡。

之後要調整封包處理邏輯（例如把 TCP/UDP 合併成同一份、改節流策略），直接改
這個檔案，或是複製一份寫成 packet_handler_v2.py，改 DTM.py 的 PACKET_HANDLER
常數切換版本——v1 保留不動，隨時可以切回來。

使用方式：
    self.packet_handler = PacketHandlerV1(
        self, ENABLE_ROUTING, ROUTING_ALGORITHM,
        PACKET_ALGORITHM_TCP, PACKET_ALGORITHM_UDP,
        PACKET_ALGORITHM_ICMP, PACKET_ALGORITHM_IPV4, PACKET_ALGORITHM_IPV6,
    )                                                    # DTM.py __init__ 建立
    self.packet_handler.unknown_TCP_packet(datapath, pkt)  # _packet_in_handler 呼叫
"""

from ryu.lib.packet import ethernet


class PacketHandlerV1:
    def __init__(self, app, enable_routing, routing_algorithm,
                 algorithm_tcp, algorithm_udp, algorithm_icmp, algorithm_ipv4, algorithm_ipv6):
        self.app = app
        self.enable_routing = enable_routing
        self.routing_algorithm = routing_algorithm
        self.algorithm_tcp = algorithm_tcp
        self.algorithm_udp = algorithm_udp
        self.algorithm_icmp = algorithm_icmp
        self.algorithm_ipv4 = algorithm_ipv4
        self.algorithm_ipv6 = algorithm_ipv6

    # ============================================
    # TCP / UDP：跟路由演算法綁在一起的封包准入邏輯
    # ============================================
    def unknown_TCP_packet(self, datapath, pkt_data):
        eth = pkt_data.get_protocol(ethernet.ethernet)
        if not eth:
            return

        pair = (eth.src, eth.dst)
        count = self.app.tcp_throttle.should_process(pair)
        if count is None:
            return  # 節流跳過

        # ★ 已有 active flow，不重複計算
        if pair in self.app.flow_registry.active_flows:
            return

        # === 以下才是真正的處理邏輯 ===
        self.app.logger.debug(f"[UNKNOWN_TCP] switch {datapath.id}, pair {pair}, count {count}")

        if self.enable_routing and self.routing_algorithm == '2014':
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

                self.app.routing_module.calculate_and_install_path(
                    src_mac=eth.src,
                    dst_mac=eth.dst,
                )
            except Exception as e:
                self.app.logger.error(f"[UNKNOWN_TCP] 路由計算失敗: {e}")
        elif self.routing_algorithm in ('2020', 'dijkstra', 'self', 'sorted'):
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

                if src_mac not in self.app.host_macs or dst_mac not in self.app.host_macs:
                    return

                if src_mac and dst_mac:
                    switch_path = self.app.routing_module.admit_flow(src_mac, dst_mac)

                    if switch_path and len(switch_path) >= 1:
                        path = self.app.build_path_with_ports(switch_path, src_mac, dst_mac)

                        if path:
                            _prio = self.app._get_next_flow_priority(src_mac, dst_mac)
                            self.app.install_flows_for_path(path, src_mac, dst_mac, priority=_prio, idle_timeout=5)
                            if (src_mac, dst_mac) in self.app.flow_registry.active_flows:
                                self.app.flow_registry.active_flows[(src_mac, dst_mac)]['priority'] = _prio
                            _first_sw, _first_in, _first_out = path[0]
                            print(f"[{self.routing_algorithm} Routing TCP] {src_mac} -> {dst_mac}: path {switch_path} | sw={_first_sw} in_port={_first_in} out_port={_first_out} priority={_prio}")
                        else:
                            print(f"[{self.routing_algorithm} Routing TCP] 無法轉換路徑信息: {switch_path}")
                    else:
                        print(f"[{self.routing_algorithm} Routing TCP] 無法為 {src_mac} -> {dst_mac} 找到路徑")
                else:
                    print(f"[{self.routing_algorithm} Routing TCP] 無法轉換 MAC: {src_mac} -> {dst_mac}")

            except Exception as e:
                self.app.logger.error(f"[{self.routing_algorithm} Routing TCP] 路由計算失敗: {e}")

        else:
            self._apply_packet_algorithm(self.algorithm_tcp, datapath, pkt_data, 'TCP')

    def unknown_UDP_packet(self, datapath, pkt_data):
        eth = pkt_data.get_protocol(ethernet.ethernet)
        if not eth:
            return

        pair = (eth.src, eth.dst)
        count = self.app.udp_throttle.should_process(pair)
        if count is None:
            return  # 節流跳過

        # ★ 已有 active flow，不重複計算
        if pair in self.app.flow_registry.active_flows:
            return

        # === 以下才是真正的處理邏輯 ===
        print(f"[UNKNOWN_UDP] switch {datapath.id}, pair {pair}, count {count}")
        self.app.logger.debug(f"[UNKNOWN_UDP] switch {datapath.id}, pair {pair}, count {count}")

        if self.enable_routing and self.routing_algorithm == '2014':
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

                self.app.routing_module.calculate_and_install_path(
                    src_mac=eth.src,
                    dst_mac=eth.dst,
                )
            except Exception as e:
                self.app.logger.error(f"[UNKNOWN_UDP] 路由計算失敗: {e}")
        elif self.routing_algorithm in ('2020', 'dijkstra', 'self', 'sorted'):
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

                if src_mac not in self.app.host_macs or dst_mac not in self.app.host_macs:
                    return

                if src_mac and dst_mac:
                    # 呼叫 DTM 模組選擇路徑
                    switch_path = self.app.routing_module.admit_flow(src_mac, dst_mac)

                    if switch_path and len(switch_path) >= 1:
                            path = self.app.build_path_with_ports(switch_path, src_mac, dst_mac)

                            if path:
                                _prio = self.app._get_next_flow_priority(src_mac, dst_mac)
                                self.app.install_flows_for_path(path, src_mac, dst_mac, priority=_prio, idle_timeout=5)
                                if (src_mac, dst_mac) in self.app.flow_registry.active_flows:
                                    self.app.flow_registry.active_flows[(src_mac, dst_mac)]['priority'] = _prio
                                _first_sw, _first_in, _first_out = path[0]
                                print(f"[{self.routing_algorithm} Routing UDP] {src_mac} -> {dst_mac}: path {switch_path} | sw={_first_sw} in_port={_first_in} out_port={_first_out} priority={_prio}")
                            else:
                                print(f"[{self.routing_algorithm} Routing UDP] 無法轉換路徑信息: {switch_path}")
                    else:
                        print(f"[{self.routing_algorithm} Routing UDP] 無法為 {src_mac} -> {dst_mac} 找到路徑")
                else:
                    print(f"[{self.routing_algorithm} Routing UDP] 無法轉換 MAC: {src_mac} -> {dst_mac}")

            except Exception as e:
                import traceback
                print(f"[{self.routing_algorithm} Routing UDP] 路由計算失敗: {e}")
                traceback.print_exc()
        else:
            self._apply_packet_algorithm(self.algorithm_udp, datapath, pkt_data, 'UDP')

    # ============================================
    # 演算法處理方法
    # ============================================
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

    # ============================================
    # 未定義流量的 Hook 處理（可擴展設計）
    # ============================================
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
