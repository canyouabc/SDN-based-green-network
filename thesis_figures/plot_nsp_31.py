# -*- coding: utf-8 -*-
"""
論文用圖：grid 5×5、能耗 switch:link = 3:1，SGH（SPF）／ESP 有無 NSP 變種
（LINK_PRUNE='NSP_COUNT'：link 依 flow 數由少到多轉移）與 MILP 最佳解的比較，共 3 張：

  nsp_31_saving.png ：三個流量等級的節能率（折線，含 MILP 最佳解）
  nsp_31_gap.png    ：各設定與 MILP 最佳解的差距（長條）
  nsp_31_hops.png   ：平均 hop 數（長條；NSP 的代價）

樣式沿用 plot_esp_range_charts.py（v2）與既有折線圖：無標題、legend 在圖上方、
SGH（SPF）=#4c72b0、ESP=#dd8452、MILP 黑色菱形、白底 dpi=300。
長條圖：無 NSP 為實心（ESP 加 '///'），+NSP 為白底同色 hatch（黑白列印可分辨）。

── 資料來源 ──
heuristic：sim.py + sweep_sorted.run_one_combo，seed_000_grid5x5_{xlow,low,mid}.json（各 10 batch），
  topo=grid_31，SORT_MODE='SPF'、ENABLE_WEIGHT_MAP=False、LINK_WEIGHT=False，
  PRESEED_ENDPOINTS（ESP）／LINK_PRUNE='NSP_COUNT' 各開關；每組 random seed 0～4 共 5 次，
  節能率 = 逐 batch 取 5 次平均後再取 10 batch 平均（mean_after_100）；hop = 有 flow 時逐秒平均。
  原始結果：log/sweep-N31_{level}_*（2026-09-29，_AppendTee 逐行緩衝修正後）。
MILP：milp_transfer/results_milpsnap_31/seed_milpsnap_grid5x5_{level}_results.csv
  （--topo grid_5x5_31，全部 OPTIMAL），combine_milp_snapshot.py 還原逐 batch 後取平均。
"""
import matplotlib
import matplotlib.font_manager as fm
import os
from decimal import Decimal, ROUND_HALF_UP

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
from matplotlib.patches import Patch

COLOR_SGH = '#4c72b0'
COLOR_ESP = '#dd8452'
COLOR_MILP = '#000000'
OUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUT_DIR, exist_ok=True)

LEVELS = ['xlow', 'low', 'mid']
FLOWS = [15.3, 29.5, 56.6]   # 各等級平均同時 flow 數
DATA = {
    'xlow': {'MILP': 50.175, 'SPF': 44.078, 'SPF+NSP': 46.0476, 'ESP': 47.0376, 'ESP+NSP': 48.3054,
             'SPF_hop': 4.5201, 'SPF+NSP_hop': 4.8105, 'ESP_hop': 4.4773, 'ESP+NSP_hop': 4.8142},
    'low': {'MILP': 46.844, 'SPF': 43.2454, 'SPF+NSP': 45.2914, 'ESP': 45.117, 'ESP+NSP': 46.1354,
            'SPF_hop': 4.3192, 'SPF+NSP_hop': 5.0108, 'ESP_hop': 4.3128, 'ESP+NSP_hop': 4.9819},
    'mid': {'MILP': 45.733, 'SPF': 43.9076, 'SPF+NSP': 45.446, 'ESP': 44.7136, 'ESP+NSP': 45.6096,
            'SPF_hop': 4.2824, 'SPF+NSP_hop': 5.1821, 'ESP_hop': 4.2819, 'ESP+NSP_hop': 5.1601},
}
SERIES = ['SPF', 'SPF+NSP', 'ESP', 'ESP+NSP']
LABEL = {'SPF': 'SGH', 'SPF+NSP': 'SGH+NSP', 'ESP': 'ESP', 'ESP+NSP': 'ESP+NSP'}
BAR_STYLE = {
    'SPF': dict(color=COLOR_SGH, edgecolor='black', hatch=None),
    'SPF+NSP': dict(color='white', edgecolor=COLOR_SGH, hatch='...'),
    'ESP': dict(color=COLOR_ESP, edgecolor='black', hatch='///'),
    'ESP+NSP': dict(color='white', edgecolor=COLOR_ESP, hatch='///'),
}


def _fmt(v, signed=False):
    """四捨五入到 2 位（half-up），避免 50.175 這類值因浮點誤差顯示成 50.17。"""
    d = Decimal(repr(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'{d:+}' if signed else f'{d}'


def _style_axes(ax):
    ax.yaxis.grid(True, color='#d9d9d9', linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color('#333333')
    ax.spines['bottom'].set_color('#333333')
    ax.tick_params(axis='both', labelsize=12)


def chart_saving():
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.plot(FLOWS, [DATA[l]['MILP'] for l in LEVELS], color=COLOR_MILP, marker='D', markersize=7,
            linewidth=1.2, label='MILP 最佳解', zorder=5)
    styles = {
        'ESP+NSP': dict(color=COLOR_ESP, marker='o', markerfacecolor=COLOR_ESP, linestyle='-'),
        'ESP': dict(color=COLOR_ESP, marker='o', markerfacecolor='white', linestyle='--'),
        'SPF+NSP': dict(color=COLOR_SGH, marker='s', markerfacecolor=COLOR_SGH, linestyle='-'),
        'SPF': dict(color=COLOR_SGH, marker='s', markerfacecolor='white', linestyle='--'),
    }
    for s in ('ESP+NSP', 'ESP', 'SPF+NSP', 'SPF'):
        st = styles[s]
        ax.plot(FLOWS, [DATA[l][s] for l in LEVELS], color=st['color'], marker=st['marker'],
                markerfacecolor=st['markerfacecolor'], markeredgecolor=st['color'], markersize=7,
                linestyle=st['linestyle'], linewidth=1.0, label=LABEL[s], zorder=4)
    ax.set_xticks(FLOWS)
    ax.set_xticklabels([f'{f:g}' for f in FLOWS])
    ax.set_xlim(8, 64)
    ax.set_ylim(40, 52)   # 折線不需從 0 起算
    ax.set_xlabel('平均流量數', fontsize=15)
    ax.set_ylabel('節能率 (%)', fontsize=15)
    _style_axes(ax)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=3, frameon=False, fontsize=12,
              handletextpad=0.4, columnspacing=1.0)
    fig.tight_layout()
    _save(fig, 'nsp_31_saving.png')


def _grouped_bars(values_of, ylabel, ylim, out_name, label_fmt, label_offset):
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    width = 0.19
    for i, s in enumerate(SERIES):
        xs = [g + (i - 1.5) * (width + 0.02) for g in range(len(LEVELS))]
        vals = [values_of(l, s) for l in LEVELS]
        st = BAR_STYLE[s]
        ax.bar(xs, vals, width=width, color=st['color'], edgecolor=st['edgecolor'], hatch=st['hatch'],
               linewidth=0.8, label=LABEL[s], zorder=3)
        for x, v in zip(xs, vals):
            ax.text(x, v + label_offset(v), label_fmt(v), ha='center',
                    va='top' if v < 0 else 'bottom', fontsize=9.5, zorder=4)
    ax.set_xticks(range(len(LEVELS)))
    ax.set_xticklabels([f'{f:g}' for f in FLOWS])
    ax.set_xlabel('平均流量數', fontsize=15)
    ax.set_ylabel(ylabel, fontsize=15)
    ax.set_ylim(*ylim)
    _style_axes(ax)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=4, frameon=False, fontsize=12,
              handletextpad=0.4, columnspacing=1.0)
    fig.tight_layout()
    _save(fig, out_name)


def chart_gap():
    _grouped_bars(lambda l, s: DATA[l][s] - DATA[l]['MILP'], '與最佳解的差距 (%)', (-7, 0.5),
                  'nsp_31_gap.png', lambda v: _fmt(v, signed=True), lambda v: -0.12)


def chart_hops():
    _grouped_bars(lambda l, s: DATA[l][s + '_hop'], '平均 hop 數', (0, 6.5),
                  'nsp_31_hops.png', lambda v: f'{v:.2f}', lambda v: 0.08)


def _save(fig, name):
    out = os.path.join(OUT_DIR, name)
    fig.savefig(out, dpi=300, facecolor='white')
    plt.close(fig)
    print('written', out)


if __name__ == '__main__':
    chart_saving()
    chart_gap()
    chart_hops()
