

# --- 導入區 (整合新舊功能所需的所有模組) ---
import os
import sys
import queue
import json
import time
import paho.mqtt.client as mqtt

# 【原始功能】導入你原有的自訂模組
from Vehicle import Vehicle
from garbage_collector import garbage_collector
from Vehicle_dispatcher import Vehicle_dispatcher

# 【共同部分】導入 SUMO 的 TraCI 函式庫
if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("please declare environment variable 'SUMO_HOME'")
import traci

# ============================================================
# 【新增功能】的全域設定與函式
# ============================================================
BROKER_ADDRESS = "127.0.0.1"
BROKER_PORT = 7883
ACTION_TOPIC = "traci_actions"
STATE_REQUEST_TOPIC = "vehicle/state/request"
STATE_RESPONSE_TOPIC_PREFIX = "vehicle/state/response/"
# 【新】新增用於啟動時「握手」的主題
HANDSHAKE_TOPIC = "system/handshake" # 指定topic做某一件事 ()
actions_queue = queue.Queue()

def _on_collab_message(client, _userdata, msg):
    """【新增功能】的總回呼函式，負責處理「最終指令」、「情報請求」和「握手」"""
    # 判斷是否為最終行動指令
    if msg.topic == ACTION_TOPIC:
        try:
            action = json.loads(msg.payload)
            action['retry_count'] = 0
            actions_queue.put(action)
        except json.JSONDecodeError: return
    
    # 判斷是否為情報請求
    elif msg.topic == STATE_REQUEST_TOPIC:
        try:
            request_data = json.loads(msg.payload)
            veh_id_to_find = request_data.get("veh_id")
            if not veh_id_to_find: return

            if veh_id_to_find in traci.vehicle.getIDList():
                laneID = traci.vehicle.getLaneID(veh_id_to_find)
                roadID = traci.lane.getEdgeID(laneID) if laneID and not laneID.startswith(':') else ""
                original_route = traci.vehicle.getRoute(veh_id_to_find)
                final_destination = original_route[-1] if original_route else ""
                
                state_info = {"roadID": roadID, "final_destination": final_destination}
                
                response_topic = STATE_RESPONSE_TOPIC_PREFIX + veh_id_to_find
                client.publish(response_topic, json.dumps(state_info), qos=1)
        except (json.JSONDecodeError, traci.TraCIException):
            return

    # 【新】增加處理握手協議的邏輯
    elif msg.topic == HANDSHAKE_TOPIC:
        try:
            handshake_data = json.loads(msg.payload)
            # 如果收到來自決策中心的「準備好了」訊息
            if handshake_data.get("status") == "controller_ready":
                print("[握手] 收到來自決策中心的準備信號，回傳確認訊息...")
                # 立刻回傳一個「我也好了」的確認訊息
                ack_payload = json.dumps({"status": "executor_ready"})
                client.publish(HANDSHAKE_TOPIC, ack_payload, qos=1)
        except json.JSONDecodeError:
            pass


# ============================================================
# 【原始功能】的函式 (保持不變)
# ============================================================
def retrieve_SUMO_vehicle_info(traci, veh_id):
    # ... (此處程式碼與你提供的一樣，保持不變)
    x, y = traci.vehicle.getPosition(veh_id)
    lon, lat = traci.simulation.convertGeo(x, y)
    laneID = traci.vehicle.getLaneID(veh_id)
    vehicleLength = traci.vehicle.getLength(veh_id)
    lanePosition = traci.vehicle.getLanePosition(veh_id)
    speed = traci.vehicle.getSpeed(veh_id) * 3.6
    laneAngle = traci.lane.getAngle(laneID)
    laneLength = traci.lane.getLength(laneID)
    travelTime = traci.lane.getTraveltime(laneID)
    connectedLanes = []
    if laneID.startswith(":"):
        for ln in traci.lane.getLinks(laneID, False):
            connectedLanes.append(ln[0])
    geofenceInfo = dict(lat=lat, lon=lon, laneID=laneID, width=laneLength/3, 
                laneAngle=laneAngle, speed=speed, travelTime=travelTime, 
                lanePosition=lanePosition, vehicleLength=vehicleLength, 
                connectedLanes=connectedLanes)
    return geofenceInfo

# ============================================================
# 主程式進入點
# ============================================================
if __name__ == '__main__':
    
    # --- 【原始功能】的初始化 (完整保留並啟用) ---
    print(" 正在初始化 Vehicle Dispatcher...")
    Vehicle_dispatcher = Vehicle_dispatcher()
    computers = dict(pc1='127.0.0.1')
    Vehicle_dispatcher.physicalComputers = computers
    pc_list = list(Vehicle_dispatcher.physicalComputers.keys())
    Vehicle_dispatcher.connect('localhost', 7884)
    print("Vehicle Dispatcher 已連線至 port 7884。")

    # --- 【新增功能】的初始化 ---
    print("正在初始化協作 MQTT 客戶端 (請求-回應模式)...")
    collab_client = mqtt.Client(client_id="sumo_executor_collab_final_rq_hs", protocol=mqtt.MQTTv311)
    collab_client.on_message = _on_collab_message
    try:
        collab_client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
    except ConnectionRefusedError:
        print(f"[錯誤] 無法連線到 MQTT Broker ({BROKER_ADDRESS}:{BROKER_PORT})。")
        sys.exit(1)
    
    # 【新】訂閱最終指令、情報請求、以及握手主題
    collab_client.subscribe([(ACTION_TOPIC, 1), (STATE_REQUEST_TOPIC, 1), (HANDSHAKE_TOPIC, 1)])
    collab_client.loop_start()
    print(f"已訂閱主題: {ACTION_TOPIC}, {STATE_REQUEST_TOPIC}, {HANDSHAKE_TOPIC}")

    # --- SUMO 啟動 (共同) ---
    sumoBinary = "/usr/local/bin/sumo-gui"
    sumocfg = "/home/paul/sumo_platform/testbed/traffic_simulation/osm.sumocfg.xml"
    if not (os.path.exists(sumoBinary) and os.path.exists(sumocfg)):
        print(f"[錯誤] 請確認 SUMO 執行檔或設定檔路徑。")
        sys.exit(1)
    sumoCmd = [sumoBinary, "-c", sumocfg, "-d", "1000", "-S", "--ignore-route-errors"]
    traci.start(sumoCmd)
    print("SUMO 模擬已啟動!")

    # --- 【原始功能】的變數初始化 (完整保留並啟用) ---
    vehicleDict = {}
    current_simulation_step = 0
    steps = {}
    event_occur_steps = set()
    geofenceInfos = {}
    publish_period = 5
    i = 0

    # ============================================================
    # 主模擬迴圈 (新舊功能並行運作)
    # ============================================================
    while traci.simulation.getMinExpectedNumber() > 0:

        # === 【新增功能】模組 1: 執行 Lane_Edge_Controller.py 發來的最終指令 ===
        # (此段邏輯保持不變)
        if not actions_queue.empty():
            act = actions_queue.get_nowait()
            try:
                veh_id = act.get("veh_id")
                if veh_id in traci.vehicle.getIDList() and not traci.vehicle.getLaneID(veh_id).startswith(':'):
                    if act.get("type") == "change_lane":
                        traci.vehicle.changeLane(veh_id, act["lane_index"], act["duration"])
                        print(f"[新增功能] 指令成功: {veh_id} 已執行 change_lane。")
                    elif act.get("type") == "change_route":
                        traci.vehicle.setRoute(veh_id, act["edge_list"])
                        print(f"指令成功: {veh_id} 路線已設定。")
                elif veh_id in traci.vehicle.getIDList():
                    if act['retry_count'] < 10:
                        act['retry_count'] += 1
                        actions_queue.put(act)
                    else:
                        print(f"[指令放棄] 車輛 {veh_id} 重試多次後仍無法執行。")
            except traci.TraCIException as e:
                print(f"[錯誤] 執行 traci 指令失敗: {e}")

        # === 【原始功能】核心邏輯：清理與資料蒐集 (完整保留) ===
        garbage_collector('127.0.0.1', 7883, '127.0.0.1', 7884, traci.simulation, vehicleDict)
        
        for veh_id in traci.vehicle.getIDList():
            vehicle = vehicleDict.setdefault(veh_id, Vehicle(veh_id))
            if vehicle.physicalComputerMapping is None:
                computer_count = len(pc_list)
                pc_index = i % computer_count
                vehicle.physicalComputerMapping = pc_list[pc_index]
                i += 1
            if (current_simulation_step - vehicle.last_publish_step) >= publish_period:
                vehicle.last_publish_step = current_simulation_step
                steps.setdefault(current_simulation_step, []).append(veh_id)
                event_occur_steps.add(current_simulation_step)
                geofenceInfos.setdefault(veh_id, []).append(retrieve_SUMO_vehicle_info(traci, veh_id))

        # === 【原始功能】核心邏輯：資料分派與等待 ACK (完整保留) ===
        veh_count = 0
        for step in sorted(list(event_occur_steps)):
            if step in steps:
                veh_list = steps.get(step, [])
                veh_count += len(veh_list)
                for veh_id in veh_list:
                    if veh_id in geofenceInfos and geofenceInfos.get(veh_id):
                        info = geofenceInfos[veh_id].pop(0)
                        pc = vehicleDict[veh_id].physicalComputerMapping
                        Vehicle_dispatcher.dispatch_vehicle(pc, veh_id, info)
                event_occur_steps.remove(step)
        
        while Vehicle_dispatcher.ack_count != veh_count:
            time.sleep(0.001)
        Vehicle_dispatcher.ack_count = 0

        # === 【新增功能】模組 2: 廣播所有車輛的即時狀態 ===
        # 【關鍵改動】此段耗費效能的廣播邏輯已被【移除】！
        # 現在只在收到請求時，才會透過 _on_collab_message 進行點對點的回應。

        # --- 模擬往前一步 (共同) ---
        current_simulation_step += 1
        traci.simulationStep()

    # --- 模擬結束後的清理 ---
    garbage_collector('127.0.0.1', 7883, '127.0.0.1', 7884, traci.simulation, vehicleDict)
    print("Simulation Done!")
    
    traci.close()
    collab_client.loop_stop()




