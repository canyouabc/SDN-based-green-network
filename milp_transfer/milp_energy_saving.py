# -*- coding: utf-8 -*-
"""
用 Gurobi 求解「靜態瞬時流量快照」下的最小能耗路由問題（MILP），
公式照抄 TANET 論文第三章 (2)(3)(4) 與 Markiewicz et al. 2014 的原始表述：

    minimize  Σ_i S_i * C_switch_i  +  Σ_(u,v) L_uv * C_link_uv

    subject to:
      - 每條 flow 的流量守恆（從 src 到 dst 恰好一條路徑，多商品流 formulation）
      - 每條 link 的容量限制（Σ 經過該 link 的 flow 頻寬 <= link_bw）
      - S_i = 1  若且唯若 switch i 被任何一條 flow 使用（含端點）
      - L_uv = 1 若且唯若 link (u,v) 被任何一條 flow 使用（任一方向）

不用預先算好的 k-shortest 候選路徑——直接用 edge-based 變數讓 Gurobi
自己找全域最優路徑，這樣才是真正的「最優解」，不受候選路徑集合大小限制。

輸入：
  --topo       拓樸資料夾名稱（對應 data/<topo>/，需有 link_bw.txt／
               link_energy.txt／switch_energy.txt，跟 sim.py 的 _TOPO_FILES
               命名慣例一致）
  --seed-path  gen_seed.py 或 gen_geant_random_seed.py 產生的 seed json
  --batch-id   要用哪個 batch 當作這次的靜態流量快照（預設用第 1 個）
  --time-limit / --mip-gap  Gurobi 求解時間/誤差容忍度上限，拓樸大時務必設

輸出：
  節能率（跟 sim.py 的 calculate_energy_saving 用同一個公式，方便直接比較）、
  每條 flow 的最優路徑、哪些 switch/link 保持開啟。

用法範例：
  python milp_energy_saving.py --topo grid_2x2 --seed-path seed.json \
      --time-limit 300 --mip-gap 0.01
"""
import argparse
import csv
import json
import sys
import time

try:
    import gurobipy as gp
    from gurobipy import GRB
except ImportError:
    print("[ERROR] 找不到 gurobipy，請先 `pip install gurobipy`（需要有效的 Gurobi 授權才能求解）")
    sys.exit(1)


# =========================================================
# 拓樸資料載入（跟 sim.py 的 MockApp._load_* 邏輯一致，只是不需要 k_short）
# =========================================================

def load_link_bw(filepath):
    """回傳 {(u,v): bw}（雙向皆有一筆），以及去重後的無向邊列表 [(u,v), ...]（u<v）"""
    link_bw = {}
    undirected = set()
    with open(filepath, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            u, v, bw = int(parts[0]), int(parts[1]), float(parts[2])
            link_bw[(u, v)] = bw
            link_bw[(v, u)] = bw
            undirected.add((min(u, v), max(u, v)))
    return link_bw, sorted(undirected)


def load_energy_col3(filepath):
    data = {}
    with open(filepath, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            data[int(parts[0])] = float(parts[2])
    return data


def load_link_energy(filepath):
    """回傳 {(u,v): energy}（雙向皆有一筆）"""
    data = {}
    with open(filepath, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            u, v, val = int(parts[0]), int(parts[1]), float(parts[2])
            data[(u, v)] = val
            data[(v, u)] = val
    return data


# grid_2x2/grid_3x3/grid_4x4/grid(5x5) 只有外圍 switch 接 host（grid_4x4_allhosts
# 才是全部 switch 都接 host），host 編號是照 grid_topo_*.py 的外圍走訪順序分配，
# 不是 switch dpid 順序，見 gen_kshort_generic.py 的 border_host_switch_map()——
# 這裡重複同一套公式，避免 milp_energy_saving.py 額外依賴 Auto_routing_k_short。
_BORDER_GRID_N = {'grid_2x2': 2, 'grid_3x3': 3, 'grid_4x4': 4, 'grid': 5, 'grid_5x5': 5, 'grid_6x6': 6}


def _border_host_switch_map(n_grid):
    def sw_id(r, c):
        return (r - 1) * n_grid + c

    border = []
    border += [(1, c) for c in range(1, n_grid + 1)]
    border += [(r, n_grid) for r in range(2, n_grid)]
    border += [(n_grid, c) for c in range(n_grid, 0, -1)]
    border += [(r, 1) for r in range(n_grid - 1, 1, -1)]
    return {idx + 1: sw_id(r, c) for idx, (r, c) in enumerate(border)}


def _fattree_host_switch_map(k):
    """跟 gen_fattree.py 的 build_fattree() 同一套規則：host 編號依
    pod -> pod內edge順序 -> edge內順序，只有 edge switch 接 host。"""
    half = k // 2
    num_core = half * half
    num_agg = k * half

    def edge_dpid(pod, j):
        return num_core + num_agg + pod * half + j + 1

    mapping = {}
    h = 0
    for pod in range(k):
        for e in range(half):
            for _ in range(half):
                h += 1
                mapping[h] = edge_dpid(pod, e)
    return mapping


_FATTREE_K = {'fattree_k4': 4}


def host_to_switch(host_name, topo=None):
    """host 名稱（如 'h5'）→ switch dpid。

    grid_4x4_allhosts／GEANT 系列 host:switch 是 1:1，h{n} 對應的 switch dpid
    就是 n。但 cap、grid_2x2/3x3/4x4/grid(5x5)、fattree_k* 都不是 1:1：
      - cap（cap_topo.py）：45 個 switch 裡只有 27 個邊緣 switch 承載 54 個
        host，每個邊緣 switch 接 HOSTS_PER_EDGE=2 個 host。
      - grid_2x2/3x3/4x4/grid（grid_topo_*.py）：只有外圍 switch 接 host，
        host 編號是外圍走訪順序，不是 dpid 順序（h12 在 grid_4x4 的 dpid
        是 5，不是 12——2026-09-23 發現，之前一直用錯）。
      - fattree_k*（gen_fattree.py）：只有 edge switch 接 host，host 編號
        依 pod -> edge 順序 -> edge內順序分配。
    """
    n = int(host_name[1:])
    if topo == 'cap':
        if n <= 42:
            return 25 + (n - 1) // 2
        return 19 + (n - 43) // 2
    if topo in _BORDER_GRID_N:
        return _border_host_switch_map(_BORDER_GRID_N[topo])[n]
    if topo in _FATTREE_K:
        return _fattree_host_switch_map(_FATTREE_K[topo])[n]
    return n


# =========================================================
# MILP 建構與求解
# =========================================================

def solve(topo_dir, flows, time_limit=None, mip_gap=None, verbose=True):
    """
    topo_dir: 'data/<topo>' 資料夾路徑
    flows: [(src_dpid, dst_dpid, bw_mbps), ...]，已經是 switch dpid（不是 host 名稱）
    回傳: dict，含 energy_saving_percent／active_switches／active_links／flow_paths
    """
    link_bw, undirected_links = load_link_bw(f'{topo_dir}/link_bw.txt')
    switch_energy = load_energy_col3(f'{topo_dir}/switch_energy.txt')
    link_energy = load_link_energy(f'{topo_dir}/link_energy.txt')

    switches = sorted(switch_energy.keys())
    directed_edges = [(u, v) for (u, v) in link_bw.keys()]  # 雙向都有

    m = gp.Model('energy_saving_milp')
    if not verbose:
        m.Params.OutputFlag = 0   # 大量 batch 迴圈時關掉 Gurobi 自己的求解log，不然1000個batch會洗版又拖慢I/O
    if time_limit:
        m.Params.TimeLimit = time_limit
    if mip_gap:
        m.Params.MIPGap = mip_gap

    n_flows = len(flows)

    # ── 決策變數 ──────────────────────────────────────────
    # S[i]：switch i 是否開啟
    S = m.addVars(switches, vtype=GRB.BINARY, name='S')
    # L[u,v]：無向 link (u,v)（u<v）是否開啟
    L = m.addVars(undirected_links, vtype=GRB.BINARY, name='L')
    # x[f, u, v]：第 f 條 flow 是否使用有向邊 u->v
    x = m.addVars(range(n_flows), directed_edges, vtype=GRB.BINARY, name='x')

    # ── 目標函數：minimize Σ S_i*C_i + Σ L_uv*C_uv ──────────
    m.setObjective(
        gp.quicksum(S[i] * switch_energy[i] for i in switches)
        + gp.quicksum(L[u, v] * link_energy[(u, v)] for (u, v) in undirected_links),
        GRB.MINIMIZE
    )

    # ── 限制式 1：流量守恆（每條 flow 從 src 到 dst 剛好一條路徑）──
    # src==dst 的「本地流量」（cap 拓樸裡同一個邊緣 switch 掛兩台 host、
    # 兩台互傳的情況）不需要走任何邊，直接跳過守恆限制式，改成強制
    # 該 switch 開啟即可——否則 src 節點會被要求淨流出=1，但沒有任何
    # 邊能製造這個淨流出，模型必然 infeasible。
    for fidx, (src, dst, bw) in enumerate(flows):
        if src == dst:
            m.addConstr(S[src] >= 1, name=f'local_flow{fidx}_{src}')
            continue
        for node in switches:
            out_flow = gp.quicksum(x[fidx, node, v] for u2, v in directed_edges if u2 == node)
            in_flow = gp.quicksum(x[fidx, u, node] for u, v2 in directed_edges if v2 == node)
            if node == src:
                m.addConstr(out_flow - in_flow == 1, name=f'flow{fidx}_conserve_{node}')
            elif node == dst:
                m.addConstr(out_flow - in_flow == -1, name=f'flow{fidx}_conserve_{node}')
            else:
                m.addConstr(out_flow - in_flow == 0, name=f'flow{fidx}_conserve_{node}')

    # ── 限制式 2：link 容量（雙向流量合計不能超過容量）──────
    for (u, v) in undirected_links:
        cap = link_bw[(u, v)]
        total_load = gp.quicksum(
            flows[fidx][2] * (x[fidx, u, v] + x[fidx, v, u])
            for fidx in range(n_flows)
        )
        m.addConstr(total_load <= cap, name=f'cap_{u}_{v}')

    # ── 限制式 3：switch 開啟狀態跟隨使用情況 ──────────────
    for i in switches:
        adj_edges = [(u, v) for (u, v) in directed_edges if u == i or v == i]
        for fidx in range(n_flows):
            for (u, v) in adj_edges:
                m.addConstr(S[i] >= x[fidx, u, v], name=f'sw_{i}_f{fidx}_{u}_{v}')

    # ── 限制式 4：link 開啟狀態跟隨使用情況（任一方向）──────
    for (u, v) in undirected_links:
        for fidx in range(n_flows):
            m.addConstr(L[u, v] >= x[fidx, u, v], name=f'lk_{u}_{v}_f{fidx}_fwd')
            m.addConstr(L[u, v] >= x[fidx, v, u], name=f'lk_{u}_{v}_f{fidx}_rev')

    if verbose:
        print(f"[MILP] switches={len(switches)}  links={len(undirected_links)}  flows={n_flows}")
        print(f"[MILP] 變數數: S={len(switches)} L={len(undirected_links)} x={n_flows*len(directed_edges)}")

    m.optimize()

    if m.Status not in (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL):
        return {'status': m.Status, 'error': 'no feasible solution found'}

    # ── 結果整理 ─────────────────────────────────────────
    active_switches = [i for i in switches if S[i].X > 0.5]
    active_links = [(u, v) for (u, v) in undirected_links if L[u, v].X > 0.5]

    total_energy = sum(switch_energy.values()) + sum(link_energy[(u, v)] for (u, v) in undirected_links)
    used_energy = (
        sum(switch_energy[i] for i in active_switches)
        + sum(link_energy[(u, v)] for (u, v) in active_links)
    )
    saving_percent = (total_energy - used_energy) / total_energy * 100.0 if total_energy > 0 else 0.0

    # 還原每條 flow 的實際路徑（從 x 變數重建，DFS 沿著被選中的邊走）
    flow_paths = []
    for fidx, (src, dst, bw) in enumerate(flows):
        path = [src]
        cur = src
        visited = {src}
        while cur != dst:
            nxt = None
            for (u, v) in directed_edges:
                if u == cur and x[fidx, u, v].X > 0.5 and v not in visited:
                    nxt = v
                    break
            if nxt is None:
                path.append('...(重建失敗，請查 x 變數)')
                break
            path.append(nxt)
            visited.add(nxt)
            cur = nxt
        flow_paths.append({'src': src, 'dst': dst, 'bw_mbps': bw, 'path': path})

    return {
        'status': m.Status,
        'status_name': {GRB.OPTIMAL: 'OPTIMAL', GRB.TIME_LIMIT: 'TIME_LIMIT(次佳解)',
                         GRB.SUBOPTIMAL: 'SUBOPTIMAL'}.get(m.Status, str(m.Status)),
        'mip_gap': m.MIPGap if m.SolCount > 0 else None,
        'total_energy_w': total_energy,
        'used_energy_w': used_energy,
        'energy_saving_percent': saving_percent,
        'active_switches': active_switches,
        'active_links': active_links,
        'flow_paths': flow_paths,
    }


# =========================================================
# CLI
# =========================================================

def load_flows_from_seed(seed_path, batch_id=None, topo=None):
    """讀 gen_seed.py / gen_geant_random_seed.py 產生的 seed json，
    取其中一個 batch 的 flows，轉成 (src_dpid, dst_dpid, bw_mbps) 列表。
    靜態快照情境下忽略 interval（不管是不是 0，統統當作同時存在）。"""
    with open(seed_path, encoding='utf-8') as f:
        seed_data = json.load(f)
    batches = seed_data['batches']
    if batch_id is None:
        batch = batches[0]
    else:
        batch = next(b for b in batches if b['batch_id'] == batch_id)
    flows = []
    for flow in batch['flows']:
        src = host_to_switch(flow['src'], topo=topo)
        dst = host_to_switch(flow['dst'], topo=topo)
        bw = flow['bw_mbps']
        flows.append((src, dst, bw))
    return flows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--topo', type=str, required=True, help='拓樸資料夾名稱，例如 grid_2x2（對應 data/grid_2x2/）')
    parser.add_argument('--seed-path', type=str, required=True)
    parser.add_argument('--batch-id', type=int, default=None, help='要用 seed 檔裡的哪個 batch，預設用第一個')
    parser.add_argument('--time-limit', type=float, default=None, help='Gurobi 求解秒數上限')
    parser.add_argument('--mip-gap', type=float, default=None, help='容許的最優性誤差比例，例如 0.01=1%')
    parser.add_argument('--all-batches', action='store_true',
                         help='在同一個 process 內跑完 seed 檔的全部 batch（不逐次重開 process/重建 '
                              'Gurobi environment），輸出成 csv。batch 數很多（例如 1000）時務必用這個，'
                              '否則光是重複啟動 process 的開銷就會比實際求解時間貴很多')
    parser.add_argument('--csv-out', type=str, default=None,
                         help='--all-batches 的 csv 輸出路徑，預設用 seed 檔名推導（去掉 .json 加 _results.csv）')
    args = parser.parse_args()

    topo_dir = f'data/{args.topo}'

    if args.all_batches:
        with open(args.seed_path, encoding='utf-8') as f:
            seed_data = json.load(f)
        batches = seed_data['batches']
        csv_path = args.csv_out or args.seed_path.replace('.json', '_results.csv')

        link_bw, undirected_links = load_link_bw(f'{topo_dir}/link_bw.txt')
        switch_energy = load_energy_col3(f'{topo_dir}/switch_energy.txt')
        n_switches, n_links = len(switch_energy), len(undirected_links)

        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['topo', 'seed_file', 'batch', 'n_switches', 'n_links', 'n_flows',
                              'energy_saving_percent', 'mip_gap', 'solve_time_sec', 'status'])
            for i, batch in enumerate(batches):
                flows = [(host_to_switch(fl['src'], topo=args.topo),
                          host_to_switch(fl['dst'], topo=args.topo),
                          fl['bw_mbps']) for fl in batch['flows']]
                t0 = time.time()
                result = solve(topo_dir, flows, time_limit=args.time_limit, mip_gap=args.mip_gap, verbose=False)
                elapsed = time.time() - t0
                writer.writerow([
                    args.topo, args.seed_path, batch.get('batch_id', i + 1), n_switches, n_links, len(flows),
                    round(result.get('energy_saving_percent', float('nan')), 4),
                    result.get('mip_gap'), round(elapsed, 3),
                    result.get('status_name', result.get('error')),
                ])
                if (i + 1) % 100 == 0 or i + 1 == len(batches):
                    print(f"[{args.seed_path}] {i+1}/{len(batches)} batch 完成")
        print(f"已存檔 {csv_path}")
    else:
        flows = load_flows_from_seed(args.seed_path, args.batch_id, topo=args.topo)
        print(f"[MILP] 讀入 {len(flows)} 條 flow（來自 {args.seed_path}）")

        result = solve(topo_dir, flows, time_limit=args.time_limit, mip_gap=args.mip_gap)

        print(f"\n{'='*60}")
        print(f"求解狀態: {result.get('status_name', result.get('error'))}")
        if 'energy_saving_percent' in result:
            print(f"MIP Gap: {result['mip_gap']}")
            print(f"節能率: {result['energy_saving_percent']:.2f}%")
            print(f"開啟 switch 數: {len(result['active_switches'])}  {result['active_switches']}")
            print(f"開啟 link 數: {len(result['active_links'])}")
            print(f"\n各 flow 最優路徑：")
            for fp in result['flow_paths']:
                print(f"  h{fp['src']} -> h{fp['dst']} ({fp['bw_mbps']:.2f} Mbps): {fp['path']}")
