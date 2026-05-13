from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSKernelSwitch, UserSwitch, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, TCLink
import time
import os

from send_arp import send_arp_all

# =========================================
# MyCLI 擴展 - iperf 壓力測試命令
# =========================================
class MyCLI(CLI):
    
    def do_sendarp(self, line):
        """輸入 sendarp 來讓所有 host 互相發送 ARP"""
        send_arp_all(self.mn)
    
    def do_iperf_stress(self, line):
        """一鍵啟動壓力測試: iperf_stress [bw] [time]
        例如: iperf_stress 100m 150
        """
        args = line.split()
        bw = args[0] if len(args) > 0 else '100m'
        t  = args[1] if len(args) > 1 else '150'
        
        net = self.mn
        
        # server 端（偶數 host）
        servers = ['h2','h4','h6','h8','h10']
        #servers = ['h2','h4','h6','h8','h10','h12','h14','h16','h18','h20',
        #           'h22','h24','h26']
        for name in servers:
            net.get(name).cmd('iperf -s -u &')
        
        print("[*] 等待 server 啟動...")
        time.sleep(2)
        
        # client 端（奇數 host）
        pairs = [
            ('h1','h2'),  ('h3','h4'),  ('h5','h6'),  ('h7','h8'),
            ('h9','h10')
        ]
        #pairs = [
        #    ('h1','h2'),  ('h3','h4'),  ('h5','h6'),  ('h7','h8'),
        #    ('h9','h10'), ('h11','h12'),('h13','h14'),('h15','h16'),
        #    ('h17','h18'),('h19','h20'),('h21','h22'),('h23','h24'),
        #    ('h25','h26'),
        #]
        for src_name, dst_name in pairs:
            src = net.get(src_name)
            dst = net.get(dst_name)
            src.cmd(f'iperf -c {dst.IP()} -u -b {bw} -t {t} &')
            print(f"[*] {src_name} → {dst_name} ({dst.IP()}) 啟動")
        
        print(f"[*] 全部啟動完成，bw={bw}, t={t}s")
    
    def do_iperf_stop(self, line):
        """停止所有 iperf"""
        for h in self.mn.hosts:
            h.cmd('kill %iperf 2>/dev/null')
        print("[*] 所有 iperf 已停止")

def load_link_bw(filename='data/link_bw.txt'):
    """讀取 link_bw.txt，返回 {(src, dst): bw_mbps} 的字典
    Mininet TCLink 最大支援 1000 Mbps，超過此值會被限制
    """
    link_bw_map = {}
    if not os.path.exists(filename):
        print(f"[WARNING] {filename} not found, using default bandwidth")
        return link_bw_map
    
    MAX_BW = 1000  # Mininet TCLink 硬限制
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    src, dst = int(parts[0]), int(parts[1])
                    bw = int(parts[2])
                    if bw > MAX_BW:
                        print(f"[WARNING] Link ({src}, {dst}): {bw} Mbps exceeds max {MAX_BW}, capping to {MAX_BW}")
                        bw = MAX_BW
                    link_bw_map[(src, dst)] = bw
                except ValueError:
                    continue
    
    return link_bw_map

def topology():
    net = Mininet(controller=RemoteController, link=TCLink, switch=OVSSwitch)
    
    # 讀取帶寬配置
    link_bw_map = load_link_bw()

    # =========================================
    # Controller
    # =========================================
    c0 = net.addController( 'c0', controller=RemoteController, ip='127.0.0.1', port=6633 )

    # =========================================
    # Core Layer (4個) s1~s4
    # =========================================
    core1 = net.addSwitch('s1')
    core2 = net.addSwitch('s2')
    core3 = net.addSwitch('s3')
    core4 = net.addSwitch('s4')

    # =========================================
    # Distribution Layer (14個) s5~s18
    # =========================================
    d1  = net.addSwitch('s5')
    d2  = net.addSwitch('s6')
    d3  = net.addSwitch('s7')
    d4  = net.addSwitch('s8')
    d5  = net.addSwitch('s9')
    d6  = net.addSwitch('s10')
    d7  = net.addSwitch('s11')
    d8  = net.addSwitch('s12')
    d9  = net.addSwitch('s13')
    d10 = net.addSwitch('s14')
    d11 = net.addSwitch('s15')
    d12 = net.addSwitch('s16')
    d13 = net.addSwitch('s17')
    d14 = net.addSwitch('s18')

    # =========================================
    # WAN Layer (6個) s19~s24
    # =========================================
    w1 = net.addSwitch('s19')
    w2 = net.addSwitch('s20')
    w3 = net.addSwitch('s21')
    w4 = net.addSwitch('s22')
    w5 = net.addSwitch('s23')
    w6 = net.addSwitch('s24')

    # =========================================
    # Access Layer (21個) s25~s45
    # =========================================
    a1  = net.addSwitch('s25')
    a2  = net.addSwitch('s26')
    a3  = net.addSwitch('s27')
    a4  = net.addSwitch('s28')
    a5  = net.addSwitch('s29')
    a6  = net.addSwitch('s30')
    a7  = net.addSwitch('s31')
    a8  = net.addSwitch('s32')
    a9  = net.addSwitch('s33')
    a10 = net.addSwitch('s34')
    a11 = net.addSwitch('s35')
    a12 = net.addSwitch('s36')
    a13 = net.addSwitch('s37')
    a14 = net.addSwitch('s38')
    a15 = net.addSwitch('s39')
    a16 = net.addSwitch('s40')
    a17 = net.addSwitch('s41')
    a18 = net.addSwitch('s42')
    a19 = net.addSwitch('s43')
    a20 = net.addSwitch('s44')
    a21 = net.addSwitch('s45')

    # =========================================
    # Host Layer (h1~h27)
    # =========================================
    h1  = net.addHost('h1',  ip='10.0.0.1/24',  mac='00:00:00:00:00:01')
    h2  = net.addHost('h2',  ip='10.0.0.2/24',  mac='00:00:00:00:00:02')
    h3  = net.addHost('h3',  ip='10.0.0.3/24',  mac='00:00:00:00:00:03')
    h4  = net.addHost('h4',  ip='10.0.0.4/24',  mac='00:00:00:00:00:04')
    h5  = net.addHost('h5',  ip='10.0.0.5/24',  mac='00:00:00:00:00:05')
    h6  = net.addHost('h6',  ip='10.0.0.6/24',  mac='00:00:00:00:00:06')
    h7  = net.addHost('h7',  ip='10.0.0.7/24',  mac='00:00:00:00:00:07')
    h8  = net.addHost('h8',  ip='10.0.0.8/24',  mac='00:00:00:00:00:08')
    h9  = net.addHost('h9',  ip='10.0.0.9/24',  mac='00:00:00:00:00:09')
    h10 = net.addHost('h10', ip='10.0.0.10/24', mac='00:00:00:00:00:0a')
    h11 = net.addHost('h11', ip='10.0.0.11/24', mac='00:00:00:00:00:0b')
    h12 = net.addHost('h12', ip='10.0.0.12/24', mac='00:00:00:00:00:0c')
    h13 = net.addHost('h13', ip='10.0.0.13/24', mac='00:00:00:00:00:0d')
    h14 = net.addHost('h14', ip='10.0.0.14/24', mac='00:00:00:00:00:0e')
    h15 = net.addHost('h15', ip='10.0.0.15/24', mac='00:00:00:00:00:0f')
    h16 = net.addHost('h16', ip='10.0.0.16/24', mac='00:00:00:00:00:10')
    h17 = net.addHost('h17', ip='10.0.0.17/24', mac='00:00:00:00:00:11')
    h18 = net.addHost('h18', ip='10.0.0.18/24', mac='00:00:00:00:00:12')
    h19 = net.addHost('h19', ip='10.0.0.19/24', mac='00:00:00:00:00:13')
    h20 = net.addHost('h20', ip='10.0.0.20/24', mac='00:00:00:00:00:14')
    h21 = net.addHost('h21', ip='10.0.0.21/24', mac='00:00:00:00:00:15')
    h22 = net.addHost('h22', ip='10.0.0.22/24', mac='00:00:00:00:00:16')
    h23 = net.addHost('h23', ip='10.0.0.23/24', mac='00:00:00:00:00:17')
    h24 = net.addHost('h24', ip='10.0.0.24/24', mac='00:00:00:00:00:18')
    h25 = net.addHost('h25', ip='10.0.0.25/24', mac='00:00:00:00:00:19')
    h26 = net.addHost('h26', ip='10.0.0.26/24', mac='00:00:00:00:00:1a')
    h27 = net.addHost('h27', ip='10.0.0.27/24', mac='00:00:00:00:00:1b')

    # =========================================
    # Core <-> Core 連線 (彼此相通)
    # =========================================
    cores = [core1, core2, core3, core4]
    for i in range(len(cores)):
        for j in range(i+1, len(cores)):
            src_dpid, dst_dpid = i+1, j+1
            bw = link_bw_map.get((src_dpid, dst_dpid), 250)
            net.addLink(cores[i], cores[j])

    # =========================================
    # Core <-> Distribution 連線
    # core1, core2 <-> d1~d8
    # core3, core4 <-> d9~d14
    # =========================================
    for idx, d in enumerate([d1, d2, d3, d4, d5, d6, d7, d8]):
        dst_dpid = idx + 5  # s5~s12
        bw1 = link_bw_map.get((1, dst_dpid), 250)
        bw2 = link_bw_map.get((2, dst_dpid), 250)
        net.addLink(core1, d)
        net.addLink(core2, d)

    for idx, d in enumerate([d9, d10, d11, d12, d13, d14]):
        dst_dpid = idx + 13  # s13~s18
        bw3 = link_bw_map.get((3, dst_dpid), 250)
        bw4 = link_bw_map.get((4, dst_dpid), 250)
        net.addLink(core3, d)
        net.addLink(core4, d)

    # =========================================
    # WAN <-> Distribution 連線 (3:1)
    # d9,  d10 <-> w1, w2, w3
    # d11, d12 <-> w4, w5, w6
    # =========================================
    wan_dist_pairs = [
        (13, 14, [w1, w2, w3], [19, 20, 21]),
        (15, 16, [w4, w5, w6], [22, 23, 24]),
    ]
    for src_d1, src_d2, wan_list, wan_dpids in wan_dist_pairs:
        d_list = [d9, d10] if src_d1 == 13 else [d11, d12]
        for d_switch, src_dpid in zip(d_list, [src_d1, src_d2]):
            for w, w_dpid in zip(wan_list, wan_dpids):
                bw = link_bw_map.get((src_dpid, w_dpid), 250)
                net.addLink(d_switch, w)

    # =========================================
    # Distribution <-> Access 連線 (4:1)
    # d1,d2   <-> a1~a4
    # d3,d4   <-> a5~a8
    # d5,d6   <-> a9~a12
    # d7,d8   <-> a13~a16
    # =========================================
    dist_access_pairs = [
        (5, 6, [a1, a2, a3, a4], [25, 26, 27, 28]),
        (7, 8, [a5, a6, a7, a8], [29, 30, 31, 32]),
        (9, 10, [a9, a10, a11, a12], [33, 34, 35, 36]),
        (11, 12, [a13, a14, a15, a16], [37, 38, 39, 40]),
    ]
    dist_map = {5: d1, 6: d2, 7: d3, 8: d4, 9: d5, 10: d6, 11: d7, 12: d8}
    
    for src_d1, src_d2, access_list, access_dpids in dist_access_pairs:
        for a, a_dpid in zip(access_list, access_dpids):
            bw1 = link_bw_map.get((src_d1, a_dpid), 250)
            bw2 = link_bw_map.get((src_d2, a_dpid), 250)
            net.addLink(dist_map[src_d1], a)
            net.addLink(dist_map[src_d2], a)

    # =========================================
    # Distribution <-> Access 連線 (5:1)
    # d13, d14 <-> a17~a21
    # =========================================
    for idx, a in enumerate([a17, a18, a19, a20, a21]):
        access_dpid = 41 + idx
        bw_d13 = link_bw_map.get((17, access_dpid), 250)
        bw_d14 = link_bw_map.get((18, access_dpid), 250)
        net.addLink(d13, a)
        net.addLink(d14, a)

    # =========================================
    # Access <-> Host 連線 (a1~a21 <-> h1~h21)
    # =========================================
    access_host = [
        (a1,  h1),  (a2,  h2),  (a3,  h3),  (a4,  h4),  (a5,  h5),
        (a6,  h6),  (a7,  h7),  (a8,  h8),  (a9,  h9),  (a10, h10),
        (a11, h11), (a12, h12), (a13, h13), (a14, h14), (a15, h15),
        (a16, h16), (a17, h17), (a18, h18), (a19, h19), (a20, h20),
        (a21, h21),
    ]
    for a, h in access_host:
        net.addLink(a, h)

    # =========================================
    # WAN <-> Host 連線 (w1~w6 <-> h22~h27)
    # =========================================
    wan_host = [
        (w1, h22), (w2, h23), (w3, h24),
        (w4, h25), (w5, h26), (w6, h27),
    ]
    for w, h in wan_host:
        net.addLink(w, h)

    net.build()

    c0.start()
    core1.start([c0]); core2.start([c0]); core3.start([c0]); core4.start([c0])
    d1.start([c0]);  d2.start([c0]);  d3.start([c0]);  d4.start([c0])
    d5.start([c0]);  d6.start([c0]);  d7.start([c0]);  d8.start([c0])
    d9.start([c0]);  d10.start([c0]); d11.start([c0]); d12.start([c0])
    d13.start([c0]); d14.start([c0])
    w1.start([c0]); w2.start([c0]); w3.start([c0])
    w4.start([c0]); w5.start([c0]); w6.start([c0])
    a1.start([c0]);  a2.start([c0]);  a3.start([c0]);  a4.start([c0])
    a5.start([c0]);  a6.start([c0]);  a7.start([c0]);  a8.start([c0])
    a9.start([c0]);  a10.start([c0]); a11.start([c0]); a12.start([c0])
    a13.start([c0]); a14.start([c0]); a15.start([c0]); a16.start([c0])
    a17.start([c0]); a18.start([c0]); a19.start([c0]); a20.start([c0])
    a21.start([c0])

    print("*** Running CLI")
    MyCLI(net)  # ← 把 CLI(net) 換成 MyCLI(net)

    print("*** Stopping network")
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    topology()