# -*- coding: utf-8 -*-
"""
link_status.py - 鏈路狀態判斷模組

根據頻寬使用率判斷 link 的狀態：
- LOW (0-20%): 低負載
- NORMAL (20-60%): 正常
- HIGH (60-80%): 高負載
- OVERLOAD (80-100%): 超載
"""

class Link_Status:
    # 狀態定義
    def __init__(self, app):
        self.app = app
        self.STATUS_SN = "SN"
        self.STATUS_LOW = "LOW"
        self.STATUS_NORMAL = "NORMAL"
        self.STATUS_HIGH = "HIGH"
        self.STATUS_OVERLOAD = "OVERLOAD"

        # 狀態閾值（百分比）
        self.THRESHOLD_SN_TO_LOW = 1
        self.THRESHOLD_LOW_TO_NORMAL = 20
        self.THRESHOLD_NORMAL_TO_HIGH = 60
        self.THRESHOLD_HIGH_TO_OVERLOAD = 80

        # 儲存所有 link 的狀態
        # {(src_dpid, dst_dpid): status}
        self.link_status_map = {}


    def get_link_status(self, usage_percent):
        """
        根據使用率百分比判斷 link 狀態
        
        Args:
            usage_percent: 頻寬使用率百分比 (0-100)
        
        Returns:
            str: 狀態字符串 (SN, LOW, NORMAL, HIGH, OVERLOAD)
        """
        if usage_percent < self.THRESHOLD_SN_TO_LOW:
            return self.STATUS_SN
        elif usage_percent < self.THRESHOLD_LOW_TO_NORMAL:
            return self.STATUS_LOW
        elif usage_percent < self.THRESHOLD_NORMAL_TO_HIGH:
            return self.STATUS_NORMAL
        elif usage_percent < self.THRESHOLD_HIGH_TO_OVERLOAD:
            return self.STATUS_HIGH
        else:
            return self.STATUS_OVERLOAD


    def update_link_status(self, src_dpid, dst_dpid, usage_percent):
        """
        更新 link 的狀態
        
        Args:
            src_dpid: 源 switch DPID
            dst_dpid: 目標 switch DPID
            usage_percent: 頻寬使用率百分比
        """
        status = self.get_link_status(usage_percent)
        key = (src_dpid, dst_dpid)
        self.link_status_map[key] = {
            'status': status,
            'usage_percent': usage_percent
        }


    def get_all_link_status(self):
        """
        取得所有 link 的狀態
        
        Returns:
            dict: {(src_dpid, dst_dpid): {'status': status, 'usage_percent': percent}}
        """
        return dict(self.link_status_map)


    def get_link_status_by_dpid(self, src_dpid, dst_dpid):
        """
        取得特定 link 的狀態
        
        Args:
            src_dpid: 源 switch DPID
            dst_dpid: 目標 switch DPID
        
        Returns:
            dict: {'status': status, 'usage_percent': percent} 或 None
        """
        key = (src_dpid, dst_dpid)
        return self.link_status_map.get(key)


    def count_links_by_status(self):
        """
        統計各狀態的 link 數量
        
        Returns:
            dict: {'SN': count, 'LOW': count, 'NORMAL': count, 'HIGH': count, 'OVERLOAD': count}
        """
        counts = {
            self.STATUS_SN: 0,
            self.STATUS_LOW: 0,
            self.STATUS_NORMAL: 0,
            self.STATUS_HIGH: 0,
            self.STATUS_OVERLOAD: 0
        }
        
        for info in self.link_status_map.values():
            status = info['status']
            if status in counts:
                counts[status] += 1
        
        return counts


    def get_status_color_code(self, status):
        """
        取得狀態對應的顏色代碼（用於日誌美化）
        
        Args:
            status: 狀態字符串
        
        Returns:
            str: ANSI 顏色代碼
        """
        color_map = {
            self.STATUS_LOW: '\033[92m',        # 綠色
            self.STATUS_NORMAL: '\033[94m',     # 藍色
            self.STATUS_HIGH: '\033[93m',       # 黃色
            self.STATUS_OVERLOAD: '\033[91m',   # 紅色
            self.STATUS_SN: '\033[90m'          # 灰色
        }
        return color_map.get(status, '')


    def get_status_description(self, status):
        """
        取得狀態的描述文字
        
        Args:
            status: 狀態字符串
        
        Returns:
            str: 描述文字
        """
        desc_map = {
            self.STATUS_LOW: "低負載",
            self.STATUS_NORMAL: "正常",
            self.STATUS_HIGH: "高負載",
            self.STATUS_OVERLOAD: "超載",
            self.STATUS_SN: "SN"
        }
        return desc_map.get(status, "未知")


    def clear_link_status(self):
        """清除所有狀態紀錄"""
        self.link_status_map.clear()
