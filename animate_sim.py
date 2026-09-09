# -*- coding: utf-8 -*-
"""
animate_sim.py
--------------
讀取 sim.py 輸出的 snap 檔（log/sim-snap-*.txt），產生 HTML 動畫。

使用方式：
    python3 animate_sim.py log/sim-snap-grid-seed_1-self-2026-05-28_00-00-00-b1.txt --save out.html
    python3 animate_sim.py <snap_file> --topo grid|cap [--interval 800] [--save out.html]
"""

import re
import json
import argparse
import matplotlib
import matplotlib.patches
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec

# =========================================
# 拓撲切換旗子
# =========================================
TOPO = 'grid'

# =========================================
# 功能旗子
# =========================================
SHOW_NS_PANEL   = False   # True：中圖顯示「排除 NS 的拓撲」；False：中圖顯示 weight map
WMAP_MAX_WEIGHT = 5       # weight map 顏色上限（超過此值與此值同色）

# =========================================
# Link status 顏色
# =========================================
LINK_COLOR = {
    'SN':       '#d5dbdb',   # 淺灰：熄燈
    'LOW':      '#85c1e9',   # 淺藍：低載可節能
    'NORMAL':   '#82e0aa',   # 淺綠：正常
    'HIGH':     '#f9e79f',   # 黃：高載
    'OVERLOAD': '#f1948a',   # 橘紅：壅塞
    'DANGER':   '#e74c3c',   # 深紅：超載
}

# =========================================
# Grid 拓撲（5×5）
# =========================================
N = 5

def sw_pos(sw_id):
    r = (sw_id - 1) // N
    c = (sw_id - 1) % N
    return (c, N - 1 - r)

def build_grid_edges():
    edges = []
    for sw in range(1, N * N + 1):
        r = (sw - 1) // N
        c = (sw - 1) % N
        if c < N - 1:
            edges.append((sw, sw + 1))
        if r < N - 1:
            edges.append((sw, sw + N))
    return edges

def build_grid_host_labels():
    border = []
    border += [(1, c) for c in range(1, N + 1)]
    border += [(r, N) for r in range(2, N)]
    border += [(N, c) for c in range(N, 0, -1)]
    border += [(r, 1) for r in range(N - 1, 1, -1)]
    return {(r - 1) * N + c: f"h{idx + 1}" for idx, (r, c) in enumerate(border)}

# =========================================
# Campus 拓撲（45 switch，27 host）
# =========================================
CAP_SW_POS = {
    1: (9.5, 6),    2: (11.5, 6),
    3: (9.5, 5),    4: (11.5, 5),
    5:  (0,   3.5), 6:  (2,   3.5),
    7:  (4,   3.5), 8:  (6,   3.5),
    9:  (8,   3.5), 10: (10,  3.5),
    11: (13,  3.5), 12: (15,  3.5),
    13: (16.5, 3.5), 14: (18,  3.5),
    15: (19.5, 3.5), 16: (21,  3.5),
    17: (22.5, 3.5), 18: (24,  3.5),
    19: (15.5, 2), 20: (17,  2), 21: (18.5, 2),
    22: (20,   2), 23: (21.5, 2), 24: (23,   2),
    25: (0, 1), 26: (1, 1), 27: (2, 1), 28: (3, 1),
    29: (4, 1), 30: (5, 1), 31: (6, 1), 32: (7, 1),
    33: (8, 1), 34: (9, 1), 35: (10, 1), 36: (11, 1),
    37: (13, 1), 38: (14, 1), 39: (15, 1), 40: (16, 1),
    41: (22, 1), 42: (23, 1), 43: (24, 1), 44: (25, 1), 45: (26, 1),
}

def build_cap_edges():
    edges = []
    core   = list(range(1,  5))
    dist   = list(range(5,  19))
    wan    = list(range(19, 25))
    access = list(range(25, 46))
    for i in range(4):
        for j in range(i + 1, 4):
            edges.append((core[i], core[j]))
    for d in dist[:8]:
        edges.append((core[0], d)); edges.append((core[1], d))
    for d in dist[8:]:
        edges.append((core[2], d)); edges.append((core[3], d))
    for d in dist[8:10]:
        for w in wan[:3]: edges.append((d, w))
    for d in dist[10:12]:
        for w in wan[3:]: edges.append((d, w))
    for grp in range(4):
        d1 = dist[grp * 2]; d2 = dist[grp * 2 + 1]
        for a in access[grp * 4: grp * 4 + 4]:
            edges.append((d1, a)); edges.append((d2, a))
    for a in access[16:]:
        edges.append((dist[12], a)); edges.append((dist[13], a))
    return edges

def build_cap_host_labels():
    labels = {}
    for i, sw in enumerate(range(25, 46)):
        labels[sw] = f"h{i + 1}"
    for i, sw in enumerate(range(19, 25)):
        labels[sw] = f"h{i + 22}"
    return labels

# =========================================
# 通用工具
# =========================================
def mac_to_host(mac):
    try:
        return f"h{int(mac.split(':')[-1], 16)}"
    except Exception:
        return mac

def get_path_edges(path):
    if not path:
        return set()
    return {(min(path[i], path[i+1]), max(path[i], path[i+1]))
            for i in range(len(path) - 1)}

# =========================================
# 解析 snap 檔
# =========================================
def parse_snap(filepath):
    """回傳 list[dict]，每個 dict 是一幀快照。"""
    frames = []
    pat = re.compile(r'\[SIM_SNAPSHOT\] (.+)')
    with open(filepath, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = pat.search(line)
            if m:
                try:
                    frames.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    pass
    return frames

# =========================================
# 建立拓撲 ax（靜態元素）
# =========================================
def setup_ax(ax, pos, edges, sw_list, host_labels,
             xlim, ylim, aspect='equal', node_size=600, show_sw_labels=True):
    ax.set_facecolor('#f8f8f8')
    ax.set_xlim(xlim[0], xlim[1])
    ax.set_ylim(ylim[0], ylim[1])
    ax.set_aspect(aspect)
    ax.axis('off')

    label_offset = 0.28 if node_size < 500 else 0.38
    font_size_sw = 6 if len(sw_list) > 25 else 7.5

    for sw, hname in host_labels.items():
        x, y = pos[sw]
        ax.text(x, y + label_offset, hname, ha='center', va='bottom',
                fontsize=6, color='#2980b9', fontweight='bold')

    if show_sw_labels:
        for sw in sw_list:
            x, y = pos[sw]
            ax.text(x, y + 0.06, str(sw), ha='center', va='center',
                    fontsize=font_size_sw, zorder=4, fontweight='bold')

    edge_artists = {}
    for a, b in edges:
        key = (min(a, b), max(a, b))
        if key in edge_artists:
            continue
        x0, y0 = pos[a]; x1, y1 = pos[b]
        line, = ax.plot([x0, x1], [y0, y1], color='#d5dbdb', lw=0.8, zorder=1)
        edge_artists[key] = line

    xs = [pos[sw][0] for sw in sw_list]
    ys = [pos[sw][1] for sw in sw_list]
    scat = ax.scatter(xs, ys, s=node_size, c=['#ffffcc'] * len(sw_list),
                      zorder=3, edgecolors='#333333', linewidths=0.8)

    subtitle = ax.text(0.5, -0.04, '', transform=ax.transAxes,
                       ha='center', va='top', fontsize=7.5, color='#555555',
                       clip_on=False)

    return {'edge_artists': edge_artists, 'scat': scat,
            'sw_list': sw_list, 'subtitle': subtitle}

# =========================================
# 更新拓撲 ax（動態元素）
# 有 link status 顏色 + active flow 粗線 + event path 高亮
# =========================================
def update_ax(artists, active_flows, non_shortest, event_path, event,
              link_status, src_sw=None, dst_sw=None):
    """
    active_flows: {(src_mac, dst_mac): [sw1, sw2, ...]}
    non_shortest: {(src_mac, dst_mac): hop}
    event_path  : list of sw ids（本幀事件的路徑），可為 None
    event       : 'admit' | 'depart' | 'reroute_rem' | 'reroute_add'
    link_status : {"u,v": {"s": "SN", "p": 50.0}}
    """
    sw_list = artists['sw_list']

    active_edges = set()
    ns_edges     = set()
    for (src, dst), path in active_flows.items():
        edges = get_path_edges(path)
        active_edges |= edges
        if (src, dst) in non_shortest:
            ns_edges |= edges
    event_edges = get_path_edges(event_path)

    # event 類型 → 高亮顏色 / 線型
    if event in ('admit', 'reroute_add'):
        ev_color  = '#27ae60'   # 綠
        ev_lw     = 3.5
        ev_ls     = '-'
    else:  # depart / reroute_rem
        ev_color  = '#7f8c8d'   # 灰
        ev_lw     = 3.0
        ev_ls     = '--'

    for key, line in artists['edge_artists'].items():
        u, v = key
        # link status 基底顏色
        lkey = f"{min(u,v)},{max(u,v)}"
        info = link_status.get(lkey, {})
        status = info.get('s', 'SN')
        base_color = LINK_COLOR.get(status, '#d5dbdb')

        if key in event_edges:
            line.set_color(ev_color)
            line.set_linewidth(ev_lw)
            line.set_linestyle(ev_ls)
            line.set_zorder(3)
        elif key in active_edges:
            # 以 link status 顏色為底，但加粗
            line.set_color(base_color if status != 'SN' else '#e74c3c')
            line.set_linewidth(2.5)
            line.set_linestyle('-')
            line.set_zorder(2)
        else:
            line.set_color('#e8e8e8')
            line.set_linewidth(0.5)
            line.set_linestyle('-')
            line.set_zorder(1)

    # switch 節點顏色：src=藍、dst=紅、active=橘黃、休眠=灰
    active_sws = {sw for path in active_flows.values() for sw in path}
    colors = []
    for sw in sw_list:
        if sw == src_sw:
            colors.append('#2980b9')   # 藍：來源 host
        elif sw == dst_sw:
            colors.append('#c0392b')   # 紅：目的 host
        elif sw in active_sws:
            colors.append('#f0b27a')   # 橘黃：有流量
        else:
            colors.append('#d5d8dc')   # 淺灰：休眠
    artists['scat'].set_facecolor(colors)

# =========================================
# 更新文字面板（右側）
# =========================================
def update_text_panel(ax_text, active_flows, non_shortest, energy_pct,
                      link_status, frame, trigger=None):
    ax_text.clear()
    ax_text.axis('off')
    ax_text.set_facecolor('#f0f0f0')

    y    = 0.99
    step = 0.048

    def txt(s, dy=None, **kw):
        nonlocal y
        kw.setdefault('fontsize', 7.5)
        kw.setdefault('transform', ax_text.transAxes)
        kw.setdefault('va', 'top')
        ax_text.text(0.05, y, s, **kw)
        y -= (dy if dy is not None else step)

    # ── 節能率 ───────────────────────────────────────────────────
    pct_color = '#1a9c3e' if energy_pct >= 30 else ('#e67e22' if energy_pct >= 15 else '#e74c3c')
    txt(f"Energy Saving: {energy_pct:.1f}%",
        fontsize=9, fontweight='bold', color=pct_color)
    y -= step * 0.3

    ev    = frame.get('event', '')
    src   = frame.get('src') or ''
    dst   = frame.get('dst') or ''
    sim_t = frame.get('t', 0.0)

    # ── Trace 事件：專用面板 ──────────────────────────────────────
    if ev.startswith('trace_'):
        current  = frame.get('current') or []
        cur_src  = current[0] if len(current) > 0 else ''
        cur_dst  = current[1] if len(current) > 1 else ''

        trace_labels = {
            'trace_sort':    ('SORT',    '#8e44ad'),
            'trace_phase1':  ('PHASE 1', '#2980b9'),
            'trace_phase2':  ('PHASE 2', '#16a085'),
            'trace_decided': ('DECIDED', '#c0392b'),
        }
        ev_label, ev_color = trace_labels.get(ev, (ev.upper(), '#555555'))
        txt(f"t={sim_t:.1f}s  [{ev_label}]  {cur_src}→{cur_dst}",
            fontsize=7.5, color=ev_color, fontweight='bold')
        y -= step * 0.4

        if trigger:
            trig_ev, trig_src, trig_dst = trigger
            trig_label = {'admit': 'ADMIT', 'depart': 'DEPART',
                          'reroute_add': 'REROUTE'}.get(trig_ev, trig_ev.upper())
            trig_color = '#27ae60' if trig_ev == 'admit' else '#7f8c8d'
            txt(f"Trigger: [{trig_label}] {trig_src}→{trig_dst}",
                fontsize=7, color=trig_color, style='italic')
        y -= step * 0.4

        # trace_sort：顯示排序清單
        if ev == 'trace_sort':
            order = frame.get('order', [])
            txt(f"Processing order  ({len(order)} flows, by min-hop desc):",
                fontsize=7.5, fontweight='bold', color='#2c3e50')
            y -= step * 0.1
            for i, entry in enumerate(order):
                fa, fb = entry[0], entry[1]
                hop    = entry[2] if len(entry) > 2 else '?'
                is_cur = (fa == cur_src and fb == cur_dst)
                prefix = '▶ ' if is_cur else f'{i+1:>2}. '
                color  = ev_color if is_cur else '#555555'
                fw     = 'bold' if is_cur else 'normal'
                txt(f"  {prefix}{fa}→{fb}  (hop={hop})", dy=step * 0.85,
                    fontsize=7, color=color, fontweight=fw)

        # trace_phase1：candidates + best_inactive
        elif ev == 'trace_phase1':
            candidates    = frame.get('candidates', [])
            best_inactive = frame.get('best_inactive')
            inactive_str  = str(best_inactive) if best_inactive is not None else '?'
            clean_tag     = '  ✓ clean-zero' if best_inactive == 0 else ''
            txt(f"Phase 1 result:", fontsize=7.5, fontweight='bold', color='#2c3e50')
            txt(f"  best_inactive = {inactive_str}{clean_tag}",
                dy=step * 0.9, fontsize=7, color='#2980b9')
            txt(f"  candidates ({len(candidates)}):",
                dy=step * 0.9, fontsize=7, color='#2c3e50')
            for p in candidates[:6]:
                path_str = ' → '.join(str(sw) for sw in p)
                txt(f"    [{path_str}]", dy=step * 0.85, fontsize=6.5, color='#555555')
            if len(candidates) > 6:
                txt(f"    ...+{len(candidates)-6} more", dy=step*0.8,
                    fontsize=6.5, color='#888888')

        # trace_phase2：weight 分數
        elif ev == 'trace_phase2':
            scores   = sorted(frame.get('scores', []), key=lambda x: -x[1])
            selected = frame.get('selected')
            txt(f"Phase 2 scores:", fontsize=7.5, fontweight='bold', color='#2c3e50')
            for path, weight in scores[:6]:
                is_sel   = (path == selected)
                prefix   = '★ ' if is_sel else '  '
                color    = '#16a085' if is_sel else '#555555'
                fw       = 'bold' if is_sel else 'normal'
                path_str = ' → '.join(str(sw) for sw in path)
                txt(f"{prefix}w={weight}  [{path_str}]",
                    dy=step * 0.85, fontsize=6.5, color=color, fontweight=fw)
            if len(scores) > 6:
                txt(f"  ...+{len(scores)-6} more", dy=step*0.8,
                    fontsize=6.5, color='#888888')

        # trace_decided：換路結果
        elif ev == 'trace_decided':
            changed  = frame.get('changed', False)
            old_path = frame.get('old_path')
            new_path = frame.get('new_path')
            result   = '↺ CHANGED' if changed else '= NO CHANGE'
            r_color  = '#c0392b' if changed else '#27ae60'
            txt(f"Decision: {result}", fontsize=8, fontweight='bold', color=r_color)
            if old_path:
                txt(f"  old: {' → '.join(str(s) for s in old_path)}",
                    dy=step*0.9, fontsize=6.5, color='#888888')
            if new_path:
                txt(f"  new: {' → '.join(str(s) for s in new_path)}",
                    dy=step*0.9, fontsize=6.5, color='#27ae60' if changed else '#555555')

        # ── 底部：目前 active flows 簡表 ─────────────────────────
        y = min(y, 0.35)
        txt(f"Active ({len(active_flows)}):",
            fontsize=7, fontweight='bold', color='#2c3e50')
        for (fa, fb) in sorted(active_flows.keys()):
            if y < 0.05:
                break
            is_cur = (fa == cur_src and fb == cur_dst)
            color  = ev_color if is_cur else '#888888'
            fw     = 'bold' if is_cur else 'normal'
            txt(f"  {'▶ ' if is_cur else ''}{fa}→{fb}",
                dy=step * 0.8, fontsize=6.5, color=color, fontweight=fw)
        return

    # ── 一般事件 ─────────────────────────────────────────────────
    ev_labels = {
        'admit':       ('▶ ADMIT',   '#27ae60'),
        'depart':      ('■ DEPART',  '#7f8c8d'),
        'reroute_rem': ('↩ RE-REM',  '#e67e22'),
        'reroute_add': ('↪ RE-ADD',  '#2980b9'),
    }
    ev_label, ev_color = ev_labels.get(ev, (ev.upper(), '#555555'))
    txt(f"t={sim_t:.1f}s  {ev_label}  {src}→{dst}",
        fontsize=7.5, color=ev_color, fontweight='bold')
    y -= step * 0.5

    # ── Active flows ──────────────────────────────────────────────
    txt(f"Active Flows  ({len(active_flows)})",
        fontsize=8, fontweight='bold', color='#2c3e50')
    y -= step * 0.2

    for (src_mac, dst_mac) in sorted(active_flows.keys()):
        if y < 0.32:
            txt(f"  ...({len(active_flows)} total)", dy=step*0.8,
                fontsize=6.5, color='#888888')
            break
        path  = active_flows[(src_mac, dst_mac)]
        h_src = src_mac
        h_dst = dst_mac
        is_ns = (src_mac, dst_mac) in non_shortest
        hop   = non_shortest.get((src_mac, dst_mac))

        if is_ns:
            label = f"★ {h_src}→{h_dst}  hop={hop}"
            color = '#e67e22'
        else:
            label = f"{h_src}→{h_dst}"
            color = '#2c3e50'
        txt(label, dy=step * 0.85, fontsize=7, fontweight='bold', color=color)

        path_str = ' → '.join(str(sw) for sw in path)
        txt(f"   {path_str}", dy=step * 0.95, fontsize=6, color='#666666')

    if non_shortest:
        y = min(y, 0.30)
        ax_text.text(0.05, 0.28, "★ = Non-Shortest Hop",
                     fontsize=7, color='#e67e22',
                     transform=ax_text.transAxes, va='top')

    # ── Link status 統計 ──────────────────────────────────────────
    counts = {}
    for info in link_status.values():
        s = info.get('s', 'SN')
        counts[s] = counts.get(s, 0) + 1

    legend_y = 0.15
    ax_text.text(0.05, legend_y + 0.03, "Link status:",
                 fontsize=7, fontweight='bold', color='#555555',
                 transform=ax_text.transAxes, va='top')
    legend_y -= 0.01
    for status, color in LINK_COLOR.items():
        cnt = counts.get(status, 0)
        if cnt == 0:
            continue
        ax_text.add_patch(
            matplotlib.patches.Rectangle((0.05, legend_y - 0.025), 0.08, 0.025,
                                          color=color, transform=ax_text.transAxes,
                                          clip_on=False)
        )
        ax_text.text(0.16, legend_y - 0.012, f"{status} ×{cnt}",
                     fontsize=6.5, color='#333333',
                     transform=ax_text.transAxes, va='center')
        legend_y -= 0.035


# =========================================
# Weight map ax（中圖 SHOW_NS_PANEL=False 時使用）
# =========================================
def update_wmap_ax(artists, wmap, src_sw=None, dst_sw=None):
    """
    將 weight_map 以顏色深淺顯示在拓撲圖上。
    weight=0：淺灰；越高越深橘。
    """
    sw_list = artists['sw_list']

    # weight 顏色插值：0→灰，1→淡黃，WMAP_MAX_WEIGHT+→深橘紅
    def weight_color(w):
        if w == 0:
            return '#d5d8dc'
        ratio = min(w / WMAP_MAX_WEIGHT, 1.0)
        # 淡黃 #fef9e7 → 深橘 #e67e22
        r = int(0xfe + (0xe6 - 0xfe) * ratio)
        g = int(0xf9 + (0x7e - 0xf9) * ratio)
        b = int(0xe7 + (0x22 - 0xe7) * ratio)
        return f'#{r:02x}{g:02x}{b:02x}'

    colors = []
    for sw in sw_list:
        w = wmap.get(str(sw), wmap.get(sw, 0))
        colors.append(weight_color(w))
        if 'wmap_texts' in artists:
            artists['wmap_texts'][sw].set_text(str(w))
    artists['scat'].set_facecolor(colors)

    # 所有 link 設為預設灰（weight map 不顯示 flow）
    for line in artists['edge_artists'].values():
        line.set_color('#d5dbdb')
        line.set_linewidth(0.8)
        line.set_linestyle('-')
        line.set_zorder(1)

    max_w = max((wmap.get(str(sw), wmap.get(sw, 0)) for sw in sw_list), default=0)
    artists['subtitle'].set_text(f"Weight Map  (max={max_w})")


# =========================================
# 動畫主函式
# =========================================
def run_animation(snap_path, interval_ms=800, save_path=None):
    frames = parse_snap(snap_path)
    if not frames:
        print(f"[animate_sim] 無資料: {snap_path}")
        return

    # ── 依拓撲取得繪圖參數 ──
    if TOPO == 'cap':
        sw_list     = list(range(1, 46))
        pos         = CAP_SW_POS
        edges       = build_cap_edges()
        host_labels = build_cap_host_labels()
        xlim        = (-1, 27)
        ylim        = (0.3, 6.8)
        aspect      = 'auto'
        node_size   = 280
        base_w      = 20
    else:
        sw_list     = list(range(1, N * N + 1))
        pos         = {sw: sw_pos(sw) for sw in sw_list}
        edges       = build_grid_edges()
        host_labels = build_grid_host_labels()
        xlim        = (-0.7, N - 0.3)
        ylim        = (-0.7, N - 0.3)
        aspect      = 'equal'
        node_size   = 600
        base_w      = 6

    # host 名稱 → switch id（用於高亮 src/dst）
    host_inv = {hname: sw for sw, hname in host_labels.items()}

    # ── 佈局：active flows | weight map or NS | text ──
    has_ns      = SHOW_NS_PANEL and any(f.get('ns') for f in frames)
    show_center = True   # 中圖恆顯示（weight map 或 NS）

    fig = plt.figure(figsize=(base_w * 2 + 4, 6.5))
    fig.patch.set_facecolor('#f8f8f8')
    gs = gridspec.GridSpec(1, 3, width_ratios=[5, 5, 3], figure=fig, wspace=0.05)
    ax1     = fig.add_subplot(gs[0])
    ax2     = fig.add_subplot(gs[1])
    ax_text = fig.add_subplot(gs[2])
    artists1 = setup_ax(ax1, pos, edges, sw_list, host_labels,
                        xlim, ylim, aspect, node_size)
    artists2 = setup_ax(ax2, pos, edges, sw_list, host_labels,
                        xlim, ylim, aspect, node_size, show_sw_labels=False)
    font_size_sw = 6 if len(sw_list) > 25 else 7.5
    wmap_texts = {}
    for sw in sw_list:
        x, y = pos[sw]
        wmap_texts[sw] = ax2.text(x, y + 0.06, '0', ha='center', va='center',
                                  fontsize=font_size_sw, zorder=4, fontweight='bold')
    artists2['wmap_texts'] = wmap_texts
    ax1.set_title("Active Flows", fontsize=9, pad=6)
    ax2.set_title("Weight Map" if not SHOW_NS_PANEL else "Excl. Non-Shortest Hop",
                  fontsize=9, pad=6)

    suptitle = fig.suptitle('', fontsize=10, y=0.98)

    # cascade 進度狀態（closure）
    cascade_state = {'order_key': None, 'flows': {}, 'needs_reset': False, 'trigger': None}

    def update(fidx):
        frame       = frames[fidx]
        event       = frame.get('event', '')
        src         = frame.get('src', '') or ''
        dst         = frame.get('dst', '') or ''
        path        = frame.get('path')
        active_raw  = frame.get('active', [])
        ns_raw      = frame.get('ns', [])
        link_status = frame.get('links', {})
        energy_pct  = frame.get('energy_pct', 0.0)
        sim_t       = frame.get('t', 0.0)
        wmap        = frame.get('wmap', {})

        active_flows = {(a, b): p for a, b, p in active_raw}
        non_shortest = {(a, b): hop for a, b, hop in ns_raw}

        # ── 取得目前 src/dst 的 switch id ───────────────────────
        is_trace = event.startswith('trace_')
        if is_trace:
            current = frame.get('current') or []
            cur_src = current[0] if len(current) > 0 else src
            cur_dst = current[1] if len(current) > 1 else dst
        else:
            cur_src, cur_dst = src, dst
        src_sw = host_inv.get(cur_src)
        dst_sw = host_inv.get(cur_dst)

        # ── trace 事件：cascade 進度追蹤 ────────────────────────
        if is_trace:
            # 只有 trace_sort 帶 order；以它判斷是否新一輪 cascade
            if event == 'trace_sort' and 'order' in frame:
                order_key = tuple(tuple(x) for x in frame['order'])
                if cascade_state['needs_reset'] or order_key != cascade_state['order_key']:
                    cascade_state['order_key'] = order_key
                    cascade_state['flows'] = {}
                    cascade_state['needs_reset'] = False

            if event == 'trace_decided':
                new_path = frame.get('new_path')
                if new_path and cur_src and cur_dst:
                    cascade_state['flows'][(cur_src, cur_dst)] = new_path

            display_flows = cascade_state['flows']

            if event == 'trace_decided':
                highlight_path = frame.get('new_path') if frame.get('changed') else None
                highlight_ev   = 'admit'
            else:
                highlight_path = None
                highlight_ev   = 'reroute_add'
        else:
            display_flows  = active_flows
            # depart / reroute_rem：不顯示舊路徑淡化，只保留 admit / reroute_add 高亮
            if event in ('admit', 'reroute_add'):
                highlight_path = path
                highlight_ev   = event
            else:
                highlight_path = None
                highlight_ev   = event
            cascade_state['order_key'] = None
            cascade_state['needs_reset'] = True
            cascade_state['trigger'] = (event, src, dst)

        # ── 左圖：cascade 進度或完整 flows ──
        update_ax(artists1, display_flows, non_shortest,
                  highlight_path, highlight_ev, link_status,
                  src_sw=src_sw, dst_sw=dst_sw)
        artists1['subtitle'].set_text(
            f"flows={len(display_flows)}/{len(active_flows)}  NS={len(non_shortest)}"
            if is_trace else
            f"flows={len(active_flows)}  NS={len(non_shortest)}")

        # ── 中圖：weight map 或 NS ───────────────────────────────
        if SHOW_NS_PANEL and has_ns:
            filtered    = {k: v for k, v in active_flows.items() if k not in non_shortest}
            is_ns_event = (src, dst) in non_shortest if src and dst else False
            ep2 = (None if is_ns_event else highlight_path) if is_trace else (None if is_ns_event else path)
            update_ax(artists2, filtered, {}, ep2, event, link_status,
                      src_sw=src_sw, dst_sw=dst_sw)
        else:
            update_wmap_ax(artists2, wmap, src_sw=src_sw, dst_sw=dst_sw)

        # ── 文字面板 ──
        update_text_panel(ax_text, active_flows, non_shortest,
                          energy_pct, link_status, frame,
                          trigger=cascade_state['trigger'] if is_trace else None)

        # ── 總標題 ──
        ev_map = {
            'admit':           'ADMIT',
            'depart':          'DEPART',
            'reroute_rem':     'REROUTE (remove)',
            'reroute_add':     'REROUTE (add)',
            'trigger_admit':   '▶ TRIGGER: ADMIT',
            'trigger_depart':  '■ TRIGGER: DEPART',
            'trace_sort':      'TRACE: SORT',
            'trace_phase1':    'TRACE: PHASE 1',
            'trace_phase2':    'TRACE: PHASE 2',
            'trace_decided':   'TRACE: DECIDED',
        }
        ev_str  = ev_map.get(event, event.upper())
        cur_tag = f"  [{cur_src}→{cur_dst}]" if (cur_src and cur_dst) else ''
        ns_tag  = '  ★NS' if (not is_trace and src and dst and (src, dst) in non_shortest) else ''
        suptitle.set_text(
            f"[{ev_str}] t={sim_t:.1f}s{cur_tag}{ns_tag}"
            f"  |  frame {fidx+1}/{len(frames)}")

    ani = animation.FuncAnimation(
        fig, update,
        frames=len(frames),
        interval=interval_ms,
        repeat=False,
    )

    plt.tight_layout(rect=[0, 0, 1, 0.96])

    if save_path:
        print(f"[animate_sim] 儲存 {len(frames)} 幀 → {save_path} ...")
        from matplotlib.animation import HTMLWriter
        ani.save(save_path, writer=HTMLWriter(embed_frames=True), dpi=72)
        print("[animate_sim] Done")
    else:
        plt.show()


# =========================================
# Entry point
# =========================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('snap', help='sim snap 檔路徑（log/sim-snap-*.txt）')
    parser.add_argument('--topo',     default=None, choices=['grid', 'cap'],
                        help='拓撲類型（預設依檔案頂部 TOPO 變數）')
    parser.add_argument('--interval', type=int, default=800,
                        help='每幀間隔 ms（預設 800）')
    parser.add_argument('--save',     default=None,
                        help='儲存 HTML 路徑（指定時不開視窗）')
    args = parser.parse_args()

    if args.topo:
        TOPO = args.topo

    if args.save:
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.animation as animation
        matplotlib.rcParams['animation.embed_limit'] = 200

    run_animation(args.snap, interval_ms=args.interval, save_path=args.save)
