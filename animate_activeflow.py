# -*- coding: utf-8 -*-
import re
import argparse
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib import gridspec

N = 5  # 5x5 grid


def sw_pos(sw_id):
    r = (sw_id - 1) // N
    c = (sw_id - 1) % N
    return (c, N - 1 - r)


def mac_to_host(mac):
    return f"h{int(mac.split(':')[-1], 16)}"


def build_edges():
    edges = []
    for sw in range(1, N * N + 1):
        r = (sw - 1) // N
        c = (sw - 1) % N
        if c < N - 1:
            edges.append((sw, sw + 1))
        if r < N - 1:
            edges.append((sw, sw + N))
    return edges


def get_path_edges(path):
    return {(min(path[i], path[i+1]), max(path[i], path[i+1]))
            for i in range(len(path) - 1)}


def parse_log(filepath):
    """解析 activeflow log。
    回傳 (all_events, weight_snapshots)
    all_events: list of (kind, src, dst, path, extra)
      kind: 'flow_add' | 'flow_rem' | 'ns_add' | 'ns_rem'
      extra: hop (ns_add 時), 否則 None
    """
    all_events = []
    weight_snapshots = {}

    add_re      = re.compile(r'\[ActiveFlow\] 新增: (.+?) -> (.+?), 路徑: \[(.+?)\]')
    rem_re      = re.compile(r'\[ActiveFlow\] 移除: (.+?) -> (.+)')
    wmap_re     = re.compile(r'\[WeightMap\] (\{.+\})')
    ns_add_re   = re.compile(r'\[NonShortest\] 新增: (.+?) -> (.+?), hop=(\d+), 路徑: \[(.+?)\]')
    ns_rem_re   = re.compile(r'\[NonShortest\] 移除: (.+?) -> (.+)')
    trigger_re  = re.compile(r'\[(FLOW_NEW|FLOW_CASCADE_NS|FLOW_CASCADE)\]')

    pending_idx     = None
    pending_trigger = None

    with open(filepath) as f:
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
                pending_idx = len(all_events) - 1
                continue

            m = rem_re.search(line)
            if m:
                src = m.group(1).strip()
                dst = m.group(2).strip()
                all_events.append(('flow_rem', src, dst, None, None))
                pending_idx = len(all_events) - 1
                continue

            m = wmap_re.search(line)
            if m:
                last_wmap = {int(k): v for k, v in eval(m.group(1)).items()}
                if pending_idx is not None:
                    weight_snapshots[pending_idx] = last_wmap
                    pending_idx = None
                continue

            m = ns_add_re.search(line)
            if m:
                src  = m.group(1).strip()
                dst  = m.group(2).strip()
                hop  = int(m.group(3))
                path = [int(x) for x in m.group(4).split(',')]
                all_events.append(('ns_add', src, dst, path, hop))
                continue

            m = ns_rem_re.search(line)
            if m:
                src = m.group(1).strip()
                dst = m.group(2).strip()
                all_events.append(('ns_rem', src, dst, None, None))

    return all_events, weight_snapshots


def build_states(all_events, weight_snapshots):
    active_flows = {}   # {(src,dst): path}
    non_shortest = {}   # {(src,dst): hop}
    states = []
    last_wmap = {}

    for i, event in enumerate(all_events):
        kind, src, dst, path, extra = event

        if kind == 'flow_add':
            active_flows[(src, dst)] = path
        elif kind == 'flow_rem':
            active_flows.pop((src, dst), None)
            non_shortest.pop((src, dst), None)
        elif kind == 'ns_add':
            non_shortest[(src, dst)] = extra   # extra = hop
        elif kind == 'ns_rem':
            non_shortest.pop((src, dst), None)

        last_wmap = weight_snapshots.get(i, last_wmap)

        states.append({
            'event':        event,
            'weight_map':   dict(last_wmap),
            'active_flows': dict(active_flows),
            'non_shortest': dict(non_shortest),
        })

    return states


def build_host_labels():
    border = []
    border += [(1, c) for c in range(1, N + 1)]
    border += [(r, N) for r in range(2, N)]
    border += [(N, c) for c in range(N, 0, -1)]
    border += [(r, 1) for r in range(N - 1, 1, -1)]
    return {(r - 1) * N + c: f"h{idx + 1}" for idx, (r, c) in enumerate(border)}


def setup_grid_ax(ax, pos, edges, host_labels):
    """初始化單一 grid ax 的靜態與動態元素，回傳 artists dict"""
    ax.set_facecolor('#f8f8f8')
    ax.set_xlim(-0.7, N - 0.3)
    ax.set_ylim(-0.7, N - 0.3)
    ax.set_aspect('equal')
    ax.axis('off')

    for sw, hname in host_labels.items():
        x, y = pos[sw]
        ax.text(x, y + 0.38, hname, ha='center', va='bottom',
                fontsize=7, color='#2980b9', fontweight='bold')

    for sw in range(1, N * N + 1):
        x, y = pos[sw]
        ax.text(x, y + 0.06, str(sw), ha='center', va='center',
                fontsize=7.5, zorder=4, fontweight='bold')

    edge_artists = {}
    for a, b in edges:
        x0, y0 = pos[a]; x1, y1 = pos[b]
        line, = ax.plot([x0, x1], [y0, y1], color='#cccccc', lw=0.8, zorder=1)
        edge_artists[(a, b)] = line

    xs = [pos[sw][0] for sw in range(1, N * N + 1)]
    ys = [pos[sw][1] for sw in range(1, N * N + 1)]
    scat = ax.scatter(xs, ys, s=600, c=['#ffffcc'] * (N * N),
                      zorder=3, edgecolors='#333333', linewidths=0.8)

    w_texts = {}
    for sw in range(1, N * N + 1):
        x, y = pos[sw]
        w_texts[sw] = ax.text(x, y - 0.2, '', ha='center', va='top',
                               fontsize=6, color='#555555', zorder=4)

    subtitle = ax.text(0.5, -0.04, '', transform=ax.transAxes,
                       ha='center', va='top', fontsize=7.5, color='#555555', clip_on=False)

    return {'edge_artists': edge_artists, 'scat': scat,
            'w_texts': w_texts, 'subtitle': subtitle}


def update_grid(artists, flows, wmap, event_kind, event_path):
    """更新單一 grid ax 的動態元素"""
    max_w = max(wmap.values()) if wmap else 1

    active_edges = set()
    for p in flows.values():
        active_edges |= get_path_edges(p)
    event_edges = get_path_edges(event_path) if event_path else set()

    for (a, b), line in artists['edge_artists'].items():
        key = (min(a, b), max(a, b))
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
    for sw in range(1, N * N + 1):
        w = wmap.get(sw, 0)
        intensity = w / max_w if max_w > 0 else 0
        colors.append(plt.cm.YlOrRd(0.1 + 0.9 * intensity))
    artists['scat'].set_facecolor(colors)

    for sw in range(1, N * N + 1):
        w = wmap.get(sw, 0)
        artists['w_texts'][sw].set_text(f'w={w}' if w > 0 else '')


def update_text_panel(ax_text, active_flows, non_shortest):
    """更新右側文字面板"""
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


def run_animation(log_path, dist_path, interval_ms, save_path=None):
    all_events, weight_snapshots = parse_log(log_path)
    if not all_events:
        print("No events found")
        return

    states = build_states(all_events, weight_snapshots)

    # 判定是否為 self 模式（log 中有 [NonShortest] 事件）
    is_self_mode = any(e[0] in ('ns_add', 'ns_rem') for e in all_events)

    # 只渲染 flow_add / flow_rem 幀（ns 事件更新 state 但不單獨成幀）
    frame_states = [s for s in states if s['event'][0] in ('flow_add', 'flow_rem')]
    if not frame_states:
        print("No ActiveFlow events found")
        return

    edges       = build_edges()
    pos         = {sw: sw_pos(sw) for sw in range(1, N * N + 1)}
    host_labels = build_host_labels()

    if is_self_mode:
        fig = plt.figure(figsize=(16, 6.5))
        fig.patch.set_facecolor('#f8f8f8')
        gs = gridspec.GridSpec(1, 3, width_ratios=[5, 5, 3],
                               figure=fig, wspace=0.05)
        ax1     = fig.add_subplot(gs[0])
        ax2     = fig.add_subplot(gs[1])
        ax_text = fig.add_subplot(gs[2])

        artists1 = setup_grid_ax(ax1, pos, edges, host_labels)
        artists2 = setup_grid_ax(ax2, pos, edges, host_labels)
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

            # Graph 1：完整 active flows
            update_grid(artists1, flows, wmap, kind, event_path)
            artists1['subtitle'].set_text(
                f"flows={len(flows)}  non-shortest={len(non_shortest)}")

            # Graph 2：排除非最短hop清單
            filtered = {k: v for k, v in flows.items() if k not in non_shortest}
            ep2 = None if is_ns else event_path
            ek2 = None if is_ns else kind
            update_grid(artists2, filtered, wmap, ek2, ep2)
            artists2['subtitle'].set_text(f"flows={len(filtered)}")

            # 文字面板
            update_text_panel(ax_text, flows, non_shortest)

            # 主標題
            tag     = "  ★non-shortest" if is_ns else ""
            trigger = f"  [{extra}]" if kind == 'flow_add' and extra else ""
            action  = f"[{'ADD' if kind == 'flow_add' else 'REMOVE'}]{trigger}  {h_src} → {h_dst}{tag}"
            suptitle.set_text(action)

    else:
        fig, ax = plt.subplots(figsize=(6, 6))
        fig.patch.set_facecolor('#f8f8f8')
        ax.set_facecolor('#f8f8f8')
        artists    = setup_grid_ax(ax, pos, edges, host_labels)
        main_title = ax.set_title('', fontsize=10, pad=10)

        def update(frame):
            state = frame_states[frame]
            wmap  = state['weight_map']
            flows = state['active_flows']
            kind, src, dst, event_path, _ = state['event']

            update_grid(artists, flows, wmap, kind, event_path)

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
                        help='k_short_dist.txt 路徑（預設 data/k_short_dist.txt）')
    parser.add_argument('--interval', type=int, default=800,
                        help='每幀間隔 ms（預設 800）')
    parser.add_argument('--save', default=None,
                        help='儲存 HTML 路徑（指定時不開視窗）')
    args = parser.parse_args()

    if args.save:
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.animation as animation

    run_animation(args.log, args.dist, args.interval, save_path=args.save)
