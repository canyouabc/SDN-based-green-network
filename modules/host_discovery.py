# -*- coding: utf-8 -*-
"""
host_discovery.py — 2026-09-11 已驗證可用，取代手動 sendarp

L2 曾經在 cap_topo.py 這種有迴圈的網狀拓撲上造成永久性廣播風暴（見下方
「為什麼曾被擱置」）。根因已在 DTM.py 修好（ARP 封包處理段落的 return
移出 REQUEST 判斷之外，ARP_REPLY 不再落入 OFPP_FLOOD）。開 Mininet 全程
不打 sendarp，[LINK_READY] 後 L2 自動送出 ARP probe，log 無異常洗版，
iperf 直接成功——完整實測通過（cap_topo.py，45 switch）。

── 原本想解決的問題 ──────────────────────────────────────────────
DTM.py 的路由 / ARP 代理都要靠 self.app.host_macs（{mac: (dpid, port)}）
才能動作。這張表目前靠 get_host()（Ryu topology 模組）被動學習——host 要
先送過封包才會被看到。sendarp（send_arp.py）是讓每個 host 互相 arping，
逼 host 集體送封包，controller 才能一次認齊，但需要人在 Mininet CLI
手動打這個指令，容易忘記。

── 為什麼曾被擱置：L2（主動 ARP 掃描）曾引發網路風暴，已實測、已修 ──
L2 送出的 ARP probe，host 依協議規定回覆後，這個回覆是「真實 host 發出、
正常走過 switch flow table」的封包（跟 _handle_arp_request 那種
controller 用 OFPPacketOut 直接注入、繞過 flow table 的回覆不同）。
因為回覆的目的地 mac 是探測時編造的假位址，DTM.py 既有的 packet_in
handler 認不得它，opcode 也不是 ARP_REQUEST，會直接掉到最後的
fallback 邏輯 → OFPP_FLOOD（DTM.py:1473，無任何防迴圈機制）。

cap_topo.py 的 core switch 是完全網狀互連（見 cap_topo.py 的
core <-> core 段），是個有迴圈的拓撲。2026-09-11 實測：只要有 host
回覆 probe，這個 flood 就會在 core mesh 裡永久循環（Ethernet 無 TTL，
不會自然消失），導致整個網路癱瘓，連事後手動 sendarp 都救不回來，
只能 sudo mn -c 重置。

這其實暴露了 DTM.py 本體的既有地雷（任何「沒被前面 if 攔到」的封包
一律 flood、無防迴圈），不是 host_discovery 特有的問題，只是這裡
第一個踩到——因為平常 host 主動送的 ARP/TCP/UDP/ICMP 都有專屬 handler
會提早 return，從沒東西真的掉到最後的 fallback 過。

**根因已修**（2026-09-11）：ARP 封包處理段落的 return 移出 REQUEST
判斷之外，讓 ARP_REPLY 也提早結束、不再落到 flood。這個代理 ARP 架構下
正常操作幾乎不會出現 ARP_REPLY，補這個 return 沒有功能損失，已用手動
sendarp + iperf 驗證無回歸。**`OFPP_FLOOD` 這個 fallback 機制本身
是否該整個存在，是更大範圍的獨立問題**（這個拓撲是封閉系統，理論上
不該有任何「不知道要送去哪」的封包；FLOOD 分支裡還夾雜 VLAN/LLDP
計數邏輯，要拔掉沒辦法簡單刪，需要先盤點——留給日後「系統性檢驗
DTM.py」處理，不影響這裡已經做的 ARP fallthrough 修正）。

── 四層 fallback 設計（只有 L1、L2 是這個檔案的責任）───────────────
    L1  讀 data/host_table.json（若存在——目前沒有任何 topo 腳本會產生
        這個檔案，是留給未來「topo 腳本啟動時自己把表寫出來」的快路徑；
        本身不送任何封包，不會觸發上述風暴，是相對安全、值得優先做的
        方向）
    L2  主動 ARP 掃描（根因已修，2026-09-11 實測通過，正式啟用）
    L3  現有的 get_host() 被動輪詢（_monitor 迴圈本來就在跑，不用這裡管）
    L4  人工 sendarp（Mininet CLI 指令，永遠可用，不用這裡管。上次事故
        發生後靠這條路徑 + sudo mn -c 重置就恢復正常，證明分層設計本身
        沒問題，出事的只有 L2 這一層的具體實作）
"""

import json
import os

from ryu.lib.packet import packet, ethernet, arp, ether_types
from ryu.topology.api import get_switch


# ── 可調常數 ──────────────────────────────────────────────────────
HOST_TABLE_PATH = 'data/host_table.json'

# 全專案所有 topo 腳本（cap_topo.py / grid_topo*.py / geant_topo.py）
# 目前都用同一個定址慣例；未來若有新拓撲用別的網段，加進這個清單即可，
# 不需要改架構。
HOST_DISCOVERY_SUBNETS = [
    ('10.0.0.', range(1, 255)),   # 10.0.0.1 ~ 10.0.0.254
]

# ARP probe 用的假來源位址（RFC 5227 Address Probe 慣例：src_ip=0.0.0.0）。
# 被問到的 host 依協議規定仍必須回覆，回覆時目的地 mac 是否「真實存在」
# 不影響 DTM.py 既有的「ARP 一律送 controller」規則（那條規則只看
# eth_type，不看目的地 mac）。
PROBE_SRC_MAC = 'ee:ee:ee:ee:ee:ee'

# 端口號超過這個值視為 OpenFlow 保留埠（OFPP_* 系列都是超大數字），
# 不當作候選 host port。這幾個拓撲從沒有超過幾十個 port 的 switch。
_MAX_PLAUSIBLE_PORT_NO = 1000


class HostDiscovery:
    def __init__(self, app):
        self.app = app

    # =========================================================
    # 入口
    # =========================================================

    def discover(self):
        """[LINK_READY] 後呼叫一次。依序試 L1 → L2，成功就把結果套進
        self.app.host_macs。任何一層出錯都不該讓 controller 掛掉——
        最壞情況就是退回原本的 L3（被動輪詢）／ L4（人工 sendarp）。"""
        try:
            table = self._try_load_table()
            if table is None:
                table = self._try_active_sweep()
            if table:
                self._apply(table)
            else:
                print('[HostDiscovery] L1/L2 都沒有結果，退回被動學習 '
                      '（get_host() 輪詢）；仍可在 Mininet CLI 手動打 sendarp')
        except Exception as e:
            print('[HostDiscovery] 發生例外，不影響其他功能，'
                  '退回被動學習／手動 sendarp: {}'.format(e))

    # =========================================================
    # L1：讀靜態表
    # =========================================================

    def _try_load_table(self):
        """讀 data/host_table.json。目前沒有任何 topo 腳本會產生這個檔案，
        所以這一層現在永遠會 miss、落到 L2——這是預期行為，不是 bug，
        是留給未來 topo 腳本自己寫表的擴充點。"""
        if not os.path.exists(HOST_TABLE_PATH):
            return None
        try:
            with open(HOST_TABLE_PATH, encoding='utf-8') as f:
                data = json.load(f)
        except (IOError, OSError, ValueError) as e:
            print('[HostDiscovery] L1 讀檔失敗（當作沒有這個檔案）: {}'.format(e))
            return None

        hosts = data.get('hosts')
        if not hosts:
            return None

        # 基本驗證：檔案內的 host 數量跟現在偵測到的 edge port 數量差太多
        # 就當作過期資料，不信任，落到 L2 重新掃描。
        edge_port_count = sum(len(ports) for ports in self._edge_ports_by_dpid().values())
        if edge_port_count and abs(len(hosts) - edge_port_count) > edge_port_count:
            print('[HostDiscovery] L1 檔案 host 數量（{}）與目前 edge port 數量'
                  '（{}）差距過大，視為過期，改用 L2'.format(len(hosts), edge_port_count))
            return None

        print('[HostDiscovery] L1 命中：{} 讀到 {} 個 host'.format(
            HOST_TABLE_PATH, len(hosts)))
        return hosts

    # =========================================================
    # L2：主動 ARP 掃描
    # =========================================================

    def _edge_ports_by_dpid(self):
        """{dpid: [port_no, ...]}，排除 switch-switch link 的 port
        （來自既有的 self.app.adjacency，LLDP 填的）與明顯的保留 port。"""
        result = {}
        for dpid in list(self.app.datapaths.keys()):
            inter_switch_ports = set(self.app.adjacency.get(dpid, {}).values())
            all_ports = self._all_ports_of(dpid)
            edge = [p for p in all_ports
                    if p not in inter_switch_ports and p < _MAX_PLAUSIBLE_PORT_NO]
            if edge:
                result[dpid] = edge
        return result

    def _all_ports_of(self, dpid):
        """優先用 Ryu core 的 datapath.ports（EventOFPPortDescStatsReply 填的，
        跟 topology 模組無關，較底層）；拿不到才退回 topology API 的
        get_switch().ports。兩邊格式不同，各自轉成 port_no 的 list。"""
        datapath = self.app.datapaths.get(dpid)
        if datapath is not None and getattr(datapath, 'ports', None):
            return list(datapath.ports.keys())

        switches = get_switch(self.app.topology_api_app, dpid)
        if switches:
            return [port.port_no for port in switches[0].ports]
        return []

    def _try_active_sweep(self):
        edge_ports = self._edge_ports_by_dpid()
        if not edge_ports:
            print('[HostDiscovery] L2 找不到任何 edge port，可能拓撲還沒穩定')
            return None

        sent = 0
        for dpid, ports in edge_ports.items():
            datapath = self.app.datapaths.get(dpid)
            if datapath is None:
                continue
            for port_no in ports:
                for prefix, ip_range in HOST_DISCOVERY_SUBNETS:
                    for i in ip_range:
                        self._send_probe(datapath, port_no, '{}{}'.format(prefix, i))
                        sent += 1

        print('[HostDiscovery] L2 已送出 {} 個 ARP probe（{} 個 edge port）；'
              '回覆會經由既有的 get_host() 輪詢自然填進 host_macs，'
              '這裡不用等、不用回傳表'.format(sent, sum(len(p) for p in edge_ports.values())))

        # L2 的回覆是非同步的（靠既有的 packet_in → topology 模組 → get_host()
        # 這條路徑，不是這個函式自己收集）。所以這裡回傳 None，讓 discover()
        # 印出「已退回被動學習」的訊息——但因為 probe 已經送出去了，
        # 被動學習很快就會有結果，不是真的沒做事。
        return None

    def _send_probe(self, datapath, port_no, target_ip):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        pkt = packet.Packet()
        pkt.add_protocol(ethernet.ethernet(
            dst='ff:ff:ff:ff:ff:ff',
            src=PROBE_SRC_MAC,
            ethertype=ether_types.ETH_TYPE_ARP))
        pkt.add_protocol(arp.arp(
            opcode=arp.ARP_REQUEST,
            src_mac=PROBE_SRC_MAC,
            src_ip='0.0.0.0',
            dst_mac='00:00:00:00:00:00',
            dst_ip=target_ip))
        pkt.serialize()

        actions = [parser.OFPActionOutput(port_no)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=pkt.data)
        datapath.send_msg(out)

    # =========================================================
    # 套用結果（只有 L1 命中時會被呼叫；L2 靠既有輪詢自己套用）
    # =========================================================

    def _apply(self, hosts):
        """hosts: {mac: {"dpid": int, "port": int, ...}}（來自 host_table.json）"""
        added = 0
        for mac, info in hosts.items():
            if mac not in self.app.host_macs:
                self.app.host_macs[mac] = (info['dpid'], info['port'])
                added += 1
        print('[HostDiscovery] 已套用 {} 個 host 進 host_macs（共 {} 個）'.format(
            added, len(self.app.host_macs)))
