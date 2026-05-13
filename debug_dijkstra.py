# -*- coding: utf-8 -*-
"""
debug_dijkstra.py - 調試基本 Dijkstra 功能
"""

from Dijkstra.modules import routing_auto_k_short

# 創建簡單測試拓撲
switches = [1, 2, 3, 4]

# 鄰接表：{src_switch: {dst_switch: port_number}}
adjacency = {
    1: {2: 1, 4: 2},       # switch 1: 到s2用埠1, 到s4用埠2
    2: {1: 1, 3: 2},       # switch 2: 到s1用埠1, 到s3用埠2
    3: {2: 1, 4: 2},       # switch 3: 到s2用埠1, 到s4用埠2
    4: {1: 1, 3: 2},       # switch 4: 到s1用埠1, 到s3用埠2
}

# 能耗
link_energy = {
    (1, 2): 10, (2, 1): 10,
    (2, 3): 5,  (3, 2): 5,
    (1, 4): 12, (4, 1): 12,
    (4, 3): 12, (3, 4): 12,
}

switch_energy = {1: 1, 2: 2, 3: 1, 4: 2}

link_delay = {(u, v): 1 for u, v in link_energy.keys()}
link_bw = {}
link_used_bw = {}

def get_link_delay_func(u, p):
    return 1

print("Topology check:")
print(f"  Switches: {switches}")
print(f"  Adjacency: {adjacency}")
print(f"  Link energy: {link_energy}")
print()

# 測試 Dijkstra
print("Testing get_min_delay_path(1, 3)...")
result = routing_auto_k_short.get_min_delay_path(
    src=1, dst=3, first_port=0, final_port=0,
    switches=switches, adjacency=adjacency, link_delay=link_delay,
    link_energy=link_energy, link_bw=link_bw, link_used_bw=link_used_bw,
    switch_energy=switch_energy, get_link_delay=get_link_delay_func,
)

if result is None:
    print("  Result: None (no path found)")
else:
    path_list, switch_path = result
    print(f"  Switch path: {switch_path}")
    print(f"  Path list: {path_list}")
