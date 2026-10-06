# -*- coding: utf-8 -*-
"""
論文用圖：GEANT、能耗 3:1、平均流量 3／5／7，SGH／SGH+NSP／ESP／ESP+NSP（4 種皆開 LINK_WEIGHT，圖例不標）
與 MILP 最佳解。樣式與畫法直接重用 plot_nsp9_31.chart()。

  nsp_31_geant.png

MILP=None 的點不畫；結果等學校電腦（milp_transfer/RUN_geant_31_k357.md）。

── 資料來源 ──
sim.py + sweep_sorted.run_one_combo，topo=geant_31，seed_000_geant_k0{3,5,7}.json（0.1～0.5 Mbps，flow 15 秒，10 batch），
SORT_MODE='SPF'、ENABLE_WEIGHT_MAP=False、LINK_WEIGHT=True，PRESEED_ENDPOINTS（ESP）／LINK_PRUNE='NSP_COUNT' 各開關；
每組 random seed 0～4 共 5 次，節能率 = 逐 batch 取 5 次平均後再取 10 batch 平均（mean_after_100）。
2026-10-06，log/sweep-{SGH,SGH+NSP,ESP,ESP+NSP}_geant_k0{3,5,7}_r{0..4}-*（series='NSP 3:1 GEANT 平均流量 3/5/7'）。
"""
import plot_nsp9_31 as base

DATA = {
    'geant': {
        3: {'SPF': 70.31, 'SPF+NSP': 70.31, 'ESP': 70.58, 'ESP+NSP': 70.58, 'MILP': None},
        5: {'SPF': 60.90, 'SPF+NSP': 60.95, 'ESP': 61.41, 'ESP+NSP': 61.46, 'MILP': None},
        7: {'SPF': 52.35, 'SPF+NSP': 52.46, 'ESP': 52.95, 'ESP+NSP': 53.08, 'MILP': None},
    },
}

if __name__ == '__main__':
    base.DATA = DATA
    base.SHOW_MILP = True
    base.OUT_PREFIX = 'nsp_31'
    base.chart('geant')
