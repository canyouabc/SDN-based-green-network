# -*- coding: utf-8 -*-
"""
path_installer.py - 路徑轉 port 資訊 + OpenFlow 流表安裝/刪除

從 DTM.py 抽出的 build_path_with_ports / install_flows_for_path /
remove_flows_for_path：把 dpid 序列轉成帶 port 資訊的 path，再把 path 轉成
正向＋反向兩條 OpenFlow rule 下發（或刪除）到對應 switch。

build_path_with_ports / install_flows_for_path 是 RoutingHost Protocol 的成員
（見 modules/routing_host.py），routing 模組直接呼叫 self.app.build_path_with_ports(...)／
self.app.install_flows_for_path(...)，所以 DTM.py 仍保留這兩個同名 wrapper。
remove_flows_for_path 目前沒有任何呼叫者（DTM.py 內外都沒有），純粹搬過來，
不留 wrapper——如果之後要用，直接呼叫 self.path_installer.remove_flows_for_path(...)。

使用方式：
    self.path_installer = PathInstaller(self, FLOW_BASE_PRIORITY)   # DTM.py __init__ 建立
    self.path_installer.build_path_with_ports(switch_path, src_mac, dst_mac)
    self.path_installer.install_flows_for_path(path, src_mac, dst_mac, priority)
"""


class PathInstaller:
    def __init__(self, app, base_priority):
        self.app = app
        self.base_priority = base_priority

    def build_path_with_ports(self, switch_path, src_mac, dst_mac):
        """將 switch_path (dpid序列) 轉換成帶有 port 資訊的 path"""
        path = []

        if len(switch_path) == 1:
            first_sw = switch_path[0]
            host_in_port = self.app.host_macs[src_mac][1]
            host_out_port = self.app.host_macs[dst_mac][1]
            path.append((first_sw, host_in_port, host_out_port))
        else:
            # 第一個 switch
            first_sw = switch_path[0]
            host_in_port = self.app.host_macs[src_mac][1]
            out_port = self.app.adjacency[first_sw][switch_path[1]]
            if out_port is None:
                return None
            path.append((first_sw, host_in_port, out_port))

            # 中間的 switch
            for i in range(1, len(switch_path) - 1):
                sw_dpid = switch_path[i]
                in_port = self.app.adjacency[sw_dpid][switch_path[i-1]]
                out_port = self.app.adjacency[sw_dpid][switch_path[i+1]]
                if in_port is None or out_port is None:
                    return None
                path.append((sw_dpid, in_port, out_port))

            # 最後一個 switch
            last_sw = switch_path[-1]
            in_port = self.app.adjacency[last_sw][switch_path[-2]]
            if in_port is None:
                return None
            host_out_port = self.app.host_macs[dst_mac][1]
            path.append((last_sw, in_port, host_out_port))

        return path

    # 主动安装流表，不依赖packet_in事件，但感覺可以寫得更彈性一些
    def install_flows_for_path(self, path, src_mac, dst_mac, priority, hard_timeout=0, idle_timeout=0):
        """主动安装流表，不依赖packet_in事件"""
        for sw_dpid, in_port, out_port in path:
            if sw_dpid not in self.app.datapaths:
                print(f"Warning: Switch {sw_dpid} not found")
                continue

            datapath = self.app.datapaths[sw_dpid]
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

    def remove_flows_for_path(self, path, src_mac, dst_mac, priority=None):
        """主動刪除流表。OFPFC_DELETE_STRICT 需指定 priority 才能精確比對。"""
        if priority is None:
            priority = self.base_priority
        for sw_dpid, in_port, out_port in path:
            if sw_dpid not in self.app.datapaths:
                print(f"Warning: Switch {sw_dpid} not found")
                continue

            datapath = self.app.datapaths[sw_dpid]
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
