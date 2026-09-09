# -*- coding: utf-8 -*-
"""
gen_grid_energy_data.py

依 grid_topo_NxN.py 相同的 sw_id／連線邏輯，產生指定尺寸 grid 拓撲的
switch_energy.txt / link_bw.txt / link_energy.txt（均勻常數值，
數值沿用 data/grid/ 現有 5x5 版本：146W/switch、250Mbps/link、0.18W/link）。

用法：
    python3 gen_grid_energy_data.py --n 3
    python3 gen_grid_energy_data.py --n 3 --outdir data/grid_3x3

預設輸出至 data/grid_{N}x{N}/（不會動到既有的 data/grid/，那是 5x5 專用）。
k_short.txt / k_short_dist.txt / base_weight_map.txt 不在此腳本產生範圍——
那三個要實際跑 Mininet + ROUTING_ALGORITHM='auto_k_short' 才能算出來。
"""
import argparse
import os

SWITCH_ENERGY_W = 146
LINK_BW_MBPS = 250
LINK_ENERGY_W = 0.18


def sw_id(r, c, N):
    return (r - 1) * N + c


def gen_switch_energy(N):
    lines = ["# dpid  type   energy(W)"]
    for r in range(1, N + 1):
        for c in range(1, N + 1):
            lines.append(f"{sw_id(r, c, N):<7} Grid   {SWITCH_ENERGY_W}")
    return "\n".join(lines) + "\n"


def _row_edges(N, r):
    return [(sw_id(r, c, N), sw_id(r, c + 1, N)) for c in range(1, N)]


def _col_edges(N, c):
    return [(sw_id(r, c, N), sw_id(r + 1, c, N)) for r in range(1, N)]


def gen_link_bw(N):
    lines = ["# src   dst   bw(Mbps)"]
    for r in range(1, N + 1):
        edges = _row_edges(N, r)
        if edges:
            lines.append(f"# 水平連線 Row {r}")
            for u, v in edges:
                lines.append(f"{u:<7} {v:<5} {LINK_BW_MBPS}")
    for c in range(1, N + 1):
        edges = _col_edges(N, c)
        if edges:
            lines.append(f"# 垂直連線 Col {c}")
            for u, v in edges:
                lines.append(f"{u:<7} {v:<5} {LINK_BW_MBPS}")
    return "\n".join(lines) + "\n"


def gen_link_energy(N):
    lines = ["# src   dst   energy(W)"]
    for r in range(1, N + 1):
        edges = _row_edges(N, r)
        if edges:
            lines.append(f"# 水平連線 Row {r}")
            for u, v in edges:
                lines.append(f"{u:<7} {v:<5} {LINK_ENERGY_W}")
    for c in range(1, N + 1):
        edges = _col_edges(N, c)
        if edges:
            lines.append(f"# 垂直連線 Col {c}")
            for u, v in edges:
                lines.append(f"{u:<7} {v:<5} {LINK_ENERGY_W}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="產生 grid 拓撲的 switch_energy / link_bw / link_energy 靜態設定檔"
    )
    parser.add_argument('--n', type=int, required=True, help='grid 邊長 N（switch 總數 = N*N）')
    parser.add_argument('--outdir', type=str, default=None,
                         help='輸出資料夾（預設 data/grid_{N}x{N}/）')
    args = parser.parse_args()

    N = args.n
    outdir = args.outdir or f"data/grid_{N}x{N}"
    os.makedirs(outdir, exist_ok=True)

    with open(os.path.join(outdir, 'switch_energy.txt'), 'w', encoding='utf-8') as f:
        f.write(gen_switch_energy(N))
    with open(os.path.join(outdir, 'link_bw.txt'), 'w', encoding='utf-8') as f:
        f.write(gen_link_bw(N))
    with open(os.path.join(outdir, 'link_energy.txt'), 'w', encoding='utf-8') as f:
        f.write(gen_link_energy(N))

    print(f"*** 已產生 {N}x{N} grid 的 switch_energy.txt / link_bw.txt / link_energy.txt -> {outdir}/")


if __name__ == '__main__':
    main()
