from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import TCLink
from send_arp import send_arp_all

# =========================================
# GEANT Network Topology
#
# 來源：SNDlib native format, network "geant"
# (https://sndlib.put.poznan.pl/download/sndlib-networks-native/geant.txt)
#
# 22 個節點（20 個歐洲城市 + ny1.ny + il1.il，皆保留、不刪減），
# 36 條無向鏈路（原始資料為 SNDlib 格式，每條鏈路單一 module 40000 Mbps，
# 此處依專案慣例縮小為 1000 Mbps，供 data/geant/link_bw.txt 與 sim.py 使用；
# 對應的流量矩陣（data/geant 流量轉換）也依相同比例 1/40 縮放，維持相對壅塞比例）。
#
# Switch 對應表（dpid = NODE SECTION 出現順序）：
#   s1 =at1.at   s2 =be1.be   s3 =ch1.ch   s4 =cz1.cz   s5 =de1.de
#   s6 =es1.es   s7 =fr1.fr   s8 =gr1.gr   s9 =hr1.hr   s10=hu1.hu
#   s11=ie1.ie   s12=il1.il   s13=it1.it   s14=lu1.lu   s15=nl1.nl
#   s16=ny1.ny   s17=pl1.pl   s18=pt1.pt   s19=se1.se   s20=si1.si
#   s21=sk1.sk   s22=uk1.uk
#
# 每個 switch 各接 1 台 host（h1~h22，編號與 switch 一致），
# 比照 grid/cap 慣例（host 與 switch 一對一，MAC 尾碼 = host 編號）。
# =========================================

NODE_NAMES = [
    'at1.at', 'be1.be', 'ch1.ch', 'cz1.cz', 'de1.de',
    'es1.es', 'fr1.fr', 'gr1.gr', 'hr1.hr', 'hu1.hu',
    'ie1.ie', 'il1.il', 'it1.it', 'lu1.lu', 'nl1.nl',
    'ny1.ny', 'pl1.pl', 'pt1.pt', 'se1.se', 'si1.si',
    'sk1.sk', 'uk1.uk',
]

# (src, dst) 依節點名稱表示，順序照原始 LINK SECTION
LINK_NAMES = [
    ('at1.at', 'ch1.ch'), ('at1.at', 'de1.de'), ('at1.at', 'hu1.hu'),
    ('at1.at', 'ny1.ny'), ('at1.at', 'si1.si'),
    ('be1.be', 'fr1.fr'), ('be1.be', 'lu1.lu'), ('be1.be', 'nl1.nl'),
    ('ch1.ch', 'fr1.fr'), ('ch1.ch', 'it1.it'),
    ('cz1.cz', 'de1.de'), ('cz1.cz', 'pl1.pl'), ('cz1.cz', 'sk1.sk'),
    ('de1.de', 'fr1.fr'), ('de1.de', 'gr1.gr'), ('de1.de', 'ie1.ie'),
    ('de1.de', 'it1.it'), ('de1.de', 'nl1.nl'), ('de1.de', 'se1.se'),
    ('es1.es', 'fr1.fr'), ('es1.es', 'it1.it'), ('es1.es', 'pt1.pt'),
    ('fr1.fr', 'lu1.lu'), ('fr1.fr', 'uk1.uk'),
    ('gr1.gr', 'it1.it'),
    ('hr1.hr', 'hu1.hu'), ('hr1.hr', 'si1.si'),
    ('hu1.hu', 'sk1.sk'),
    ('ie1.ie', 'uk1.uk'),
    ('il1.il', 'it1.it'), ('il1.il', 'nl1.nl'),
    ('nl1.nl', 'uk1.uk'),
    ('ny1.ny', 'uk1.uk'),
    ('pl1.pl', 'se1.se'),
    ('pt1.pt', 'uk1.uk'),
    ('se1.se', 'uk1.uk'),
]

NODE_TO_DPID = {name: i + 1 for i, name in enumerate(NODE_NAMES)}
NUM_SWITCHES = len(NODE_NAMES)


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
    # Switches（dpid 依 NODE_NAMES 順序，1-based）
    # =========================================
    switches = [net.addSwitch(f's{i}') for i in range(1, NUM_SWITCHES + 1)]

    # =========================================
    # Hosts（每個 switch 各接 1 台，h 編號與 switch 編號一致）
    # =========================================
    hosts = [
        net.addHost(f'h{i}', ip=f'10.0.0.{i}/24', mac=f'00:00:00:00:00:{i:02x}')
        for i in range(1, NUM_SWITCHES + 1)
    ]

    # =========================================
    # Switch <-> Switch（依 GEANT LINK SECTION，36 條）
    # =========================================
    for src_name, dst_name in LINK_NAMES:
        net.addLink(switches[NODE_TO_DPID[src_name] - 1],
                    switches[NODE_TO_DPID[dst_name] - 1])

    # =========================================
    # Switch <-> Host（一對一）
    # =========================================
    for sw, h in zip(switches, hosts):
        net.addLink(sw, h)

    # =========================================
    # 啟動
    # =========================================
    net.build()
    c0.start()
    for sw in switches:
        sw.start([c0])

    print("*** 設定 PacketIn rate limit...")
    for sw in switches:
        sw.cmd(f'sudo ovs-vsctl set controller {sw.name} '
               f'controller-rate-limit=100 controller-burst-limit=25')

    print("*** Running CLI")
    MyCLI(net)

    print("*** Stopping network")
    net.stop()


if __name__ == '__main__':
    setLogLevel('info')
    topology()
