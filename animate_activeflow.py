# -*- coding: utf-8 -*-
import re
import argparse
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec

# =========================================
# 拓撲切換旗子：'grid' 或 'cap'
# 可直接改這行，或用 --topo 參數覆蓋
# =========================================
TOPO = 'grid'

# =========================================
# Grid 拓撲設定（5×5）
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
# Campus 拓撲設定（45 switch，27 host）
# 佈局說明：
#   y=6    Core s1,s2
#   y=5    Core s3,s4
#   y=3.5  Dist A (s5-s12, left) | Dist B (s13-s18, right)
#   y=2    WAN s19-s24 (under Dist B s13-s16)
#   y=1    Access s25-s45
# =========================================
CAP_SW_POS = {
    # Core s1-s4（2×2 全連接）
    1: (9.5, 6),    2: (11.5, 6),
    3: (9.5, 5),    4: (11.5, 5),

    # Dist A s5-s12（連接 core s1,s2）
    5:  (0,   3.5), 6:  (2,   3.5),
    7:  (4,   3.5), 8:  (6,   3.5),
    9:  (8,   3.5), 10: (10,  3.5),
    11: (13,  3.5), 12: (15,  3.5),

    # Dist B s13-s18（連接 core s3,s4）
    13: (16.5, 3.5), 14: (18,  3.5),
    15: (19.5, 3.5), 16: (21,  3.5),
    17: (22.5, 3.5), 18: (24,  3.5),

    # WAN s19-s24
    19: (15.5, 2), 20: (17,  2), 21: (18.5, 2),
    22: (20,   2), 23: (21.5, 2), 24: (23,   2),

    # Access grp0 s25-s28（dist s5,s6）
    25: (0, 1), 26: (1, 1), 27: (2, 1), 28: (3, 1),
    # Access grp1 s29-s32（dist s7,s8）
    29: (4, 1), 30: (5, 1), 31: (6, 1), 32: (7, 1),
    # Access grp2 s33-s36（dist s9,s10）
    33: (8, 1), 34: (9, 1), 35: (10, 1), 36: (11, 1),
    # Access grp3 s37-s40（dist s11,s12）
    37: (13, 1), 38: (14, 1), 39: (15, 1), 40: (16, 1),
    # Access grp4 s41-s45（dist s17,s18）
    41: (22, 1), 42: (23, 1), 43: (24, 1), 44: (25, 1), 45: (26, 1),
}


def build_cap_edges():
    edges = []
    core   = list(range(1,  5))
    dist   = list(range(5,  19))
    wan    = list(range(19, 25))
    access = list(range(25, 46))

    # Core 全連接
    for i in range(4):
        for j in range(i + 1, 4):
            edges.append((core[i], core[j]))

    # Core s1,s2 <-> Dist A (s5-s12)
    for d in dist[:8]:
        edges.append((core[0], d))
        edges.append((core[1], d))

    # Core s3,s4 <-> Dist B (s13-s18)
    for d in dist[8:]:
        edges.append((core[2], d))
        edges.append((core[3], d))

    # Dist s13,s14 <-> WAN s19-s21
    for d in dist[8:10]:
        for w in wan[:3]:
            edges.append((d, w))

    # Dist s15,s16 <-> WAN s22-s24
    for d in dist[10:12]:
        for w in wan[3:]:
            edges.append((d, w))

    # Access grp0-3（各 4 個 access，雙上行）
    for grp in range(4):
        d1 = dist[grp * 2]
        d2 = dist[grp * 2 + 1]
        for a in access[grp * 4: grp * 4 + 4]:
            edges.append((d1, a))
            edges.append((d2, a))

    # Access grp4（s41-s45，dist s17,s18）
    for a in access[16:]:
        edges.append((dist[12], a))
        edges.append((dist[13], a))

    return edges


def build_cap_host_labels():
    labels = {}
    for i, sw in enumerate(range(25, 46)):   # access s25-s45 → h1-h21
        labels[sw] = f"h{i + 1}"
    for i, sw in enumerate(range(19, 25)):   # WAN s19-s24 → h22-h27
        labels[sw] = f"h{i + 22}"
    return labels


# =========================================
# 通用工具
# =========================================
def mac_to_host(mac):
    return f"h{int(mac.split(':')[-1], 16)}"


def get_path_edges(path):
    return {(min(path[i], path[i+1]), max(path[i], path[i+1]))
            for i in range(len(path) - 1)}


# =========================================
# Log 解析（不變）
# =========================================
def parse_log(filepath):
    import json

    all_events = []
    snapshots  = {}

    add_re      = re.compile(r'\[ActiveFlow\] 新增: (.+?) -> (.+?), 路徑: \[(.+?)\]')
    rem_re      = re.compile(r'\[ActiveFlow\] 移除: (.+?) -> (.+)')
    snapshot_re = re.compile(r'\[SNAPSHOT\] (.+)')
    trigger_re  = re.compile(r'\[(FLOW_NEW|FLOW_CASCADE_NS|FLOW_CASCADE)\]')

    pending_trigger = None
    last_event_idx  = None

    with open(filepath, encoding='utf-8', errors='replace') as f:
        for line in f:
            mt = trigger_re.search(line)
            if mt:
                pending_trigger = mt.group(1)
                continue
            m = add_re.search(line)
            if m:
                src  = m.group(1).strip()
                dst  = m.group(2).strip()
                path = [int(x) for x in m.group(3).split(',')]
                all_events.append(('flow_add', src, dst, path, pending_trigger))
                pending_trigger = None
                last_event_idx  = len(all_events) - 1
                continue
            m = rem_re.search(line)
            if m:
                all_events.append(('flow_rem', m.group(1).strip(), m.group(2).strip(), None, None))
                last_event_idx = len(all_events) - 1
                continue
            m = snapshot_re.search(line)
            if m and last_event_idx is not None:
                snapshots[last_event_idx] = json.loads(m.group(1))
                last_event_idx = None

    return all_events, snapshots


def build_states(all_events, snapshots):
    states    = []
    last_snap = {'active': [], 'ns': [], 'wmap': {}}

    for i, event in enumerate(all_events):
        if i in snapshots:
            last_snap = snapshots[i]

        active_flows = {(e[0], e[1]): e[2] for e in last_snap.get('active', [])}
        non_shortest = {(e[0], e[1]): e[2] for e in last_snap.get('ns', [])}
        wmap         = {int(k): v for k, v in last_snap.get('wmap', {}).items()}

        states.append({
            'event':        event,
            'weight_map':   wmap,
            'active_flows': active_flows,
            'non_shortest': non_shortest,
        })

    return states


# =========================================
# 通用繪圖（grid / campus 共用）
# =========================================
def setup_ax(ax, pos, edges, sw_list, host_labels,
             xlim, ylim, aspect='equal', node_size=600):
    """初始化一個 ax 的靜態元素，回傳 artists dict"""
    ax.set_facecolor('#f8f8f8')
    ax.set_xlim(xlim[0], xlim[1])
    ax.set_ylim(ylim[0], ylim[1])
    ax.set_aspect(aspect)
    ax.axis('off')

    label_offset = 0.28 if node_size < 500 else 0.38
    font_size_sw = 6 if len(sw_list) > 25 else 7.5
    font_size_w  = 5 if len(sw_list) > 25 else 6

    for sw, hname in host_labels.items():
        x, y = pos[sw]
        ax.text(x, y + label_offset, hname, ha='center', va='bottom',
                fontsize=6, color='#2980b9', fontweight='bold')

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
        line, = ax.plot([x0, x1], [y0, y1], color='#cccccc', lw=0.8, zorder=1)
        edge_artists[key] = line

    xs = [pos[sw][0] for sw in sw_list]
    ys = [pos[sw][1] for sw in sw_list]
    scat = ax.scatter(xs, ys, s=node_size, c=['#ffffcc'] * len(sw_list),
                      zorder=3, edgecolors='#333333', linewidths=0.8)

    w_texts = {}
    for sw in sw_list:
        x, y = pos[sw]
        w_texts[sw] = ax.text(x, y - 0.18, '', ha='center', va='top',
                               fontsize=font_size_w, color='#555555', zorder=4)

    subtitle = ax.text(0.5, -0.04, '', transform=ax.transAxes,
                       ha='center', va='top', fontsize=7.5, color='#555555', clip_on=False)

    return {'edge_artists': edge_artists, 'scat': scat,
            'sw_list': sw_list, 'w_texts': w_texts, 'subtitle': subtitle}


def update_ax(artists, flows, wmap, event_kind, event_path):
    """更新一個 ax 的動態元素"""
    sw_list = artists['sw_list']
    max_w   = max(wmap.values()) if wmap else 1

    active_edges = set()
    for p in flows.values():
        active_edges |= get_path_edges(p)
    event_edges = get_path_edges(event_path) if event_path else set()

    for key, line in artists['edge_artists'].items():
        if key in event_edges:
            line.set_color('#27ae60' if event_kind == 'flow_add' else '#7f8c8d')
            line.set_linewidth(3.0)
            line.set_linestyle('-' if event_kind == 'flow_add' else '--')
        elif key in active_edges:
            line.set_color('#e74c3c')
            line.set_linewidth(2.0)
            line.set_linestyle('-')
        else:
            line.set_color('#cccccc')
            line.set_linewidth(0.8)
            line.set_linestyle('-')

    colors = []
    for sw in sw_list:
        w = wmap.get(sw, 0)
        intensity = w / max_w if max_w > 0 else 0
        colors.append(plt.cm.YlOrRd(0.1 + 0.9 * intensity))
    artists['scat'].set_facecolor(colors)

    for sw in sw_list:
        w = wmap.get(sw, 0)
        artists['w_texts'][sw].set_text(f'w={w}' if w > 0 else '')


def update_text_panel(ax_text, active_flows, non_shortest):
    """更新右側文字面板（不變）"""
    ax_text.clear()
    ax_text.axis('off')
    ax_text.set_facecolor('#f0f0f0')

    y    = 0.97
    step = 0.052

    ax_text.text(0.05, y, f"Active Flows  ({len(active_flows)})",
                 fontsize=8, fontweight='bold', transform=ax_text.transAxes, va='top')
    y -= step * 1.3

    for (src, dst) in sorted(active_flows.keys()):
        h_src = mac_to_host(src)
        h_dst = mac_to_host(dst)
        is_ns = (src, dst) in non_shortest
        hop   = non_shortest.get((src, dst))

        if is_ns:
            label = f"★ {h_src}→{h_dst}  hop={hop}"
            color = '#e67e22'
        else:
            label = f"   {h_src}→{h_dst}"
            color = '#2c3e50'

        ax_text.text(0.05, y, label, fontsize=7, color=color,
                     transform=ax_text.transAxes, va='top')
        y -= step
        if y < 0.08:
            ax_text.text(0.05, y, f"  ...({len(active_flows)} total)",
                         fontsize=6.5, color='#888888',
                         transform=ax_text.transAxes, va='top')
            break

    ax_text.text(0.05, 0.03, "★ = Non-Shortest Hop",
                 fontsize=7, color='#e67e22', transform=ax_text.transAxes, va='bottom')


# =========================================
# 動畫主函式
# =========================================
def run_animation(log_path, dist_path, interval_ms, save_path=None):
    all_events, snapshots = parse_log(log_path)
    if not all_events:
        print("No events found")
        return

    states = build_states(all_events, snapshots)
    is_self_mode = bool(snapshots)

    frame_states = states
    if not frame_states:
        print("No ActiveFlow events found")
        return

    # ── 依據 TOPO 選擇佈局參數 ──
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
    else:  # grid
        sw_list     = list(range(1, N * N + 1))
        pos         = {sw: sw_pos(sw) for sw in sw_list}
        edges       = build_grid_edges()
        host_labels = build_grid_host_labels()
        xlim        = (-0.7, N - 0.3)
        ylim        = (-0.7, N - 0.3)
        aspect      = 'equal'
        node_size   = 600
        base_w      = 6

    if is_self_mode:
        fig = plt.figure(figsize=(base_w * 2 + 4, 6.5))
        fig.patch.set_facecolor('#f8f8f8')
        gs = gridspec.GridSpec(1, 3, width_ratios=[5, 5, 3],
                               figure=fig, wspace=0.05)
        ax1     = fig.add_subplot(gs[0])
        ax2     = fig.add_subplot(gs[1])
        ax_text = fig.add_subplot(gs[2])

        artists1 = setup_ax(ax1, pos, edges, sw_list, host_labels,
                            xlim, ylim, aspect, node_size)
        artists2 = setup_ax(ax2, pos, edges, sw_list, host_labels,
                            xlim, ylim, aspect, node_size)
        ax1.set_title("All Active Flows", fontsize=9, pad=6)
        ax2.set_title("Excl. Non-Shortest Hop", fontsize=9, pad=6)
        suptitle = fig.suptitle('', fontsize=10)

        def update(frame):
            state        = frame_states[frame]
            wmap         = state['weight_map']
            flows        = state['active_flows']
            non_shortest = state['non_shortest']
            kind, src, dst, event_path, extra = state['event']

            h_src = mac_to_host(src)
            h_dst = mac_to_host(dst)
            is_ns = (src, dst) in non_shortest

            update_ax(artists1, flows, wmap, kind, event_path)
            artists1['subtitle'].set_text(
                f"flows={len(flows)}  non-shortest={len(non_shortest)}")

            filtered = {k: v for k, v in flows.items() if k not in non_shortest}
            ep2 = None if is_ns else event_path
            ek2 = None if is_ns else kind
            update_ax(artists2, filtered, wmap, ek2, ep2)
            artists2['subtitle'].set_text(f"flows={len(filtered)}")

            update_text_panel(ax_text, flows, non_shortest)

            tag     = "  ★non-shortest" if is_ns else ""
            trigger = f"  [{extra}]" if kind == 'flow_add' and extra else ""
            action  = f"[{'ADD' if kind == 'flow_add' else 'REMOVE'}]{trigger}  {h_src} → {h_dst}{tag}"
            suptitle.set_text(action)

    else:
        fig, ax = plt.subplots(figsize=(base_w, 6))
        fig.patch.set_facecolor('#f8f8f8')
        ax.set_facecolor('#f8f8f8')
        artists    = setup_ax(ax, pos, edges, sw_list, host_labels,
                              xlim, ylim, aspect, node_size)
        main_title = ax.set_title('', fontsize=10, pad=10)

        def update(frame):
            state = frame_states[frame]
            wmap  = state['weight_map']
            flows = state['active_flows']
            kind, src, dst, event_path, _ = state['event']

            update_ax(artists, flows, wmap, kind, event_path)
            max_w = max(wmap.values()) if wmap else 0
            h_src = mac_to_host(src)
            h_dst = mac_to_host(dst)
            action = f"[{'ADD' if kind == 'flow_add' else 'REMOVE'}]  {h_src} → {h_dst}  path: {event_path}"
            main_title.set_text(
                f"{action}\nactive flows: {len(flows)}  max weight: {max_w}")

    ani = animation.FuncAnimation(
        fig, update,
        frames=len(frame_states),
        interval=interval_ms,
        repeat=False
    )

    plt.tight_layout()
    if save_path:
        print(f"[animate] Saving {len(frame_states)} frames to {save_path} ...")
        from matplotlib.animation import HTMLWriter
        ani.save(save_path, writer=HTMLWriter(embed_frames=True), dpi=72)
        print("[animate] Done")
    else:
        plt.show()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('log', help='activeflow log 路徑')
    parser.add_argument('--dist', default='data/k_short_dist.txt',
                        help='k_short_dist.txt 路徑')
    parser.add_argument('--topo', default=None, choices=['grid', 'cap'],
                        help='拓撲類型（預設使用檔案頂部的 TOPO 變數）')
    parser.add_argument('--interval', type=int, default=800,
                        help='每幀間隔 ms（預設 800）')
    parser.add_argument('--save', default=None,
                        help='儲存 HTML 路徑（指定時不開視窗）')
    args = parser.parse_args()

    if args.topo:
        TOPO = args.topo  # CLI 參數覆蓋檔案頂部設定

    if args.save:
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.animation as animation
        matplotlib.rcParams['animation.embed_limit'] = 200

    run_animation(args.log, args.dist, args.interval, save_path=args.save)
