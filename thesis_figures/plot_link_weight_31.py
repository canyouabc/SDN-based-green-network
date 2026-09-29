# -*- coding: utf-8 -*-
"""
論文用圖：grid 5×5、能耗 switch:link = 3:1、xlow 流量（平均同時 15 條 flow）下，
SGH／ESP 有無 link 權重（LINK_WEIGHT）與 MILP 最佳解的比較，共 2 張：

  link_weight_31_avg.png    ：10 batch 平均（長條）+ MILP 最佳解（黑色虛線）
  link_weight_31_batch.png  ：逐 batch（點圖，batch 彼此獨立所以不連線）

樣式沿用 plot_esp_range_charts.py（v2）：無標題、legend 在圖上方、SGH=#4c72b0、
ESP=#dd8452、ESP 長條加 '///' hatch、MILP 黑色、白底 dpi=300。

── 資料來源（詳見 docs/link_weight_experiment_2026-09-29.md）──
heuristic：sim.py + sweep_sorted.run_one_combo，seed_000_grid5x5_xlow.json（10 batch），
  topo=grid_31，SORT_MODE='SPF'、ENABLE_WEIGHT_MAP=False，PRESEED_ENDPOINTS／LINK_WEIGHT 各開關，
  每組 random seed 0～4 共 5 次，逐 batch 取 5 次平均（mean_after_100）。
MILP：milp_transfer/results_milpsnap_31/seed_milpsnap_grid5x5_xlow_results.csv
  （--topo grid_5x5_31，1287 題全 OPTIMAL），combine_milp_snapshot.py 還原逐 batch。

⚠️ heuristic 數字為 sweep_sorted._AppendTee 逐行緩衝修正「之前」的執行結果（約漏 2% ENERGY 取樣）；
修正後重跑差距 <= 0.05 個百分點，詳見 docs/link_weight_experiment_2026-09-29.md 末段。
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
from matplotlib.lines import Line2D
from decimal import Decimal, ROUND_HALF_UP


def _fmt(v, signed=False):
    """四捨五入到 2 位（half-up）：MILP 平均剛好是 50.175，f'{:.2f}' 受浮點誤差影響會印成 50.17，
    與 docs／energy_saving_summary.csv 的 50.18 不一致。"""
    d = Decimal(repr(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'{d:+}' if signed else f'{d}'

COLOR_SGH = '#4c72b0'
COLOR_ESP = '#dd8452'
COLOR_MILP = '#000000'
HATCH_ESP = '///'
YLABEL = '節能率 (%)'

OUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUT_DIR, exist_ok=True)

# 逐 batch 節能率（batch 1～10）
MILP = [49.88, 49.6, 49.94, 49.7, 50.35, 50.06, 49.26, 52.03, 50.85, 50.08]
SGH = [44.02, 43.638, 45.516, 43.624, 44.18, 43.218, 42.696, 46.288, 44.502, 43.582]
SGH_LINK = [44.46, 44.246, 45.812, 44.024, 44.758, 43.862, 43.384, 46.5, 45.112, 44.026]
ESP = [46.736, 47.152, 48.01, 46.734, 47.4, 46.454, 46.252, 48.286, 46.962, 46.548]
ESP_LINK = [46.68, 47.216, 48.248, 47.058, 47.596, 46.676, 46.408, 48.466, 47.204, 46.678]
# 10 batch 平均：直接由逐 batch 資料計算，差距才不會有「先四捨五入再相減」的誤差
AVG = {k: sum(v) / len(v) for k, v in
       {'MILP': MILP, 'SGH': SGH, 'SGH_LINK': SGH_LINK, 'ESP': ESP, 'ESP_LINK': ESP_LINK}.items()}


def _style_axes(ax):
    ax.yaxis.grid(True, color='#d9d9d9', linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color('#333333')
    ax.spines['bottom'].set_color('#333333')
    ax.tick_params(axis='y', labelsize=12)


def chart_avg():
    bars = [
        ('SGH', AVG['SGH'], COLOR_SGH, None),
        ('SGH\n+link權重', AVG['SGH_LINK'], COLOR_SGH, None),
        ('ESP', AVG['ESP'], COLOR_ESP, HATCH_ESP),
        ('ESP\n+link權重', AVG['ESP_LINK'], COLOR_ESP, HATCH_ESP),
    ]
    x = [0, 1, 2.4, 3.4]   # SGH 與 ESP 兩組之間留空
    fig, ax = plt.subplots(figsize=(5.6, 3.9))
    for xi, (label, v, color, hatch) in zip(x, bars):
        ax.bar(xi, v, width=0.7, color=color, edgecolor='black', linewidth=0.6, hatch=hatch, zorder=3)
        gap = v - AVG['MILP']
        ax.text(xi, v - 1.2, _fmt(v), ha='center', va='top', fontsize=12,
                bbox=dict(facecolor='white', edgecolor='none', pad=1.5), zorder=4)
        ax.text(xi, v / 2, _fmt(gap, signed=True), ha='center', va='center', fontsize=11,
                color='black', bbox=dict(facecolor='white', edgecolor='none', pad=1.5), zorder=4)
    ax.axhline(AVG['MILP'], color=COLOR_MILP, linestyle='--', linewidth=1.2, zorder=4)
    ax.text(-0.55, AVG['MILP'] + 0.6, _fmt(AVG['MILP']), ha='left', va='bottom', fontsize=12)

    ax.set_xticks(x)
    ax.set_xticklabels([b[0] for b in bars], fontsize=13)
    ax.set_ylabel(YLABEL, fontsize=15)
    ax.set_ylim(0, 60)
    ax.set_xlim(-0.6, x[-1] + 0.6)
    _style_axes(ax)
    handles = [Line2D([0], [0], color=COLOR_MILP, linestyle='--', linewidth=1.2, label='MILP 最佳解'),
               Line2D([0], [0], color='none', label='頂端：節能率　中央：與最佳解差距')]
    ax.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=2,
              frameon=False, fontsize=13, handletextpad=0.5, columnspacing=1.2)
    fig.tight_layout()
    out = os.path.join(OUT_DIR, 'link_weight_31_avg.png')
    fig.savefig(out, dpi=300, facecolor='white')
    plt.close(fig)
    print('written', out)


def chart_batch():
    batches = list(range(1, 11))
    series = [
        ('MILP 最佳解', MILP, dict(color=COLOR_MILP, marker='D', markerfacecolor=COLOR_MILP)),
        ('ESP+link權重', ESP_LINK, dict(color=COLOR_ESP, marker='o', markerfacecolor='white')),
        ('ESP', ESP, dict(color=COLOR_ESP, marker='o', markerfacecolor=COLOR_ESP)),
        ('SGH+link權重', SGH_LINK, dict(color=COLOR_SGH, marker='s', markerfacecolor='white')),
        ('SGH', SGH, dict(color=COLOR_SGH, marker='s', markerfacecolor=COLOR_SGH)),
    ]
    fig, ax = plt.subplots(figsize=(8, 4))
    for label, ys, st in series:
        ax.plot(batches, ys, linestyle='none', markersize=6, markeredgewidth=1.1,
                markeredgecolor=st['color'], marker=st['marker'], markerfacecolor=st['markerfacecolor'],
                label=label, zorder=3)
    ax.set_xticks(batches)
    ax.tick_params(axis='x', labelsize=12)
    ax.set_xlabel('batch', fontsize=15)
    ax.set_ylabel(YLABEL, fontsize=15)
    ax.set_ylim(40, 54)   # 點圖不需從 0 起算
    _style_axes(ax)
    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=5, frameon=False,
              fontsize=12, handletextpad=0.3, columnspacing=1.0)
    fig.tight_layout()
    out = os.path.join(OUT_DIR, 'link_weight_31_batch.png')
    fig.savefig(out, dpi=300, facecolor='white')
    plt.close(fig)
    print('written', out)


if __name__ == '__main__':
    chart_avg()
    chart_batch()
