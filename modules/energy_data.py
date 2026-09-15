# -*- coding: utf-8 -*-
"""
energy_data.py - 能耗/頻寬設定檔讀取 + 節能統計

從 DTM.py 抽出的 load_switch_energy / load_link_txt / calculate_energy_saving_from_flows：
啟動時讀 data/switch_energy.txt、data/link_energy.txt、data/link_bw.txt 建立能耗/頻寬表，
並提供「目前 active flows 覆蓋了多少 switch/link」對照初始總能耗算出節能百分比。

switch_energy / link_energy / link_bw 是 RoutingHost Protocol 的屬性（routing 模組
直接讀 self.app.switch_energy 這種 dict，不是呼叫方法），所以 DTM.py 的 __init__
仍會把這三個 dict 的參照掛回 self.switch_energy 等屬性上，維持 Protocol 不變。
initial_switch_energy / initial_link_energy 只有 calculate_energy_saving_from_flows
自己用，不對外露出。

使用方式：
    self.energy_data = EnergyData(self)          # DTM.py __init__ 建立
    self.switch_energy = self.energy_data.switch_energy
    self.link_energy   = self.energy_data.link_energy
    self.link_bw        = self.energy_data.link_bw
    self.energy_data.calculate_energy_saving_from_flows()
"""

import logging

# DTM.py 在 import 這個模組之前已經設定好 "energy" logger 的 handler
# （見 DTM.py 開頭的 Logger 區塊），這裡用同名字取得的是同一個 logger 物件。
energy_logger = logging.getLogger("energy")


class EnergyData:
    def __init__(self, app,
                 switch_energy_path='data/switch_energy.txt',
                 link_energy_path='data/link_energy.txt',
                 link_bw_path='data/link_bw.txt'):
        self.app = app
        self.switch_energy = self._load_switch_energy(switch_energy_path)
        # link_energy 與 link_bw 的 key 是 (src_dpid, dst_dpid)，value 分別是能耗與帯寶
        # 因為相同格式，所以共用同一個載入函數 _load_link_txt
        self.link_energy = self._load_link_txt(link_energy_path)
        self.link_bw = self._load_link_txt(link_bw_path)

        self.initial_switch_energy = dict(self.switch_energy)
        self.initial_link_energy = dict(self.link_energy)

    def _load_switch_energy(self, filepath):
        data = {}
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    dpid   = int(parts[0])
                    energy = int(parts[2])
                    data[dpid] = energy
            print(f"*** Switch 能耗設定載入成功，共 {len(data)} 個 switch")
        except FileNotFoundError:
            print(f"*** 找不到 {filepath}")
        return data

    def _load_link_txt(self, filepath):
        # filepath 應該是完整路徑，例如 'data/link_energy.txt'
        data = {}
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    src = int(parts[0])
                    dst = int(parts[1])
                    val = float(parts[2])
                    data[(src, dst)] = val
                    data[(dst, src)] = val   # ← 補上雙向
        except FileNotFoundError:
            print(f"[警告] 找不到 {filepath}")
        return data

    def calculate_energy_saving_from_flows(self):
        active_flows = self.app.get_active_flows()

        # 從 active_flows 推導出 active_switches 和 active_links
        active_switches = set()
        active_links = set()

        for host_a, host_b, path in active_flows:
            for dpid in path:
                active_switches.add(dpid)
            for i in range(len(path) - 1):
                active_links.add((path[i], path[i+1]))

        # 以下跟原本一樣
        # initial_link_energy 裡每條實體連線存了 (u,v) 跟 (v,u) 兩筆（方便雙向查詢），
        # 加總前要先去重成唯一的無向連線 (min(u,v), max(u,v))，否則每條連線的能耗會被算兩次。
        unique_links = {(min(u, v), max(u, v)) for (u, v) in self.initial_link_energy}
        total_energy = sum(self.initial_switch_energy.values()) + \
                    sum(self.initial_link_energy[link] for link in unique_links)

        used_sw_energy   = sum(self.initial_switch_energy.get(n, 0)
                            for n in active_switches)
        unique_active_links = {(min(u, v), max(u, v)) for (u, v) in active_links}
        used_link_energy = sum(self.initial_link_energy.get(link, 0)
                            for link in unique_active_links)
        current_energy   = used_sw_energy + used_link_energy

        saving  = total_energy - current_energy
        percent = saving / total_energy * 100

        print(f"===== 能耗統計 ===== 節省能耗：{saving:.2f} W ({percent:.1f}%)")
        energy_logger.info(f"ENERGY saving={saving:.2f}W percent={percent:.1f}%")

        return saving, percent
