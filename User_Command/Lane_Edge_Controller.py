# # 檔名: controller.py (決策中心 C)
# # 功能: 接收外部指令，整合即時車輛狀態，呼叫專家計算，並發布最終行動方案。

# import os
# import sys
# import queue
# import threading
# import json
# import time
# import paho.mqtt.client as mqtt

# # --- 路徑設定，確保能找到 computing 模組 ---
# # 假設 controller.py 和 computing.py 在同一個資料夾
# script_dir = os.path.dirname(os.path.abspath(__file__))
# if script_dir not in sys.path:
#     sys.path.insert(0, script_dir)

# # --- 導入我們的計算專家 ---
# # 假設計算核心的檔名是 computing.py，裡面的類別是 Computing
# try:
#     from Computing import Computing
# except ImportError:
#     print("[決策中心 C] [錯誤] 找不到 'computing.py' 或裡面的 'Computing' 類別。")
#     sys.exit(1)


# # --- MQTT 設定 ---
# BROKER_ADDRESS = "127.0.0.1"
# BROKER_PORT = 7883
# COMMAND_TOPIC = "commands/vehicle/#"  # 訂閱：來自 cli.py 的原始指令
# STATE_TOPIC = "vehicle/state/#"       # 訂閱：來自 retrive_vehicle_pos.py 的即時狀態
# ACTION_TOPIC = "traci_actions"        # 發布：給 retrive_vehicle_pos.py 的最終指令

# # 【注意】請確認此路徑是否與你的地圖檔路徑相符
# NET_FILE = "/home/paul/sumo_platform/testbed/testbed/traffic_simulation/new_osm.net.xml"
# if not os.path.exists(NET_FILE):
#     print(f"[決策中心 C] [錯誤] 找不到地圖檔案: {NET_FILE}")
#     sys.exit(1)

# # --- 全域變數 ---
# # 存放從 cli.py 收到的原始指令
# cmd_queue = queue.Queue()
# # 存放從 retrive_vehicle_pos.py 收到的車輛即時狀態
# vehicle_states = {}


# # --- MQTT 訊息處理函式 ---
# def _on_message(client, _userdata, msg):
#     """
#     總訊息處理函式，會根據主題判斷訊息類型並分派。
#     """
#     # 判斷是否為原始指令
#     if mqtt.topic_matches_sub(COMMAND_TOPIC, msg.topic):
#         try:
#             data = json.loads(msg.payload)
#             veh_id = msg.topic.split('/')[-1]
#             # 把 (車輛ID, 指令內容, MQTT客戶端實例) 放進佇列
#             cmd_queue.put((veh_id, data, client))
#         except json.JSONDecodeError:
#             pass # 忽略格式錯誤的訊息
    
#     # 判斷是否為車輛狀態更新
#     elif mqtt.topic_matches_sub(STATE_TOPIC, msg.topic):
#         try:
#             veh_id = msg.topic.split('/')[-1]
#             # 更新該車輛的即時狀態
#             vehicle_states[veh_id] = json.loads(msg.payload)
#         except json.JSONDecodeError:
#             pass # 忽略格式錯誤的訊息


# def _worker(net_file_path: str):
#     """
#     幕僚執行緒：核心邏輯所在，不斷地從佇列中取出任務來處理。
#     """
#     # 建立一個計算專家 (Computing) 的實例
#     lec = Computing(net_file_path)
#     print("[決策中心 C] 專案經理已就位，等待指令...")

#     while True:
#         # 從佇列中取得任務，如果沒有任務會在這裡暫停等待
#         veh_id, data, client = cmd_queue.get()
#         print(f"[決策中心 C] 經理正在處理任務: {data.get('cmd')} for {veh_id}")
        
#         try:
#             command = data.get("cmd")
#             if not command:
#                 continue
            
#             action = None # 初始化行動指令為空

#             # --- 處理換道指令 ---
#             if command == "change_lane":
#                 lane_index = data.get("lane_index")
#                 duration = data.get("duration", 6) # 如果沒給持續時間，預設為6秒
#                 if lane_index is not None:
#                     # 直接呼叫專家產生標準的換道指令書
#                     action = lec.plan_change_lane(veh_id, int(lane_index), int(duration))

#             # --- 處理換路段指令 ---
#             elif command == "change_edge":
#                 target_edge = data.get("edge_id")
                
#                 # --- 耐心等待情報的邏輯 ---
#                 max_wait_time = 2  # 最長等待 2 秒
#                 wait_interval = 0.2 # 每 0.2 秒檢查一次
#                 waited_time = 0
#                 current_state = vehicle_states.get(veh_id)
                
#                 # 如果小本本裡還沒有這台車的資料，就開始等待
#                 while not current_state and waited_time < max_wait_time:
#                     # print(f"[決策中心 C] 經理正在等待車輛 {veh_id} 的即時狀態...")
#                     time.sleep(wait_interval)
#                     waited_time += wait_interval
#                     current_state = vehicle_states.get(veh_id)

#                 # --- 拿到情報後，開始規劃 ---
#                 if target_edge and current_state:
#                     current_edge = current_state.get("roadID")
#                     final_destination = current_state.get("final_destination")
                    
#                     if current_edge and final_destination:
#                         # 呼叫專家規劃智慧銜接路線
#                         action = lec.plan_change_edge(veh_id, current_edge, target_edge, final_destination)
#                     else:
#                         print(f"  [警告] 車輛 {veh_id} 的狀態情報不完整，無法規劃路徑。")
#                 else:
#                     # 【任務重排版】如果等待逾時，不要放棄，把任務放回佇列尾端再試一次
#                     print(f"  [提示] 等待逾時，暫時無法取得 {veh_id} 的狀態，稍後重試。")
#                     cmd_queue.put((veh_id, data, client)) # 放回佇列

#             # --- 如果成功產生了行動指令，就發布出去 ---
#             if action:
#                 action_payload = json.dumps(action)
#                 client.publish(ACTION_TOPIC, action_payload, qos=1)
#                 print(f"  [發布] 已將施工藍圖發布到 {ACTION_TOPIC}")

#         except Exception as exc:
#             print(f"[決策中心 C] [嚴重錯誤] 處理指令時發生未預期的錯誤: {exc}")


# if __name__ == "__main__":
#     # 建立並啟動在背景運作的幕僚執行緒
#     # args=(NET_FILE,) 後面的逗號是必要的，表示這是一個單一元素的元組
#     threading.Thread(target=_worker, args=(NET_FILE,), daemon=True).start()

#     # 建立主 MQTT 客戶端
#     client = mqtt.Client(client_id="command_controller_main", protocol=mqtt.MQTTv311)
#     client.on_message = _on_message
    
#     try:
#         client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
#     except ConnectionRefusedError:
#         print(f"[決策中心 C] [錯誤] 無法連線到 MQTT Broker ({BROKER_ADDRESS}:{BROKER_PORT})。請先啟動 Broker。")
#         sys.exit(1)

#     # 一次訂閱兩個主題：指令 和 狀態更新
#     client.subscribe([(COMMAND_TOPIC, 1), (STATE_TOPIC, 0)])
#     print(f"[決策中心 C] 已訂閱主題: {COMMAND_TOPIC} 和 {STATE_TOPIC}")
    
#     # 進入無限迴圈，專心監聽訊息
#     client.loop_forever()







#newnew

# 檔名: Lane_Edge_Controller.py (決策中心 C) - 【自動重試升級版】
# 功能: 當情報請求逾時，不再直接放棄，而是會自動將任務放回佇列，稍後重試。

import os
import sys
import queue
import threading
import json
import time
import paho.mqtt.client as mqtt

# --- 路徑與模組導入 (保持不變) ---
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)
try:
    from Computing import Computing
except ImportError:
    #print("[C] [錯誤] 找不到 'Computing.py' 或裡面的 'Computing' 類別。")
    sys.exit(1)



# --- MQTT 設定 (保持不變) ---
BROKER_ADDRESS = "127.0.0.1"
BROKER_PORT = 7883
COMMAND_TOPIC = "commands/vehicle/#"
STATE_REQUEST_TOPIC = "vehicle/state/request"
STATE_RESPONSE_TOPIC = "vehicle/state/response/#"
ACTION_TOPIC = "traci_actions"
HANDSHAKE_TOPIC = "system/handshake"



# 地圖檔路徑 (請確認)
NET_FILE = "/home/paul/sumo_platform/testbed/testbed/traffic_simulation/new_osm.net.xml"
if not os.path.exists(NET_FILE):
    print(f"[C] [錯誤] 找不到地圖檔案: {NET_FILE}")
    sys.exit(1)



# --- 全域變數 (保持不變) ---
cmd_queue = queue.Queue()
vehicle_states = {}
executor_is_ready = False



# --- MQTT 訊息處理函式 (保持不變) ---
def _on_message(client, _userdata, msg):
    global executor_is_ready
    if mqtt.topic_matches_sub(COMMAND_TOPIC, msg.topic):
        try:
            data = json.loads(msg.payload)
            veh_id = msg.topic.split('/')[-1]
            cmd_queue.put((veh_id, data, client))
        except json.JSONDecodeError: pass
    elif mqtt.topic_matches_sub(STATE_RESPONSE_TOPIC, msg.topic):
        try:
            veh_id = msg.topic.split('/')[-1]
            vehicle_states[veh_id] = json.loads(msg.payload)
        except json.JSONDecodeError: pass
    elif msg.topic == HANDSHAKE_TOPIC:
        try:
            handshake_data = json.loads(msg.payload)
            if handshake_data.get("status") == "executor_ready":
                print("[握手] 確認系統已連線！")
                executor_is_ready = True
        except json.JSONDecodeError: pass

def _worker(net_file_path: str):
    """幕僚執行緒：核心決策邏輯。"""
    lec = Computing(net_file_path)
    print("[C](請求-回應模式)。")

    while True:
        veh_id, data, client = cmd_queue.get()
        print(f"[C] 正在處理任務: {data.get('cmd')} for {veh_id}")
        
        try:
            command = data.get("cmd")
            if not command: continue
            
            action = None
            if command == "change_lane":
                lane_index = data.get("lane_index")
                duration = data.get("duration", 6)
                if lane_index is not None:
                    action = lec.plan_change_lane(veh_id, int(lane_index), int(duration))

            elif command == "change_edge":
                target_edge = data.get("edge_id")
                
                # 【關鍵改動】取得或初始化重試次數
                retry_count = data.get("retry_count", 0)

                # 發出請求的邏輯保持不變，但只在第一次嘗試時發出
                if retry_count == 0:
                    print(f"  [請求] 對 {veh_id} 請求...")
                    request_payload = json.dumps({"veh_id": veh_id})
                    client.publish(STATE_REQUEST_TOPIC, request_payload, qos=1)

                max_wait_time = 3
                wait_interval = 0.1
                waited_time = 0
                current_state = vehicle_states.get(veh_id)
                
                while not current_state and waited_time < max_wait_time:
                    time.sleep(wait_interval)
                    waited_time += wait_interval
                    current_state = vehicle_states.get(veh_id)

                if target_edge and current_state:
                    current_edge = current_state.get("roadID")
                    final_destination = current_state.get("final_destination")
                    
                    if current_edge and final_destination:
                        action = lec.plan_change_edge(veh_id, current_edge, target_edge, final_destination)
                    else:
                        print(f"  [警告] 收到的車輛 {veh_id} 狀態不完整。")
                    
                    if veh_id in vehicle_states:
                        del vehicle_states[veh_id] 
                else:
                    # 【關鍵改動】如果逾時，執行自動重試邏輯
                    if retry_count < 5: # 最多重試 5 次
                        print(f"  [提示] 對 {veh_id} 的情報回應超時，將自動重試 (第 {retry_count + 1} 次)...")
                        # 更新重試次數
                        data["retry_count"] = retry_count + 1
                        # 將任務放回佇列，稍後再試
                        cmd_queue.put((veh_id, data, client))
                    else:
                        print(f"  [錯誤] 對 {veh_id} 的情報請求重試多次後仍然失敗。")

            if action:
                action_payload = json.dumps(action)
                client.publish(ACTION_TOPIC, action_payload, qos=1)
                print(f"  [發布] 已將施工藍圖發布到 {ACTION_TOPIC}")

        except Exception as exc:
            print(f"[C] [嚴重錯誤] 處理指令時發生未預期的錯誤: {exc}")


if __name__ == "__main__":
    # (主程式的握手邏輯保持不變)
    threading.Thread(target=_worker, args=(NET_FILE,), daemon=True).start()

    client = mqtt.Client(client_id="command_controller_main", protocol=mqtt.MQTTv311)
    client.on_message = _on_message
    
    try:
        client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
    except ConnectionRefusedError:
        print(f"[C] [錯誤] 無法連線到 MQTT Broker。")
        sys.exit(1)

    client.subscribe([(COMMAND_TOPIC, 1), (STATE_RESPONSE_TOPIC, 1), (HANDSHAKE_TOPIC, 1)])
    client.loop_start() 
    
    #print("[握手] ，等待確認...")
    handshake_payload = json.dumps({"status": "controller_ready"})
    client.publish(HANDSHAKE_TOPIC, handshake_payload, qos=1)
    
    handshake_timeout = 10
    wait_start_time = time.time()
    while not executor_is_ready:
        time.sleep(0.5)
        if time.time() - wait_start_time > handshake_timeout:
            print("[握手] [錯誤] 等待執行官確認超時，程式即將結束。")
            sys.exit(1)

    print("--- C，可以開始接收指令 ---")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[C] 正在關閉...")
        client.loop_stop()
