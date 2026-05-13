# -*- coding: utf-8 -*-
"""
routing_2014.py - 被動式路由模組 (2014 版本)

此模組提供 on-demand 的路由計算功能
在 packet_in TCP/UDP 事件觸發時，動態計算最短路徑並安裝流表
使用 Dijkstra_2014 演算法
"""

from ryu.lib import hub
from .pure_Dijkstra import Pure_Dijkstra

class Routing_2014:
    def __init__(self, app):
         self.app = app
         self.pure_dijkstra = Pure_Dijkstra(self)
    def calculate_and_install_path(
        self,
        src_mac,
        dst_mac,
        required_bw=0,
    ):
        """
        被動式路由計算 - 在 packet_in 事件時觸發
        
        Args:
            src_mac: 源 MAC 位址
            dst_mac: 目的地 MAC 位址
            myswitches: 全部 switch dpid 列表
            adjacency: 拓撲鄰接表
            link_delay: link 延遲字典
            link_energy: link 能耗字典
            link_bw: link 帶寬字典
            link_used_bw: link 已用帶寬字典
            switch_energy: switch 能耗字典
            host_macs: host MAC → (dpid, port) 的對應
            get_link_delay_func: 查詢 link 延遲的函數
            install_flows_for_path_func: 安裝流表的函數
            required_bw: 所需頻寬（Mbps）
        
        Returns:
            path 或 None（如果無可用路徑）
        """
        
        # 檢查源目 MAC 是否存在
        if src_mac not in self.app.host_macs or dst_mac not in self.app.host_macs:
            print(f"[2014_Dijkstra] MAC 對應不存在: {src_mac} -> {dst_mac}")
            return None
        
        src_dpid, src_port = self.app.host_macs[src_mac]
        dst_dpid, dst_port = self.app.host_macs[dst_mac]
        
        print(f"[2014_Dijkstra] 計算路徑: {src_mac}({src_dpid}) -> {dst_mac}({dst_dpid})")
        
        # ← 計算正向路徑
        result_forward = self.pure_dijkstra.get_min_delay_path(
            src_dpid, dst_dpid,
            src_port, dst_port,
            self.app.myswitches, self.app.adjacency, self.app.link_delay, self.app.link_energy, self.app.link_bw,
            self.app.link_used_bw, self.app.switch_energy, self.app.get_link_delay_func,
            required_bw=required_bw
        )
        
        if not result_forward:
            print(f"[2014_Dijkstra] 無可用路徑: {src_mac} -> {dst_mac}")
            return None
        
        p_forward, path_forward = result_forward
        
        # ← 計算反向路徑
        result_backward = self.pure_dijkstra.get_min_delay_path(
            dst_dpid, src_dpid,
            dst_port, src_port,
            self.app.myswitches, self.app.adjacency, self.app.link_delay, self.app.link_energy, self.app.link_bw,
            self.app.link_used_bw, self.app.switch_energy, self.app.get_link_delay_func,
            required_bw=required_bw
        )
        
        # 安裝正向流表
        print(f"[2014_Dijkstra] 安裝正向流表: {src_mac} -> {dst_mac}")
        self.app.install_flows_for_path(p_forward, src_mac, dst_mac, 3, 10)
        
        # 安裝反向流表（如果存在）
        if result_backward:
            p_backward, path_backward = result_backward
            print(f"[2014_Dijkstra] 安裝反向流表: {dst_mac} -> {src_mac}, 路徑: {path_backward}")
            self.app.install_flows_for_path(p_backward, dst_mac, src_mac, 3, 10)
            print(f"[2014_Dijkstra] 反向流表已安裝")
        else:
            print(f"[2014_Dijkstra] 警告：無反向路徑從 {dst_mac} ({dst_dpid}) 到 {src_mac} ({src_dpid})")
        
        return p_forward

