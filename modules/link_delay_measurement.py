# -*- coding: utf-8 -*-
"""
Link Delay Measurement - 從 DTM.py 抽出的延遲計算模組
保持原本的命名與邏輯，直接取用 DTM 中的全域變數和函式
    """



import time

class Link_Delay_Measurement:
    def __init__(self, app):
        self.app = app
    # 暫存的鏈路延遲測量值（保持 DTM 原本的全域變數名稱）
        self.temp_lldp_link_delay = {}
        self.temp_echo_link_delay = {}

        # 最終的延遲記錄
        self.link_delay = {}


    def update_link_delay(self, switch_a, switch_b, delay):
        """更新延遲紀錄"""
        try:
            self.link_delay[(switch_a, switch_b)] = float(delay)
        except Exception as e:
            print(f"[ERROR] update_link_delay 失敗: {e}")


    def get_link_delay(self, switch_a, switch_b):
        """取得延遲紀錄"""
        try:
            return self.link_delay[(switch_a, switch_b)]
        except Exception as e:
            print(f"[ERROR] get_link_delay 失敗: {e}")
            return None


    def _init_pair_state(self, switch_a, switch_b):
        """初始化某對 switch 的量測暫存狀態"""
        try:
            self.temp_lldp_link_delay[(switch_a, switch_b)] = 0
            self.temp_lldp_link_delay[(switch_b, switch_a)] = 0
            self.temp_echo_link_delay[(switch_a, switch_b)] = 0
            self.temp_echo_link_delay[(switch_b, switch_a)] = 0
        except Exception as e:
            print(f"[ERROR] _init_pair_state 失敗: {e}")


    def handle_lldp_reply(self, switch_a, switch_b):
        """處理 LLDP 回覆（在 packet_in handler 中呼叫）"""
        try:
            #print(f"*** [DEBUG] handle_lldp_reply 被呼叫: ({switch_a}, {switch_b})")
            key = (switch_a, switch_b)
            if key in self.temp_lldp_link_delay and self.temp_lldp_link_delay[key] < 0:
                result  = self.temp_lldp_link_delay[key] + (time.time() * 1000)
                if result < 500:  # 只接受 500ms 內的回覆
                    self.temp_lldp_link_delay[key] = result
                else:
                    self.temp_lldp_link_delay[key] = 0  # 太舊，歸零視為未收到            
        except Exception as e:
            print(f"[ERROR] handle_lldp_reply 失敗: {e}")


    def handle_echo_reply(self, dpid):
        """處理 Echo 回覆（在 echo_reply_handler 中呼叫）"""
        try:
            for key in list(self.temp_echo_link_delay.keys()):
                if key[0] == dpid and self.temp_echo_link_delay[key] < 0:
                    result = self.temp_echo_link_delay[key] + (time.time() * 1000)
                    if result < 500:  # 只接受 500ms 內的回覆
                        self.temp_echo_link_delay[key] = result
                    else:
                        self.temp_echo_link_delay[key] = 0  # 太舊，歸零視為未收到
        except Exception as e:
            print(f"[ERROR] handle_echo_reply 失敗: {e}")

    def measure_pair_delay(self, switch_a, switch_b, send_lldp_func, send_echo_func, sleep_func, max_retry=3):
        """
        量測 switch_a 與 switch_b 之間的延遲
        對應 DTM 中的 _switch_to_switch_delay_count() 邏輯
        
        Args:
            switch_a: 源 switch DPID
            switch_b: 目標 switch DPID
            send_lldp_func: 發送 LLDP 的函式 (switch_a, switch_b) 無回傳值
            send_echo_func: 發送 Echo 的函式 (switch_a, switch_b) 無回傳值
            sleep_func: 睡眠函式 (通常是 hub.sleep)
            max_retry: 最大重試次數
        """
        
        try:
            MAX_RETRY = max_retry
            
            for retry in range(MAX_RETRY):
                delay = 0
                
                for i in range(3):
                    try:
                        sleep_time = 0
                        self._init_pair_state(switch_a, switch_b)
                        
                        # 發送探測封包，記錄發送時間
                        send_lldp_func(switch_a, switch_b)
                        send_lldp_func(switch_b, switch_a)
                        send_echo_func(switch_a, switch_b)
                        send_echo_func(switch_b, switch_a)
                        
                        sleep_func(0.05)
                        #print(f"[DELAY] ({switch_a},{switch_b}) lldp_ab={self.temp_lldp_link_delay[(switch_a,switch_b)]:.1f} lldp_ba={self.temp_lldp_link_delay[(switch_b,switch_a)]:.1f} echo_ab={self.temp_echo_link_delay[(switch_a,switch_b)]:.1f} echo_ba={self.temp_echo_link_delay[(switch_b,switch_a)]:.1f}", flush=True)

                        # 在發送後立即記錄時刻（減去時間戳記）
                        # ← 時間戳記錄應該在 send_lldp_func 內部做，不是在這裡！
                        #self.temp_lldp_link_delay[(switch_a, switch_b)] = self.temp_lldp_link_delay[(switch_a, switch_b)] - (time.time() * 1000)
                        #self.temp_lldp_link_delay[(switch_b, switch_a)] = self.temp_lldp_link_delay[(switch_b, switch_a)] - (time.time() * 1000)
                        #self.temp_echo_link_delay[(switch_a, switch_b)] = self.temp_echo_link_delay[(switch_a, switch_b)] - (time.time() * 1000)
                        #self.temp_echo_link_delay[(switch_b, switch_a)] = self.temp_echo_link_delay[(switch_b, switch_a)] - (time.time() * 1000)
                        #print(self.temp_lldp_link_delay[(switch_a, switch_b)], self.temp_lldp_link_delay[(switch_b, switch_a)], self.temp_echo_link_delay[(switch_a, switch_b)], self.temp_echo_link_delay[(switch_b, switch_a)])
                        
                        # 等待回復
                        ''' 晚點修復，先看看這樣的邏輯是否能正常運作
                        while (self.temp_lldp_link_delay[(switch_a, switch_b)] <= 0 or
                            self.temp_echo_link_delay[(switch_a, switch_b)] <= 0 or
                            self.temp_lldp_link_delay[(switch_b, switch_a)] <= 0 or
                            self.temp_echo_link_delay[(switch_b, switch_a)] <= 0):
                            print(self.temp_lldp_link_delay[(switch_a, switch_b)], self.temp_lldp_link_delay[(switch_b, switch_a)], self.temp_echo_link_delay[(switch_a, switch_b)], self.temp_echo_link_delay[(switch_b, switch_a)])
                            
                            sleep_func(0.1)
                            sleep_time += 0.1
                            if sleep_time >= 1:
                                if i >= 2:
                                    print(f"*** Timeout: {switch_a} <-> {switch_b}")
                                else:
                                    print(f"*** Retry measure: {switch_a} <-> {switch_b}")
                                break
                        
                        if sleep_time >= 1:
                            sleep_func(0.5)
                            continue
                        '''
                        # 計算雙向平均延遲（與 DTM 相同邏輯）
                        delay = (self.temp_lldp_link_delay[(switch_a, switch_b)]
                                + self.temp_lldp_link_delay[(switch_b, switch_a)]
                                - self.temp_echo_link_delay[(switch_a, switch_b)]
                                - self.temp_echo_link_delay[(switch_b, switch_a)]) / 2
                    except Exception as e:
                        print(f"[ERROR] measure_pair_delay 內迴圈失敗: {e}")
                        continue
                
                if delay > -1: # ← 允許微小的負值誤差
                    break
                else:
                    print(f"*** delay <= 0 ({delay:.2f}) {switch_a} <-> {switch_b}，重試第 {retry+1} 次")
                    sleep_func(0.5)
            
            if delay > -1:
                self.update_link_delay(switch_a, switch_b, delay)
                self.update_link_delay(switch_b, switch_a, delay)
            else:
                print(f"*** 重試 {MAX_RETRY} 次後仍失敗，保留上一次的值")
        except Exception as e:
            print(f"[ERROR] measure_pair_delay 失敗: {e}")
