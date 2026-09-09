from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink
from send_arp import send_arp_all

# =========================================
# 4×4 Grid Topology
#
# N x N switches arranged in a grid, connected horizontally and
# vertically to their neighbors. Border switches (perimeter of the
# grid) each connect to exactly one host.
#
# Host numbering order: top row left→right, right column top→bottom,
# bottom row right→left, left column bottom→top.
# Total hosts = 4*(N-1) = 12.
#
# Same generation pattern as grid_topo.py (5×5), only N differs.
# =========================================

N = 4  # grid 大小

def sw_id(r, c):
    """(row, col) 從 1 開始，回傳 switch dpid（1-based）"""
    return (r - 1) * N + c


class MyCLI(CLI):
    def do_sendarp(self, line):
        """輸入 sendarp 來讓所有 host 互相發送 ARP"""
        send_arp_all(self.mn)

    def do_iperf_stop(self, line):
        """停止所有 iperf"""
        for h in self.mn.hosts:
            h.cmd('kill %iperf 2>/dev/null')
        print("[*] 所有 iperf 已停止")



def topology():
    net = Mininet(controller=RemoteController, link=TCLink, switch=OVSSwitch)

    # =========================================
    # Controller
    # =========================================
    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    # =========================================
    # 建立 N*N 個 switch（s1~sN*N）
    # switches[r][c]，index 從 0 開始
    # =========================================
    switches = {}
    for r in range(1, N + 1):
        for c in range(1, N + 1):
            dpid = sw_id(r, c)
            switches[(r, c)] = net.addSwitch(f's{dpid}')

    # =========================================
    # Grid 連線
    # =========================================
    # 水平連線：同一 row 的相鄰 switch
    for r in range(1, N + 1):
        for c in range(1, N):
            net.addLink(switches[(r, c)], switches[(r, c + 1)])

    # 垂直連線：同一 col 的相鄰 switch
    for r in range(1, N):
        for c in range(1, N + 1):
            net.addLink(switches[(r, c)], switches[(r + 1, c)])

    # =========================================
    # 外圍 switch 與 host 配對
    # 順序：上排左→右、右排上→下、下排右→左、左排下→上
    # =========================================
    border = []
    border += [(1, c) for c in range(1, N + 1)]          # 上排: (1,1)~(1,N)
    border += [(r, N) for r in range(2, N)]               # 右排: (2,N)~(N-1,N)
    border += [(N, c) for c in range(N, 0, -1)]           # 下排: (N,N)~(N,1)
    border += [(r, 1) for r in range(N - 1, 1, -1)]      # 左排: (N-1,1)~(2,1)

    hosts = []
    for idx, (r, c) in enumerate(border):
        h_num  = idx + 1
        ip     = f'10.0.0.{h_num}/24'
        mac    = f'00:00:00:00:00:{h_num:02x}'
        h = net.addHost(f'h{h_num}', ip=ip, mac=mac)
        net.addLink(switches[(r, c)], h)
        hosts.append(h)

    print(f"*** 共 {len(border)} 個外圍 switch，各接一個 host")

    # =========================================
    # 啟動
    # =========================================
    net.build()
    c0.start()

    for r in range(1, N + 1):
        for c in range(1, N + 1):
            switches[(r, c)].start([c0])

    print("*** Running CLI")
    MyCLI(net)

    print("*** Stopping network")
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    topology()
