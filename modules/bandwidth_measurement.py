    # -*- coding: utf-8 -*-
"""
bandwidth_measurement.py - 頻寬使用率量測模組

透過 PortStats Request/Reply 計算每條 link 的頻寬使用率
"""

import time
from collections import defaultdict

class Bandwidth_Measurement:
    def __init__(self, app):
        self.app = app
        # 暫存埠統計資訊（用於計算增量）
        # {(dpid, port_no): {'tx_bytes': bytes, 'timestamp': timestamp}}
        self.port_stats_cache = defaultdict(lambda: {'tx_bytes': 0, 'timestamp': 0})

        # 頻寬使用率紀錄
        # {(src_dpid, dst_dpid, out_port): usage_percent}
        self.bandwidth_usage = {}


    def send_port_stats_request(self, datapath):
        """
        發送 PortStats Request 到指定 switch
        
        Args:
            datapath: Ryu datapath 物件
        
        Returns:
            bool: 是否成功發送
        """
        try:
            ofproto = datapath.ofproto
            ofproto_parser = datapath.ofproto_parser
            
            # 發送埠統計請求（port_no=OFPP_ANY 表示所有埠）
            req = ofproto_parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
            datapath.send_msg(req)
            
            return True
            
        except Exception as e:
            print(f"[BW] Error sending PortStats Request to {datapath.id}: {e}")
            return False


    def handle_port_stats_reply(self, dpid, port_stats_list, link_bw):
        """
        處理 PortStats Reply 並計算頻寬使用率
        
        Args:
            dpid: Switch DPID
            port_stats_list: 埠統計資料列表
            link_bw: link_bw 字典 {(src_dpid, dst_dpid): bandwidth}
        
        Returns:
            dict: {(src_dpid, dst_dpid): usage_percent} 的字典
        """
        result = {}
        current_time = time.time()
        
        try:
            for stat in port_stats_list:
                port_no = stat.port_no
                tx_bytes = stat.tx_bytes
                
                cache_key = (dpid, port_no)
                prev_stats = self.port_stats_cache[cache_key]
                prev_tx_bytes = prev_stats['tx_bytes']
                prev_time = prev_stats['timestamp']
                
                # 第一次沒有前一次的資訊，跳過計算
                if prev_time == 0:
                    self.port_stats_cache[cache_key]['tx_bytes'] = tx_bytes
                    self.port_stats_cache[cache_key]['timestamp'] = current_time
                    continue
                
                # 計算字節增量和時間差
                bytes_diff = tx_bytes - prev_tx_bytes
                time_diff = current_time - prev_time
                
                # 避免時間為0的情況
                if time_diff <= 0:
                    self.port_stats_cache[cache_key]['tx_bytes'] = tx_bytes
                    self.port_stats_cache[cache_key]['timestamp'] = current_time
                    continue
                
                # 計算吞吐量（bytes/sec）
                throughput_bps = (bytes_diff / time_diff) * 8  # 轉換為 bits/sec
                
                # 從 link_bw 查詢該埠對應的 link 容量
                # 這需要根據拓撲資訊推斷，暫存在 bandwidth_usage 中供後續查詢
                self.bandwidth_usage[(dpid, port_no)] = {
                    'tx_bytes': tx_bytes,
                    'throughput_bps': throughput_bps,
                    'timestamp': current_time
                }
                
                result[(dpid, port_no)] = {
                    'tx_bytes': tx_bytes,
                    'throughput_bps': throughput_bps
                }
                
                # 更新快取
                self.port_stats_cache[cache_key]['tx_bytes'] = tx_bytes
                self.port_stats_cache[cache_key]['timestamp'] = current_time
            
            return result
            
        except Exception as e:
            print(f"[BW] Error handling PortStats Reply for switch {dpid}: {e}")
            return {}


    def calculate_bandwidth_usage_percent(self, dpid, port_no, link_bw, adjacency):
        """
        計算特定埠的頻寬使用率百分比
        
        Args:
            dpid: Switch DPID
            port_no: 埠編號
            link_bw: {(src_dpid, dst_dpid): bw} 字典
            adjacency: 拓撲鄰接表
        
        Returns:
            float: 使用率百分比 (0-100)，如果無法計算返回 None
        """
        key = (dpid, port_no)
        
        if key not in self.bandwidth_usage:
            return None
        
        stats = self.bandwidth_usage[key]
        throughput_bps = stats['throughput_bps']
        
        # 尋找該埠連接到的下一個 switch
        # 根據 adjacency 判斷
        dst_dpid = None
        for neighbor, port in self.adjacency[dpid].items():
            if port == port_no:
                dst_dpid = neighbor
                break
        
        if dst_dpid is None:
            return None
        
        # 查詢 link 的容量
        link_key = (dpid, dst_dpid)
        if link_key not in link_bw:
            return None
        
        capacity_bps = link_bw[link_key] * 1e9  # 轉換為 bits/sec（假設輸入是 Gbps）
        
        if capacity_bps == 0:
            return None
        
        usage_percent = (throughput_bps / capacity_bps) * 100
        
        return usage_percent


    def get_all_bandwidth_usage(self):
        """
        取得所有已量測的頻寬使用率
        
        Returns:
            dict: 全部的頻寬使用率紀錄
        """
        return dict(self.bandwidth_usage)


    def clear_bandwidth_stats(self):
        """清除所有頻寬統計資訊"""
        self.bandwidth_usage.clear()
        self.port_stats_cache.clear()
