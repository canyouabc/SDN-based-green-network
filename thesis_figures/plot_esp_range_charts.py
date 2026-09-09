# -*- coding: utf-8 -*-
"""
論文用圖：SGH vs SGH+ESP 節能率範圍比較（浮動長條圖），共 5 張
（grid 2x2 / 3x3 / 4x4 / 5x5 + GEANT）。

── 樣式規格（v2，2026-09 定案）──────────────────────────────
- 無標題（原本的 "Grid n×n" / "GEANT" 標題拿掉）
- Legend（"SGH（最佳～最差）"／"SGH+ESP（最佳～最差）"）移到圖表正上方
  （原本標題的位置），字級放大到 13
- SGH+ESP 的長條加斜線 hatch（'///'），跟 SGH 的實心區分，
  確保黑白列印也能分辨兩個系列（不能只靠顏色）
- Y 軸標籤「節能百分比」改為「節能率」
- X/Y 軸標籤字級 15、刻度數字字級 11~13
- 長條上下的數值標籤字級放大到 11~12
- 顏色沿用最早期使用者提供的 build_paper_charts.py：
  SGH = #4c72b0（淡藍），SGH+ESP = #dd8452（淡橙）
- 圖表本體 5.6×3.9 吋，dpi=300，白底

── 資料來源 ──────────────────────────────────────────────
grid 2x2/3x3/4x4/5x5：使用者論文草稿裡貼的圖片，逐張讀圖取得數值
（原始 seed 檔案 seed_*_grid*.json 雖仍在專案根目錄，但每份只有 3 個
batch，跟論文寫的「隨機 10 組流量」對不上，無法重新算出完全一致的
數字，因此改用「直接讀取使用者已發布圖片上的數字標籤」這個方式取得
可信數據——不是重新模擬出來的）。

GEANT：sim.py --algorithm sorted --topo geant（811:1 能耗比例），
data/geant_random_{10,20,40}.json，透過 sweep_sorted.py
（ENABLE_WEIGHT_MAP 固定 False，8 組 SORT_MODE × PRESEED_ENDPOINTS 組合）
跑出來的 min/max，可用同一套指令重新產生：
    python sweep_sorted.py  # SEED_PATH/TOPO/ALGORITHM 改成
                             # data/geant_random_10.json / 'geant' / 'sorted'
                             # （20、40 flow 同理，各自替換 SEED_PATH）

再重新畫圖只需要執行這支檔案：
    python thesis_figures/plot_esp_range_charts.py
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

YLABEL = '節能率 (%)'
XLABEL = '平均流量數'
LEGEND_SGH = 'SGH（最佳～最差）'
LEGEND_ESP = 'SGH+ESP（最佳～最差）'

COLOR_SGH = '#4c72b0'
COLOR_ESP = '#dd8452'
HATCH_ESP = '///'

OUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(OUT_DIR, exist_ok=True)


def make_chart(points, out_name, y_max_override=None):
    all_vals = [v for p in points for v in (p['best_sgh'], p['worst_sgh'], p['best_esp'], p['worst_esp'])]
    y_max = y_max_override or ((max(all_vals) // 5 + 1) * 5 + 5)

    n = len(points)
    x = list(range(n))
    width = 0.32

    fig, ax = plt.subplots(figsize=(5.6, 3.9))

    for i, p in enumerate(points):
        bottom_sgh = p['worst_sgh']
        h_sgh = max(p['best_sgh'] - p['worst_sgh'], 0.15)
        ax.bar(x[i] - width/2 - 0.02, h_sgh, width=width, bottom=bottom_sgh,
               color=COLOR_SGH, edgecolor='black', linewidth=0.6,
               label=LEGEND_SGH if i == 0 else None, zorder=3)

        bottom_esp = p['worst_esp']
        h_esp = max(p['best_esp'] - p['worst_esp'], 0.15)
        ax.bar(x[i] + width/2 + 0.02, h_esp, width=width, bottom=bottom_esp,
               color=COLOR_ESP, edgecolor='black', linewidth=0.6, hatch=HATCH_ESP,
               label=LEGEND_ESP if i == 0 else None, zorder=3)

        ax.text(x[i] - width/2 - 0.02, p['best_sgh'] + y_max*0.014, f"{p['best_sgh']:.1f}",
                ha='center', va='bottom', fontsize=12)
        ax.text(x[i] - width/2 - 0.02, p['worst_sgh'] - y_max*0.026, f"{p['worst_sgh']:.1f}",
                ha='center', va='top', fontsize=11, color='#444444')
        ax.text(x[i] + width/2 + 0.02, p['best_esp'] + y_max*0.014, f"{p['best_esp']:.1f}",
                ha='center', va='bottom', fontsize=12)
        ax.text(x[i] + width/2 + 0.02, p['worst_esp'] - y_max*0.026, f"{p['worst_esp']:.1f}",
                ha='center', va='top', fontsize=11, color='#444444')

    ax.set_xticks(x)
    ax.set_xticklabels([f"{p['flows']:g}" for p in points], fontsize=13)
    ax.set_xlabel(XLABEL, fontsize=15)
    ax.set_ylabel(YLABEL, fontsize=15)
    ax.set_ylim(0, y_max)
    ax.yaxis.grid(True, color='#d9d9d9', linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color('#333333')
    ax.spines['bottom'].set_color('#333333')
    ax.tick_params(axis='y', labelsize=12)

    ax.legend(loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=2,
              frameon=False, fontsize=13, handletextpad=0.5, columnspacing=1.2)

    fig.tight_layout()
    fname = os.path.join(OUT_DIR, out_name)
    fig.savefig(fname, dpi=300, facecolor='white')
    plt.close(fig)
    print('written', fname)


# ── grid 2x2（讀自使用者論文草稿圖片）──
make_chart([
    {'flows': 1, 'best_sgh': 27.8, 'worst_sgh': 24.7, 'best_esp': 27.8, 'worst_esp': 27.8},
    {'flows': 2, 'best_sgh': 24.0, 'worst_sgh': 22.0, 'best_esp': 24.0, 'worst_esp': 24.0},
    {'flows': 4, 'best_sgh': 8.3,  'worst_sgh': 7.0,  'best_esp': 8.3,  'worst_esp': 8.3},
], 'grid_2x2.png', y_max_override=45)

# ── grid 3x3 ──
make_chart([
    {'flows': 7.5, 'best_sgh': 19.5, 'worst_sgh': 14.7, 'best_esp': 22.8, 'worst_esp': 22.7},
    {'flows': 15,  'best_sgh': 12.9, 'worst_sgh': 5.7,  'best_esp': 13.9, 'worst_esp': 13.9},
    {'flows': 30,  'best_sgh': 11.8, 'worst_sgh': 5.0,  'best_esp': 12.8, 'worst_esp': 12.8},
], 'grid_3x3.png', y_max_override=45)

# ── grid 4x4 ──
make_chart([
    {'flows': 15, 'best_sgh': 27.5, 'worst_sgh': 15.3, 'best_esp': 30.2, 'worst_esp': 30.1},
    {'flows': 30, 'best_sgh': 25.7, 'worst_sgh': 12.4, 'best_esp': 26.6, 'worst_esp': 26.6},
    {'flows': 60, 'best_sgh': 25.5, 'worst_sgh': 12.4, 'best_esp': 25.7, 'worst_esp': 25.6},
], 'grid_4x4.png', y_max_override=45)

# ── grid 5x5（讀自使用者最早提供的參考圖片）──
make_chart([
    {'flows': 30,  'best_sgh': 35.7, 'worst_sgh': 19.5, 'best_esp': 37.3, 'worst_esp': 37.2},
    {'flows': 60,  'best_sgh': 36.4, 'worst_sgh': 19.2, 'best_esp': 37.0, 'worst_esp': 37.0},
    {'flows': 120, 'best_sgh': 36.3, 'worst_sgh': 18.3, 'best_esp': 36.6, 'worst_esp': 36.6},
], 'grid_5x5.png', y_max_override=45)

# ── GEANT（sorted，811:1 能耗比例，data/geant_random_{10,20,40}.json）──
make_chart([
    {'flows': 10, 'best_sgh': 28.69, 'worst_sgh': 27.31, 'best_esp': 31.41, 'worst_esp': 29.59},
    {'flows': 20, 'best_sgh': 10.06, 'worst_sgh': 8.69,  'best_esp': 12.76, 'worst_esp': 12.76},
    {'flows': 40, 'best_sgh': 1.38,  'worst_sgh': 0.92,  'best_esp': 1.38,  'worst_esp': 1.38},
], 'geant.png', y_max_override=40)
