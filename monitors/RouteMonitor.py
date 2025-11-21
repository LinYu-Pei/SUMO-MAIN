# # monitors/RouteMonitor.py
# # (最終版 v6.8：修正 on_message 中忽略 "busy" 狀態的錯誤)

# import paho.mqtt.client as mqtt
# import json
# import time
# import threading
# import logging
# import argparse

# # --- Logging Setup ---
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger("RouteMonitor")

# # --- 快取結構定義 ---
# lane_event_cache = {}
# vehicle_idle_veto_cache = {}
# cache_lock = threading.Lock()
# EVENT_EXPIRATION_SECONDS = 20
# VEHICLE_IDLE_VETO_SECONDS = 5
# SWARM_CONFIRM_THRESHOLD = 15
# OBU_STATE_SEVERITY = {
#     "StuckAtGreenLight": 5, "StoppedInTraffic": 4, "SlowTraffic": 3,
#     "NormalRedLightStop": 2, "FreeFlow": 1, "Initializing": 0
# }

# # --- 跨世界通訊設定 ---
# INTER_WORLD_TOPIC = "system/inter_world_hotspots"

# # --- 預設允許的車輛類型 ---
# DEFAULT_ALLOWED_VCLASSES = ["passenger", "truck", "bus", "motorcycle"]

# # ============================================================ #
# # 輔助函式
# # ============================================================ #
# def get_edge_id_from_lane_id(lane_id):
#     """ 從 lane_id (如 'edge123_0') 提取 edge_id ('edge123') """
#     if not lane_id or lane_id.startswith(':'): return None
#     try: return lane_id.rsplit('_', 1)[0]
#     except Exception: return None

# # ============================================================ #
# # 聚合器與發布器 (Aggregator & Publisher)
# # ============================================================ #
# def aggregator_and_publisher(client, world_id):
#     """
#     聚合器執行緒。
#     融合本地數據與外部世界情報，發布本地路況快照，並分享本地 Hotspot。
#     """
#     status_topic = f"worlds/{world_id}/global_road_status"
#     last_published_hotspots = {} # {lane_id: level}

#     while True:
#         time.sleep(1) # 每秒聚合一次

#         final_road_status_for_broadcast = {}
#         lanes_that_became_clear_locally = []
#         hotspots_to_share = {} # {lane_id: {"status": "CONGESTED", "level": ...}}

#         current_time = time.time()

#         with cache_lock:
#             # --- 1. 清理過期的報告和路段 ---
#             lanes_to_remove_from_cache = []
#             for lane_id in list(lane_event_cache.keys()):
#                 event = lane_event_cache[lane_id]
#                 has_active_problem_reports = False
#                 event["is_externally_triggered"] = False # 重置外部觸發標記

#                 vehicles_to_remove = []
#                 for veh_id, report in list(event["reports"].items()):
#                     if current_time - report["timestamp"] <= EVENT_EXPIRATION_SECONDS:
#                         if OBU_STATE_SEVERITY.get(report["state"], 0) >= OBU_STATE_SEVERITY["SlowTraffic"]:
#                             has_active_problem_reports = True
#                         if veh_id.startswith("EXTERNAL_"):
#                              event["is_externally_triggered"] = True
#                     else:
#                         vehicles_to_remove.append(veh_id)

#                 for veh_id in vehicles_to_remove:
#                      if veh_id in event["reports"]:
#                           del event["reports"][veh_id]

#                 is_rsu_busy = event.get("is_rsu_busy", False)
#                 if current_time - event.get("rsu_last_update", 0) > EVENT_EXPIRATION_SECONDS:
#                     is_rsu_busy = False
#                     event["is_rsu_busy"] = False

#                 if not has_active_problem_reports and not is_rsu_busy:
#                      if event.get("last_state", "Normal") != "Normal":
#                          logger.info(f"✅ [{world_id}] [狀態解除] 路段 {lane_id} 已無活躍報告/RSU，恢復正常。")
#                          lanes_that_became_clear_locally.append(lane_id)
#                      lanes_to_remove_from_cache.append(lane_id)
#                 elif not has_active_problem_reports:
#                      event["is_externally_triggered"] = False
            
#             # 統一刪除
#             # for lane_id in lanes_to_remove_from_cache:
#             #     if lane_id in lane_event_cache:
#             #         del lane_event_cache[lane_id]

#             # --- 2. 聚合當前所有活躍路段的狀態 ---
#             for lane_id, event_data in lane_event_cache.items():
#                 reports = event_data.get("reports", {}).values()

#                 local_problem_vehicle_count = sum(1 for r in reports if OBU_STATE_SEVERITY.get(r.get('state', ''), 0) >= OBU_STATE_SEVERITY["StoppedInTraffic"] and not r.get("source", "").startswith("EXTERNAL_"))
                
#                 worst_obu_state_obj = max(reports, key=lambda r: OBU_STATE_SEVERITY.get(r.get('state', ''), 0), default={"state": "FreeFlow"}) if reports else {"state": "FreeFlow"}
#                 worst_obu_state = worst_obu_state_obj.get('state', 'FreeFlow')
                
#                 is_rsu_busy = event_data.get("is_rsu_busy", False)
#                 is_externally_triggered = event_data.get("is_externally_triggered", False)
#                 previous_state = event_data.get("last_state", "Normal")
                
#                 final_state, action, priority = "Normal", "Monitor", 5

#                 # 判斷壅塞狀態邏輯 (同上版本)
#                 if worst_obu_state == "StuckAtGreenLight":
#                     final_state, action, priority = "SevereCongestion", "MandatoryReroute", 1
#                 elif local_problem_vehicle_count >= SWARM_CONFIRM_THRESHOLD and is_rsu_busy:
#                     final_state, action, priority = "SwarmConfirmedCongestion", "MandatoryReroute", 1.5
#                 elif worst_obu_state == "StoppedInTraffic" and (is_rsu_busy or is_externally_triggered):
#                     final_state, action, priority = "ConfirmedCongestion", "SuggestReroute", 2
#                 elif worst_obu_state == "SlowTraffic" and is_rsu_busy:
#                     final_state, action, priority = "UnderObservation", "Monitor", 4
                
#                 # Idle 否決票
#                 if lane_id in vehicle_idle_veto_cache:
#                      if current_time - vehicle_idle_veto_cache[lane_id] <= VEHICLE_IDLE_VETO_SECONDS:
#                           final_state, action, priority = "Normal", "Monitor", 5
#                      else:
#                           del vehicle_idle_veto_cache[lane_id]

#                 if final_state != previous_state:
#                     logger.info(f"📢 [{world_id}] [狀態變更] 路段 {lane_id} 狀態從 {previous_state} 變為 {final_state}")
                
#                 event_data["last_state"] = final_state
                
#                 # 加入本地廣播列表
#                 if action != "Monitor":
#                     final_road_status_for_broadcast[lane_id] = {
#                         "final_state": final_state, 
#                         "action": action, 
#                         "priority": priority
#                     }
                    
#                 # 【階段二】判斷是否要分享 Hotspot
#                 is_locally_triggered = any(OBU_STATE_SEVERITY.get(r.get('state', ''), 0) >= OBU_STATE_SEVERITY["SlowTraffic"] for r in reports if not r.get("source", "").startswith("EXTERNAL_")) or is_rsu_busy

#                 if is_locally_triggered and action != "Monitor": # 任何非 Monitor 狀態都分享
#                      hotspots_to_share[lane_id] = {"status": "CONGESTED", "level": final_state}

#         # --- 3. 發布整合後的「本地世界路況快照」給 OBC ---
#         payload_to_publish = {"road_status": final_road_status_for_broadcast}
#         client.publish(status_topic, json.dumps(payload_to_publish), qos=0)
        
#         # if final_road_status_for_broadcast: # 減少日誌量
#         #      logger.info(f"📡 [{world_id}] 已發布本地路況快照 (含 {len(final_road_status_for_broadcast)} 條路段) 至 {status_topic}")

#         # --- 4. 【階段二】處理跨世界 Hotspot 的分享 ---
#         current_hotspots_set = set(hotspots_to_share.keys())
#         last_published_set = set(last_published_hotspots.keys())

#         # --- 分享新增/變化的 Hotspot 給其他 RouteMonitor ---
#         for lane_id, data in hotspots_to_share.items():
#             level = data["level"]
#             if lane_id not in last_published_set or last_published_hotspots.get(lane_id) != level:
#                 hotspot_payload = {
#                     "source_world": world_id, "lane_id": lane_id, "status": data["status"],
#                     "congestion_level": level, "timestamp": current_time
#                 }
#                 client.publish(INTER_WORLD_TOPIC, json.dumps(hotspot_payload), qos=1)
#                 logger.info(f"🌐 [{world_id}] ---> 分享 Hotspot 至 {INTER_WORLD_TOPIC}: {lane_id} ({level})")
#                 last_published_hotspots[lane_id] = level

#         # --- 分享已解除的 Hotspot 給其他 RouteMonitor ---
#         cleared_lanes_to_share = (last_published_set - current_hotspots_set).union(
#             set(l for l in lanes_that_became_clear_locally if l in last_published_set)
#         )

#         for lane_id in cleared_lanes_to_share:
#             clear_payload_inter_world = {
#                 "source_world": world_id, "lane_id": lane_id, "status": "CLEAR", "timestamp": current_time
#             }
#             client.publish(INTER_WORLD_TOPIC, json.dumps(clear_payload_inter_world), qos=1)
#             logger.info(f"🌐 [{world_id}] ---> 分享解除情報至 {INTER_WORLD_TOPIC}: {lane_id}")
#             if lane_id in last_published_hotspots:
#                  del last_published_hotspots[lane_id]


# def on_connect(client, userdata, flags, reason_code, properties):
#     """MQTT 連線回呼函式"""
#     world_id = userdata["world_id"]
#     if reason_code == 0:
#         logger.info(f"'{client._client_id}' 連線成功。")
#     else:
#         logger.error(f"連線失敗, code: {reason_code}")

#     # 訂閱本世界的高頻數據
#     client.subscribe(f"worlds/{world_id}/rsu/raw_data")
#     client.subscribe(f"worlds/{world_id}/lanes/status/#")
#     client.subscribe(f"worlds/{world_id}/vehicles/perception/report")
#     logger.info(f"[{world_id}] 已訂閱專屬高頻主題: worlds/{world_id}/#")

#     # --- 【階段二】訂閱跨世界情報 ---
#     client.subscribe(INTER_WORLD_TOPIC)
#     logger.info(f"[{world_id}] 已訂閱跨世界情報: {INTER_WORLD_TOPIC}")
#     # ---

# def on_message(client, userdata, msg):
#     """MQTT 訊息回呼函式"""
#     topic = msg.topic
#     world_id = userdata["world_id"]
    
#     try:
#         payload = msg.payload.decode('utf-8')
#     except UnicodeDecodeError:
#         logger.warning(f"無法解碼來自 {topic} 的訊息。")
#         return

#     default_cache_entry = {"reports": {}, "last_state": "Normal", "is_rsu_busy": False, "rsu_last_update": 0.0, "is_externally_triggered": False}

#     with cache_lock:
#         current_time = time.time()
        
#         # --- 處理本地高頻數據 ---
#         if topic.startswith(f"worlds/{world_id}/"):
#             if topic.endswith('/rsu/raw_data'):
#                 try:
#                     rsu_raw_data = json.loads(payload)
#                     for lane_id, data in rsu_raw_data.items():
#                         if not lane_id or lane_id.startswith(':'): continue
#                         event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
#                         event["is_rsu_busy"] = data.get("vehicle_count", 0) > 0 and data.get("mean_speed", -1) < 5.0
#                         event["rsu_last_update"] = current_time
#                 except Exception as e:
#                     logger.error(f"處理 RSU 原始數據時發生錯誤: {e}")
            
#             elif topic.endswith('/vehicles/perception/report'):
#                 try:
#                     data = json.loads(payload)
#                     lane_id, veh_id, obu_state = data.get("lane_id"), data.get("veh_id"), data.get("obu_state")
#                     if not lane_id or not veh_id or not obu_state or lane_id.startswith(':'): return
#                     event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
#                     event["reports"][veh_id] = {"state": obu_state, "timestamp": current_time, "source": "LOCAL_OBU"}
#                 except Exception as e:
#                     logger.error(f"處理 OBU 報告時出錯: {e}")
                    
#             # --- 【教授修正】: 處理 "busy" 狀態 ---
#             elif '/lanes/status/' in topic:
#                 try:
#                     lane_id, data = topic.split('/')[-1], json.loads(payload)
#                     status, source = data.get("status", "").lower(), data.get("source", "UnknownVehicle")
                    
#                     if status == "idle" and ("Vehicle" in source or "Sensor" in source):
#                         # 收到 "idle" 否決票
#                         vehicle_idle_veto_cache[lane_id] = time.time()
#                         # print(f"DEBUG [{world_id}] Received idle veto for lane {lane_id}")
                    
#                     elif status == "busy":
#                         logger.info(f"🔥 [{world_id}] 收到來自 OBU ({source}) 的高優先級 'busy' 警告: {lane_id}")
#                         event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
                        
#                         # 【教授修正】: 將來源標記為本地，以便 is_locally_triggered 捕獲
#                         report_id = f"LOCAL_OBC_STUCK_{source}" 
#                         event["reports"][report_id] = {
#                             "state": "StoppedInTraffic", # 模擬成嚴重壅塞
#                             "timestamp": current_time,
#                             "source": f"LOCAL_OBC_STUCK" # 標記為本地來源
#                         }

#                 except Exception as e:
#                     logger.error(f"處理車道狀態訊息時出錯 ({topic}): {e}")

#         # --- 【階段二】處理來自其他世界的 Hotspot 情報 ---
#         elif topic == INTER_WORLD_TOPIC:
#            try:
#                data = json.loads(payload)
#                source_world = data.get("source_world")
               
#                if source_world == world_id: return # 忽略自己
               
#                lane_id = data.get("lane_id")
#                external_status = data.get("status")
#                if not lane_id: return

#                event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
#                external_report_id = f"EXTERNAL_{source_world}_{lane_id}"

#                if external_status == "CONGESTED":
#                    event["reports"][external_report_id] = {
#                        "state": "StoppedInTraffic", # 內化為基礎壅塞
#                        "timestamp": current_time,
#                        "source": f"EXTERNAL_{source_world}"
#                    }
#                    logger.info(f"🌐 [{world_id}] <--- 內化來自 [{source_world}] 的壅塞情報: {lane_id}")
               
#                elif external_status == "CLEAR":
#                    if external_report_id in event["reports"]:
#                        del event["reports"][external_report_id]
#                        logger.info(f"🌐 [{world_id}] <--- 內化來自 [{source_world}] 的解除情報: {lane_id}")

#            except Exception as e:
#                logger.error(f"處理跨世界情報時出錯 ({payload}): {e}")
#         # ---


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Route Monitor for a specific SUMO world")
#     parser.add_argument('--world-id', type=str, required=True, help='The ID of the world this monitor belongs to')
#     args = parser.parse_args()
#     world_id = args.world_id

#     client_id = f"RouteMonitor_{world_id}"
#     logger.info(f"RouteMonitor for world '{world_id}' is starting with client ID '{client_id}'...")
    
#     mqttc = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
#     mqttc.user_data_set({"world_id": world_id})
#     mqttc.on_connect, mqttc.on_message = on_connect, on_message

#     try:
#         mqttc.connect("localhost", 7883, 60)
#         aggregator_thread = threading.Thread(target=aggregator_and_publisher, args=(mqttc, world_id,), daemon=True)
#         aggregator_thread.start()
#         logger.info(f"RouteMonitor for '{world_id}' has started.")
#         mqttc.loop_forever()
        
#     except KeyboardInterrupt:
#         logger.info(f"收到中斷指令，正在為 '{world_id}' 執行清理...")
#     except Exception as e:
#         logger.error(f"RouteMonitor 發生未預期錯誤: {e}")
#     finally:
#         logger.info("正在發布最終的 CLEAR 快照...")
#         status_topic = f"worlds/{world_id}/global_road_status"
#         clear_payload_local = {"road_status": {}}
        
#         # --- 發布最終的跨世界 CLEAR 訊息 ---
#         lanes_to_clear_globally = []
#         with cache_lock:
#              lanes_to_clear_globally = list(lane_event_cache.keys())

#         clear_payload_global = {"source_world": world_id, "status": "CLEAR", "timestamp": time.time()}
#         # ---

#         try:
#             if mqttc.is_connected():
#                 mqttc.publish(status_topic, json.dumps(clear_payload_local), qos=1, retain=False)
#                 logger.info(f"已發布本地 CLEAR 快照至 {status_topic}")
                
#                 # 發布跨世界 CLEAR
#                 for lane_id in lanes_to_clear_globally:
#                      clear_payload_global["lane_id"] = lane_id
#                      mqttc.publish(INTER_WORLD_TOPIC, json.dumps(clear_payload_global), qos=1)
#                 if lanes_to_clear_globally:
#                      logger.info(f"已發布 {len(lanes_to_clear_globally)} 條跨世界 CLEAR 情報至 {INTER_WORLD_TOPIC}")

#             else:
#                 logger.warning("MQTT 未連線，無法發布最終 CLEAR 快照/情報。")
#         except Exception as pub_e:
#             logger.error(f"發布最終 CLEAR 快照/情報時失敗: {pub_e}")
        
#         logger.info("清理完成，正在斷開連線...")
#         time.sleep(1.0)
#         mqttc.disconnect()
#         logger.info(f"RouteMonitor for '{world_id}' 已安全關閉。")











# monitors/RouteMonitor.py
# (最終版 v7.0：實現 Control/Data Broker 分離)

import paho.mqtt.client as mqtt
import json
import time
import threading
import logging
import argparse

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("RouteMonitor")

# --- 快取結構定義 ---
lane_event_cache = {}
vehicle_idle_veto_cache = {}
cache_lock = threading.Lock()
EVENT_EXPIRATION_SECONDS = 20
VEHICLE_IDLE_VETO_SECONDS = 5
SWARM_CONFIRM_THRESHOLD = 15
OBU_STATE_SEVERITY = {
    "StuckAtGreenLight": 5, "StoppedInTraffic": 4, "SlowTraffic": 3,
    "NormalRedLightStop": 2, "FreeFlow": 1, "Initializing": 0
}

# --- 跨世界通訊設定 ---
# 【教授註解】Flow 7: 跨世界情報，改為在 Control Broker (7884) 上交換
INTER_WORLD_TOPIC = "system/inter_world_hotspots"

# --- 預設允許的車輛類型 ---
DEFAULT_ALLOWED_VCLASSES = ["passenger", "truck", "bus", "motorcycle"]

# ============================================================ #
# 輔助函式 (保持不變)
# ============================================================ #
def get_edge_id_from_lane_id(lane_id):
    """
    從 SUMO 的 lane_id (例如 'edge123_0') 中提取 edge_id ('edge123')。
    這有助於對整個路段而不是單一車道進行操作。
    """
    if not lane_id or lane_id.startswith(':'): return None
    try: return lane_id.rsplit('_', 1)[0]
    except Exception: return None

# ============================================================ #
# 聚合器與發布器 (Aggregator & Publisher)
# ============================================================ #

# 【教授註解】函式簽名變更：現在需要傳入 data_client (7883) 和 control_client (7884)
def aggregator_and_publisher(data_client, control_client, world_id):
    """
    RouteMonitor 的核心執行緒，每秒運行一次。
    主要職責：
    1. 清理過期的舊壅塞報告。
    2. 聚合來自 RSU、OBC 和其他世界的情報，分析判斷出最終的路況狀態。
    3. 將分析後的「本地路況快照」發布到 Data Broker (7883)，供本地車輛決策。
    4. 將本地偵測到的「壅塞熱點」或「解除情報」發布到 Control Broker (7884)，與其他世界共享。
    """
    
    # 【教授註解】Flow 4: 本地路況快照，發布於 Data Broker (7883)
    status_topic = f"worlds/{world_id}/global_road_status"
    
    last_published_hotspots = {} # {lane_id: level}

    while True:
        time.sleep(1) # 每秒聚合一次

        final_road_status_for_broadcast = {}
        lanes_that_became_clear_locally = []
        hotspots_to_share = {} # {lane_id: {"status": "CONGESTED", "level": ...}}

        current_time = time.time()

        with cache_lock:
            # --- 1. 清理過期的報告和路段 (邏輯不變) ---
            lanes_to_remove_from_cache = []
            for lane_id in list(lane_event_cache.keys()):
                event = lane_event_cache[lane_id]
                has_active_problem_reports = False
                event["is_externally_triggered"] = False # 重置外部觸發標記

                vehicles_to_remove = []
                for veh_id, report in list(event["reports"].items()):
                    if current_time - report["timestamp"] <= EVENT_EXPIRATION_SECONDS:
                        if OBU_STATE_SEVERITY.get(report["state"], 0) >= OBU_STATE_SEVERITY["SlowTraffic"]:
                            has_active_problem_reports = True
                        if veh_id.startswith("EXTERNAL_"):
                            event["is_externally_triggered"] = True
                    else:
                        vehicles_to_remove.append(veh_id)

                for veh_id in vehicles_to_remove:
                    if veh_id in event["reports"]:
                        del event["reports"][veh_id]

                is_rsu_busy = event.get("is_rsu_busy", False)
                if current_time - event.get("rsu_last_update", 0) > EVENT_EXPIRATION_SECONDS:
                    is_rsu_busy = False
                    event["is_rsu_busy"] = False

                if not has_active_problem_reports and not is_rsu_busy:
                    if event.get("last_state", "Normal") != "Normal":
                        logger.info(f"✅ [{world_id}] [狀態解除] 路段 {lane_id} 已無活躍報告/RSU，恢復正常。")
                        lanes_that_became_clear_locally.append(lane_id)
                    lanes_to_remove_from_cache.append(lane_id)
                elif not has_active_problem_reports:
                    event["is_externally_triggered"] = False
            
            # 統一刪除
            # for lane_id in lanes_to_remove_from_cache:
            #     if lane_id in lane_event_cache:
            #         del lane_event_cache[lane_id]

            # --- 2. 聚合當前所有活躍路段的狀態 (邏輯不變) ---
            for lane_id, event_data in lane_event_cache.items():
                reports = event_data.get("reports", {}).values()

                local_problem_vehicle_count = sum(1 for r in reports if OBU_STATE_SEVERITY.get(r.get('state', ''), 0) >= OBU_STATE_SEVERITY["StoppedInTraffic"] and not r.get("source", "").startswith("EXTERNAL_"))
                
                worst_obu_state_obj = max(reports, key=lambda r: OBU_STATE_SEVERITY.get(r.get('state', ''), 0), default={"state": "FreeFlow"}) if reports else {"state": "FreeFlow"}
                worst_obu_state = worst_obu_state_obj.get('state', 'FreeFlow')
                
                is_rsu_busy = event_data.get("is_rsu_busy", False)
                is_externally_triggered = event_data.get("is_externally_triggered", False)
                previous_state = event_data.get("last_state", "Normal")
                
                final_state, action, priority = "Normal", "Monitor", 5

                # 判斷壅塞狀態邏輯 (同上版本)
                if worst_obu_state == "StuckAtGreenLight":
                    final_state, action, priority = "SevereCongestion", "MandatoryReroute", 1
                elif local_problem_vehicle_count >= SWARM_CONFIRM_THRESHOLD and is_rsu_busy:
                    final_state, action, priority = "SwarmConfirmedCongestion", "MandatoryReroute", 1.5
                elif worst_obu_state == "StoppedInTraffic" and (is_rsu_busy or is_externally_triggered):
                    final_state, action, priority = "ConfirmedCongestion", "SuggestReroute", 2
                elif worst_obu_state == "SlowTraffic" and is_rsu_busy:
                    final_state, action, priority = "UnderObservation", "Monitor", 4
                
                # Idle 否決票
                if lane_id in vehicle_idle_veto_cache:
                    if current_time - vehicle_idle_veto_cache[lane_id] <= VEHICLE_IDLE_VETO_SECONDS:
                        final_state, action, priority = "Normal", "Monitor", 5
                    else:
                        del vehicle_idle_veto_cache[lane_id]

                if final_state != previous_state:
                    logger.info(f"📢 [{world_id}] [狀態變更] 路段 {lane_id} 狀態從 {previous_state} 變為 {final_state}")
                
                event_data["last_state"] = final_state
                
                # 加入本地廣播列表
                if action != "Monitor":
                    final_road_status_for_broadcast[lane_id] = {
                        "final_state": final_state, 
                        "action": action, 
                        "priority": priority
                    }
                    
                # 【階段二】判斷是否要分享 Hotspot
                is_locally_triggered = any(OBU_STATE_SEVERITY.get(r.get('state', ''), 0) >= OBU_STATE_SEVERITY["SlowTraffic"] for r in reports if not r.get("source", "").startswith("EXTERNAL_")) or is_rsu_busy

                if is_locally_triggered and action != "Monitor": # 任何非 Monitor 狀態都分享
                    hotspots_to_share[lane_id] = {"status": "CONGESTED", "level": final_state}

        # --- 3. 發布整合後的「本地世界路況快照」給 OBC ---
        payload_to_publish = {"road_status": final_road_status_for_broadcast}
        
        # 【教授註解】Flow 4: 發布到 Data Broker (7883)
        if data_client and data_client.is_connected():
            data_client.publish(status_topic, json.dumps(payload_to_publish), qos=0)
        
        # if final_road_status_for_broadcast: # 減少日誌量
        #     logger.info(f"📡 [{world_id}] 已發布本地路況快照 (含 {len(final_road_status_for_broadcast)} 條路段) 至 {status_topic}")

        # --- 4. 【階段二】處理跨世界 Hotspot 的分享 ---
        current_hotspots_set = set(hotspots_to_share.keys())
        last_published_set = set(last_published_hotspots.keys())

        # --- 分享新增/變化的 Hotspot 給其他 RouteMonitor ---
        for lane_id, data in hotspots_to_share.items():
            level = data["level"]
            if lane_id not in last_published_set or last_published_hotspots.get(lane_id) != level:
                hotspot_payload = {
                    "source_world": world_id, "lane_id": lane_id, "status": data["status"],
                    "congestion_level": level, "timestamp": current_time
                }
                
                # 【教授註解】Flow 7: 發布跨世界情報到 Control Broker (7884)
                if control_client and control_client.is_connected():
                    control_client.publish(INTER_WORLD_TOPIC, json.dumps(hotspot_payload), qos=1)
                
                logger.info(f"🌐 [{world_id}] ---> 分享 Hotspot 至 {INTER_WORLD_TOPIC} (7884): {lane_id} ({level})")
                last_published_hotspots[lane_id] = level

        # --- 分享已解除的 Hotspot 給其他 RouteMonitor ---
        cleared_lanes_to_share = (last_published_set - current_hotspots_set).union(
            set(l for l in lanes_that_became_clear_locally if l in last_published_set)
        )

        for lane_id in cleared_lanes_to_share:
            clear_payload_inter_world = {
                "source_world": world_id, "lane_id": lane_id, "status": "CLEAR", "timestamp": current_time
            }
            
            # 【教授註解】Flow 7: 發布跨世界情報到 Control Broker (7884)
            if control_client and control_client.is_connected():
                control_client.publish(INTER_WORLD_TOPIC, json.dumps(clear_payload_inter_world), qos=1)
                
            logger.info(f"🌐 [{world_id}] ---> 分享解除情報至 {INTER_WORLD_TOPIC} (7884): {lane_id}")
            if lane_id in last_published_hotspots:
                del last_published_hotspots[lane_id]


# 【教授註解】新函式：用於連接 Data Broker (7883)
def on_data_connect(client, userdata, flags, reason_code, properties):
    """
    當成功連接到 Data Broker (7883) 時的回呼函式。
    主要訂閱來自本地世界 OBC 的感知數據 (Flow 3)。
    """
    world_id = userdata["world_id"]
    if reason_code == 0:
        logger.info(f"'{client._client_id}' (Data Broker 7883) 連線成功。")
    else:
        logger.error(f"'{client._client_id}' (Data Broker 7883) 連線失敗, code: {reason_code}")

    # 【教授註解】Flow 3: 訂閱 OBU 感知報告
    client.subscribe(f"worlds/{world_id}/lanes/status/#")
    client.subscribe(f"worlds/{world_id}/vehicles/perception/report")
    logger.info(f"[{world_id}] 已訂閱 (7883) 本地 OBU 應用主題: worlds/{world_id}/#")

# 【教授註解】新函式：用於連接 Control Broker (7884)
def on_control_connect(client, userdata, flags, reason_code, properties):
    """
    當成功連接到 Control Broker (7884) 時的回呼函式。
    主要訂閱來自 SUMO 平台的 RSU 原始數據 (Flow 2) 和跨世界的壅塞情報 (Flow 7)。
    """
    world_id = userdata["world_id"]
    if reason_code == 0:
        logger.info(f"'{client._client_id}' (Control Broker 7884) 連線成功。")
    else:
        logger.error(f"'{client._client_id}' (Control Broker 7884) 連線失敗, code: {reason_code}")

    # 【教授註解】Flow 2: 訂閱 RSU 原始數據
    client.subscribe(f"worlds/{world_id}/rsu/raw_data")
    logger.info(f"[{world_id}] 已訂閱 (7884) 平台 RSU 主題: worlds/{world_id}/rsu/raw_data")

    # 【教授註解】Flow 7: 訂閱跨世界情報
    client.subscribe(INTER_WORLD_TOPIC)
    logger.info(f"[{world_id}] 已訂閱 (7884) 跨世界情報: {INTER_WORLD_TOPIC}")


# 【教授註解】此函式保持單一，同時服務兩個 Client
def on_message(client, userdata, msg):
    """
    處理所有 MQTT 訊息的統一回呼函式。
    它會根據訊息的主題和來源 Broker (7883 或 7884) 將其分派到不同的處理邏輯：
    - 來自 7884 的 RSU 數據和跨世界情報。
    - 來自 7883 的 OBC 感知報告和狀態更新。
    所有收到的數據都會被存入 lane_event_cache 中，供 aggregator 執行緒進行分析。
    """
    topic = msg.topic
    world_id = userdata["world_id"]
    
    try:
        payload = msg.payload.decode('utf-8')
    except UnicodeDecodeError:
        logger.warning(f"無法解碼來自 {topic} 的訊息。")
        return

    default_cache_entry = {"reports": {}, "last_state": "Normal", "is_rsu_busy": False, "rsu_last_update": 0.0, "is_externally_triggered": False}

    with cache_lock:
        current_time = time.time()
        
        # --- 處理 RSU 數據 (Flow 2, 來自 7884) ---
        if topic.endswith('/rsu/raw_data'):
            try:
                rsu_raw_data = json.loads(payload)
                for lane_id, data in rsu_raw_data.items():
                    if not lane_id or lane_id.startswith(':'): continue
                    event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
                    event["is_rsu_busy"] = data.get("vehicle_count", 0) > 0 and data.get("mean_speed", -1) < 5.0
                    event["rsu_last_update"] = current_time
            except Exception as e:
                logger.error(f"處理 RSU 原始數據時發生錯誤 (來自 7884): {e}")
        
        # --- 處理 OBU 感知報告 (Flow 3, 來自 7883) ---
        elif topic.endswith('/vehicles/perception/report'):
            try:
                data = json.loads(payload)
                lane_id, veh_id, obu_state = data.get("lane_id"), data.get("veh_id"), data.get("obu_state")
                if not lane_id or not veh_id or not obu_state or lane_id.startswith(':'): return
                event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
                event["reports"][veh_id] = {"state": obu_state, "timestamp": current_time, "source": "LOCAL_OBU"}
            except Exception as e:
                logger.error(f"處理 OBU 報告時出錯 (來自 7883): {e}")
                
        # --- 處理 OBU 'busy'/'idle' 狀態 (Flow 3, 來自 7883) ---
        elif '/lanes/status/' in topic:
            try:
                lane_id, data = topic.split('/')[-1], json.loads(payload)
                status, source = data.get("status", "").lower(), data.get("source", "UnknownVehicle")
                
                if status == "idle" and ("Vehicle" in source or "Sensor" in source):
                    vehicle_idle_veto_cache[lane_id] = time.time()
                
                elif status == "busy":
                    logger.info(f"🔥 [{world_id}] 收到來自 OBU ({source}) 的高優先級 'busy' 警告: {lane_id}")
                    event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
                    
                    report_id = f"LOCAL_OBC_STUCK_{source}" 
                    event["reports"][report_id] = {
                        "state": "StoppedInTraffic", # 模擬成嚴重壅塞
                        "timestamp": current_time,
                        "source": f"LOCAL_OBC_STUCK" # 標記為本地來源
                    }

            except Exception as e:
                logger.error(f"處理車道狀態訊息時出錯 ({topic}, 來自 7883): {e}")

        # --- 處理跨世界 Hotspot 情報 (Flow 7, 來自 7884) ---
        elif topic == INTER_WORLD_TOPIC:
            try:
                data = json.loads(payload)
                source_world = data.get("source_world")
                
                if source_world == world_id: return # 忽略自己
                
                lane_id = data.get("lane_id")
                external_status = data.get("status")
                if not lane_id: return

                event = lane_event_cache.setdefault(lane_id, default_cache_entry.copy())
                external_report_id = f"EXTERNAL_{source_world}_{lane_id}"

                if external_status == "CONGESTED":
                    event["reports"][external_report_id] = {
                        "state": "StoppedInTraffic", # 內化為基礎壅塞
                        "timestamp": current_time,
                        "source": f"EXTERNAL_{source_world}"
                    }
                    logger.info(f"🌐 [{world_id}] <--- 內化來自 [{source_world}] 的壅塞情報 (7884): {lane_id}")
                
                elif external_status == "CLEAR":
                    if external_report_id in event["reports"]:
                        del event["reports"][external_report_id]
                        logger.info(f"🌐 [{world_id}] <--- 內化來自 [{source_world}] 的解除情報 (7884): {lane_id}")

            except Exception as e:
                logger.error(f"處理跨世界情報時出錯 ({payload}, 來自 7884): {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Route Monitor for a specific SUMO world")
    parser.add_argument('--world-id', type=str, required=True, help='The ID of the world this monitor belongs to')
    args = parser.parse_args()
    world_id = args.world_id

    # 【教授註解】創建兩個 Client ID
    data_client_id = f"RouteMonitor_Data_{world_id}"
    control_client_id = f"RouteMonitor_Control_{world_id}"
    logger.info(f"RouteMonitor for world '{world_id}' is starting with Client IDs '{data_client_id}' (7883) and '{control_client_id}' (7884)...")
    
    # 【教授註解】實例化 Data Client (7883)
    data_client = mqtt.Client(client_id=data_client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    data_client.user_data_set({"world_id": world_id, "broker_port": 7883})
    data_client.on_connect = on_data_connect
    data_client.on_message = on_message # 共享 on_message

    # 【教授註解】實例化 Control Client (7884)
    control_client = mqtt.Client(client_id=control_client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    control_client.user_data_set({"world_id": world_id, "broker_port": 7884})
    control_client.on_connect = on_control_connect
    control_client.on_message = on_message # 共享 on_message
    
    aggregator_thread = None

    try:
        # 【教授註解】連接兩個 Broker
        data_client.connect("localhost", 7883, 60)
        control_client.connect("localhost", 7884, 60)
        
        # 【教授註解】將兩個 Client 都傳入聚合器
        aggregator_thread = threading.Thread(target=aggregator_and_publisher, args=(data_client, control_client, world_id,), daemon=True)
        aggregator_thread.start()
        
        logger.info(f"RouteMonitor for '{world_id}' has started.")
        
        # 【教授註解】啟動兩個 Client 的 network loop
        data_client.loop_start()
        control_client.loop_start()
        
        # 保持主執行緒存活
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info(f"收到中斷指令，正在為 '{world_id}' 執行清理...")
    except Exception as e:
        logger.error(f"RouteMonitor 發生未預期錯誤: {e}")
    finally:
        logger.info("正在發布最終的 CLEAR 快照...")
        
        # --- 清理 Data Broker (7883) ---
        status_topic = f"worlds/{world_id}/global_road_status"
        clear_payload_local = {"road_status": {}}
        try:
            if data_client.is_connected():
                data_client.publish(status_topic, json.dumps(clear_payload_local), qos=1, retain=False)
                logger.info(f"已發布本地 CLEAR 快照至 {status_topic} (7883)")
        except Exception as pub_e:
            logger.error(f"發布最終本地 CLEAR 快照 (7883) 時失敗: {pub_e}")

        # --- 清理 Control Broker (7884) ---
        lanes_to_clear_globally = []
        with cache_lock:
            lanes_to_clear_globally = list(lane_event_cache.keys())
        clear_payload_global = {"source_world": world_id, "status": "CLEAR", "timestamp": time.time()}

        try:
            if control_client.is_connected():
                for lane_id in lanes_to_clear_globally:
                    clear_payload_global["lane_id"] = lane_id
                    control_client.publish(INTER_WORLD_TOPIC, json.dumps(clear_payload_global), qos=1)
                if lanes_to_clear_globally:
                    logger.info(f"已發布 {len(lanes_to_clear_globally)} 條跨世界 CLEAR 情報至 {INTER_WORLD_TOPIC} (7884)")
            else:
                logger.warning("MQTT Control Client (7884) 未連線，無法發布最終跨世界 CLEAR 情報。")
        except Exception as pub_e:
            logger.error(f"發布最終跨世界 CLEAR 情報 (7884) 時失敗: {pub_e}")
        
        logger.info("清理完成，正在斷開連線...")
        
        # 【教授註解】斷開兩個 Client
        if data_client.is_connected():
            data_client.loop_stop()
            data_client.disconnect()
            
        if control_client.is_connected():
            control_client.loop_stop()
            control_client.disconnect()
            
        logger.info(f"RouteMonitor for '{world_id}' 已安全關閉。")
