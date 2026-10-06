# regen_seeds.py
# ─────────────────────────────────────────────────────────────────
# 依 seeds/manifest.json 記錄的參數，用 gen_seed.py 重新產生 sim 用的 seed 檔。
#
# gen_seed.py 用 random.Random(seed)，同一組參數（seed／hosts／flow_duration／
# lambda／bw_min／bw_max／num_batches）必定產生逐位元組相同的檔案，所以 sim seed
# 不另外保存檔案，只保存參數（2026-10-06 驗證：清單內每一個都能重產出跟原檔相同的內容）。
# 前提是 gen_seed.py 的抽樣邏輯不改；改了就重現不出來。
#
# 輸出到專案根目錄（跟過去 seed 檔放的位置相同），所以 sweep_sorted.py 的 SEED_PATH、
# sim.py --seed 等既有寫法不用改。
#
# 用法：
#   python regen_seeds.py seed_000_grid5x5_xlow.json seed_000_grid5x5_low.json
#   python regen_seeds.py --list              # 列出清單裡有哪些
#   python regen_seeds.py --all [--out-dir D] # 全部重產
# ─────────────────────────────────────────────────────────────────
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, 'seeds', 'manifest.json')


def regen(name, params, out_dir):
    # gen_seed.py 沒有 experiment_duration 參數（寫死 150），清單裡的值必須跟它一致
    assert params['experiment_duration'] == 150, f'{name}: experiment_duration={params["experiment_duration"]}，gen_seed.py 無法產生'
    out = os.path.join(out_dir, name)
    cmd = [sys.executable, os.path.join(HERE, 'gen_seed.py'),
           '--seed', str(params['seed']), '--batches', str(params['num_batches']),
           '--hosts', str(params['num_hosts']), '--output', out]
    # 這幾個 CLI 參數一律轉成 float；清單裡是整數，代表當初沒下參數、用的是 gen_seed.py 的
    # 預設常數（例如 seed_000_cap 的 flow_duration=40），這時也不要傳，表頭才會跟原檔一樣是整數
    for flag, key in (('--flow-duration', 'flow_duration'), ('--lambda', 'lambda'),
                      ('--bw-min', 'bw_min'), ('--bw-max', 'bw_max')):
        if not isinstance(params[key], int):
            cmd += [flag, repr(params[key])]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('names', nargs='*', help='要重產的 seed 檔名（例如 seed_000_grid5x5_xlow.json）')
    parser.add_argument('--all', action='store_true', help='重產清單內全部')
    parser.add_argument('--list', action='store_true', help='列出清單內容')
    parser.add_argument('--out-dir', default=HERE, help='輸出資料夾，預設專案根目錄')
    args = parser.parse_args()

    manifest = json.load(open(MANIFEST, encoding='utf-8'))['seeds']
    if args.list:
        for name, p in manifest.items():
            print(f"{name}  seed={p['seed']} hosts={p['num_hosts']} lambda={p['lambda']} "
                  f"bw={p['bw_min']}~{p['bw_max']} flow_duration={p['flow_duration']} batches={p['num_batches']}")
        sys.exit(0)

    names = list(manifest) if args.all else args.names
    if not names:
        parser.error('請給 seed 檔名，或用 --all／--list')
    unknown = [n for n in names if n not in manifest]
    if unknown:
        sys.exit(f'清單裡沒有：{unknown}（用 --list 查看）')
    os.makedirs(args.out_dir, exist_ok=True)
    for n in names:
        print(f'已產生 {regen(n, manifest[n], args.out_dir)}')
