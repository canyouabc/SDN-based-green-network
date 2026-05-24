from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink
from send_arp import send_arp_all

# =========================================
# Campus Network Topology
#
# [Core]  s1 ── s2      (s1~s4 完全互連)
#          |╲  /|
#          | ╲╱ |
#          | ╱╲ |
#          |/  \|
#         s3 ── s4
#
# [Distribution A]  s1,s2 <-> s5~s12   (d1~d8)
# [Distribution B]  s3,s4 <-> s13~s18  (d9~d14)
#
# [WAN]  s13,s14 <-> s19,s20,s21  (w1~w3)
#        s15,s16 <-> s22,s23,s24  (w4~w6)
#
# [Access]  s5, s6  <-> s25~s28  → h1~h4
#           s7, s8  <-> s29~s32  → h5~h8
#           s9, s10 <-> s33~s36  → h9~h12
#           s11,s12 <-> s37~s40  → h13~h16
#           s17,s18 <-> s41~s45  → h17~h21
#
# [WAN Host]  s19~s24 → h22~h27
#
# 共 45 個 switch，27 個 host
# =========================================


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

    c0 = net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)

    # =========================================
    # Switches
    # =========================================
    core   = [net.addSwitch(f's{i}') for i in range(1,  5)]   # s1~s4   (4)
    dist   = [net.addSwitch(f's{i}') for i in range(5,  19)]  # s5~s18  (14)
    wan    = [net.addSwitch(f's{i}') for i in range(19, 25)]  # s19~s24 (6)
    access = [net.addSwitch(f's{i}') for i in range(25, 46)]  # s25~s45 (21)

    # =========================================
    # Hosts  h1~h27
    # =========================================
    hosts = [
        net.addHost(f'h{i}', ip=f'10.0.0.{i}/24', mac=f'00:00:00:00:00:{i:02x}')
        for i in range(1, 28)
    ]

    # =========================================
    # Core <-> Core  (完全互連)
    # =========================================
    for i in range(4):
        for j in range(i + 1, 4):
            net.addLink(core[i], core[j])

    # =========================================
    # Core <-> Distribution
    # s1,s2 (core[0,1]) <-> s5~s12  (dist[0~7])
    # s3,s4 (core[2,3]) <-> s13~s18 (dist[8~13])
    # =========================================
    for d in dist[:8]:
        net.addLink(core[0], d)
        net.addLink(core[1], d)

    for d in dist[8:]:
        net.addLink(core[2], d)
        net.addLink(core[3], d)

    # =========================================
    # WAN <-> Distribution
    # s13,s14 (dist[8,9])   <-> s19~s21 (wan[0~2])
    # s15,s16 (dist[10,11]) <-> s22~s24 (wan[3~5])
    # =========================================
    for d in dist[8:10]:
        for w in wan[:3]:
            net.addLink(d, w)

    for d in dist[10:12]:
        for w in wan[3:]:
            net.addLink(d, w)

    # =========================================
    # Distribution <-> Access  (4:1，雙上行)
    # grp 0: s5, s6  (dist[0,1]) <-> s25~s28 (access[0~3])
    # grp 1: s7, s8  (dist[2,3]) <-> s29~s32 (access[4~7])
    # grp 2: s9, s10 (dist[4,5]) <-> s33~s36 (access[8~11])
    # grp 3: s11,s12 (dist[6,7]) <-> s37~s40 (access[12~15])
    # =========================================
    for grp in range(4):
        d1 = dist[grp * 2]
        d2 = dist[grp * 2 + 1]
        for a in access[grp * 4 : grp * 4 + 4]:
            net.addLink(d1, a)
            net.addLink(d2, a)

    # =========================================
    # Distribution <-> Access  (5:1，雙上行)
    # s17,s18 (dist[12,13]) <-> s41~s45 (access[16~20])
    # =========================================
    for a in access[16:]:
        net.addLink(dist[12], a)
        net.addLink(dist[13], a)

    # =========================================
    # Access <-> Host  (a1~a21 → h1~h21)
    # =========================================
    for a, h in zip(access, hosts[:21]):
        net.addLink(a, h)

    # =========================================
    # WAN <-> Host  (w1~w6 → h22~h27)
    # =========================================
    for w, h in zip(wan, hosts[21:]):
        net.addLink(w, h)

    # =========================================
    # 啟動
    # =========================================
    net.build()
    c0.start()
    for sw in core + dist + wan + access:
        sw.start([c0])

    print("*** Running CLI")
    MyCLI(net)

    print("*** Stopping network")
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    topology()
