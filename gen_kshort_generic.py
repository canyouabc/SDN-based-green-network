# -*- coding: utf-8 -*-
"""
通用版離線 k-shortest 產生器（不需要開 Mininet），取代原本一次性寫死單一拓樸的
gen_grid4x4_allhosts_kshort.py。用當前 data/<topo>/ 底下的 link_bw/link_energy/
switch_energy 重新算 k_short.txt／k_short_dist.txt。

host↔switch 對應有兩種模式：
  - 預設（不帶 --grid-n）：host 1:1 對應 switch dpid（h{n} -> switch n），
    適用 grid_4x4_allhosts、GEANT 這類「每個 switch 都接一個 host」的拓樸。
  - 帶 --grid-n N：適用 grid_2x2/grid_3x3/grid_4x4/grid(5x5) 這種「只有外圍
    switch 接 host」的拓樸——host 編號是照 grid_topo_*.py 的外圍走訪順序
    （上→右→下→左）分配的，不是 dpid 順序，必須用 border_host_switch_map()
    重現同一套走訪邏輯才會對應到正確的 switch，否則會像 2026-09-23 發現的
    那樣：內部 switch 被誤當成 host、真正外圍的 host switch 反而漏算。

用法：
  python gen_kshort_generic.py --topo grid_4x4_allhosts --hosts 16 --k 200
  python gen_kshort_generic.py --topo grid_4x4 --hosts 12 --grid-n 4 --k 200
"""
import argparse
import contextlib
import io
from collections import defaultdict
from modules.routing_auto_k_short import Auto_routing_k_short


def border_host_switch_map(n_grid):
    """重現 grid_topo_*.py 的外圍走訪順序，回傳 {host_num(1-based): switch_dpid}。"""
    def sw_id(r, c):
        return (r - 1) * n_grid + c

    border = []
    border += [(1, c) for c in range(1, n_grid + 1)]
    border += [(r, n_grid) for r in range(2, n_grid)]
    border += [(n_grid, c) for c in range(n_grid, 0, -1)]
    border += [(r, 1) for r in range(n_grid - 1, 1, -1)]
    return {idx + 1: sw_id(r, c) for idx, (r, c) in enumerate(border)}


class MiniApp:
    def __init__(self, data_dir, num_switches, host_to_dpid=None):
        self.myswitches = []
        self.adjacency = defaultdict(lambda: defaultdict(lambda: None))
        self.link_bw = {}
        self.link_delay = {}
        self.link_used_bw = {}
        self.host_macs = {}
        self._load_link_bw(f'{data_dir}/link_bw.txt')
        self.switch_energy = self._load_col3(f'{data_dir}/switch_energy.txt')
        self.link_energy = self._load_link_val(f'{data_dir}/link_energy.txt')
        if host_to_dpid is None:
            host_to_dpid = {n: n for n in range(1, num_switches + 1)}
        for host_num, dpid in host_to_dpid.items():
            mac = f'00:00:00:00:00:{host_num:02x}'
            self.host_macs[mac] = (dpid, 1)

    def _load_link_bw(self, filepath):
        with open(filepath, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                u, v, bw = int(parts[0]), int(parts[1]), float(parts[2])
                self.link_bw[(u, v)] = bw
                self.link_bw[(v, u)] = bw
                self.adjacency[u][v] = v
                self.adjacency[v][u] = u
                for sw in (u, v):
                    if sw not in self.myswitches:
                        self.myswitches.append(sw)

    def _load_col3(self, filepath):
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

    def _load_link_val(self, filepath):
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


def check_missing_direct_edges(link_bw_path, k_short_path, host_to_dpid):
    """驗證「兩個switch都有host」的每一條實體邊，兩個方向的 host pair 是否都有
    對應的直接 1-hop 候選路徑。只看兩端都有host的邊——沒有host的內部switch
    不該被拿來檢查（它們本來就不會出現在任何 host-to-host 的查詢裡）。"""
    dpid_to_host = {dpid: host for host, dpid in host_to_dpid.items()}

    edges = set()
    with open(link_bw_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            u, v = int(parts[0]), int(parts[1])
            if u in dpid_to_host and v in dpid_to_host:
                edges.add((min(u, v), max(u, v)))

    direct = {}
    with open(k_short_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            src_dpid = host_to_dpid.get(int(parts[0].split(':')[-1], 16))
            dst_dpid = host_to_dpid.get(int(parts[1].split(':')[-1], 16))
            i = 0
            has2 = False
            while i + 4 < len(parts):
                path = [int(x) for x in parts[i + 4].strip('[]').split(',')]
                if len(path) == 2 and path[0] == src_dpid and path[-1] == dst_dpid:
                    has2 = True
                i += 5
            direct[(src_dpid, dst_dpid)] = direct.get((src_dpid, dst_dpid), False) or has2

    missing = []
    for (u, v) in edges:
        for a, b in [(u, v), (v, u)]:
            if not direct.get((a, b), False):
                missing.append((dpid_to_host[a], dpid_to_host[b]))  # 回報 host 編號，較直覺
    return missing


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--topo', type=str, required=True, help='data/<topo>/ 的資料夾名稱')
    parser.add_argument('--hosts', type=int, required=True, help='host 數')
    parser.add_argument('--grid-n', type=int, default=None,
                         help='只有外圍switch接host的NxN grid拓樸（grid_2x2/3x3/4x4/grid(5x5)）才需要帶，'
                              '傳入grid邊長N，會依grid_topo_*.py的外圍走訪順序建立正確的host↔switch對應；'
                              '不帶則沿用host 1:1對應switch dpid的舊慣例（grid_4x4_allhosts/GEANT等）')
    parser.add_argument('--k', type=int, default=200)
    args = parser.parse_args()

    data_dir = f'data/{args.topo}'
    host_to_dpid = border_host_switch_map(args.grid_n) if args.grid_n else None
    if host_to_dpid is not None and len(host_to_dpid) != args.hosts:
        raise SystemExit(f'--grid-n {args.grid_n} 算出的外圍host數={len(host_to_dpid)}，'
                          f'跟 --hosts {args.hosts} 對不上，請檢查參數')
    app = MiniApp(data_dir, args.hosts, host_to_dpid=host_to_dpid)
    gen = Auto_routing_k_short(app)
    with contextlib.redirect_stdout(io.StringIO()):
        n = gen.compute_all_k_shortest_paths_once(k=args.k, output_filepath=f'{data_dir}/k_short.txt')
    print(f'[{args.topo}] 完成，共 {n} 條路徑')

    missing = check_missing_direct_edges(f'{data_dir}/link_bw.txt', f'{data_dir}/k_short.txt',
                                          host_to_dpid or {n: n for n in range(1, args.hosts + 1)})
    if missing:
        print(f'[{args.topo}] 警告：仍有 {len(missing)} 個 ordered pair 缺少直接1-hop候選: {missing[:10]}')
    else:
        print(f'[{args.topo}] 驗證通過：所有相鄰 pair 都有直接1-hop候選')
