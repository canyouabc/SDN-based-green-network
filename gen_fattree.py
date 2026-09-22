# -*- coding: utf-8 -*-
"""
產生 k-ary fat-tree 的離線資料（不需要開 Mininet），比照 GEANT／grid_4x4_allhosts
當初的做法：直接組出 adjacency，寫 data/<topo>/ 的 link_bw／link_energy／
switch_energy，再呼叫 Auto_routing_k_short 算 k_short.txt／k_short_dist.txt。

拓樸規則（標準 k-ary fat-tree，k 必須是偶數）：
  - k 個 pod，每個 pod 有 k/2 個 aggregation switch、k/2 個 edge switch
  - (k/2)^2 個 core switch，分成 k/2 組（group），每組 k/2 個
  - core switch (group=g, idx=i) 連到每個 pod 的 aggregation switch j=g
  - 同一個 pod 內，aggregation 與 edge 兩兩全連接（bipartite）
  - 每個 edge switch 接 k/2 個 host

dpid 編號順序：core(1..) → 依序每個 pod 的 agg → 每個 pod 的 edge。
host 編號順序：依 pod → pod 內 edge 順序 → edge 內順序，逐一編號（h1 開始）。

用法：
  python gen_fattree.py --k 4 --switch-energy 146 --link-energy 0.18 --link-bw 250
"""
import argparse
import contextlib
import io
import os
from collections import defaultdict
from modules.routing_auto_k_short import Auto_routing_k_short


def build_fattree(k):
    """回傳 (edges, host_to_dpid)。edges 是 [(u,v), ...] 無向邊列表（dpid，1-based）。"""
    half = k // 2
    num_core = half * half
    num_agg = k * half
    num_edge = k * half

    def core_dpid(g, i):
        return g * half + i + 1

    def agg_dpid(pod, j):
        return num_core + pod * half + j + 1

    def edge_dpid(pod, j):
        return num_core + num_agg + pod * half + j + 1

    edges = []
    # core <-> agg：core(g,i) 連到每個 pod 的 agg(pod, j=g)
    for g in range(half):
        for i in range(half):
            c = core_dpid(g, i)
            for pod in range(k):
                edges.append((c, agg_dpid(pod, g)))
    # agg <-> edge：同一 pod 內全連接
    for pod in range(k):
        for j in range(half):
            for e in range(half):
                edges.append((agg_dpid(pod, j), edge_dpid(pod, e)))

    # host 編號：依 pod -> pod 內 edge 順序 -> edge 內順序
    host_to_dpid = {}
    h = 0
    for pod in range(k):
        for e in range(half):
            for _ in range(half):
                h += 1
                host_to_dpid[h] = edge_dpid(pod, e)

    return edges, host_to_dpid, {'core': num_core, 'agg': num_agg, 'edge': num_edge}


class FatTreeApp:
    """比照 gen_kshort_generic.py 的 MiniApp，供 Auto_routing_k_short 使用。"""
    def __init__(self, edges, host_to_dpid, switch_energy_val, link_energy_val, link_bw_val):
        self.myswitches = []
        self.adjacency = defaultdict(lambda: defaultdict(lambda: None))
        self.link_bw = {}
        self.link_delay = {}
        self.link_used_bw = {}
        self.host_macs = {}
        self.switch_energy = {}
        self.link_energy = {}

        switches = set()
        for u, v in edges:
            switches.add(u)
            switches.add(v)
            self.adjacency[u][v] = v
            self.adjacency[v][u] = u
            self.link_bw[(u, v)] = link_bw_val
            self.link_bw[(v, u)] = link_bw_val
            self.link_energy[(u, v)] = link_energy_val
            self.link_energy[(v, u)] = link_energy_val
        self.myswitches = sorted(switches)
        for sw in self.myswitches:
            self.switch_energy[sw] = switch_energy_val

        for host_num, dpid in host_to_dpid.items():
            mac = f'00:00:00:00:00:{host_num:02x}'
            self.host_macs[mac] = (dpid, 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--k', type=int, required=True, help='fat-tree 的 k（偶數，每個switch的port數）')
    parser.add_argument('--switch-energy', type=float, default=146.0)
    parser.add_argument('--link-energy', type=float, default=0.18)
    parser.add_argument('--link-bw', type=float, default=250.0)
    parser.add_argument('--kshort-k', type=int, default=200, help='k-shortest 的 k（候選路徑數上限）')
    args = parser.parse_args()

    if args.k % 2 != 0:
        raise SystemExit('k 必須是偶數')

    edges, host_to_dpid, counts = build_fattree(args.k)
    topo_name = f'fattree_k{args.k}'
    data_dir = f'data/{topo_name}'
    os.makedirs(data_dir, exist_ok=True)

    unique_edges = sorted({(min(u, v), max(u, v)) for u, v in edges})
    with open(f'{data_dir}/link_bw.txt', 'w', encoding='utf-8') as f:
        f.write('# src   dst   bw(Mbps)\n')
        for u, v in unique_edges:
            f.write(f'{u}\t{v}\t{args.link_bw}\n')
    with open(f'{data_dir}/link_energy.txt', 'w', encoding='utf-8') as f:
        f.write('# src   dst   energy(W)\n')
        for u, v in unique_edges:
            f.write(f'{u}\t{v}\t{args.link_energy}\n')
    all_switches = sorted({u for e in edges for u in e})
    with open(f'{data_dir}/switch_energy.txt', 'w', encoding='utf-8') as f:
        f.write('# dpid  name  energy(W)\n')
        for dpid in all_switches:
            f.write(f'{dpid}\ts{dpid}\t{args.switch_energy}\n')

    print(f"[{topo_name}] k={args.k}: core={counts['core']} agg={counts['agg']} edge={counts['edge']} "
          f"switch總數={len(all_switches)} link總數={len(unique_edges)} host總數={len(host_to_dpid)}")

    app = FatTreeApp(edges, host_to_dpid, args.switch_energy, args.link_energy, args.link_bw)
    gen = Auto_routing_k_short(app)
    with contextlib.redirect_stdout(io.StringIO()):
        n = gen.compute_all_k_shortest_paths_once(k=args.kshort_k, output_filepath=f'{data_dir}/k_short.txt')
    print(f"[{topo_name}] k_short 完成，共 {n} 條路徑")

    # 驗證：兩端都有host的邊，是否都有直接1-hop候選（沿用gen_kshort_generic.py的邏輯）
    import sys
    sys.path.insert(0, '.')
    from gen_kshort_generic import check_missing_direct_edges
    missing = check_missing_direct_edges(f'{data_dir}/link_bw.txt', f'{data_dir}/k_short.txt', host_to_dpid)
    if missing:
        print(f"[{topo_name}] 警告：{len(missing)} 個 host pair 缺少直接1-hop候選: {missing[:10]}")
    else:
        print(f"[{topo_name}] 驗證通過：所有相鄰host pair都有直接1-hop候選")
