'''

來源 k_short.txt

host_a |host_b |編號| cost |switch路徑
00:00:00:00:00:16  00:00:00:00:00:01  0  585  [19,13,3,1,5,25]

目的：
使用 k_short.txt，取代 Dijkstra，直接將流量分配到 k_short，看哪條路徑符合需求

理論上，只會用到 host_a, host_b, switch路徑 這三個欄位
'''

'''
來源 link_status.py

def get_all_link_status():
    """
    取得所有 link 的狀態
    
    Returns:
        dict: {(src_dpid, dst_dpid): {'status': status, 'usage_percent': percent}}
    """
    return dict(link_status_map)


'''

'''
這個演算法，是以 k-short 為底子，偵測 k 個 link 的狀態，然後去分配流量
透過 get_all_link_status() 取得所有 link 的狀態
演算法會將流量分成 5 個狀態，SN,S0,S1,S2,S3
SN: 0-1% (因為可能會有極小的流量，如LLDP，所以將 0-1% 定義為 SN，視為無流量的 link)
S0: 1-20% (LOW)
S1: 20-60% (NORMAL)
S2: 60-80% (HIGH)
S3: 80-100% (OVERLOAD)

'''

'''
當有 LOW 的 link 時，會優先考慮將 LOW 的流量分配到 NORMAL 的 link
目的是減少整體的 link 使用率，以達到節能的效果
'''

'''
當有 Overload 的 link 時，會優先考慮將 OVERLOAD 的流量分配到 NORMAL 的 link
目的是提高 route 的 QoS，減少 packet loss 的情況
'''

'''
High 的 link 是一種緩衝設計，避免 Overload 的 link 在分流時，出現乒乓效應
所以 High 的 link，不參與接受流量，也不參與分流
'''

'''
當有新的流量需求時，演算法會先檢查 k-short 的路徑，看看路徑上的 link 狀態

1.先判斷有沒有已開啟路徑
(所以要有一個機制，可以判斷 k-short 的路徑，是否已經有流量在使用)
(但必須撇出 OVERLOAD 的 link，因為 OVERLOAD 的 link 是不參與分流的)
(論文是這樣說，但我覺得設計上，HIGH 的 link 也不應該參與分流)

2.如果有已完全開啟路徑，從已開啟路徑中，尋找路徑
(我認為這邊有幾種不同的實作可能性，所以要保留判斷路徑的彈性)

3.如果沒有已完全開啟路徑，從 k-short 的路徑中，尋找路徑
(開啟比例越高的路徑，優先考慮分配流量)

4.如果 k-short 的路徑中，都沒有符合的路徑，則將 OVERLOAD 的 link 加入分流的考慮範圍
'''

'''
def 定期偵測 link 狀態:
    while True:
        獲得所有 link 狀態
        若有 LOW, OVERLOAD 的 link:
            重新分配有經過該 link 的流量(dpid_a, dpid_b)
        sleep (n秒)

'''

from ryu.lib import hub
from .link_status import Link_Status
from .routing_base import RoutingBase
import random
import time

class Routing_DTM_2020(RoutingBase):
    def __init__(self, app):
        self.app = app
        self.link_status = app.link_status
        # 直接從 app 取得 link_status 模組的引用，避免重複初始化
        self.k_short_paths = {}

        self.load_k_short_paths('data/k_short.txt')
    # ===== 模組初始化 =====
    # 啟動時讀取 k_short.txt


    '''
    def k_short 的路徑開啟狀態:
        #k-short 有路徑欄位，如[24,15,3,1,11,40]
        #透過 get_all_link_status() 取得所有 link 的狀態
        #檢查順序，(24-15)流量多少，(15-3)流量多少，(3-1)流量多少，(1-11)流量多少，(11-40)流量多少
        #如果有0-1%的 link，則整條路徑視為 SN，SN 的 counter 加 1
        #理論上來說，全啟動的路徑，SN 的conunter 是 0，可以以此來判斷
        #假如沒有全啟動的路徑，則以 SN 的 counter 來判斷，SN 越小，代表需要開啟的 link 越少，則優先考慮分配流量
        #(這裡的設計是用 link來判斷，用switch呢？雖然會複雜很多就是了)
        
        for 路徑 in k_short 的路徑:
            for link in 路徑 的路徑:
                Hop_counter ++
                if link 的狀態是 SN:
                    SN_counter ++
                if link 的狀態是 OVERLOAD:
                    先不考慮這條路徑
        SN 越小，越優先
        相同 SN 的話，Hop 越小，越優先
        SN 與 Hop 都相同的話，隨機選一條路徑(隨機的機制要可彈性，之後可能會變動)
        if 有路徑:
            return 選出的唯一路徑
        else:
            考慮含有 OVERLOAD 的 link 的路徑
            SN 越小，越優先
            相同 SN 的話，Hop 越小，越優先
            SN 與 Hop 都相同的話，隨機選一條路徑(隨機的機制要可彈性，之後可能會變動)
        if 有路徑:
            return 選出的唯一路徑
        else:
            return 沒有路徑
    '''




    def find_reroute_path(self, host_a, host_b, remove_path=None, retrans_path=None):
        """根據 link 狀態選擇最適合的 k-short 路徑"""
        
        all_link_status = self.link_status.get_all_link_status()
        
        if (host_a, host_b) not in self.k_short_paths:
            print(f"[k_short_path_status] 沒有 k-short 路徑: {host_a} -> {host_b}")
            return None
        
        paths = self.k_short_paths[(host_a, host_b)]
        
        # 如果指定了要排除的路徑，就從候選中移除
        if remove_path:
            paths = [p for p in paths if p != remove_path]
        
        if not paths:
            print(f"[k_short_path_status] 沒有可用的 k-short 路徑: {host_a} -> {host_b}")
            return None
        
        # 第一輪：不考慮 OVERLOAD link 的路徑
        valid_paths = []
        
        for path in paths:
            hop_counter = 0
            sn_counter = 0
            has_overload = False
            
            for i in range(len(path) - 1):
                link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                hop_counter += 1

                link_info = all_link_status.get(link, {})
                status = link_info.get('status', 'SN')

                if status == 'SN':
                    sn_counter += 1
                elif status == 'OVERLOAD':
                    has_overload = True
                    break
            
            if not has_overload:
                valid_paths.append((sn_counter, hop_counter, path))
            
        
        # 如果有找到路徑，按 SN、Hop 排序後選擇
        if valid_paths:
            valid_paths.sort(key=lambda x: (x[0], x[1]))
            best_sn = valid_paths[0][0]
            best_hop = valid_paths[0][1]
            
            # 找出所有 SN 和 Hop 都相同的路徑
            candidates = [p for p in valid_paths if p[0] == best_sn and p[1] == best_hop]
            
            if retrans_path and any(p[2] == retrans_path for p in candidates):
                return None  # 如果重傳路徑在候選中，則不選擇任何路徑
            
            return random.choice(candidates)[2]
        
        # 第二輪：考慮含有 OVERLOAD link 的路徑
        valid_paths_with_overload = []
        
        for path in paths:
            hop_counter = 0
            sn_counter = 0
            
            for i in range(len(path) - 1):
                link = (min(path[i], path[i + 1]), max(path[i], path[i + 1]))
                hop_counter += 1

                link_info = all_link_status.get(link, {})
                status = link_info.get('status', 'SN')

                if status == 'SN':
                    sn_counter += 1
            
            valid_paths_with_overload.append((sn_counter, hop_counter, path))
        
        if valid_paths_with_overload:
            valid_paths_with_overload.sort(key=lambda x: (x[0], x[1]))
            best_sn = valid_paths_with_overload[0][0]
            best_hop = valid_paths_with_overload[0][1]
            
            candidates = [p for p in valid_paths_with_overload if p[0] == best_sn and p[1] == best_hop]
            
            if retrans_path and any(p[2] == retrans_path for p in candidates):
                return None  # 如果重傳路徑在候選中，則不選擇任何路徑        
            return random.choice(candidates)[2]
        
        return None

    '''
    def 當有新流量加入時呼叫:
        獲得 k-short 的路徑()
        k_short 的路徑開啟狀態()
        if 有回應路徑:
            return 路徑
        else:
            return 沒有路徑

    '''

    def find_path_for_new_flow(self, host_a, host_b):
        """當有新流量加入時呼叫"""
        path = self.find_reroute_path(host_a, host_b)
        
        if path:
            #print(f"[2020 Routing] 選擇路徑: {host_a} -> {host_b}, 路徑: {path}")
            self.app.add_active_flow(host_a, host_b, path)
            return path
        else:
            #print(f"[2020 Routing] 沒有可用路徑: {host_a} -> {host_b}")
            return None
        

    def load_k_short_paths(self, filepath='data/k_short.txt'):
        """
        讀取 k_short.txt 並加載到 k_short_paths 全局變數
        格式：每行可能包含多條路徑，每條路徑佔 5 個欄位：
              host_a  host_b  編號  cost  [switch路徑]
        """
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split()
                    i = 0
                    while i + 4 < len(parts):
                        host_a = parts[i]
                        host_b = parts[i + 1]
                        # parts[i+2] = index, parts[i+3] = cost（不需要使用）
                        path_str = parts[i + 4].strip('[]')
                        switch_path = [int(x) for x in path_str.split(',')]

                        if (host_a, host_b) not in self.k_short_paths:
                            self.k_short_paths[(host_a, host_b)] = []
                        self.k_short_paths[(host_a, host_b)].append(switch_path)

                        i += 5

            print(f"[k_short] 成功加載 {len(self.k_short_paths)} 個 (host_a, host_b) 對的 k-shortest paths")

        except FileNotFoundError:
            print(f"[k_short] 找不到檔案: {filepath}")
        except Exception as e:
            print(f"[k_short] 解析 k_short.txt 時出錯: {e}")


    # ===== 模組初始化 =====
    # 在模組被導入時自動加載 k_short.txt


        