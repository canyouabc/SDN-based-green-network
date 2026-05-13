# -*- coding: utf-8 -*-
from collections import defaultdict

from operator import attrgetter
from ryu.app.wsgi import ControllerBase
from ryu.base import app_manager
from ryu.controller import mac_to_port
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.lib import hub
from ryu.lib import mac
from ryu.lib.mac import haddr_to_bin
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import packet
from ryu.ofproto import ofproto_v1_3
from ryu.topology import event, switches
from ryu.topology.api import get_link, get_switch


# switches
myswitches = []

# mymac[srcmac]->(switch, port)
mymac = {}

# adjacency map [sw1][sw2]->port from sw1 to sw2
adjacency = defaultdict(lambda: defaultdict(lambda: None))
datapath_list = {}

loss_rate = defaultdict(lambda: defaultdict(lambda: None))

LOSS_RATE_FILE = "loss_rate.txt"
ENABLE_LOSS_AWARE_ROUTING = True


def _load_loss_rate_file(file_path=LOSS_RATE_FILE):
    """Populate the loss_rate adjacency map from file."""
    global loss_rate
    loss_rate.clear()
    loaded_edges = 0
    try:
        with open(file_path, "r") as fin:
            for raw_line in fin:
                line = raw_line.strip()
                if not line or line.startswitch("#"):
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                src_dpid, dst_dpid = parts[0], parts[1]
                try:
                    link_loss = float(parts[2])
                except ValueError:
                    continue
                loss_rate[src_dpid][dst_dpid] = link_loss
                loss_rate[dst_dpid][src_dpid] = link_loss
                loaded_edges += 1
        if loaded_edges == 0:
            return False
        print("Loaded {} loss-rate entries from {}".format(loaded_edges, file_path))
        return True
    except IOError:
        print("Could not open {}; continuing without loss-aware routing".format(file_path))
        return False


def get_min_loss_path(src, dst, first_port, final_port):
    if not loss_rate:
        return None
    print("Dijkstra's minimum loss rate path algorithm")
    print("src=", src, " dst=", dst, " first_port=", first_port, " final_port=", final_port)
    min_loss = {}
    previous = {}
    for dpid in myswitches:
        min_loss[dpid] = float("Inf")
        previous[dpid] = None
    if src not in myswitches or dst not in myswitches:
        return None
    min_loss[src] = 0
    queue = set(myswitches)
    print("Q:", queue)
    while len(queue) > 0:
        u = min(queue, key=lambda node: min_loss[node])
        if min_loss[u] == float("Inf"):
            break
        queue.remove(u)
        print("Q:", queue, "u:", u)
        for p in myswitches:
            if adjacency[u][p] is None:
                continue
            link_loss = loss_rate.get(str(u), {}).get(str(p))
            if link_loss is None:
                continue
            print("link_loss:", str(u), "->", str(p), ":", link_loss, "%")
            alt = min_loss[u] + link_loss
            if alt < min_loss[p]:
                min_loss[p] = alt
                previous[p] = u
    if src == dst:
        path = [src]
    elif previous[dst] is None:
        return None
    else:
        r = []
        p = dst
        r.append(p)
        q = previous[p]
        while q is not None:
            if q == src:
                r.append(q)
                break
            p = q
            r.append(p)
            q = previous[p]
        r.reverse()
        if not r or r[0] != src:
            return None
        path = r
    hops = []
    in_port = first_port
    for s1, s2 in zip(path[:-1], path[1:]):
        out_port = adjacency[s1][s2]
        if out_port is None or adjacency[s2][s1] is None:
            return None
        hops.append((s1, in_port, out_port))
        in_port = adjacency[s2][s1]
    hops.append((dst, in_port, final_port))
    return hops


def minimum_distance(distance, queue):
    # print("minimum_distance() is called", " distance=", distance, " Q=", queue)
    min_value = float("Inf")
    node = 0
    for value in queue:
        if distance[value] < min_value:
            min_value = distance[value]
            node = value
    return node


def get_path(src, dst, first_port, final_port):
    # Dijkstra's algorithm
    global myswitches, adjacency
    print("Dijkstra's shortest path algorithm")
    print("get_path is called, src=", src, " dst=", dst, " first_port=", first_port, " final_port=", final_port)
    distance = {}
    previous = {}
    for dpid in myswitches:
        distance[dpid] = float("Inf")
        previous[dpid] = None
    distance[src] = 0
    queue = set(myswitches)
    while len(queue) > 0:
        u = minimum_distance(distance, queue)
        queue.remove(u)
        for p in myswitches:
            if adjacency[u][p] is not None:
                weight = 1
                if distance[u] + weight < distance[p]:
                    distance[p] = distance[u] + weight
                    previous[p] = u
    r = []
    p = dst
    r.append(p)
    q = previous[p]
    while q is not None:
        if q == src:
            r.append(q)
            break
        p = q
        r.append(p)
        q = previous[p]
    r.reverse()
    path = [src] if src == dst else r
    hops = []
    in_port = first_port
    for s1, s2 in zip(path[:-1], path[1:]):
        out_port = adjacency[s1][s2]
        hops.append((s1, in_port, out_port))
        in_port = adjacency[s2][s1]
    hops.append((dst, in_port, final_port))
    return hops


class ProjectController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ProjectController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.topology_api_app = self
        self.datapaths = {}
        self.monitor_thread = hub.spawn(self._monitor)
        self.loss_aware_ready = _load_loss_rate_file()

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                # self.logger.debug('register datapath: %016x', datapath.id)
                print("register datapath:", datapath.id)
                self.datapaths[datapath.id] = datapath
        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                # self.logger.debug('unregister datapath: %016x', datapath.id)
                print("unregister datapath:", datapath.id)
                del self.datapaths[datapath.id]

    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            hub.sleep(3)

    def _request_stats(self, datapath):
        # self.logger.debug('send stats request: %016x', datapath.id)
        # print 'send stats request:', datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPFlowStatsRequest(datapath)
        datapath.send_msg(req)
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def _compute_forward_path(self, src_mac, dst_mac):
        """Pick the best available path between two hosts."""
        src_switch, src_port = mymac[src_mac]
        dst_switch, dst_port = mymac[dst_mac]
        loss_path = None
        if ENABLE_LOSS_AWARE_ROUTING and self.loss_aware_ready and loss_rate:
            loss_path = get_min_loss_path(src_switch, dst_switch, src_port, dst_port)
        if loss_path:
            return loss_path
        return get_path(src_switch, dst_switch, src_port, dst_port)

    def ls(self, obj):
        print("\n".join([x for x in dir(obj) if x[0] != "_"]))

    def add_flow(self, datapath, in_port, dst, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = datapath.ofproto_parser.OFPMatch(in_port=in_port, eth_dst=dst)
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath,
            match=match,
            cookie=0,
            command=ofproto.OFPFC_ADD,
            idle_timeout=0,
            hard_timeout=0,
            priority=ofproto.OFP_DEFAULT_PRIORITY,
            instructions=inst,
        )
        datapath.send_msg(mod)

    def install_path(self, path, ev, src_mac, dst_mac):
        print("install_path is called")
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        for sw, in_port, out_port in path:
            print(src_mac, "->", dst_mac, "via", sw, "in_port=", in_port, "out_port=", out_port)
            match = parser.OFPMatch(in_port=in_port, eth_src=src_mac, eth_dst=dst_mac)
            actions = [parser.OFPActionOutput(out_port)]
            datapath = datapath_list[sw]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            mod = datapath.ofproto_parser.OFPFlowMod(
                datapath=datapath,
                match=match,
                idle_timeout=0,
                hard_timeout=0,
                priority=1,
                instructions=inst,
            )
            datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        print("switch_features_handler is called")
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = datapath.ofproto_parser.OFPFlowMod(
            datapath=datapath,
            match=match,
            cookie=0,
            command=ofproto.OFPFC_ADD,
            idle_timeout=0,
            hard_timeout=0,
            priority=0,
            instructions=inst,
        )
        datapath.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # print "packet_in event:", ev.msg.datapath.id, " in_port:", ev.msg.match['in_port']
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match["in_port"]
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        # print("eth.ethertype=", eth.ethertype)
        # avodi broadcast from LLDP
        if eth.ethertype == 35020:
            return
        dst = eth.dst
        src = eth.src
        dpid = datapath.id
        # print("src=", src, " dst=", dst, " type=", hex(eth.ethertype))
        # print("adjacency=", adjacency)
        self.mac_to_port.setdefault(dpid, {})
        if src not in mymac.keys():
            mymac[src] = (dpid, in_port)
        if dst in mymac.keys():
            path = self._compute_forward_path(src, dst)
            if path:
                print("Path=", path)
                self.install_path(path, ev, src, dst)
                out_port = path[0][2]
            else:
                out_port = ofproto.OFPP_FLOOD
        else:
            out_port = ofproto.OFPP_FLOOD
        actions = [parser.OFPActionOutput(out_port)]
        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data
        if out_port == ofproto.OFPP_FLOOD:
            # print "FLOOD"
            while len(actions) > 0:
                actions.pop()
            for i in range(1, 23):
                actions.append(parser.OFPActionOutput(i))
            # print "actions=", actions
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data,
            )
            datapath.send_msg(out)
        else:
            # print "unicast"
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=data,
            )
            datapath.send_msg(out)

    events = [
        event.EventSwitchEnter,
        event.EventSwitchLeave,
        event.EventPortAdd,
        event.EventPortDelete,
        event.EventPortModify,
        event.EventLinkAdd,
        event.EventLinkDelete,
    ]

    @set_ev_cls(events)
    def get_topology_data(self, ev):
        print("get_topology_data() is called")
        global myswitches, adjacency, datapath_list
        switch_list = get_switch(self.topology_api_app, None)
        myswitches[:] = [switch.dp.id for switch in switch_list]
        for switch in switch_list:
            datapath_list[switch.dp.id] = switch.dp
        print("myswitches=", myswitches)
        links_list = get_link(self.topology_api_app, None)
        mylinks = [
            (link.src.dpid, link.dst.dpid, link.src.port_no, link.dst.port_no)
            for link in links_list
        ]
        for s1, s2, port1, port2 in mylinks:
            adjacency[s1][s2] = port1
            adjacency[s2][s1] = port2
            print(s1, ":", port1, "<--->", s2, ":", port2)

