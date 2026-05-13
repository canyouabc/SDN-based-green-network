from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink
from send_arp import send_arp_all

# =========================================
# 5×5 Grid Topology
#
#       h1    h2    h3    h4    h5
#        |     |     |     |     |
#       s1 -- s2 -- s3 -- s4 -- s5
#        |     |     |     |     |
# h16 - s6 -- s7 -- s8 -- s9 --s10 - h6
#        |     |     |     |     |
# h15 -s11 --s12 --s13 --s14 --s15 - h7
#        |     |     |     |     |
# h14 -s16 --s17 --s18 --s19 --s20 - h8
#        |     |     |     |     |
# h13 -s21 --s22 --s23 --s24 --s25 - h9
#              |     |     |
#             h12   h11   h10
#
# 外圍 switch 共 16 個，各接一個 host（角落只算一次）：
#   上排 左→右: s1~s5        → h1~h5
#   右排 上→下: s10,s15,s20  → h6~h8
#   下排 右→左: s25~s21      → h9~h13
#   左排 下→上: s16,s11,s6   → h14~h16
# =========================================

N = 5  # grid 大小

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
    # 建立 25 個 switch（s1~s25）
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
    border += [(1, c) for c in range(1, N + 1)]          # 上排: (1,1)~(1,5)
    border += [(r, N) for r in range(2, N)]               # 右排: (2,5)~(4,5)
    border += [(N, c) for c in range(N, 0, -1)]           # 下排: (5,5)~(5,1)
    border += [(r, 1) for r in range(N - 1, 1, -1)]      # 左排: (4,1)~(2,1)

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
