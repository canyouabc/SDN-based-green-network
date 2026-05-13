from mininet.net import Mininet
from mininet.node import Controller, RemoteController, OVSKernelSwitch, UserSwitch, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel
from mininet.link import Link, TCLink

def topology():
        net = Mininet( controller=RemoteController, link=TCLink, switch=OVSSwitch )

        # Add hosts and switches
        h1= net.addHost( 'h1', mac="00:00:00:00:00:01" )
        h2= net.addHost( 'h2', mac="00:00:00:00:00:02" )

        s0 = net.addSwitch( 's0' )
        s1 = net.addSwitch( 's1' )
        s2 = net.addSwitch( 's2' )
        s3 = net.addSwitch( 's3' )
        s4 = net.addSwitch( 's4' )
        s5 = net.addSwitch( 's5' )
        s6 = net.addSwitch( 's6' )
        s7 = net.addSwitch( 's7' )
        s8 = net.addSwitch( 's8' )

        c0 = net.addController( 'c0', controller=RemoteController, ip='127.0.0.1', port=6633 )

        # 每條連結都有獨立的延遲設定，單位為毫秒
        net.addLink( h1, s0)
        net.addLink( h2, s4)
        net.addLink( s0, s1, delay='40ms') 
        net.addLink( s1, s2, delay='80ms') 
        net.addLink( s2, s3, delay='70ms') 
        net.addLink( s3, s4, delay='10ms')  
        net.addLink( s0, s7, delay='80ms') 
        net.addLink( s1, s7, delay='110ms') 
        net.addLink( s7, s8, delay='70ms')
        net.addLink( s7, s6, delay='10ms')
        net.addLink( s6, s8, delay='60ms')
        net.addLink( s8, s2, delay='20ms')
        net.addLink( s6, s5, delay='20ms')
        net.addLink( s2, s5, delay='40ms')
        net.addLink( s3, s5, delay='140ms')
        net.addLink( s5, s4, delay='100ms')


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

        print ("*** Running CLI")
        CLI( net )

        print ("*** Stopping network")
        net.stop()

if __name__ == '__main__':
    setLogLevel( 'info' )
    topology()   