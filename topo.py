from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSKernelSwitch, UserSwitch, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, TCLink
import threading
import time
import random

def change_delay_periodically(net):
    """定時改變鏈路延遲"""
    while True:
        time.sleep(10)  # 每 10 秒改變一次
        
        # 改變 s8-s9 鏈路的延遲 (原本 50ms)
        new_delay = random.randint(10, 50)
        #print(f"\n*** Changing s8-s9 delay to {new_delay}ms")
        
        # 獲取 s8-s9 之間的鏈路
        links = net.linksBetween(net.get('s8'), net.get('s9'))
        if links:
            link = links[0]
            # 修改兩端接口的延遲
            link.intf1.config(delay=f'{new_delay}ms')
            link.intf2.config(delay=f'{new_delay}ms')
def topology():
        net = Mininet( controller=RemoteController, link=TCLink, switch=OVSSwitch )

        # Add hosts and switches
        h1= net.addHost( 'h1', ip='10.0.0.1/24', mac="00:00:00:00:00:01" )
        h2= net.addHost( 'h2', ip='10.0.0.2/24', mac="00:00:00:00:00:02" )
        h3= net.addHost( 'h3', ip='10.0.0.3/24', mac="00:00:00:00:00:03" )
        h4= net.addHost( 'h4', ip='10.0.0.4/24', mac="00:00:00:00:00:04" )

        s1 = net.addSwitch( 's1' )
        s2 = net.addSwitch( 's2' )
        s3 = net.addSwitch( 's3' )
        s4 = net.addSwitch( 's4' )
        s5 = net.addSwitch( 's5' )
        s6 = net.addSwitch( 's6' )
        s7 = net.addSwitch( 's7' )
        s8 = net.addSwitch( 's8' )
        s9 = net.addSwitch( 's9' )


        c0 = net.addController( 'c0', controller=RemoteController, ip='127.0.0.1', port=6633 )

        # 每條連結都有獨立的延遲設定，單位為毫秒
        net.addLink( h1, s1)
        net.addLink( h2, s3)
        net.addLink( h3, s7)
        net.addLink( h4, s9)
        net.addLink( s1, s2, delay='50ms')
        net.addLink( s2, s3, delay='30ms')
        net.addLink( s1, s4, delay='60ms')
        net.addLink( s2, s5, delay='10ms')
        net.addLink( s3, s6, delay='10ms')
        net.addLink( s4, s5, delay='70ms')
        net.addLink( s5, s6, delay='80ms')
        net.addLink( s4, s7, delay='90ms')
        net.addLink( s5, s8, delay='40ms')
        net.addLink( s6, s9, delay='20ms')
        net.addLink( s7, s8, delay='500ms')
        net.addLink( s8, s9, delay='50ms')

        # 啟動定時器執行緒
        delay_thread = threading.Thread(target=change_delay_periodically, args=(net,))
        delay_thread.daemon = True  # 設為 daemon，主程序結束時自動終止
        delay_thread.start()

        net.build()
        
        c0.start()
        s1.start( [c0] )
        s2.start( [c0] )
        s3.start( [c0] )
        s4.start( [c0] )
        s5.start( [c0] )
        s6.start( [c0] )
        s7.start( [c0] )
        s8.start( [c0] )
        s9.start( [c0] )
        
        
        print( "*** Running CLI" )
        CLI( net )

        print ("*** Stopping network")
        net.stop()

if __name__ == '__main__':
    setLogLevel( 'info' )
    topology()

