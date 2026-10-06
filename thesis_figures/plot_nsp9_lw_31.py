# -*- coding: utf-8 -*-
"""
論文用圖：跟 plot_nsp9_31.py 同樣的 5 條線（SGH／SGH+NSP／ESP／ESP+NSP／MILP 最佳解），
但 4 種 heuristic 全部改用開了 LINK_WEIGHT（LW：Phase1 成本 = 新開 switch 能耗 + 新開 link 能耗）的結果。
圖例不標 LW（使用者要求），圖樣式與畫法直接重用 plot_nsp9_31.chart()。

  nsp9_lw_31_grid3x3.png ／ nsp9_lw_31_grid4x4.png ／ nsp9_lw_31_grid5x5.png

── 資料來源 ──
同 plot_nsp9_31.py；LW 四組另外在 2026-10-06 跑（LINK_WEIGHT=True，其餘相同，random seed 0～4 各 10 batch），
log/sweep-{SGH,ESP}+LW{,+NSP}_{grid}_{level}_r{0..4}-*。5×5 流量 15 的 SGH+LW／ESP+LW 與 09-29 文件數字相同。
"""
import plot_nsp9_31 as base

# 下面保留 LW／無 LW 兩組完整數字備查；畫圖時把 *+LW 的值放進 base 的 'SPF'／'ESP' 等欄位
DATA = {
    'grid3x3': {
        5.625: {'SPF': 33.50, 'SPF+NSP': 34.30, 'SPF+LW': 34.16, 'SPF+LW+NSP': 34.19, 'ESP': 36.29, 'ESP+NSP': 36.70, 'ESP+LW': 36.65, 'ESP+LW+NSP': 36.64, 'MILP': 36.84},
        7.5: {'SPF': 27.75, 'SPF+NSP': 29.05, 'SPF+LW': 29.00, 'SPF+LW+NSP': 28.99, 'ESP': 30.78, 'ESP+NSP': 31.51, 'ESP+LW': 31.36, 'ESP+LW+NSP': 31.36, 'MILP': 31.56},
        9.375: {'SPF': 23.83, 'SPF+NSP': 25.53, 'SPF+LW': 25.51, 'SPF+LW+NSP': 25.50, 'ESP': 26.57, 'ESP+NSP': 27.72, 'ESP+LW': 27.65, 'ESP+LW+NSP': 27.66, 'MILP': 27.77},
    },
    'grid4x4': {
        7.5: {'SPF': 42.32, 'SPF+NSP': 42.90, 'SPF+LW': 42.75, 'SPF+LW+NSP': 42.72, 'ESP': 45.32, 'ESP+NSP': 45.40, 'ESP+LW': 45.20, 'ESP+LW+NSP': 45.20, 'MILP': 45.69},
        11.25: {'SPF': 36.24, 'SPF+NSP': 37.36, 'SPF+LW': 37.11, 'SPF+LW+NSP': 37.10, 'ESP': 40.52, 'ESP+NSP': 40.86, 'ESP+LW': 40.44, 'ESP+LW+NSP': 40.43, 'MILP': 40.94},
        15: {'SPF': 35.22, 'SPF+NSP': 36.50, 'SPF+LW': 36.21, 'SPF+LW+NSP': 36.28, 'ESP': 38.43, 'ESP+NSP': 39.03, 'ESP+LW': 38.64, 'ESP+LW+NSP': 38.63, 'MILP': 39.08},
    },
    'grid5x5': {
        15: {'SPF': 44.08, 'SPF+NSP': 46.05, 'SPF+LW': 44.57, 'SPF+LW+NSP': 45.69, 'ESP': 47.04, 'ESP+NSP': 48.31, 'ESP+LW': 47.20, 'ESP+LW+NSP': 48.20, 'MILP': 50.18},
        22.5: {'SPF': 43.37, 'SPF+NSP': 45.35, 'SPF+LW': 43.83, 'SPF+LW+NSP': 44.87, 'ESP': 45.60, 'ESP+NSP': 46.76, 'ESP+LW': 45.78, 'ESP+LW+NSP': 46.72, 'MILP': 48.18},
        30: {'SPF': 43.25, 'SPF+NSP': 45.29, 'SPF+LW': 43.63, 'SPF+LW+NSP': 44.70, 'ESP': 45.12, 'ESP+NSP': 46.14, 'ESP+LW': 45.19, 'ESP+LW+NSP': 46.08, 'MILP': 46.84},
    },
}


def lw_only(d):
    return {t: {f: {'SPF': v['SPF+LW'], 'SPF+NSP': v['SPF+LW+NSP'], 'ESP': v['ESP+LW'],
                    'ESP+NSP': v['ESP+LW+NSP'], 'MILP': v['MILP']} for f, v in rows.items()}
            for t, rows in d.items()}


if __name__ == '__main__':
    base.DATA = lw_only(DATA)
    base.SHOW_MILP = True
    base.OUT_PREFIX = 'nsp9_lw_31'
    for t in base.DATA:
        base.chart(t)
