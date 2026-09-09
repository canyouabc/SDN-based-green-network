import os
import time
from mininet.cli import CLI

### 在 mininet 中輸入 sendarp 就會執行這個函式，讓所有 host 互相發送 ARP Request

def send_arp_all(net):
    hosts = net.hosts
    total = len(hosts) * (len(hosts) - 1)
    count = 0

    print(f"[*] 共需發送 {total} 次 ARP Request...")

    for src in hosts:
        for dst in hosts:
            if src == dst:
                continue

            dst_ip = dst.IP()
            iface  = src.defaultIntf().name
            src.cmd(f'arping -c 1 -i {iface} {dst_ip} > /dev/null 2>&1 &')

            count += 1
            print(f"[{count}/{total}] {src.name} -> {dst.name} ({dst_ip})")
            if count % 80 == 0:
                time.sleep(0.5)

    print("[*] 等待所有 ARP 發送完成...")

    print("[*] ARP 全部發送完畢！")

    # 寫出旗標檔，讓 DTM.py 的 dynamic_Dijkstra_test（auto_k_short 模式）知道
    # ARP 真的送完了，才開始輪詢 host_macs 穩定度，避免在這之前提早觸發計算
    open('arp_done.flag', 'w').close()


class MyCLI(CLI):
    """自訂 CLI，新增 sendarp 指令"""

    # 只要方法名稱是 do_xxx
    # 在 CLI 輸入 xxx 就會自動執行
    def do_sendarp(self, line):
        """輸入 sendarp 來讓所有 host 互相發送 ARP"""
        send_arp_all(self.mn)