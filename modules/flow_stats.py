# -*- coding: utf-8 -*-
"""
flow_stats.py - 子流流量統計模組

透過 OFPFlowStatsRequest / OFPFlowStatsReply 取得
指定 switch 上每條 flow rule 的封包數與位元組數。

設計：每條 flow 在建立時 assign 一台固定的 switch（路徑上的第一台），
只向有 assigned flow 的 switch 發送請求，避免跨 switch 資料混用。

使用方式：
    # Flow 建立 / 移除時呼叫
    self.flow_stats.assign(src, dst, path)   # add_active_flow 時呼叫
    self.flow_stats.unassign(src, dst)        # remove_active_flow 時呼叫

    # 輪詢（只向有 assigned flow 的 switch 發送請求）
    self.flow_stats.request_assigned()

    # 在 EventOFPFlowStatsReply handler 中呼叫
    self.flow_stats.handle_reply(ev)

    # 讀取結果
    stats = self.flow_stats.get(src, dst)    # 取得某 flow 的最新統計
"""

import time
from datetime import datetime
from collections import defaultdict


class FlowStats:
    def __init__(self, app):
        self.app = app

        # (src, dst) -> dpid：每條 flow 固定監測的 switch
        self._assignment = {}

        # dpid -> set of (src, dst)：反查，哪些 flow 被分配到這台 switch
        self._sw_to_flows = defaultdict(set)

        # (src, dst) -> {'byte_count': int, 'timestamp': float}：上一輪快照
        self._prev = {}

        # dpid -> [entry, ...]：最新一次 reply 的原始資料
        self._raw = {}


    # =========================================================
    # Flow 分配
    # =========================================================

    def assign(self, src, dst, path):
        """將 flow (src→dst) 分配到路徑上的第一台 switch。

        Args:
            src: 來源 MAC
            dst: 目的 MAC
            path: [dpid, ...] switch 列表
        """
        if not path:
            return

        # reroute 時先清舊分配
        self.unassign(src, dst)

        dpid = path[0]
        self._assignment[(src, dst)] = dpid
        self._sw_to_flows[dpid].add((src, dst))

    def unassign(self, src, dst):
        """移除 flow (src→dst) 的分配。"""
        dpid = self._assignment.pop((src, dst), None)
        if dpid is not None:
            self._sw_to_flows[dpid].discard((src, dst))
            if not self._sw_to_flows[dpid]:
                del self._sw_to_flows[dpid]
        self._prev.pop((src, dst), None)

    # =========================================================
    # 發送請求
    # =========================================================

    def request_assigned(self):
        """只向有 assigned flow 的 switch 發送 OFPFlowStatsRequest。"""
        for dpid in list(self._sw_to_flows.keys()):
            self._request(dpid)

    def _request(self, dpid):
        datapath = self.app.datapaths.get(dpid)
        if datapath is None:
            return False

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        req = parser.OFPFlowStatsRequest(
            datapath,
            flags=0,
            table_id=ofproto.OFPTT_ALL,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            cookie=0,
            cookie_mask=0,
        )
        datapath.send_msg(req)
        return True

    # =========================================================
    # 處理 Reply
    # =========================================================

    def handle_reply(self, ev):
        """處理 EventOFPFlowStatsReply，只儲存 assigned flow 的資料。"""
        msg = ev.msg
        dpid = msg.datapath.id
        timestamp = time.time()

        # 這台 switch 上有哪些 assigned flow
        assigned = self._sw_to_flows.get(dpid, set())
        if not assigned:
            return

        entries = []
        for stat in msg.body:
            if stat.priority == 0:
                continue  # 跳過 table-miss
            m = dict(stat.match._fields2)
            src = m.get('eth_src')
            dst = m.get('eth_dst')
            if (src, dst) not in assigned:
                continue  # 只保留 assigned flow
            entries.append({
                'src':          src,
                'dst':          dst,
                'byte_count':   stat.byte_count,
                'packet_count': stat.packet_count,
                'duration_sec': stat.duration_sec,
                'timestamp':    timestamp,
            })

        self._raw[dpid] = entries

    # =========================================================
    # 輸出
    # =========================================================

    def log_summary(self):
        """將所有 assigned flow 的流量以 Mbps 輸出。"""
        if not self._assignment:
            return

        ts = datetime.now().strftime('%H:%M:%S')
        lines = [f"[FlowStats] ── {ts} ───────────────────────────────"]

        for (src, dst), dpid in sorted(self._assignment.items()):
            entries = self._raw.get(dpid, [])
            # 找對應這條 flow 的 entry
            entry = next((e for e in entries
                          if e['src'] == src and e['dst'] == dst), None)

            if entry is None:
                lines.append(f"  {src} → {dst}    (no data yet)")
                continue

            cur_bytes = entry['byte_count']
            cur_time  = entry['timestamp']
            prev = self._prev.get((src, dst))

            if prev and (cur_time - prev['timestamp']) > 0:
                dt   = cur_time - prev['timestamp']
                mbps = (cur_bytes - prev['byte_count']) * 8 / dt / 1_000_000
            else:
                mbps = 0.0

            self._prev[(src, dst)] = {'byte_count': cur_bytes, 'timestamp': cur_time}

            lines.append(
                f"  {src} → {dst}"
                f"  {mbps:>8.3f} Mbps  dur={entry['duration_sec']}s  sw={dpid}"
            )

        lines.append("[FlowStats] ────────────────────────────────────")
        print('\n'.join(lines))
