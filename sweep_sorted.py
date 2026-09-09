# sweep_sorted.py
# ─────────────────────────────────────────────────────────────────
# 對同一份 seed，批次跑 routing_DTM_sorted.py 的多組設定組合，
# 每組各自完成 sim → parse_log → matplotlib_DTM 的完整流程，
# 最後把所有組合的逐 batch 結果（含 AVERAGE）疊成一份 sweep_comparison.csv。
#
# 使用方式：
#   python3 sweep_sorted.py
# ─────────────────────────────────────────────────────────────────

import os
import sys
import json
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
import matplotlib.font_manager as fm

# 自動偵測系統上有沒有裝支援中文的字型；找不到就退回英文標籤，
# 避免在沒裝對應字型的機器（例如這台 Mininet VM）畫出方框亂碼。
_CJK_FONT_CANDIDATES = [
    'Microsoft JhengHei', 'Microsoft YaHei', 'SimHei',      # Windows
    'Noto Sans CJK TC', 'Noto Sans CJK SC', 'Noto Sans CJK JP',
    'WenQuanYi Zen Hei', 'WenQuanYi Micro Hei',              # 常見 Linux 套件
    'Droid Sans Fallback', 'AR PL UMing CN', 'AR PL UKai CN',
    'PingFang TC', 'PingFang SC', 'Heiti TC',                # macOS
]
_available_fonts = {f.name for f in fm.fontManager.ttflist}
_CJK_FONT = next((f for f in _CJK_FONT_CANDIDATES if f in _available_fonts), None)
if _CJK_FONT:
    matplotlib.rcParams['font.sans-serif'] = [_CJK_FONT, 'sans-serif']
else:
    print("[sweep_sorted] 找不到中文字型，圖表標籤將改用英文")
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt

import sim
from parse_log import parse_log
import matplotlib_DTM


class _AppendTee:
    """用 append（'a'）模式持續開著檔案，而不是 sim._Tee 的 'w'（截斷）模式；
    這樣才能跟 Simulator._log() 各自獨立開檔、寫入同一份檔案時不會互相截斷內容。"""
    def __init__(self, filepath, stdout):
        self._file = open(filepath, 'a', encoding='utf-8')
        self._stdout = stdout

    def write(self, data):
        self._stdout.write(data)
        self._file.write(data)

    def flush(self):
        self._stdout.flush()
        self._file.flush()

    def close(self):
        self._file.close()

# ── 設定 ────────────────────────────────────────────────────────
SEED_PATH = 'seed_000_cap.json'
TOPO      = 'cap'   # 'grid'(5x5) | 'cap' | 'grid_2x2' | 'grid_3x3' | 'grid_4x4' | 'grid_6x6' | 'grid_7x7'
ALGORITHM = 'sorted'
MAKE_PLOTS = False   # 每組 combo 是否也產出 batch_N.png（組數多時建議關閉）

# 未被 combo 覆蓋的旗標，一律重置回這裡的值，確保每組互不影響、可重現
BASELINE = {
    'SORT_MODE':          'LPF',
    'WEIGHT_MODE':        'STATIC',
    'LOAD_CHECK_MODE':    'INCREMENTAL',
    'ENABLE_WEIGHT_MAP':  True,
    'PRESEED_ENDPOINTS':  False,
}
#
#ENABLE_WEIGHT_MAP = True    # True：Phase 2 用 base_weight_map 打分；False：並列時直接 random
#SORT_MODE = 'DENSITY'    # 'LPF'：依理論最短 hop 由大到小（現行）
#                      # 'DENSITY'：依最小路徑集合在 weight_map 上的平均權重由大到小
#                      # 'SPF'：依理論最短 hop 由小到大（最短路徑優先）
#                      # 'HDF'：依 flow 已知頻寬由大到小（最高流量優先）
#                      # 'SDF'：依 flow 已知頻寬由小到大（最低流量優先）
#                      # SPF/HDF/SDF 對應 SGH 論文的 Shortest Path First / High(est) Demand First / Smallest Demand First
#WEIGHT_MODE = 'DECAY'   # 'STATIC'：weight_map 整輪處理期間固定不變（現行）
#                         # 'DECAY'：每條 flow 選路完成後，扣除該 flow 最小路徑集合對 weight_map 的貢獻
#LOAD_CHECK_MODE = 'INCREMENTAL'  # DANGER 前瞻檢查用的 link 負載來源
#                                 # 'INCREMENTAL'：自己維護 link_load，隨每條 flow 的選路結果即時增減（預設）
#                                 # 'LIVE'：每次檢查都重新掃一次 active_flows 現算，較簡單但較耗運算
#PRESEED_ENDPOINTS = False  # True：每輪處理前，先把這輪所有 flow 的起訖點 switch（同一 host pair
#                           # 不管選哪條候選路徑都固定相同）預先標記為 active，不讓 clean_zero／
#                           # inactive_counter 把「反正一定要開」的 switch 誤判成選路的代價
#
# ── 要掃的組合，自行增減，只需指定要覆蓋的欄位 ──────────────────
COMBOS = [
    {'name': 'LPF',    'SORT_MODE': 'LPF','ENABLE_WEIGHT_MAP': False},
    {'name': 'SPF',    'SORT_MODE': 'SPF', 'ENABLE_WEIGHT_MAP': False},
    {'name': 'HDF',    'SORT_MODE': 'HDF', 'ENABLE_WEIGHT_MAP': False},
    {'name': 'SDF',    'SORT_MODE': 'SDF', 'ENABLE_WEIGHT_MAP': False},
    #{'name': 'LPF_ENABLE_WEIGHT_MAP', 'SORT_MODE': 'LPF', 'ENABLE_WEIGHT_MAP': True},
    #{'name': 'SPF_ENABLE_WEIGHT_MAP', 'SORT_MODE': 'SPF', 'ENABLE_WEIGHT_MAP': True},
    #{'name': 'HDF_ENABLE_WEIGHT_MAP', 'SORT_MODE': 'HDF', 'ENABLE_WEIGHT_MAP': True},
    #{'name': 'SDF_ENABLE_WEIGHT_MAP', 'SORT_MODE': 'SDF', 'ENABLE_WEIGHT_MAP': True},
    #{'name': 'DENSITY', 'SORT_MODE': 'DENSITY', 'ENABLE_WEIGHT_MAP': False},
    #{'name': 'DENSITY_ENABLE_WEIGHT_MAP', 'SORT_MODE': 'DENSITY', 'ENABLE_WEIGHT_MAP': True},

    {'name': 'LPF_PRESEED',    'SORT_MODE': 'LPF', 'ENABLE_WEIGHT_MAP': False, 'PRESEED_ENDPOINTS': True},
    {'name': 'SPF_PRESEED',    'SORT_MODE': 'SPF', 'ENABLE_WEIGHT_MAP': False, 'PRESEED_ENDPOINTS': True},
    {'name': 'HDF_PRESEED',    'SORT_MODE': 'HDF', 'ENABLE_WEIGHT_MAP': False, 'PRESEED_ENDPOINTS': True},
    {'name': 'SDF_PRESEED',    'SORT_MODE': 'SDF', 'ENABLE_WEIGHT_MAP': False, 'PRESEED_ENDPOINTS': True},
    #{'name': 'LPF_ENABLE_WEIGHT_MAP_PRESEED', 'SORT_MODE': 'LPF', 'ENABLE_WEIGHT_MAP': True, 'PRESEED_ENDPOINTS': True},
    #{'name': 'SPF_ENABLE_WEIGHT_MAP_PRESEED', 'SORT_MODE': 'SPF', 'ENABLE_WEIGHT_MAP': True, 'PRESEED_ENDPOINTS': True},
    #{'name': 'HDF_ENABLE_WEIGHT_MAP_PRESEED', 'SORT_MODE': 'HDF', 'ENABLE_WEIGHT_MAP': True, 'PRESEED_ENDPOINTS': True},
    #{'name': 'SDF_ENABLE_WEIGHT_MAP_PRESEED', 'SORT_MODE': 'SDF', 'ENABLE_WEIGHT_MAP': True, 'PRESEED_ENDPOINTS': True},
    #{'name': 'DENSITY_PRESEED', 'SORT_MODE': 'DENSITY', 'ENABLE_WEIGHT_MAP': False, 'PRESEED_ENDPOINTS': True},
    #{'name': 'DENSITY_ENABLE_WEIGHT_MAP_PRESEED', 'SORT_MODE': 'DENSITY', 'ENABLE_WEIGHT_MAP': True, 'PRESEED_ENDPOINTS': True},
]


def run_one_combo(combo, seed_data):
    """套用一組設定，完整跑過 seed 的所有 batch，回傳這組 combo 的
    energy_saving_summary（逐 batch + AVERAGE），已標上 combo 的欄位。"""
    # ALGORITHM='sorted_link' 時，COMBOS 的設定要套用到 routing_DTM_sorted_link
    # 這個模組（sim.Simulator 也是依 ALGORITHM 切換去 import 它），
    # 不然 sim.Simulator 實際用的模組跟這裡改的模組會對不上，等於白跑。
    if ALGORITHM == 'sorted_link':
        import modules.routing_DTM_sorted_link as rm
    else:
        import modules.routing_DTM_sorted as rm

    resolved = dict(BASELINE)
    resolved.update({k: v for k, v in combo.items() if k in BASELINE})
    for key, val in resolved.items():
        setattr(rm, key, val)

    sim.TOPO = TOPO

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    run_dir = f"log/sweep-{combo['name']}-{timestamp}"
    os.makedirs(run_dir, exist_ok=True)
    log_path = f"{run_dir}/experiment.log"

    print(f"\n{'='*60}")
    print(f"  combo={combo['name']}  resolved={resolved}")
    print(f"{'='*60}")

    # stdout 與 experiment.log 導向同一份檔案：
    # [DANGER_UNAVOIDABLE] 等訊息是 print()，跟 BATCH/ENERGY/HISTORY（_log()）
    # 本來是兩條分開的輸出流，合併寫入同一份才能讓 parse_log.py 一次讀到全部。
    old_stdout = sys.stdout
    tee = _AppendTee(log_path, old_stdout)
    sys.stdout = tee
    try:
        flow_duration = seed_data.get('flow_duration', 40)
        exp_dur = seed_data.get('experiment_duration', 150)

        for batch in seed_data['batches']:
            # 比照原本 sim.py CLI 的做法：每個 batch 各自建一個全新的 Simulator，
            # 讓 flow_history_count／reroute_count_* 等 HISTORY 計數器逐 batch 歸零，
            # 不會累加成 batch1、batch1+batch2、batch1+batch2+batch3。
            s = sim.Simulator(algorithm=ALGORITHM, log_path=log_path)
            bid = batch['batch_id']
            events = sim.load_seed_events(batch, flow_duration)
            event_idx, n_events = 0, len(events)

            s._log(f"=== BATCH {bid} START ===")
            for sec in range(0, exp_dur + 1):
                while event_idx < n_events and events[event_idx][0] <= sec:
                    sim_t, kind, src, dst, bw = events[event_idx]
                    if kind == 'admit':
                        s.admit(src, dst, bw, sim_t=sim_t)
                    else:
                        s.depart(src, dst, sim_t=sim_t)
                    event_idx += 1
                s._log_energy_second(sec)
            s._log_history()
            s._log(f"=== BATCH {bid} END ===")
    finally:
        sys.stdout = old_stdout
        tee.close()

    csv_path = f"{run_dir}/experiment.csv"
    parse_log(log_path, csv_path)
    base = matplotlib_DTM.analyze(csv_path, run_dir, make_plots=MAKE_PLOTS)

    base = base.reset_index()  # index (batch id / 'AVERAGE') 變成一般欄位 'batch'
    base.insert(0, 'name', combo.get('name', str(resolved)))
    for key in reversed(list(BASELINE.keys())):
        base.insert(1, key, resolved[key])
    return base



# ── 色票（dataviz 色票驗證過的 4 slot：blue / aqua / yellow / green） ──
_COLOR_FF = "#2a78d6"  # ENABLE_WEIGHT_MAP=False, PRESEED=False
_COLOR_TF = "#1baf7a"  # ENABLE_WEIGHT_MAP=True,  PRESEED=False
_COLOR_FT = "#eda100"  # ENABLE_WEIGHT_MAP=False, PRESEED=True
_COLOR_TT = "#008300"  # ENABLE_WEIGHT_MAP=True,  PRESEED=True
_INK_PRIMARY   = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED     = "#898781"
_GRID_COLOR    = "#e1e0d9"
_SURFACE       = "#fcfcfb"

# 固定的 (ENABLE_WEIGHT_MAP, PRESEED_ENDPOINTS) → (label, color) 對照表。
# 實際要畫哪幾條線由 _plot_sweep_bar() 依 avg 裡真正出現過的組合動態決定，
# 這裡只負責「如果出現了，要用什麼標籤/顏色」，本身不代表 4 條線都會畫出來。
_SERIES_STYLE = {
    (False, False): ("SGH",                                    _COLOR_FF),
    (True,  False): ("ENABLE_WEIGHT_MAP=True, PRESEED=False",  _COLOR_TF),
    (False, True):  ("SGH+ESP",                                _COLOR_FT),
    (True,  True):  ("ENABLE_WEIGHT_MAP=True, PRESEED=True",   _COLOR_TT),
}
if _CJK_FONT:
    _METRICS = [
        ("a) 節能百分比 (%)", "mean_after_100",   "節能 (%)"),
        ("b) 平均 hop 數",    "history_avg_hops", "平均 hop 數"),
    ]
else:
    _METRICS = [
        ("a) Energy saving (%)", "mean_after_100",   "Energy saving (%)"),
        ("b) Average hop count", "history_avg_hops", "Avg hop count"),
    ]


def _plot_sweep_bar(avg: pd.DataFrame, out_path: str):
    """畫節能百分比／平均 hop 數雙面板長條圖，依 SORT_MODE 分組、WEIGHT_MAP/PRESEED 當子長條。
    只畫 avg 裡實際出現過的 (ENABLE_WEIGHT_MAP, PRESEED_ENDPOINTS) 組合，
    COMBOS 沒跑到的組合不會出現在 legend 裡。"""
    sort_order = list(dict.fromkeys(avg['SORT_MODE']))  # 保留出現順序，去重
    present_keys = list(dict.fromkeys(
        zip(avg['ENABLE_WEIGHT_MAP'], avg['PRESEED_ENDPOINTS'])
    ))  # 保留出現順序，去重
    series = [(label, color, wm, preseed)
              for (wm, preseed) in present_keys
              for label, color in [_SERIES_STYLE[(wm, preseed)]]]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), facecolor=_SURFACE)
    n_series = len(series)
    bar_w, gap = 0.18, 0.02
    group_centers = np.arange(len(sort_order))
    legend_handles = []

    for panel_idx, (title, col, ylabel) in enumerate(_METRICS):
        ax = axes[panel_idx]
        ax.set_facecolor(_SURFACE)
        all_vals = []
        for i, (label, color, wm, preseed) in enumerate(series):
            offset = (i - (n_series - 1) / 2) * (bar_w + gap)
            values = []
            for sm in sort_order:
                row = avg[
                    (avg['SORT_MODE'] == sm)
                    & (avg['ENABLE_WEIGHT_MAP'] == wm)
                    & (avg['PRESEED_ENDPOINTS'] == preseed)
                ]
                values.append(row[col].iloc[0] if len(row) else np.nan)
            all_vals.extend(values)
            x = group_centers + offset
            bars = ax.bar(x, values, width=bar_w, color=color, label=label,
                          edgecolor=_SURFACE, linewidth=1.2, zorder=3)
            if panel_idx == 0:
                legend_handles.append(bars)

        vmin, vmax = np.nanmin(all_vals), np.nanmax(all_vals)
        pad = (vmax - vmin) * 0.6 if vmax > vmin else max(vmax * 0.05, 0.05)
        ax.set_ylim(vmin - pad, vmax + pad)
        ax.set_xticks(group_centers)
        ax.set_xticklabels(sort_order, fontsize=11, color=_INK_PRIMARY)
        ax.set_ylabel(ylabel, fontsize=10, color=_INK_SECONDARY)
        ax.set_title(title, fontsize=12, color=_INK_PRIMARY, loc="left", pad=10)
        ax.yaxis.grid(True, color=_GRID_COLOR, linewidth=1, zorder=0)
        ax.set_axisbelow(True)
        for spine in ["top", "right", "left"]:
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.tick_params(axis="y", colors=_INK_MUTED, labelsize=9)
        ax.tick_params(axis="x", length=0)

    _legend = fig.legend(
        [h[0] for h in legend_handles], [s[0] for s in series],
        loc="upper center", bbox_to_anchor=(0.5, 1.06), ncol=2,
        frameon=False, fontsize=9.5,
    )
    for _text in _legend.get_texts():
        _text.set_color(_INK_SECONDARY)
    fig.tight_layout(rect=[0, 0, 1, 0.92])
    fig.savefig(out_path, dpi=200, facecolor=_SURFACE, bbox_inches="tight")
    plt.close(fig)


def _write_summary(comparison: pd.DataFrame, out_dir: str):
    """輸出這輪 sweep 的文字摘要（summary.txt）+ 對照圖（sweep_bar.png）到 out_dir。"""
    avg = comparison[comparison['batch'] == 'AVERAGE'].reset_index(drop=True)

    chart_path = os.path.join(out_dir, "sweep_bar.png")
    _plot_sweep_bar(avg, chart_path)

    best  = avg.loc[avg['mean_after_100'].idxmax()]
    worst = avg.loc[avg['mean_after_100'].idxmin()]
    zero_cols = ['re_link', 're_high_hop', 're_low_share', 're_high_load',
                 'shortest_ratio', 'danger_unavoidable']
    all_zero = (comparison[zero_cols] == 0).all().all()
    flow_vals = avg['total_flows'].unique()

    lines = [
        f"TOPO={TOPO}  SEED_PATH={SEED_PATH}  ALGORITHM={ALGORITHM}",
        f"最高節能: {best['name']}  {best['mean_after_100']:.2f}%",
        f"最低節能: {worst['name']}  {worst['mean_after_100']:.2f}%",
        f"history_avg_hops 範圍: {avg['history_avg_hops'].min():.2f} ~ {avg['history_avg_hops'].max():.2f}",
        f"reroute/danger 全部欄位是否全 0: {all_zero}",
        f"total_flows 是否 20 組一致: {len(flow_vals) == 1}  {flow_vals}",
        "",
        avg.sort_values('mean_after_100', ascending=False)[
            ['name', 'SORT_MODE', 'ENABLE_WEIGHT_MAP', 'PRESEED_ENDPOINTS',
             'mean_after_100', 'history_avg_hops', 'total_flows']
        ].to_string(index=False),
    ]
    summary_text = "\n".join(lines)

    summary_path = os.path.join(out_dir, "summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print(f"\n{'='*60}\n=== Sweep 摘要 ===\n{'='*60}")
    print(summary_text)
    print(f"\n圖表已存至: {chart_path}")
    print(f"摘要已存至: {summary_path}")


def main():
    with open(SEED_PATH, encoding='utf-8') as f:
        seed_data = json.load(f)

    all_results = []
    for combo in COMBOS:
        result = run_one_combo(combo, seed_data)
        all_results.append(result)

    comparison = pd.concat(all_results, ignore_index=True)
    comparison.to_csv('sweep_comparison.csv', index=False)
    print(f"\n全部 {len(COMBOS)} 組 combo 完成，彙總表已存至 sweep_comparison.csv")

    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    summary_dir = f"log/sweep-summary-{timestamp}"
    os.makedirs(summary_dir, exist_ok=True)
    _write_summary(comparison, summary_dir)


if __name__ == '__main__':
    main()
