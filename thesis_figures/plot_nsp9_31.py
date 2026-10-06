# -*- coding: utf-8 -*-
"""
論文用圖：grid 3×3／4×4／5×5、能耗 switch:link = 3:1，每個拓撲 3 組平均流量數下
SGH（SPF）／SGH+NSP／ESP／ESP+NSP 的節能率（折線），每拓撲一張：

  nsp9_31_grid3x3.png ／ nsp9_31_grid4x4.png ／ nsp9_31_grid5x5.png

MILP 欄位填了數字才會畫（黑菱形）；9 組全部 OPTIMAL（milp_transfer/RUN_grid_3x3_4x4_5x5_31_nsp9.md）。
樣式沿用 plot_nsp_31.py。

── 資料來源 ──
sim.py + sweep_sorted.run_one_combo，topo=grid_{3x3_31,4x4_31,31}，SORT_MODE='SPF'、ENABLE_WEIGHT_MAP=False、
LINK_WEIGHT=False，PRESEED_ENDPOINTS（ESP）／LINK_PRUNE='NSP_COUNT' 各開關；每組 random seed 0～4 共 5 次，
節能率 = 逐 batch 取 5 次平均後再取 10 batch 平均（mean_after_100）。2026-10-06，
log/sweep-{SGH,SGH+NSP,ESP,ESP+NSP}_{grid}_{level}_r{0..4}-*（series='NSP 3:1 九組流量 grid3x3/4x4/5x5'）。
seed：seed_000_grid3x3_{k03,low,k05}、seed_000_grid4x4_{xlow,k03,low}、seed_000_grid5x5_{xlow,k03,low}
（0.1～0.5 Mbps，flow 15 秒，10 batch）。5×5 的 xlow／low 與 plot_nsp_31.py（09-29）數字完全相同。
MILP：milp_transfer/results_milpsnap_31/，combine_milp_snapshot.py 還原逐 batch 後取平均。
"""
import matplotlib
import matplotlib.font_manager as fm
import os

_CJK_FONT_CANDIDATES = [
    'Microsoft JhengHei', 'Microsoft YaHei', 'SimHei',
    'Noto Sans CJK TC', 'Noto Sans CJK SC', 'Noto Sans CJK JP',
    'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei',
    'Droid Sans Fallback', 'AR PL UMing CN', 'AR PL UKai CN',
    'PingFang TC', 'PingFang SC', 'Heiti TC',
]
_available_fonts = {f.name for f in fm.fontManager.ttflist}
_CJK_FONT = next((f for f in _CJK_FONT_CANDIDATES if f in _available_fonts), None)
if _CJK_FONT:
    matplotlib.rcParams['font.sans-serif'] = [_CJK_FONT, 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt

COLOR_SGH = '#4c72b0'
COLOR_ESP = '#dd8452'
COLOR_MILP = '#000000'
SHOW_MILP = True
OUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
OUT_PREFIX = 'nsp9_31'   # plot_nsp9_lw_31.py 換資料重用 chart() 時改成 'nsp9_lw_31'
os.makedirs(OUT_DIR, exist_ok=True)

# 每拓撲：平均流量數 → 各設定節能率（%）；MILP=None 表示尚無結果
DATA = {
    'grid3x3': {
        5.625: {'SPF': 33.50, 'SPF+NSP': 34.30, 'ESP': 36.29, 'ESP+NSP': 36.70, 'MILP': 36.84},
        7.5:   {'SPF': 27.75, 'SPF+NSP': 29.05, 'ESP': 30.78, 'ESP+NSP': 31.51, 'MILP': 31.56},
        9.375: {'SPF': 23.83, 'SPF+NSP': 25.53, 'ESP': 26.57, 'ESP+NSP': 27.72, 'MILP': 27.77},
    },
    'grid4x4': {
        7.5:   {'SPF': 42.32, 'SPF+NSP': 42.90, 'ESP': 45.32, 'ESP+NSP': 45.40, 'MILP': 45.69},
        11.25: {'SPF': 36.24, 'SPF+NSP': 37.36, 'ESP': 40.52, 'ESP+NSP': 40.86, 'MILP': 40.94},
        15:    {'SPF': 35.22, 'SPF+NSP': 36.50, 'ESP': 38.43, 'ESP+NSP': 39.03, 'MILP': 39.08},
    },
    'grid5x5': {
        15:    {'SPF': 44.08, 'SPF+NSP': 46.05, 'ESP': 47.04, 'ESP+NSP': 48.31, 'MILP': 50.18},
        22.5:  {'SPF': 43.37, 'SPF+NSP': 45.35, 'ESP': 45.60, 'ESP+NSP': 46.76, 'MILP': 48.18},
        30:    {'SPF': 43.25, 'SPF+NSP': 45.29, 'ESP': 45.12, 'ESP+NSP': 46.14, 'MILP': 46.84},
    },
}
LABEL = {'SPF': 'SGH', 'SPF+NSP': 'SGH+NSP', 'ESP': 'ESP', 'ESP+NSP': 'ESP+NSP'}
STYLES = {
    'ESP+NSP': dict(color=COLOR_ESP, marker='o', markerfacecolor=COLOR_ESP, linestyle='-'),
    'ESP': dict(color=COLOR_ESP, marker='o', markerfacecolor='white', linestyle='--'),
    'SPF+NSP': dict(color=COLOR_SGH, marker='s', markerfacecolor=COLOR_SGH, linestyle='-'),
    'SPF': dict(color=COLOR_SGH, marker='s', markerfacecolor='white', linestyle='--'),
}


def _style_axes(ax):
    ax.yaxis.grid(True, color='#d9d9d9', linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color('#333333')
    ax.spines['bottom'].set_color('#333333')
    ax.tick_params(axis='both', labelsize=12)


def chart(topo):
    d = DATA[topo]
    flows = sorted(d)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    milp = [(f, d[f]['MILP']) for f in flows if SHOW_MILP and d[f]['MILP'] is not None]
    if milp:
        ax.plot([f for f, _ in milp], [v for _, v in milp], color=COLOR_MILP, marker='D', markersize=7,
                linewidth=1.2 if len(milp) == len(flows) else 0, label='MILP 最佳解', zorder=5)
    for s in ('ESP+NSP', 'ESP', 'SPF+NSP', 'SPF'):
        st = STYLES[s]
        ax.plot(flows, [d[f][s] for f in flows], color=st['color'], marker=st['marker'],
                markerfacecolor=st['markerfacecolor'], markeredgecolor=st['color'], markersize=7,
                linestyle=st['linestyle'], linewidth=1.0, label=LABEL[s], zorder=4)
    ax.set_xticks(flows)
    ax.set_xticklabels([f'{f:g}' for f in flows])
    span = flows[-1] - flows[0]
    ax.set_xlim(flows[0] - span * 0.15, flows[-1] + span * 0.15)
    vals = [v for f in flows for k, v in d[f].items() if v is not None and (SHOW_MILP or k != 'MILP')]
    ax.set_ylim(int(min(vals)) - 1, int(max(vals)) + 2)   # 折線不需從 0 起算
    ax.set_xlabel('平均流量數', fontsize=15)
    ax.set_ylabel('節能率 (%)', fontsize=15)
    _style_axes(ax)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=5 if milp else 4, frameon=False,
              fontsize=12 if not milp else 11, handletextpad=0.4, columnspacing=1.0)
    fig.tight_layout()
    out = os.path.join(OUT_DIR, f'{OUT_PREFIX}_{topo}.png')
    fig.savefig(out, dpi=300, facecolor='white')
    plt.close(fig)
    print('written', out)


if __name__ == '__main__':
    for t in DATA:
        chart(t)
