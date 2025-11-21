# import os
# import sys
# import queue
# import json
# import time
# import statistics
# import paho.mqtt.client as mqtt
# import traceback

# from traffic_Vehicle import Vehicle
# from traffic_Vehicle_dispatcher import VehicleDispatcher

# if 'SUMO_HOME' in os.environ:
#     tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
#     sys.path.append(tools)
# else:
#     sys.exit("請設定環境變數 'SUMO_HOME'")
# import traci

# class CONFIG:
#     SUMO_BINARY_PATH = "/usr/local/bin/sumo-gui"
#     SUMO_CONFIG_FILE = "/home/paul/sumo_platform/testbed/traffic_simulation/osm.sumocfg.xml"
#     SIMULATION_DELAY = 1000
#     COLLAB_BROKER_ADDRESS = "127.0.0.1"
#     COLLAB_BROKER_PORT = 7883
#     DISPATCHER_BROKER_ADDRESS = "localhost"
#     DISPATCHER_BROKER_PORT = 7884
#     ACTION_TOPIC = "traci_actions"
#     STATE_REQUEST_TOPIC = "vehicle/state/request"
#     STATE_RESPONSE_TOPIC_PREFIX = "vehicle/state/response/"
#     HANDSHAKE_TOPIC = "system/handshake"
#     ARRIVED_VEHICLES_TOPIC = "arrivedIDList"
#     MAX_ACTION_RETRY = 10
#     PUBLISH_PERIOD_STEPS = 1

# class CollaborationCommunicator:
#     def __init__(self, traci_instance):
#         self.client = mqtt.Client(client_id="sumo_executor_collab_modular", callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
#         self.client.on_message = self._on_message
#         self.actions_queue = queue.Queue()
#         self.traci = traci_instance

#     def connect(self):
#         try:
#             self.client.connect(CONFIG.COLLAB_BROKER_ADDRESS, CONFIG.COLLAB_BROKER_PORT, 60)
#             print(f"✅ [協作模組] 成功連線至 MQTT Broker ({CONFIG.COLLAB_BROKER_ADDRESS}:{CONFIG.COLLAB_BROKER_PORT})")
#         except ConnectionRefusedError:
#             print(f"❌ [協作模組] 無法連線至 MQTT Broker。")
#             sys.exit(1)

#     def start(self):
#         topics = [(CONFIG.ACTION_TOPIC, 1), (CONFIG.STATE_REQUEST_TOPIC, 1), (CONFIG.HANDSHAKE_TOPIC, 1)]
#         self.client.subscribe(topics)
#         self.client.loop_start()
#         print(f"✅ [協作模組] 已訂閱主題: {[t[0] for t in topics]}")

#     def stop(self):
#         self.client.loop_stop(force=True)
#         self.client.disconnect()
#         print("⏹️ [協作模組] MQTT 連線已停止。")

#     def _on_message(self, _client, _userdata, msg):
#         topic_handlers = { CONFIG.ACTION_TOPIC: self._handle_action, CONFIG.STATE_REQUEST_TOPIC: self._handle_state_request, CONFIG.HANDSHAKE_TOPIC: self._handle_handshake }
#         handler = topic_handlers.get(msg.topic)
#         if handler: handler(msg.payload)
        
#     def _handle_action(self, payload):
#         try:
#             action = json.loads(payload)
#             action['retry_count'] = 0
#             self.actions_queue.put(action)
#         except json.JSONDecodeError: pass

#     def _handle_state_request(self, payload):
#         try:
#             req = json.loads(payload)
#             veh_id = req.get("veh_id")
#             if not veh_id or veh_id not in self.traci.vehicle.getIDList(): return
#             laneID = self.traci.vehicle.getLaneID(veh_id)
#             roadID = self.traci.lane.getEdgeID(laneID) if laneID and not laneID.startswith(':') else ""
#             route = self.traci.vehicle.getRoute(veh_id)
#             dest = route[-1] if route else ""
#             state_info = {"roadID": roadID, "final_destination": dest}
#             self.client.publish(CONFIG.STATE_RESPONSE_TOPIC_PREFIX + veh_id, json.dumps(state_info), qos=1)
#         except (json.JSONDecodeError, self.traci.TraCIException): pass

#     def _handle_handshake(self, payload):
#         try:
#             data = json.loads(payload)
#             if data.get("status") == "controller_ready":
#                 print("🤝 [握手] 收到 Controller 準備信號，回傳確認...")
#                 ack_payload = json.dumps({"status": "executor_ready"})
#                 self.client.publish(CONFIG.HANDSHAKE_TOPIC, ack_payload, qos=1)
#         except json.JSONDecodeError: pass

#     def process_actions(self):
#         if self.actions_queue.empty(): return
#         act = self.actions_queue.get_nowait()
#         veh_id = act.get("veh_id")
#         try:
#             if veh_id in self.traci.vehicle.getIDList() and not self.traci.vehicle.getLaneID(veh_id).startswith(':'):
#                 if act.get("type") == "change_lane": self.traci.vehicle.changeLane(veh_id, act["lane_index"], act["duration"])
#                 elif act.get("type") == "change_route": self.traci.vehicle.setRoute(veh_id, act["edge_list"])
#             elif veh_id in self.traci.vehicle.getIDList():
#                 if act['retry_count'] < CONFIG.MAX_ACTION_RETRY:
#                     act['retry_count'] += 1
#                     self.actions_queue.put(act)
#         except self.traci.TraCIException: pass


# class SumoExecutor:

#     def __init__(self):
#         self.traci = None
#         self.comm = None
#         self.dispatcher = None
#         self.vehicle_dict = {}
#         self.current_step = 0

#         self.TEST_PEAK_BACKLOG_THRESHOLD = 28000
#         self.TEST_START_BACKLOG_THRESHOLD = 28000
#         self.TEST_STOP_BACKLOG_THRESHOLD = 27000

#         self.test_state = "IDLE"
#         self.sim_delta_t = 1.0
#         self.vehicle_count_accumulator = 0
#         self.steps_in_measurement = 0
#         self.start_trigger_backlog_count = 0

#         self.start_perf_time = 0.0
#         self.end_perf_time = 0.0
#         self.start_wall_time = 0.0
#         self.end_wall_time = 0.0
#         self.start_sim_step = 0
#         self.end_sim_step = 0


#     def start_sumo(self):
#         sumo_cmd = [
#             CONFIG.SUMO_BINARY_PATH,
#             "-c", CONFIG.SUMO_CONFIG_FILE,
#             "-d", str(CONFIG.SIMULATION_DELAY),
#             "--ignore-route-errors",
#             "--time-to-teleport", "-1",
#             "--tls.all-off"
#         ]
#         try:
#             traci.start(sumo_cmd)
#             self.traci = traci
#             print("✅ [SUMO] 模擬已啟動!")
#         except Exception as e:
#             print(f"❌ [SUMO] 啟動失敗: {e}")
#             sys.exit(1)

#     def initialize_modules(self):
#         self.comm = CollaborationCommunicator(self.traci)
#         self.comm.connect()
#         self.comm.start()
#         self.dispatcher = VehicleDispatcher()
#         self.dispatcher.connect(CONFIG.DISPATCHER_BROKER_ADDRESS, CONFIG.DISPATCHER_BROKER_PORT)
#         self.sim_delta_t = self.traci.simulation.getDeltaT()
        
#         print(f"✅ [測試設定] 模擬步長 (Delta T) 設置為: {self.sim_delta_t} 秒")
#         print(f"✅ [測試設定] 將等待「等待插入車輛數」 > {self.TEST_PEAK_BACKLOG_THRESHOLD} 後，再於其 < {self.TEST_START_BACKLOG_THRESHOLD} 時開始測試。")

#     def run_simulation_loop(self):
#         pc_list = ['pc1']
#         pc_idx_counter = 0

#         print("\n--- 模擬主迴圈開始 ---")

#         while self.traci.simulation.getMinExpectedNumber() > 0:
#             self._cleanup_arrived_vehicles()
#             self.comm.process_actions()
#             self._run_original_dispatcher_logic(pc_list, pc_idx_counter)
#             pc_idx_counter += 1
            
#             self.traci.simulationStep()
#             self.current_step += 1
            
#             if self.test_state != "FINISHED":
#                 backlogged_vehicles = self.traci.simulation.getMinExpectedNumber() - self.traci.simulation.getDepartedNumber()

#                 if self.test_state == "IDLE":
#                     if backlogged_vehicles > self.TEST_PEAK_BACKLOG_THRESHOLD:
#                         self.test_state = "ARMED"
#                         print(f"\n[測試狀態] IDLE -> ARMED (入口壓力已達高峰: {backlogged_vehicles})")
                
#                 elif self.test_state == "ARMED":
#                     if backlogged_vehicles < self.TEST_START_BACKLOG_THRESHOLD:
#                         self.test_state = "MEASURING"
#                         self.start_perf_time = time.perf_counter()
#                         self.start_wall_time = time.time()
#                         self.start_sim_step = self.current_step
#                         self.start_trigger_backlog_count = backlogged_vehicles
#                         self.vehicle_count_accumulator += self.traci.vehicle.getIDCount()
#                         self.steps_in_measurement = 1
#                         print(f"\n✅ [RTF 測試開始] 等待插入車輛數為 {backlogged_vehicles} (< {self.TEST_START_BACKLOG_THRESHOLD})")
#                         print(f"   -> 開始時間: {time.strftime('%H:%M:%S', time.localtime(self.start_wall_time))}, SUMO 步數: {self.start_sim_step}")
                        
#                         if backlogged_vehicles < self.TEST_STOP_BACKLOG_THRESHOLD:
#                             print("⚠️ [即時觸發] 測試開始條件與結束條件在同一步驟內被滿足。")
#                             self.test_state = "FINISHED"
#                             self.end_perf_time = time.perf_counter()
#                             self.end_wall_time = time.time()
#                             self.end_sim_step = self.current_step
#                             self._calculate_and_report_interval_rtf()
#                             print("✅ [RTF 測試報告已產生] 模擬將繼續運行...")

#                 elif self.test_state == "MEASURING":
#                     self.vehicle_count_accumulator += self.traci.vehicle.getIDCount()
#                     self.steps_in_measurement += 1
#                     if backlogged_vehicles < self.TEST_STOP_BACKLOG_THRESHOLD:
#                         self.test_state = "FINISHED"
#                         self.end_perf_time = time.perf_counter()
#                         self.end_wall_time = time.time()
#                         self.end_sim_step = self.current_step
#                         self._calculate_and_report_interval_rtf()
#                         print("✅ [RTF 測試報告已產生] 模擬將繼續運行...")

#     def _run_original_dispatcher_logic(self, pc_list, pc_idx_counter):
#         for veh_id in self.traci.vehicle.getIDList():
#             vehicle = self.vehicle_dict.get(veh_id)
#             if not vehicle:
#                 vehicle = Vehicle(
#                     veh_id=veh_id,
#                     shared_mqtt_client=self.comm.client,
#                     virtual_host=CONFIG.COLLAB_BROKER_ADDRESS,
#                     virtual_port=CONFIG.COLLAB_BROKER_PORT
#                 )
#                 self.vehicle_dict[veh_id] = vehicle
#             if vehicle.physicalComputerMapping is None:
#                 vehicle.physicalComputerMapping = pc_list[pc_idx_counter % len(pc_list)]
#             if (self.current_step - vehicle.last_publish_step) >= CONFIG.PUBLISH_PERIOD_STEPS:
#                 vehicle.last_publish_step = self.current_step
#                 info = self._retrieve_sumo_info(veh_id)
#                 if info:
#                     pc_topic = vehicle.physicalComputerMapping
#                     self.dispatcher.dispatch_vehicle(pc_topic, veh_id, info)

#     def _retrieve_sumo_info(self, veh_id):
#         try:
#             x, y = self.traci.vehicle.getPosition(veh_id)
#             lon, lat = self.traci.simulation.convertGeo(x, y)
#             laneID = self.traci.vehicle.getLaneID(veh_id)
#             if not laneID.startswith(":"):
#                 return {"lat": lat, "lon": lon, "laneID": laneID, "width": self.traci.lane.getLength(laneID) / 3, "laneAngle": self.traci.lane.getAngle(laneID), "speed": self.traci.vehicle.getSpeed(veh_id) * 3.6, "travelTime": self.traci.lane.getTraveltime(laneID), "lanePosition": self.traci.vehicle.getLanePosition(veh_id), "vehicleLength": self.traci.vehicle.getLength(veh_id), "connectedLanes": [link[0] for link in self.traci.lane.getLinks(laneID, False)]}
#             else:
#                 return {"lat": lat, "lon": lon, "laneID": laneID}
#         except self.traci.TraCIException:
#             return {}

#     def _cleanup_arrived_vehicles(self):
#         arrived_ids = list(self.traci.simulation.getArrivedIDList())
#         if not arrived_ids: return
#         if self.comm:
#             self.comm.client.publish(CONFIG.ARRIVED_VEHICLES_TOPIC, json.dumps(arrived_ids), qos=1)
#         for veh_id in arrived_ids:
#             if veh_id in self.vehicle_dict:
#                 if hasattr(self.vehicle_dict[veh_id], 'disconnect'):
#                     self.vehicle_dict[veh_id].disconnect()
#                 del self.vehicle_dict[veh_id]

#     def cleanup(self):
#         self._cleanup_arrived_vehicles()
#         if self.traci and not self.traci.isClosed():
#             self.traci.close()
#         if self.comm:
#             self.comm.stop()
#         if self.dispatcher:
#             self.dispatcher.disconnect()
#         print("✅ 所有資源已清理完畢。")

#     def _calculate_and_report_interval_rtf(self):
#         total_real_time = self.end_perf_time - self.start_perf_time
#         total_steps = self.end_sim_step - self.start_sim_step

#         if total_steps <= 0:
#             print("⚠️ [RTF 測試警告] 測量區間過短 (少於1步)，無法計算有意義的 RTF。")
#             total_steps = 1
            
#         total_sim_time = total_steps * self.sim_delta_t
#         rtf_raw = total_sim_time / total_real_time if total_real_time > 0 else float('inf')

#         avg_vehicles = self.vehicle_count_accumulator / self.steps_in_measurement if self.steps_in_measurement > 0 else 0
#         end_trigger_backlog_count = self.traci.simulation.getMinExpectedNumber() - self.traci.simulation.getDepartedNumber()

#         start_clock_time = time.strftime('%H:%M:%S', time.localtime(self.start_wall_time))
#         end_clock_time = time.strftime('%H:%M:%S', time.localtime(self.end_wall_time))

#         report = f"""
# ╔══════════════════════════════════════════════════════════════════════════════════
# ║                                📊 入口壓力區間效能測試報告 (RTF)                                
# ╠══════════════════════════════════════════════════════════════════════════════════
# ║ 測試設定 (Parameters)
# ║ ────────────────────
# ║ • 壓力高峰門檻: 等待插入車輛數 > {self.TEST_PEAK_BACKLOG_THRESHOLD}
# ║ • 測試開始門檻: 等待插入車輛數 < {self.TEST_START_BACKLOG_THRESHOLD}
# ║ • 測試結束門檻: 等待插入車輛數 < {self.TEST_STOP_BACKLOG_THRESHOLD}
# ╟──────────────────────────────────────────────────────────────────────────────────
# ║ 測量期間紀錄 (Measurement Period)
# ║ ───────────────────────────
# ║ ▶ 開始 (Start)
# ║   - 觸發時等待數: {self.start_trigger_backlog_count} 輛
# ║   - SUMO 時間步:  {self.start_sim_step}
# ║   - 真實世界時間: {start_clock_time}
# ║ ▶ 結束 (End)
# ║   - 結束時等待數: {end_trigger_backlog_count} 輛
# ║   - SUMO 時間步:  {self.end_sim_step}
# ║   - 真實世界時間: {end_clock_time}
# ╟──────────────────────────────────────────────────────────────────────────────────
# ║ 統計結果 (Summary)
# ║ ────────────
# ║ • 真實世界耗時:   {total_real_time:.3f} 秒
# ║ • 模擬世界耗時:   {total_sim_time:.1f} 秒 ({total_steps} 步)
# ║ • 區間平均在途車輛數: {avg_vehicles:.1f} 輛
# ╠══════════════════════════════════════════════════════════════════════════════════
# ║  最終即時因子 (Real-Time Factor, RTF): {rtf_raw:.4f}
# ╚══════════════════════════════════════════════════════════════════════════════════
# """
#         print(report)

# if __name__ == '__main__':
#     if not (os.path.exists(CONFIG.SUMO_BINARY_PATH) and os.path.exists(CONFIG.SUMO_CONFIG_FILE)):
#         print(f"❌ [錯誤] 請在 CONFIG 中確認 SUMO 執行檔或設定檔路徑。")
#         sys.exit(1)
    
#     executor = SumoExecutor()
#     try:
#         executor.start_sumo()
#         executor.initialize_modules()
#         executor.run_simulation_loop()
#     except KeyboardInterrupt:
#         print("\nℹ️ 偵測到使用者中斷 (Ctrl+C)...")
#     except Exception as e:
#         print(f"\n❌ 主程式發生未預期的錯誤: {e}")
#         traceback.print_exc()
#     finally:
#         print("\n正在進行清理工作...")
#         if 'executor' in locals() and hasattr(executor, 'traci') and executor.traci:
#             try:
#                 if not traci.isClosed():
#                     executor.cleanup()
#             except traci.TraCIException:
#                 pass
#         print("程式已安全退出。")



# traffic_simulation/RetriveVehiclePos_distributed_v1.py (簡化測試條件版)

import os
import sys
import queue
import json
import time
import paho.mqtt.client as mqtt

# 假設這些是您專案中的模組
from traffic_Vehicle import Vehicle
from garbage_collector import garbage_collector
from traffic_Vehicle_dispatcher import VehicleDispatcher

if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("請宣告環境變數 'SUMO_HOME'")
import traci

# --- MQTT Settings (保持不變) ---
BROKER_ADDRESS = "127.0.0.1"
VIRTUAL_BROKER_PORT = 7884
PHYSICAL_BROKER_PORT = 7883
ACTION_TOPIC = "traci_actions"
actions_queue = queue.Queue()

def _on_action_message(_client, _userdata, msg):
    try:
        action = json.loads(msg.payload.decode('utf-8'))
        actions_queue.put(action)
    except json.JSONDecodeError:
        pass

def retrieve_SUMO_vehicle_info(traci_instance, veh_id):
    # (此函式內容不變)
    x, y = traci_instance.vehicle.getPosition(veh_id)
    lon, lat = traci_instance.simulation.convertGeo(x, y)
    laneID = traci_instance.vehicle.getLaneID(veh_id)
    vehicleLength = traci_instance.vehicle.getLength(veh_id)
    lanePosition = traci_instance.vehicle.getLanePosition(veh_id)
    speed = traci_instance.vehicle.getSpeed(veh_id) * 3.6
    laneAngle = traci_instance.lane.getAngle(laneID)
    laneLength = traci_instance.lane.getLength(laneID)
    travelTime = traci_instance.lane.getTraveltime(laneID)
    route_ids = traci_instance.vehicle.getRoute(veh_id)
    connectedLanes = []
    if laneID.startswith(":"):
        try:
            links = traci_instance.lane.getLinks(laneID, False)
            for ln in links:
                connectedLanes.append(ln[0])
        except traci.TraCIException:
            pass 
    geofenceInfo = dict(lat=lat, lon=lon, laneID=laneID, width=laneLength/3, laneAngle=laneAngle, speed=speed, travelTime=travelTime, lanePosition=lanePosition, vehicleLength=vehicleLength, connectedLanes=connectedLanes, route=route_ids)
    return geofenceInfo

if __name__ == '__main__':
    sumo_proc = None
    try:
        start_real_time = time.time()
        
        print("Initializing Vehicle Dispatcher...")
        vehicle_dispatcher = VehicleDispatcher()
        computers = dict(pc1='127.0.0.1')
        vehicle_dispatcher.physicalComputers = computers
        pc_list = list(vehicle_dispatcher.physicalComputers.keys())
        vehicle_dispatcher.connect('localhost', VIRTUAL_BROKER_PORT)
        print(f"Vehicle Dispatcher connected to port {VIRTUAL_BROKER_PORT}.")
        
        print("Initializing Action Listener...")
        action_client = mqtt.Client(client_id="sumo_action_listener", callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        action_client.on_message = _on_action_message
        action_client.connect(BROKER_ADDRESS, VIRTUAL_BROKER_PORT, 60)
        action_client.subscribe(ACTION_TOPIC, qos=1)
        action_client.loop_start()
        print(f"Subscribed to topic: {ACTION_TOPIC}")

        sumoBinary = "/usr/local/bin/sumo-gui"
        sumocfg_path = "/home/paul/sumo_platform/testbed/traffic_simulation/osm.sumocfg.xml"
        if not os.path.exists(sumocfg_path):
            raise FileNotFoundError(f"SUMO config file not found at: {sumocfg_path}")
        
        step_length = 1.0
        sumo_port_to_use = 8813
        
        sumoCmd = [ sumoBinary, "-c", sumocfg_path, f"--step-length={step_length}", "--ignore-route-errors", "--num-clients", "2" ]
        
        print("Starting SUMO and connecting TraCI...")
        traci.start(sumoCmd, port=sumo_port_to_use)
        print(f"✅ SUMO simulation connected, TraCI server is on fixed port {sumo_port_to_use}.")

        # --- NEW: 簡化的測試變數 ---
        is_measuring = False
        test_completed = False
        sim_delta_t = step_length
        start_perf_time = 0.0
        start_sim_step = 0

        # --- NEW: 簡化的報告函式 ---
        def calculate_and_report_rtf():
            end_perf_time = time.perf_counter()
            total_real_time = end_perf_time - start_perf_time
            total_steps = current_simulation_step - start_sim_step
            
            if total_steps <= 0: return

            total_sim_time = total_steps * sim_delta_t
            rtf_raw = total_sim_time / total_real_time if total_real_time > 0 else float('inf')

            report = f"""
╔═════════════════════════════════════════════════════════════
║ 📊 效能測試報告 (Performance Report)
╠═════════════════════════════════════════════════════════════
║ • 測試區間: {start_sim_step}步 -> {current_simulation_step}步 ({total_steps} 步)
║ • 真實世界耗時: {total_real_time:.3f} 秒
║ • 模擬世界耗時: {total_sim_time:.1f} 秒
╠═════════════════════════════════════════════════════════════
║ 最終效能倍率 (Performance Multiplier): {rtf_raw:.4f}x
╚═════════════════════════════════════════════════════════════
"""
            print(report)

        # --- 主模擬迴圈 ---
        vehicleDict = {}
        current_simulation_step = 0
        publish_period = 1
        i = 0

        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            current_simulation_step += 1
            
            # --- MODIFIED: 全新的、簡化的測試狀態機 ---
            if not test_completed:
                active_vehicle_count = traci.vehicle.getIDCount()

                if not is_measuring:
                    # 開始條件：車輛數 > 10
                    if active_vehicle_count > 10:
                        is_measuring = True
                        start_perf_time = time.perf_counter()
                        start_sim_step = current_simulation_step
                        print(f"\n✅ [RTF 測試開始] 偵測到車輛數 ({active_vehicle_count}) > 10")
                else: # 正在測量中
                    # 結束條件：車輛數 < 5
                    if active_vehicle_count < 5:
                        is_measuring = False
                        test_completed = True # 標記測試完成，不再觸發
                        print(f"⏹️ [RTF 測試結束] 偵測到車輛數 ({active_vehicle_count}) < 5")
                        calculate_and_report_rtf()

            # (指令處理邏輯不變)
            while not actions_queue.empty():
                act = actions_queue.get_nowait()
                try:
                    veh_id = act.get("veh_id")
                    if veh_id in traci.vehicle.getIDList():
                        if act.get("type") == "reroute_from_current":
                            # ... (監控打印邏輯保持不變) ...
                except traci.TraCIException:
                    pass

            if current_simulation_step % 10 == 0:
                 garbage_collector('127.0.0.1', PHYSICAL_BROKER_PORT, '127.0.0.1', VIRTUAL_BROKER_PORT, traci, vehicleDict)
            
            # (車輛資料發布邏輯不變)
            vehicles_to_publish = []
            active_vehicles_list = traci.vehicle.getIDList()
            for veh_id in active_vehicles_list:
                if veh_id not in vehicleDict:
                    vehicle = Vehicle(veh_id)
                    pc_index = i % len(pc_list)
                    vehicle.physicalComputerMapping = pc_list[pc_index]
                    vehicleDict[veh_id] = vehicle
                    i += 1
                else:
                    vehicle = vehicleDict[veh_id]
                if (current_simulation_step - vehicle.last_publish_step) >= publish_period:
                    vehicle.last_publish_step = current_simulation_step
                    vehicles_to_publish.append(veh_id)
            
            if vehicles_to_publish:
                for veh_id in vehicles_to_publish:
                    info = retrieve_SUMO_vehicle_info(traci, veh_id)
                    pc = vehicleDict[veh_id].physicalComputerMapping
                    vehicle_dispatcher.dispatch_vehicle(pc, veh_id, info)
                
                expected_acks = len(vehicles_to_publish)
                wait_start_time = time.time()
                while vehicle_dispatcher.ack_count < expected_acks:
                    time.sleep(0.001)
                    if time.time() - wait_start_time > 10:
                        break
                vehicle_dispatcher.reset_ack_count()
    
    except (traci.TraCIException, RuntimeError, FileNotFoundError) as e:
        print(f"An error occurred: {e}")
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user.")
    finally:
        # 最終清理
        print("\n正在進行清理工作...")
        try:
            if traci and not traci.isClosed():
                traci.close()
                print("TraCI connection closed.")
        except Exception:
            pass 
        if 'action_client' in locals() and action_client.is_connected():
            action_client.loop_stop()
            action_client.disconnect()
        if 'vehicle_dispatcher' in locals():
            vehicle_dispatcher.disconnect()
        print("程式已安全退出。")