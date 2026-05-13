from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSKernelSwitch, UserSwitch, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, TCLink

# 這個 topo 主要是給 Dijkstra 驗證用的

def topology():
        net = Mininet( controller=RemoteController, link=TCLink, switch=OVSSwitch )

        # Add hosts and switches
        h1= net.addHost( 'h1', mac="00:00:00:00:00:01" )
        h2 = net.addHost( 'h2', mac="00:00:00:00:00:02" )

        s1 = net.addSwitch( 's1' )
        s2 = net.addSwitch( 's2' )
        s3 = net.addSwitch( 's3' )
        s4 = net.addSwitch( 's4' )
        s5 = net.addSwitch( 's5' )

        c0 = net.addController( 'c0', controller=RemoteController, ip='127.0.0.1', port=6633 )

        # 每條連結都有獨立的延遲設定，單位為毫秒
        linkopt1=dict(loss=10)     
        linkopt2=dict(loss=12)    
        linkopt3=dict(loss=5)      
        linkopt4=dict(loss=12)     
        linkopt5=dict(loss=50)     
        net.addLink( h1, s1)
        net.addLink( h2, s4)
        net.addLink( s1, s2, **linkopt1)    
        net.addLink( s2, s3, **linkopt2)   
        net.addLink( s3, s4, **linkopt3)   
        net.addLink( s4, s5, **linkopt4)    
        net.addLink( s1, s5, **linkopt5)    

        net.build()

        c0.start()
        s1.start( [c0] )
        s2.start( [c0] )
        s3.start( [c0] )
        s4.start( [c0] )
        s5.start( [c0] )

        print ("*** Running CLI")
        CLI( net )

        print ("*** Stopping network")
        net.stop()

if __name__ == '__main__':
    setLogLevel( 'info' )
    topology()   
