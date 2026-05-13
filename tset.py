import gurobipy as gp
from gurobipy import GRB
from collections import defaultdict
import sys

# ── 拓撲定義（只寫單向，自動展開雙向） ──────────────────────────────────────

_links_one_way = {
    # Core <-> Core (400 Mbps)
    (1,2):400, (1,3):400, (1,4):400,
    (2,3):400, (2,4):400, (3,4):400,
    # Core <-> Distribution (150 Mbps)
    (1,5):150,  (1,6):150,  (1,7):150,  (1,8):150,
    (1,9):150,  (1,10):150, (1,11):150, (1,12):150,
    (2,5):150,  (2,6):150,  (2,7):150,  (2,8):150,
    (2,9):150,  (2,10):150, (2,11):150, (2,12):150,
    (3,13):150, (3,14):150, (3,15):150, (3,16):150,
    (3,17):150, (3,18):150,
    (4,13):150, (4,14):150, (4,15):150, (4,16):150,
    (4,17):150, (4,18):150,
    # Distribution <-> WAN (100 Mbps)
    (13,19):100, (13,20):100, (13,21):100,
    (14,19):100, (14,20):100, (14,21):100,
    (15,22):100, (15,23):100, (15,24):100,
    (16,22):100, (16,23):100, (16,24):100,
    # Distribution <-> Access (50 Mbps)
    (5,25):50, (5,26):50, (5,27):50, (5,28):50,
    (6,25):50, (6,26):50, (6,27):50, (6,28):50,
    (7,29):50, (7,30):50, (7,31):50, (7,32):50,
    (8,29):50, (8,30):50, (8,31):50, (8,32):50,
    (9,33):50, (9,34):50, (9,35):50, (9,36):50,
    (10,33):50, (10,34):50, (10,35):50, (10,36):50,
    (11,37):50, (11,38):50, (11,39):50, (11,40):50,
    (12,37):50, (12,38):50, (12,39):50, (12,40):50,
    (17,41):50, (17,42):50, (17,43):50, (17,44):50, (17,45):50,
    (18,41):50, (18,42):50, (18,43):50, (18,44):50, (18,45):50,
}

# 自動展開雙向
links = {}
for (i, j), bw in _links_one_way.items():
    links[(i, j)] = bw
    links[(j, i)] = bw

# Access/WAN Switch <-> Host（上行限制不應該限制雙向合計）
switch_to_host = {
    25:46, 26:47, 27:48, 28:49, 29:50,
    30:51, 31:52, 32:53, 33:54, 34:55,
    35:56, 36:57, 37:58, 38:59, 39:60,
    40:61, 41:62, 42:63, 43:64, 44:65,
    45:66,
    19:67, 20:68, 21:69,
    22:70, 23:71, 24:72,
}
for sw, h in switch_to_host.items():
    # ← 改為 1000，避免 host 端成為瓶頸
    links[(sw, h)] = 1000
    links[(h, sw)] = 1000

# physical_links：去除雙向重複，供 solve_mcf 使用
physical_links = set()
for (i, j) in links:
    physical_links.add((min(i, j), max(i, j)))

all_nodes = set()
for (i, j) in links:
    all_nodes.add(i)
    all_nodes.add(j)


# ── 流量需求資料結構 ───────────────────────────────────────────────────────────
# 格式：(host_a, host_b, 流量 Gbit/s)
# host_a 每秒送 x Gbit/s 的流量到 host_b
#
# 【方法一】直接在程式碼中定義
DEMANDS = [
    # (src_host, dst_host, Gbit/s)
    (46, 70, 0.005),   # h1  -> h25,  5 Mbps
    (47, 71, 0.003),   # h2  -> h26,  3 Mbps
    (48, 67, 0.004),   # h3  -> h22,  4 Mbps
    (54, 62, 0.006),   # h9  -> h17,  6 Mbps
    (50, 68, 0.002),   # h5  -> h23,  2 Mbps
    (55, 63, 0.007),   # h10 -> h18,  7 Mbps
]

# ↓ 補上這個函式
def load_demands_from_file(filepath):
    """
    從文字檔讀取需求，每行格式：
        host_a  host_b  流量(Gbit/s)
    # 開頭為注解行，空白行忽略
    """
    demands = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                src  = int(parts[0])
                dst  = int(parts[1])
                gbps = float(parts[2])
                demands.append((src, dst, gbps))
    except FileNotFoundError:
        print(f"[警告] 找不到檔案 '{filepath}'，改用內建 DEMANDS")
        return DEMANDS
    return demands

# ── 流量分解（Flow Decomposition） ───────────────────────────────────────────

def decompose_flow(src, dst, flow_vals):
    """
    將邊上的流量值分解成 [(路徑, 流量_Mbps), ...] 的清單。
    flow_vals: dict {(i,j): flow_value}，只包含流量 > 0 的邊
    """
    residual = defaultdict(float, flow_vals)
    paths = []
    EPS = 1e-6

    while True:
        # DFS 找從 src 到 dst 的路徑
        stack = [(src, [src], float("inf"))]
        visited = set()
        found = None

        while stack:
            node, path, bottleneck = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            if node == dst:
                found = (path, bottleneck)
                break
            for (i, j), val in list(residual.items()):
                if i == node and val > EPS and j not in visited:
                    stack.append((j, path + [j], min(bottleneck, val)))

        if not found:
            break

        path, bottleneck = found
        for k in range(len(path) - 1):
            residual[(path[k], path[k + 1])] -= bottleneck
        paths.append((path, bottleneck))

    return paths


# ── 讀取能耗資料 ──────────────────────────────────────────────────────────────

def load_switch_energy(filepath):
    """讀取 switch_energy.txt"""
    energy = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                dpid = int(parts[0])
                watt = float(parts[2])
                energy[dpid] = watt
    except FileNotFoundError:
        print(f"[警告] 找不到 {filepath}")
    return energy

def load_link_energy(filepath):
    """讀取 link_energy.txt"""
    energy = {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                src  = int(parts[0])
                dst  = int(parts[1])
                watt = float(parts[2])
                # 只保留單向（小→大），避免重複計算能耗
                key = (min(src, dst), max(src, dst))
                energy[key] = watt
    except FileNotFoundError:
        print(f"[警告] 找不到 {filepath}")
    return energy

# ── 多商品流最佳化（最小化總能耗） ───────────────────────────────────────────

def solve_mcf(demands, switch_energy, link_energy):
    demands_mbps = [(s, d, bw * 1000) for s, d, bw in demands]
    K = len(demands_mbps)
    link_list = list(links.keys())

    switch_nodes = [n for n in all_nodes if n <= 45]
    energy_links = list(link_energy.keys())  # 單向 key (小→大)

    # ← 新增：建立實體 link 集合（去除雙向重複）
    physical_links = set()
    for (i, j) in link_list:
        physical_links.add((min(i, j), max(i, j)))

    model = gp.Model("mcf_energy")
    model.setParam("OutputFlag", 0)
    model.setParam("TimeLimit", 120)

    f = model.addVars(
        [(k, i, j) for k in range(K) for (i, j) in link_list],
        lb=0.0, name="f"
    )
    y_sw = model.addVars(switch_nodes, vtype=GRB.BINARY, name="y_sw")
    y_lk = model.addVars(energy_links, vtype=GRB.BINARY, name="y_lk")

    sw_cost = gp.quicksum(switch_energy.get(n, 0) * y_sw[n] for n in switch_nodes)
    lk_cost = gp.quicksum(link_energy[(i, j)] * y_lk[i, j] for (i, j) in energy_links)
    model.setObjective(sw_cost + lk_cost, GRB.MINIMIZE)

    # 流量守恆約束
    for k, (src, dst, bw) in enumerate(demands_mbps):
        for n in all_nodes:
            inflow  = gp.quicksum(f[k, i, j] for (i, j) in link_list if j == n)
            outflow = gp.quicksum(f[k, i, j] for (i, j) in link_list if i == n)
            if n == src:
                model.addConstr(outflow - inflow == bw)
            elif n == dst:
                model.addConstr(inflow - outflow == bw)
            else:
                model.addConstr(inflow == outflow)

    # ← 修正：對每條 link 個別建立 switch 啟動約束
    for (u, v) in physical_links:
        cap = links.get((u, v), links.get((v, u), 0))

        # 雙向流量合計
        total_flow = gp.quicksum(
            f[k, i, j]
            for k in range(K)
            for (i, j) in [(u, v), (v, u)]
            if (i, j) in links
        )

        # 雙向加總不超過容量
        model.addConstr(total_flow <= cap)

        # link 啟動約束
        key = (u, v)
        if key in link_energy:
            model.addConstr(total_flow <= cap * y_lk[key])

        # ← 修正：switch 啟動約束，對每個端點分別建立
        # 只要這條 link 有流量，兩端的 switch 都必須啟動
        for n in [u, v]:
            if n in switch_nodes:
                model.addConstr(total_flow <= cap * y_sw[n])

    model.optimize()

    if model.Status in (GRB.OPTIMAL, GRB.TIME_LIMIT):
        total_energy = model.ObjVal
        path_result = []
        for k, (src, dst, bw) in enumerate(demands_mbps):
            flow_vals = {
                (i, j): f[k, i, j].X
                for (i, j) in link_list
                if f[k, i, j].X > 1e-6
            }
            paths = decompose_flow(src, dst, flow_vals)
            path_result.append((src, dst, bw / 1000, paths))

        active_switches = [n for n in switch_nodes if y_sw[n].X > 0.5]
        active_links    = [(i, j) for (i, j) in energy_links if y_lk[i, j].X > 0.5]

        status = "optimal" if model.Status == GRB.OPTIMAL else "timelimit"
        return status, total_energy, path_result, active_switches, active_links
    elif model.Status == GRB.INFEASIBLE:
        return "infeasible", None, None, None, None
    else:
        return "other", None, None, None, None


# ── 印出結果 ─────────────────────────────────────────────────────────────────

def print_results(status, total_energy, path_result, demands,
                  active_switches, active_links, switch_energy, link_energy):
    sep = "=" * 62
    print(sep)
    print("  多商品流最佳化結果（最小能耗）")
    print(sep)

    if status == "infeasible":
        print("  [無解] 流量需求超過網路容量，無法同時滿足所有需求。")
        return
    if status == "timelimit":
        print("  [警告] 求解器達到時間上限，以下為當前最佳解（非保證最優）。")

    print(f"  求解狀態   : {status}")
    print(f"  總能耗     : {total_energy:.2f} W")
    print()

    # 啟動的節點與 link
    print(f"  啟動 Switch 數量 : {len(active_switches)}")
    print(f"  啟動 Switch 列表 : {active_switches}")
    sw_energy_total = sum(switch_energy.get(n, 0) for n in active_switches)
    # active_links 現在是單向 key，直接加總即可
    lk_energy_total = sum(link_energy.get((i, j), 0) for (i, j) in active_links)
    print(f"  Switch 能耗合計  : {sw_energy_total:.2f} W")
    print(f"  Link 能耗合計    : {lk_energy_total:.2f} W")
    print()

    # 路徑結果
    for idx, ((src, dst, gbps_orig), (_, _, _, paths)) in \
            enumerate(zip(demands, path_result), 1):
        total_flow_mbps = sum(fl for _, fl in paths)
        print(f"  需求 {idx}: {node_label(src)} --> {node_label(dst)}  "
              f"{gbps_orig:.4f} Gbit/s = {gbps_orig*1000:.2f} Mbps")
        print(f"  實際分配: {total_flow_mbps:.2f} Mbps")
        for pidx, (path, flow_mbps) in enumerate(paths, 1):
            bottleneck = min(links[(path[k], path[k+1])]
                             for k in range(len(path)-1))
            path_str = " -> ".join(node_label(n) for n in path)
            print(f"    路徑 {pidx}: {path_str}")
            print(f"           流量={flow_mbps:.2f} Mbps  "
                  f"瓶頸頻寬={bottleneck} Mbps")
        print()
    print(sep)


# ── 原始單需求路徑工具（供參考） ─────────────────────────────────────────────

def find_path_with_min_bw(source, target, min_bw):
    """檢查是否存在瓶頸頻寬 >= min_bw 的路徑"""
    # 只保留頻寬 >= min_bw 的邊
    valid_links = {(i,j): bw for (i,j), bw in links.items() if bw >= min_bw}

    model = gp.Model("path")
    model.setParam("OutputFlag", 0)

    x = model.addVars(valid_links.keys(), vtype=GRB.BINARY, name="x")
    model.setObjective(gp.quicksum(x[i,j] for (i,j) in valid_links), GRB.MINIMIZE)

    for n in all_nodes:
        inflow  = gp.quicksum(x[i,j] for (i,j) in valid_links if j == n)
        outflow = gp.quicksum(x[i,j] for (i,j) in valid_links if i == n)
        if n == source:
            model.addConstr(outflow - inflow == 1)
        elif n == target:
            model.addConstr(inflow - outflow == 1)
        else:
            model.addConstr(inflow == outflow)

    model.optimize()

    if model.Status == GRB.OPTIMAL:
        path_edges = [(i,j) for (i,j) in valid_links if x[i,j].X > 0.5]
        edge_map = {i: j for (i,j) in path_edges}
        path = [source]
        cur = source
        while cur != target and cur in edge_map:
            cur = edge_map[cur]
            path.append(cur)
        return path
    return None


def find_best_path(source, target):
    """二元搜尋最大瓶頸頻寬"""
    bw_levels = sorted(set(links.values()), reverse=True)
    best_path = None
    best_bw = 0

    for bw in bw_levels:
        path = find_path_with_min_bw(source, target, bw)
        if path:
            best_path = path
            best_bw = bw
            break  # 找到最大頻寬就停

    return best_path, best_bw


def find_minhop_path(source, target):
    """最少跳數路徑"""
    model = gp.Model("minhop")
    model.setParam("OutputFlag", 0)

    x = model.addVars(links.keys(), vtype=GRB.BINARY, name="x")
    model.setObjective(gp.quicksum(x[i,j] for (i,j) in links), GRB.MINIMIZE)

    for n in all_nodes:
        inflow  = gp.quicksum(x[i,j] for (i,j) in links if j == n)
        outflow = gp.quicksum(x[i,j] for (i,j) in links if i == n)
        if n == source:
            model.addConstr(outflow - inflow == 1)
        elif n == target:
            model.addConstr(inflow - outflow == 1)
        else:
            model.addConstr(inflow == outflow)

    model.optimize()

    if model.Status == GRB.OPTIMAL:
        path_edges = [(i,j) for (i,j) in links if x[i,j].X > 0.5]
        edge_map = {i: j for (i,j) in path_edges}
        path = [source]
        cur = source
        while cur != target and cur in edge_map:
            cur = edge_map[cur]
            path.append(cur)
        actual_bw = min(links[(path[k], path[k+1])] for k in range(len(path)-1))
        return path, actual_bw
    return None, None


def node_label(n):
    """將節點編號轉成可讀標籤"""
    if 46 <= n <= 66:
        return f"h{n-45}"      # h46=h1, h47=h2, ...
    elif 67 <= n <= 72:
        return f"h{n-45}"      # h67=h22, h68=h23, ...
    else:
        return str(n)          # Switch 直接顯示原始編號

# ── 主程式 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # ← 加這行

    switch_energy = load_switch_energy("switch_energy.txt")
    link_energy   = load_link_energy("link_energy.txt")

    print(f"[能耗資料] Switch: {len(switch_energy)} 筆, "
          f"Link: {len(link_energy)} 筆")  # ← 確認讀到資料

    if len(sys.argv) >= 2:
        filepath = sys.argv[1]
    else:
        filepath = "demands.txt"

    demands = load_demands_from_file(filepath)
    print(f"[資料來源] 從檔案 '{filepath}' 讀取 {len(demands)} 筆需求\n")

    print("流量需求清單:")
    for i, (s, d, bw) in enumerate(demands, 1):
        print(f"  {i}. {node_label(s)} --> {node_label(d)}  "
              f"{bw:.4f} Gbit/s ({bw*1000:.2f} Mbps)")
    print()

    status, total_energy, path_result, active_switches, active_links = \
        solve_mcf(demands, switch_energy, link_energy)

    print_results(status, total_energy, path_result, demands,
                  active_switches, active_links, switch_energy, link_energy)


