# # # # traffic_simulation/main_world_sim.py
# # # # (實現雙 Broker 架構 - Control:7884, Data:7883)
# # # 獨立兩個世界可以運行
# # #可以關閉透過後端交換訊息
# # #可以封鎖壅塞路段

# import os
# import sys
# import time
# import json
# import queue
# import threading
# import paho.mqtt.client as mqtt
# from paho.mqtt.properties import Properties
# from paho.mqtt.packettypes import PacketTypes
# import statistics
# # import math # 似乎未使用
# import traceback
# import signal
# import xml.etree.ElementTree as ET
# from xml.dom import minidom

# # --- SUMO 環境設定 ---
# if 'SUMO_HOME' in os.environ:
#     tools_path = os.path.join(os.environ['SUMO_HOME'], 'tools')
#     if tools_path not in sys.path:
#         sys.path.insert(0, tools_path)
# try:
#     import traci
# except ImportError:
#     print("錯誤：無法導入 traci 模組。")
#     print("請確保 SUMO 已正確安裝，並且 SUMO_HOME 環境變數已設置，")
#     print("或者 $SUMO_HOME/tools 目錄已添加到 PYTHONPATH。")
#     sys.exit(1)


# # --- 導入自訂模組 ---
# try:
#     from traffic_Vehicle import Vehicle
#     from garbage_collector import garbage_collector
#     from traffic_Vehicle_dispatcher import Vehicle_dispatcher
# except ImportError as e:
#     print(f"錯誤：無法導入自訂模組: {e}")
#     print("請確保 traffic_Vehicle.py, garbage_collector.py, traffic_Vehicle_dispatcher.py 與此腳本在同一目錄下。")
#     sys.exit(1)


# # --- 外部 Hotspot 主題 ---
# INTER_WORLD_TOPIC = "system/inter_world_hotspots"
# # --- 預設允許的車輛類型 ---
# DEFAULT_ALLOWED_VCLASSES = ["passenger", "truck", "bus", "motorcycle"]
# # --- (顏色常數) ---
# CLOSED_LANE_COLOR = (255, 0, 0, 255) # (R, G, B, Alpha) - 紅色


# # ============================================================ #
# # 輔助函式 (保持不變)
# # ============================================================ #
# def get_edge_id_from_lane_id(lane_id):
#     """ 從 lane_id (如 'edge123_0') 提取 edge_id ('edge123') """
#     if not lane_id or lane_id.startswith(':'): return None
#     try: return lane_id.rsplit('_', 1)[0]
#     except Exception: return None

# def retrieve_vehicle_state(traci_instance, veh_id, current_step):
#     """ 從 SUMO 獲取指定車輛的詳細狀態，增加健壯性。 """
#     try:
#         x, y = traci_instance.vehicle.getPosition(veh_id)
#         lon, lat = traci_instance.simulation.convertGeo(x, y)
#         laneID = traci_instance.vehicle.getLaneID(veh_id)
#         vehicleLength = traci_instance.vehicle.getLength(veh_id)
#         lanePosition = traci_instance.vehicle.getLanePosition(veh_id)
#         speed = traci_instance.vehicle.getSpeed(veh_id)
#         laneLength = 0.0; travelTime = -1.0; maxSpeed = 0.0
#         if laneID and not laneID.startswith(':'):
#             try:
#                 laneLength = traci_instance.lane.getLength(laneID)
#                 travelTime = traci_instance.lane.getTraveltime(laneID)
#                 maxSpeed = traci_instance.lane.getMaxSpeed(laneID)
#             except traci.TraCIException: pass
#         current_route = []; destination_edge = None
#         try:
#             current_route = traci_instance.vehicle.getRoute(veh_id)
#             destination_edge = current_route[-1] if current_route else None
#         except traci.TraCIException: pass
#         next_tls_info = None
#         try:
#             tls_raw_data = traci_instance.vehicle.getNextTLS(veh_id)
#             if tls_raw_data:
#                 tls = tls_raw_data[0]
#                 next_tls_info = {"id": tls[0], "distance": tls[2], "state": tls[3]}
#         except traci.TraCIException: pass
#         connectedLanes = []
#         if laneID and laneID.startswith(":"):
#             try:
#                 links = traci_instance.lane.getLinks(laneID, False)
#                 for link in links: connectedLanes.append(link[0])
#             except traci.TraCIException: pass
#         vehicleState = dict(lat=lat, lon=lon, laneID=laneID, speed=speed, travelTime=travelTime,
#                             lanePosition=lanePosition, vehicleLength=vehicleLength,
#                             connectedLanes=connectedLanes, laneLength=laneLength,
#                             currentRoute=current_route, destinationEdge=destination_edge,
#                             maxSpeed=maxSpeed, current_step=current_step, next_tls=next_tls_info)
#         return vehicleState
#     except traci.TraCIException as e: return None

# def setup_dispatcher(config, world_id):
#     """ 初始化並連接到虛擬 Broker (7884) 的車輛分派器。 """
#     print(f"[{world_id}] 正在初始化車輛分派器 (Vehicle Dispatcher)...")
#     dispatcher = Vehicle_dispatcher()
#     computers = dict(pc1='127.0.0.1')
#     dispatcher.physicalComputers = computers
#     pc_list = list(dispatcher.physicalComputers.keys())
#     try:
#         # 【教授註記】Vehicle_dispatcher 預設連接 7884 (Control Broker)
#         dispatcher.connect(config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'], world_id)
#         print(f"[{world_id}] 車輛分派器連接成功 (7884)。")
#     except Exception as e:
#         print(f"❌ [{world_id}] 車輛分派器連接失敗 (7884): {e}")
#         return None, []
#     return dispatcher, pc_list

# def start_sumo(config, traci_port):
#     """ 啟動 SUMO 模擬實例。 """
#     world_id_log = config.get('world_id', 'SIM')
#     print(f"[{world_id_log}] 正在啟動 SUMO，使用 TraCI Port: {traci_port}...")
#     sumo_binary = config.get('SUMO_BINARY', '/usr/local/bin/sumo-gui')
#     config_file = config.get('SUMO_CONFIG_FILE')
#     if not config_file or not os.path.exists(config_file): raise FileNotFoundError(f"SUMO 配置文件未找到: {config_file}")
#     if not os.path.exists(sumo_binary):
#         from shutil import which
#         if which(sumo_binary) is None: raise FileNotFoundError(f"SUMO 執行檔未找到: {sumo_binary}")
#         else: sumo_binary = which(sumo_binary)
#     sumoCmd = [ sumo_binary, "-c", config_file, "--time-to-teleport", "-1", "--ignore-route-errors", "true",
#                 "--no-step-log", "true", "--no-warnings", "true",
#                 "--log", f"sumo_log_{world_id_log}_{time.strftime('%Y%m%d_%H%M%S')}.txt", ]
#     try:
#         traci.start(sumoCmd, port=traci_port, numRetries=20, label=f"TraCI_{world_id_log}")
#         print(f"[{world_id_log}] TraCI.start 成功，已連接到 SUMO。")
#     except Exception as e:
#         print(f"❌ [{world_id_log}] Traci.start 失敗: {e}")
#         raise

# def collect_and_prepare_dispatch_data(current_step, config, vehicle_dict, pc_list, pc_counter):
#     """ 收集所有應在此步長發布狀態的車輛，並分配 OBC (pc)。 """
#     vehicles_to_dispatch_this_step = []
#     vehicle_states_this_step = {}
#     publish_period = config['PUBLISH_PERIOD_STEPS']
#     try: current_vehicle_ids = set(traci.vehicle.getIDList())
#     except traci.TraCIException: return [], {}, pc_counter
#     for veh_id in current_vehicle_ids:
#         if veh_id not in vehicle_dict: vehicle_dict[veh_id] = Vehicle(veh_id)
#         vehicle = vehicle_dict[veh_id]
#         if vehicle.physicalComputerMapping is None and pc_list:
#             pc_index = pc_counter % len(pc_list)
#             vehicle.physicalComputerMapping = pc_list[pc_index]
#             pc_counter += 1
#         should_publish = (publish_period == 1) or \
#                          (vehicle.last_publish_step == 0 and current_step >= 1) or \
#                          (current_step >= vehicle.last_publish_step + publish_period)
#         if should_publish: vehicles_to_dispatch_this_step.append(veh_id)
#     vehicles_to_actually_dispatch = []
#     if vehicles_to_dispatch_this_step:
#         for veh_id in vehicles_to_dispatch_this_step:
#             state = retrieve_vehicle_state(traci, veh_id, current_step)
#             if state is not None:
#                 vehicle_states_this_step[veh_id] = state
#                 vehicles_to_actually_dispatch.append(veh_id)
#                 if veh_id in vehicle_dict: vehicle_dict[veh_id].last_publish_step = current_step
#     return vehicles_to_actually_dispatch, vehicle_states_this_step, pc_counter

# def wait_for_acks(dispatcher, target_count):
#     """ 等待 OBC 回傳 ACK，確保同步。 """
#     if target_count <= 0 or not dispatcher: return
#     timeout = config.get('ACK_TIMEOUT', 5.0)
#     start_time = time.perf_counter()
#     waited_time = 0
#     sleep_interval = 0.005
#     while dispatcher.ack_count < target_count and waited_time < timeout:
#         time.sleep(sleep_interval)
#         waited_time = time.perf_counter() - start_time
#     if dispatcher.ack_count < target_count: print(f"⚠️ [{config.get('world_id', 'SIM')}] 等待 ACK 超時！預期 {target_count}, 收到 {dispatcher.ack_count}。")
#     dispatcher.ack_count = 0

# def update_rtf_monitor(rtf_state, config, current_step, time_elapsed_for_step, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, step_timings, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data):
#     """ 更新 RTF 效能監控數據，但只打印簡略信息。 """
#     world_id = config.get('world_id', 'SIM')
#     if not rtf_state.get('active', False) and current_step >= config['SIMULATION_START_STEP']:
#         rtf_state['active'] = True
#     if rtf_state.get('active', False):
#         current_rtf = 1.0 / time_elapsed_for_step if time_elapsed_for_step > 1e-9 else float('inf')
#         rtf_data.append(current_rtf)
#         current_vehicle_count = 0; halting_vehicles = 0
#         try:
#             current_vehicle_count = traci.vehicle.getIDCount()
#             if current_vehicle_count > 0:
#                 all_vehicle_ids = traci.vehicle.getIDList()
#                 halting_vehicles = sum(1 for veh_id in all_vehicle_ids if traci.vehicle.getSpeed(veh_id) < 0.1)
#         except traci.TraCIException:
#             current_vehicle_count = len(vehicleDict); halting_vehicles = 0
#         congestion_percentage = (halting_vehicles / current_vehicle_count * 100) if current_vehicle_count > 0 else 0.0
#         if current_vehicle_count >= 0:
#             congestion_data.append(congestion_percentage)
#             halting_vehicle_data.append(halting_vehicles)
#             vehicle_count_data.append(current_vehicle_count)
        
#         # --- 計算部分仍然保留 ---
#         t0 = step_timings.get('T0_SumoStep', 0); t1 = step_timings.get('T1_DataCollection', 0)
#         t2 = step_timings.get('T2_RoundTripWait', 0); t3 = step_timings.get('T3_Rerouting', 0)
#         t4 = step_timings.get('T4_SimControl', 0); measured_total = t0 + t1 + t2 + t3 + t4
#         script_overhead = max(0.0, time_elapsed_for_step - measured_total)
#         processed_vehicles = step_timings.get('Processed_Vehicles', 0)
#         if processed_vehicles > 0:
#             t0_avg = t0 / processed_vehicles; t1_avg = t1 / processed_vehicles
#             t2_avg = t2 / processed_vehicles; overhead_avg = script_overhead / processed_vehicles
#             if all(t >= 0 for t in [t0_avg, t1_avg, t2_avg, overhead_avg]):
#                 t0_per_vehicle_data.append(t0_avg * 1000); t1_per_vehicle_data.append(t1_avg * 1000)
#                 t2_per_vehicle_data.append(t2_avg * 1000); overhead_per_vehicle_data.append(overhead_avg * 1000)
#     return rtf_state


# def generate_xml_report(filename, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_data, t1_data, t2_data, overhead_data, t3_data, reroute_counts, total_reroutes, total_steps):
#     """ 生成 XML 格式的效能報告。 """
#     root = ET.Element("PerformanceReport")
#     summary_node = ET.SubElement(root, "MacroscopicSummary")
#     if rtf_data:
#         rtf_node = ET.SubElement(summary_node, "RealTimeFactor")
#         ET.SubElement(rtf_node, "Unit").text = "Steps_per_Second"
#         try:
#             ET.SubElement(rtf_node, "Mean").text = f"{statistics.mean(rtf_data):.4f}"
#             ET.SubElement(rtf_node, "Median").text = f"{statistics.median(rtf_data):.4f}"
#             ET.SubElement(rtf_node, "Max").text = f"{max(rtf_data):.4f}"
#             ET.SubElement(rtf_node, "Min").text = f"{min(rtf_data):.4f}"
#         except (statistics.StatisticsError, ValueError): pass
#     if vehicle_count_data:
#         vc_node = ET.SubElement(summary_node, "VehicleCount")
#         try:
#             ET.SubElement(vc_node, "Mean").text = f"{statistics.mean(vehicle_count_data):.2f}"
#             ET.SubElement(vc_node, "Max").text = f"{max(vehicle_count_data)}"
#         except (statistics.StatisticsError, ValueError): pass
#     reroute_summary_node = ET.SubElement(summary_node, "ReroutingOverallStats")
#     ET.SubElement(reroute_summary_node, "TotalReroutesProcessed").text = str(total_reroutes)
#     avg_req_per_step = total_reroutes / total_steps if total_steps > 0 else 0
#     ET.SubElement(reroute_summary_node, "AverageRequestsPerSimulationStep").text = f"{avg_req_per_step:.4f}"
#     micro_summary_node = ET.SubElement(root, "MicroscopicSummary")
#     micro_summary_node.set("Unit", "Milliseconds")
#     def add_stats_node(parent, name, data):
#         mean = 0.0
#         if data:
#             node = ET.SubElement(parent, name)
#             try:
#                 mean = statistics.mean(data)
#                 ET.SubElement(node, "Mean").text = f"{mean:.4f}"
#                 if len(data) > 1: ET.SubElement(node, "StdDev").text = f"{statistics.stdev(data):.4f}"
#                 else: ET.SubElement(node, "StdDev").text = "N/A"
#             except (statistics.StatisticsError, ValueError): pass
#         return mean
#     mean_t0 = add_stats_node(micro_summary_node, "T0_SUMO_Internal_Step", t0_data)
#     mean_t1 = add_stats_node(micro_summary_node, "T1_DataCollection", t1_data)
#     mean_t2 = add_stats_node(micro_summary_node, "T2_RoundTripWait", t2_data)
#     mean_overhead = add_stats_node(micro_summary_node, "T_Overhead", overhead_data)
#     if any(m > 0 for m in [mean_t0, mean_t1, mean_t2, mean_overhead]):
#         total_node = ET.SubElement(micro_summary_node, "Total_Per_Vehicle_Time")
#         ET.SubElement(total_node, "Mean").text = f"{mean_t0 + mean_t1 + mean_t2 + mean_overhead:.4f}"
#     if t3_data:
#         t3_batch_node = ET.SubElement(micro_summary_node, "T3_Rerouting_Batch")
#         t3_batch_node.set("Description", "Time to process a batch of reroute requests per step")
#         try:
#             mean_t3_batch = statistics.mean(t3_data)
#             ET.SubElement(t3_batch_node, "Mean").text = f"{mean_t3_batch:.4f}"
#             if len(t3_data) > 1: ET.SubElement(t3_batch_node, "StdDev").text = f"{statistics.stdev(t3_data):.4f}"
#             else: ET.SubElement(t3_batch_node, "StdDev").text = "N/A"
#             ET.SubElement(t3_batch_node, "Max").text = f"{max(t3_data):.4f}"; ET.SubElement(t3_batch_node, "Min").text = f"{min(t3_data):.4f}"
#             total_t3_time_ms = sum(t3_data)
#             avg_per_veh_ms = total_t3_time_ms / total_reroutes if total_reroutes > 0 else 0
#             per_veh_node = ET.SubElement(micro_summary_node, "T3_Rerouting_PerVehicle")
#             ET.SubElement(per_veh_node, "Mean").text = f"{avg_per_veh_ms:.6f}"
#         except (statistics.StatisticsError, ValueError): pass
#     xml_string = ET.tostring(root, 'utf-8');
#     try: pretty_xml_string = minidom.parseString(xml_string).toprettyxml(indent="    ")
#     except Exception: pretty_xml_string = xml_string.decode('utf-8')
#     try:
#         with open(filename, "w", encoding='utf-8') as f: f.write(pretty_xml_string)
#         print(f"\n✅ [{config.get('world_id', 'SIM')}] 效能報告已成功生成至檔案: {filename}")
#     except IOError as e: print(f"\n❌ [{config.get('world_id', 'SIM')}] 無法寫入效能報告檔案 {filename}: {e}")



# def print_performance_report(config, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data, t3_per_step_data, reroute_counts_per_step, total_reroutes_processed, total_simulation_steps):
#     """ 在終端打印最終的效能報告。 """
#     world_id = config.get('world_id', 'SIM'); print("\n" + "="*50 + f"\n===== [{world_id}] 📊 最終效能綜合報告 📊 =====\n" + "="*50)
#     if not rtf_data: print("未收集到足夠的 RTF 測試數據，無法生成報告。" + "\n" + "="*50); return

#     def print_stats(label, data, unit=""):
#         if not data: print(f"   - {label}: 無數據"); return
#         try:
#             mean = statistics.mean(data)
#             median = statistics.median(data)
#             maximum = max(data)
#             minimum = min(data)
#             print(f"   - {label}:")
#             print(f"     - 平均值 (Mean):   {mean:.4f}{unit}")
#             print(f"     - 中位數 (Median): {median:.4f}{unit}")
#             print(f"     - 最高/最低:       {maximum:.4f}{unit} / {minimum:.4f}{unit}")
#             if len(data) > 1:
#                  stdev = statistics.stdev(data)
#                  print(f"     - 標準差 (StdDev): {stdev:.4f}{unit}")
#             else:
#                  print(f"     - 標準差 (StdDev): N/A (數據點不足)")
#         except (statistics.StatisticsError, ValueError, TypeError) as e: print(f"   - 計算 {label} 統計時發生錯誤: {e}")

#     print("\n---  瞬時RTF (步/秒) 效能 ---"); print_stats("RTF", rtf_data, unit=" Steps/Sec")
#     print("\n---  車輛數統計 (測試期間) ---")
#     if vehicle_count_data:
#         try: print(f"   - 平均車輛數: {statistics.mean(vehicle_count_data):.2f}"); print(f"   - 最高車輛數:   {max(vehicle_count_data)}")
#         except (statistics.StatisticsError, ValueError) as e: print(f"   - 計算車輛數統計時發生錯誤: {e}")
#     else: print("   - 無車輛數數據")
#     print("\n---  壅塞率 (%) 統計 ---"); print_stats("壅塞率", congestion_data, unit="%")
#     print("\n---  停止車輛數統計 ---")
#     if halting_vehicle_data:
#         try: print(f"   - 平均停止車輛數: {statistics.mean(halting_vehicle_data):.2f}"); print(f"   - 最高停止車輛數:   {max(halting_vehicle_data)}")
#         except (statistics.StatisticsError, ValueError) as e: print(f"   - 計算停止車輛數統計時發生錯誤: {e}")
#     else: print("   - 無停止車輛數數據")

#     print("\n---  單車處理效能穩定性 (毫秒/輛) ---")
#     if t0_per_vehicle_data:
#         def print_perf_stats(label, data):
#             mean = 0.0; stdev_str = "N/A"
#             if data:
#                 try: 
#                     mean = statistics.mean(data)
#                     if len(data) > 1: stdev_str = f"{statistics.stdev(data):.4f} ms"
#                 except (statistics.StatisticsError, ValueError) : pass # 捕獲異常
#             print(f"   - {label}: 平均值: {mean:.4f} ms, 標準差: {stdev_str}")
        
#         try:
#             print_perf_stats("T0 (SUMO內部計算)", t0_per_vehicle_data)
#             print_perf_stats("T1 (SUMO資訊擷取)", t1_per_vehicle_data)
#             print_perf_stats("T2 (分派至OBC並等待ACK)", t2_per_vehicle_data)
#             print_perf_stats("T_Overhead (腳本行政開銷)", overhead_per_vehicle_data)
#             all_data_present = all([t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data])
#             if all_data_present:
#                 try:
#                     total_avg = sum(statistics.mean(d) for d in [t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data])
#                     print(f"   - -------------------------------------------------")
#                     print(f"   - 單車平均總耗時:                      {total_avg:.4f} ms")
#                 except statistics.StatisticsError: print("   - 無法計算單車平均總耗時 (數據不足)")
#             else: print("   - 部分效能數據缺失，無法計算單車平均總耗時。")
#         except (ValueError) as e: print(f"   - 計算單車效能統計時發生錯誤: {e}")
#     else: print("   - 未收集到單車處理時間數據。")

#     print("\n---  T3 Reroute 請求處理效能 ---")
#     if not t3_per_step_data: print("   - 模擬期間未執行任何 Reroute 操作。")
#     else:
#         try:
#             print(f"  [總體統計]"); print(f"   - 模擬期間總處理請求數: {total_reroutes_processed} 次")
#             avg_req_per_step = total_reroutes_processed / total_simulation_steps if total_simulation_steps > 0 else 0
#             print(f"   - 全域平均請求數:       {avg_req_per_step:.4f} 次 / 每個模擬步長")
#             print(f"\n  [T3 批次處理耗時 (毫秒/批次)]")
#             mean_t3=statistics.mean(t3_per_step_data); max_t3=max(t3_per_step_data); min_t3=min(t3_per_step_data)
#             print(f"   - 平均耗時: {mean_t3:.4f} ms/批次"); print(f"   - 最長/最短: {max_t3:.4f} / {min_t3:.4f} ms")
#             if len(t3_per_step_data) > 1: print(f"   - 標準差:   {statistics.stdev(t3_per_step_data):.4f} ms")
#             total_t3_time_ms = sum(t3_per_step_data)
#             avg_per_vehicle_ms = total_t3_time_ms / total_reroutes_processed if total_reroutes_processed > 0 else 0
#             print(f"\n  [單車 Reroute 平均耗時 (毫秒/輛)]"); print(f"   - 平均耗時: {avg_per_vehicle_ms:.6f} ms/輛 (總耗時 / 總請求數)")
#         except (statistics.StatisticsError, ValueError) as e: print(f"   - 計算 Reroute 效能統計時發生錯誤: {e}")

#     print("\n" + "="*50 + "\n")
#     generate_xml_report(config['OUTPUT_XML_FILE'], rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data, t3_per_step_data, reroute_counts_per_step, total_reroutes_processed, total_simulation_steps)


# def connect_mqtt(host, port, client_id, on_message_callback, topics_to_subscribe, smart_rerouting_enabled, world_id):
#     """ 
#     【教授修改】此函式現在是一個通用的 MQTT 連接器。
#     它會連接到指定的 host:port，並訂閱指定的 topics。
#     """
#     print(f"[{world_id}] 正在連接 MQTT Broker {host}:{port} (Client ID: {client_id})...")
#     client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
#     client.user_data_set({"world_id": world_id})
#     client.on_message = on_message_callback

#     # --- MQTT 連接/斷開回調 (修正 on_disconnect 參數) ---
#     def on_connect(client, userdata, flags, rc, properties):
#         if rc == 0:
#             print(f"✅ MQTT Client '{client._client_id}' ({host}:{port}) 連接成功。")
#             for topic in topics_to_subscribe: 
#                 print(f"   -> 訂閱: {topic}")
#                 client.subscribe(topic)
            
#             # 【教授修改 v7.1】: 移除 Main World 專用的廣播邏輯
#             # (smart_rerouting_enabled 參數將由 sub_world 的 main() 傳入 None)
#             if smart_rerouting_enabled is not None: 
#                 # 這段邏輯理論上在 sub_world 中不應該被觸發
#                 if userdata["world_id"] == "main_world": # 雖然不應觸發，但保留此檢查以防萬一
#                     print(f"📢 正在廣播全域設定：智慧 Reroute -> {smart_rerouting_enabled}"); 
#                     config_payload = json.dumps({"smart_rerouting_enabled": smart_rerouting_enabled}); 
#                     client.publish("system/config", config_payload, qos=1, retain=True)

#         else:
#             try: reason_name = mqtt.ReasonCodes(rc).getName()
#             except: reason_name = "Unknown"
#             print(f"❌ MQTT Client '{client._client_id}' ({host}:{port}) 連接失敗，返回碼: {rc} ({reason_name})")

#     def on_disconnect(client, userdata, flags, rc, properties): # 修正參數
#          if rc != 0:
#              try: reason_name = mqtt.ReasonCodes(rc).getName()
#              except: reason_name = "Unknown"
#              print(f"⚠️ MQTT Client '{client._client_id}' ({host}:{port}) 意外斷開連接，返回碼: {rc} ({reason_name})。")

#     client.on_connect = on_connect
#     client.on_disconnect = on_disconnect

#     try:
#         client.connect(host, port, keepalive=60)
#         client.loop_start()
#         return client
#     except Exception as e:
#         print(f"❌ MQTT Client '{client_id}' ({host}:{port}) 連接時發生錯誤: {e}")
#         return None


# # --- 全局變量 ---
# config = {}
# vehicleDict = {}

# def main():
#     # --- !! 配置區 !! ---
#     # 【教授修改】: 配置為 sub_world
#     # world_id = "main_world"
#     # traci_port = 8813
#     # initial_routes_file = None

#     world_id = "sub_world"      # <--- 設定為 sub_world
#     traci_port = 8814           # <--- 設定為 sub_world 的端口
#     initial_routes_file = None  # <--- 假設 .sumocfg 已載入 .rou.xml
#     # --- !! 修改結束 !! ---

#     # --- 基本設定 (使用全局 config) ---
#     global config
#     config = {
#         'world_id': world_id,
#         'PHYSICAL_BROKER': {'host': '127.0.0.1', 'port': 7883}, # Data Broker
#         'VIRTUAL_BROKER': {'host': '127.0.0.1', 'port': 7884}, # Control Broker
#         'SUMO_BINARY': "/usr/local/bin/sumo-gui", # 固定使用 GUI
#         'SUMO_CONFIG_FILE': os.path.join(os.path.dirname(os.path.abspath(__file__)), "osm.sumocfg_incident.xml"), # <--- 使用 sub_world 的 config
#         'TRACI_PORT': traci_port,
#         'PUBLISH_PERIOD_STEPS': 1,
#         'RTF_PRINT_INTERVAL_STEPS': 100, # 減少打印頻率
#         'RSU_PUBLISH_INTERVAL_STEPS': 5,
#         'SIMULATION_START_STEP': 10,
#         'SIMULATION_END_STEP': 3600,
#         'OUTPUT_XML_FILE': f'report_{world_id}_{time.strftime("%Y%m%d_%H%M%S")}.xml',
#         'ACK_TIMEOUT': 5.0
#     }
#     # --- 功能開關 ---
#     ENABLE_PERCEPTION_SYSTEM = True
#     ENABLE_SMART_REROUTING = True
#     ENABLE_EXTERNAL_CONTROL = True # 開啟外部控制功能
#     # --- !! 配置結束 !! ---


#     print(f"=================================================\n🚀 模擬世界啟動中... World ID: [{world_id}], TraCI Port: [{traci_port}]\n=================================================")
    
#     # --- 初始化 Dispatcher (連接 7884 Control Broker) ---
#     vehicle_dispatcher, pc_list = setup_dispatcher(config, world_id)
#     if vehicle_dispatcher is None:
#         print(f"❌ [{world_id}] 無法初始化 Vehicle Dispatcher (7884)，終止模擬。")
#         return

#     # --- 啟動 SUMO ---
#     try:
#         start_sumo(config, config['TRACI_PORT'])
#         print(f"✅ [{world_id}] SUMO 模擬已啟動！")
#     except Exception as e:
#         print(f"❌ [{world_id}] 啟動 SUMO 失敗: {e}")
#         if vehicle_dispatcher and hasattr(vehicle_dispatcher, 'mqttc') and vehicle_dispatcher.mqttc.is_connected():
#             vehicle_dispatcher.disconnect()
#         return

#     # --- 初始化 Queues 和狀態 ---
#     reroute_requests_queue = queue.Queue()
#     # world_registry = set() # 【教授修改 v7.1】: sub_world 不需要維護註冊表
#     simulation_control_queue = queue.Queue() # 用於緩衝外部 Edge 控制指令
#     externally_closed_edges = set()          # 追蹤因外部指令而關閉的 Edge

#     # --- MQTT 指令回調函式 (可被多個 Client 共用) ---
#     def on_command_message(client, userdata, msg):
#         """ 
#         處理來自 MQTT 的指令 (可來自 7883 或 7884)。
#         它會根據 'msg.topic' 來區分任務。
#         """
#         try:
#             current_world_id = userdata["world_id"]
#             payload_str = msg.payload.decode('utf-8')
#             if not payload_str: return
#             payload = json.loads(payload_str)

#             # (Flow 5) Reroute 請求 (來自 7883 Data Broker)
#             expected_reroute_topic = f"worlds/{current_world_id}/reroute_request"
#             if msg.topic == expected_reroute_topic:
#                 if isinstance(payload, dict) and 'veh_id' in payload:
#                     reroute_requests_queue.put(payload)

#             # 【教授修改 v7.1】: 移除 (Flow 7) 的監聽邏輯
#             # (Flow 7) 世界註冊 (sub_world 不處理這個)
#             # elif msg.topic == "system/worlds/register":
#             #     pass # sub_world 不需要處理其他世界的註冊

#             # (Flow 8) 外部 Hotspot 情報 (來自 7884 Control Broker)
#             elif msg.topic == INTER_WORLD_TOPIC and ENABLE_EXTERNAL_CONTROL:
#                 source_world = payload.get("source_world")
#                 # 確保不會處理自己發出的 Hotspot
#                 if source_world and isinstance(source_world, str) and source_world != current_world_id:
#                     lane_id = payload.get("lane_id")
#                     status = payload.get("status")
#                     edge_id = get_edge_id_from_lane_id(lane_id)

#                     if edge_id and status in ["CONGESTED", "CLEAR"]:
#                         command = None
#                         reason = f"EXTERNAL_{status}"
#                         if status == "CONGESTED":
#                             command = "CLOSE_EDGE"
#                             reason = f"EXTERNAL_CONGESTED_{payload.get('congestion_level', 'UNKNOWN')}"
#                         elif status == "CLEAR":
#                             command = "OPEN_EDGE"

#                         if command:
#                             control_command = {"command": command, "edge_id": edge_id, "source_world": source_world, "reason": reason}
#                             simulation_control_queue.put(control_command)

#         except (json.JSONDecodeError, UnicodeDecodeError, IndexError, KeyError, AttributeError) as e:
#             print(f"[{userdata.get('world_id','?')}] 處理指令時發生錯誤 ({msg.topic}, Payload: '{msg.payload.decode('utf-8', errors='ignore')}'): {e}")


#     # --- 【教授修改】建立 Data Client (7883) 的訂閱列表 ---
#     topics_to_subscribe_data = []
#     if ENABLE_SMART_REROUTING: 
#         # (Flow 5)
#         topics_to_subscribe_data.append(f"worlds/{world_id}/reroute_request")

#     # --- 【教授修改】連接 Data Client (7883) ---
#     command_client = connect_mqtt(
#         config['PHYSICAL_BROKER']['host'], config['PHYSICAL_BROKER']['port'],
#         f"SimCmdHandler_Data_{world_id}_{int(time.time())}",
#         on_command_message, 
#         topics_to_subscribe_data,
#         None, # 【教授修改 v7.1】: sub_world 不負責廣播全局配置，固定為 None
#         world_id
#     )
#     if command_client is None:
#         if vehicle_dispatcher and vehicle_dispatcher.mqttc.is_connected():
#             vehicle_dispatcher.disconnect()
#         return
#     print(f"[{world_id}] 資料指令接收器 (7883) 已啟動...")
    
#     # --- 【教授修改】建立 Control Client (7884) 的訂閱列表 ---
#     topics_to_subscribe_control = []
    
#     # 【教授修改 v7.1】: 移除 (Flow 7) 的訂閱邏輯
#     # if world_id == "main_world": topics_to_subscribe_control.append("system/worlds/register") 
    
#     if ENABLE_EXTERNAL_CONTROL: 
#         # (Flow 8)
#         topics_to_subscribe_control.append(INTER_WORLD_TOPIC)
    
#     # --- 【教授修改】連接 Control Client (7884) ---
#     control_client = connect_mqtt(
#         config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'],
#         f"SimCmdHandler_Control_{world_id}_{int(time.time())}",
#         on_command_message, # 重複使用同一個 message handler
#         topics_to_subscribe_control,
#         None, # 這個 client 不負責廣播 config
#         world_id
#     )
#     if control_client is None:
#         if command_client and command_client.is_connected():
#             command_client.disconnect()
#         if vehicle_dispatcher and vehicle_dispatcher.mqttc.is_connected():
#             vehicle_dispatcher.disconnect()
#         return
#     print(f"[{world_id}] 平台控制接收器 (7884) 已啟動...")
#     # --- 雙 Broker Client 建立完畢 ---


#     # --- 子世界註冊 ---
#     # 【教授註記 v7.1】: 這段邏輯是 sub_world 專屬且正確的 ("喊 '到'")
#     if world_id != "main_world": # 確保這段邏輯只在子世界執行
#         print(f"[{world_id}] 等待 1 秒...")
#         time.sleep(1.0)
#         print(f"[{world_id}] 發布上線註冊訊息 (7884)...")
#         register_payload = json.dumps({"world_id": world_id, "status": "online", "timestamp": time.time()})
#         try:
#             # 【教授修改】(Flow 7) 改用 control_client (7884) 發布註冊
#             if control_client and control_client.is_connected():
#                 control_client.publish("system/worlds/register", register_payload, qos=1)
#                 print(f"[{world_id}] 註冊訊息已發布至 (7884)。")
#             else: 
#                 print(f"⚠️ [{world_id}] Control Client (7884) 未連接，無法發布註冊訊息。")
#         except Exception as e: 
#             print(f"❌ [{world_id}] 發布註冊訊息 (7884) 時出錯: {e}")


#     # --- 初始化模擬狀態和數據收集 ---
#     global vehicleDict
#     vehicleDict.clear()
#     current_simulation_step = 0
#     pc_assignment_counter = 0

#     rtf_state = {'active': False}
#     rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data = [], [], [], []
#     t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data = [], [], [], []
#     t3_per_step_data, reroute_counts_per_step, total_reroutes_processed = [], [], 0

#     print("\n" + "="*30 + f"\n[{world_id}] RTF 效能測試模組已準備就緒。\n" + "="*30)

#     # --- 優雅關閉處理 ---
#     shutdown_flag = threading.Event()
#     def signal_handler(signum, frame):
#         print(f"\n[{world_id}] 捕獲到信號 {signum} ({signal.Signals(signum).name})，設置關閉標誌...")
#         shutdown_flag.set()
#     signal.signal(signal.SIGINT, signal_handler)
#     signal.signal(signal.SIGTERM, signal_handler)

#     # --- 主模擬循環 ---
#     try:
#         while not shutdown_flag.is_set():
#             # --- 檢查 TraCI 連接和模擬狀態 ---
#             try:
#                 current_sim_time_check = traci.simulation.getTime()
#                 if traci.simulation.getMinExpectedNumber() <= 0 and current_simulation_step > 0:
#                     print(f"[{world_id}] 模擬中已無車輛 (步長 {current_simulation_step})，結束模擬。")
#                     break
#             except (traci.TraCIException, ConnectionResetError, OSError) as conn_err:
#                  print(f"[{world_id}] TraCI 連接錯誤 ({type(conn_err).__name__})，終止模擬。")
#                  break
#             if current_simulation_step >= config['SIMULATION_END_STEP']:
#                  print(f"[{world_id}] 達到模擬結束步長 {config['SIMULATION_END_STEP']}，結束模擬。")
#                  break

#             step_start_time = time.perf_counter()
#             step_timings = {}

#             # --- 1. 處理來自外部世界的 SUMO 控制指令 (來自 7884) ---
#             t4_start = time.perf_counter()
#             control_commands_processed_this_step = 0
#             if ENABLE_EXTERNAL_CONTROL:
#                 current_edge_list = None
#                 while not simulation_control_queue.empty():
#                     try: command_data = simulation_control_queue.get_nowait()
#                     except queue.Empty: break

#                     edge_id = command_data.get("edge_id")
#                     command = command_data.get("command")
#                     source = command_data.get("source_world", "UNKNOWN")

#                     if not edge_id or not command: continue

#                     if current_edge_list is None:
#                         try: current_edge_list = traci.edge.getIDList()
#                         except traci.TraCIException: current_edge_list = []

#                     if edge_id not in current_edge_list: continue

#                     allowed_classes = DEFAULT_ALLOWED_VCLASSES

#                     try:
#                         if command == "CLOSE_EDGE":
#                             if edge_id not in externally_closed_edges:
#                                 print(f"🕹️ [{world_id}] <- (來自 {source} on 7884) 關閉 Edge {edge_id}")
#                                 traci.edge.setDisallowed(edge_id, allowed_classes)
#                                 # 對edge所有的lane著色
#                                 try:
#                                     for i in range(traci.edge.getLaneNumber(edge_id)):
#                                         lane_id = f"{edge_id}_{i}"
#                                         traci.lane.setColor(lane_id, CLOSED_LANE_COLOR) 
#                                 except traci.TraCIException as e_color: # 【教授修正 v7.2.1】: 捕捉變數 e_color
#                                     print(f"⚠️ [{world_id}] 設置車道 {edge_id} 顏色時出錯: {e_color}")
#                                 externally_closed_edges.add(edge_id)

#                                 control_commands_processed_this_step += 1
#                         elif command == "OPEN_EDGE":
#                             if edge_id in externally_closed_edges:
#                                 print(f"🕹️ [{world_id}] <- (來自 {source} on 7884) 開啟 Edge {edge_id}")
#                                 # 【教授建議】: 傳入空清單 '[]' 來重置路權，允許所有車輛
#                                 traci.edge.setAllowed(edge_id, [])
                                
#                                 try:
#                                     for i in range(traci.edge.getLaneNumber(edge_id)):
#                                         lane_id = f"{edge_id}_{i}"
#                                         # 2. 視覺化：將顏色設置為 None 來恢復 SUMO 預設
#                                         traci.lane.setColor(lane_id, None) 
#                                 except traci.TraCIException as e_color:
#                                     print(f"⚠️ [{world_id}] 重置車道 {edge_id} 顏色時出錯: {e_color}")
#                                 # --- 顏色設置結束 ---
                                
#                                 externally_closed_edges.remove(edge_id)
#                                 control_commands_processed_this_step += 1
#                     except traci.TraCIException as e: print(f"⚠️ [{world_id}] 執行 SUMO 指令出錯 ({command} on {edge_id}): {e}")
#                     except Exception as e: print(f"💥 [{world_id}] 處理 SUMO 指令時發生非預期錯誤: {e}")

#             t4_end = time.perf_counter()
#             step_timings['T4_SimControl'] = t4_end - t4_start
#             step_timings['control_commands_processed'] = control_commands_processed_this_step

#             # --- 2. 執行 SUMO 步長 ---
#             t0_start = time.perf_counter()
#             traci.simulationStep()
#             t0_end = time.perf_counter()
#             current_simulation_step += 1
#             step_timings['T0_SumoStep'] = t0_end - t0_start

#             # --- 3. 發布 RSU 數據 (發布到 7884) ---
#             if ENABLE_PERCEPTION_SYSTEM and current_simulation_step % config['RSU_PUBLISH_INTERVAL_STEPS'] == 0:
#                 rsu_raw_data = {}
#                 try:
#                     all_detectors = traci.inductionloop.getIDList()
#                     if all_detectors:
#                          for det_id in all_detectors:
#                              try:
#                                  lane_id = traci.inductionloop.getLaneID(det_id)
#                                  mean_speed = traci.inductionloop.getLastStepMeanSpeed(det_id)
#                                  vehicle_count = traci.inductionloop.getLastStepVehicleNumber(det_id)
#                                  if lane_id and not lane_id.startswith(':') and mean_speed >= 0:
#                                      rsu_raw_data[lane_id] = {"mean_speed": mean_speed, "vehicle_count": vehicle_count}
#                              except traci.TraCIException: continue
#                          if rsu_raw_data:
#                              # 【教授修改】(Flow 2) 改用 control_client (7884) 發布 RSU 數據
#                              if control_client and control_client.is_connected():
#                                  control_client.publish(f"worlds/{world_id}/rsu/raw_data", json.dumps(rsu_raw_data), qos=0)
#                 except traci.TraCIException: pass


#             # --- 4. 處理本地 Reroute 請求 (來自 7883) ---
#             t3_duration_sec, reroutes_this_step, avg_time_per_veh_ms = 0, 0, 0.0
#             if ENABLE_SMART_REROUTING:
#                 t3_start = time.perf_counter()
#                 processed_reroutes_in_batch = 0
#                 current_vehicle_list = []
#                 try: current_vehicle_list = traci.vehicle.getIDList()
#                 except traci.TraCIException: pass

#                 while not reroute_requests_queue.empty() and processed_reroutes_in_batch < 1000:
#                     try: request = reroute_requests_queue.get_nowait()
#                     except queue.Empty: break

#                     veh_id_to_reroute = request.get('veh_id')
#                     if veh_id_to_reroute and veh_id_to_reroute in current_vehicle_list:
#                         try:
#                             traci.vehicle.rerouteTraveltime(veh_id_to_reroute)
#                             reroutes_this_step += 1
#                         except traci.TraCIException: pass
#                     processed_reroutes_in_batch += 1

#                 t3_end = time.perf_counter()
#                 t3_duration_sec = t3_end - t3_start
#                 if reroutes_this_step > 0:
#                     avg_time_per_veh_ms = (t3_duration_sec * 1000) / reroutes_this_step
#                 if processed_reroutes_in_batch > 0:
#                      t3_per_step_data.append(t3_duration_sec * 1000)
#                      reroute_counts_per_step.append(reroutes_this_step)
#                 total_reroutes_processed += reroutes_this_step


#             step_timings['T3_Rerouting'] = t3_duration_sec
#             step_timings['reroute_count'] = reroutes_this_step
#             step_timings['reroute_avg_ms'] = avg_time_per_veh_ms


#             # --- 5. 垃圾回收 (同時使用 7883 和 7884) ---
#             try:
#                 is_traci_connected_gc = False
#                 try: traci.simulation.getTime(); is_traci_connected_gc = True
#                 except (traci.TraCIException, ConnectionResetError, OSError): is_traci_connected_gc = False
#                 if is_traci_connected_gc:
#                     garbage_collector(config['PHYSICAL_BROKER']['host'], config['PHYSICAL_BROKER']['port'],
#                                       config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'],
#                                       traci.simulation, vehicleDict, world_id)
#             except Exception as gc_e: print(f"[{world_id}] Error during garbage collection: {gc_e}")


#             # --- 6. 收集數據並分派給 OBC ---
#             t1_start = time.perf_counter()
#             vehicles_to_dispatch, vehicle_states, pc_assignment_counter = collect_and_prepare_dispatch_data(
#                 current_simulation_step, config, vehicleDict, pc_list, pc_assignment_counter
#             )
#             t1_end = time.perf_counter()
#             step_timings['T1_DataCollection'] = t1_end - t1_start
#             step_timings['Processed_Vehicles'] = len(vehicles_to_dispatch)


#             # --- 7. 發送數據給 OBC 並等待 ACK (發布到 7884) ---
#             ack_target_count = len(vehicles_to_dispatch)
#             t2_duration = 0.0
#             if ack_target_count > 0:
#                 t2_start = time.perf_counter()
#                 dispatched_count_actual = 0
#                 for veh_id in vehicles_to_dispatch:
#                      if veh_id in vehicle_states:
#                          vehicle = vehicleDict.get(veh_id)
#                          if not vehicle or not vehicle.physicalComputerMapping: continue
#                          pc = vehicle.physicalComputerMapping
#                          state_data = vehicle_states[veh_id]
#                          dispatch_topic = f"{pc}_{world_id}"
#                          try:
#                              if vehicle_dispatcher and vehicle_dispatcher.mqttc and vehicle_dispatcher.mqttc.is_connected():
#                                  vehicle_dispatcher.dispatch_vehicle(dispatch_topic, veh_id, state_data)
#                                  dispatched_count_actual += 1
#                          except Exception as dispatch_e: print(f"[{world_id}] Error dispatching vehicle {veh_id}: {dispatch_e}")
#                 if dispatched_count_actual > 0: wait_for_acks(vehicle_dispatcher, dispatched_count_actual)
#                 t2_end = time.perf_counter()
#                 t2_duration = t2_end - t2_start
#             step_timings['T2_RoundTripWait'] = t2_duration


#             # --- 8. 更新 RTF 監控 (只打印簡略信息) ---
#             step_end_time = time.perf_counter()
#             time_elapsed_for_step = step_end_time - step_start_time
#             rtf_state = update_rtf_monitor(
#                 rtf_state, config, current_simulation_step, time_elapsed_for_step,
#                 rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, step_timings,
#                 t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data
#             )


#     except KeyboardInterrupt:
#         print(f"\n[{world_id}] 收到關閉信號，退出主循環...")
#     except traci.FatalTraCIError as e:
#         print(f"\n💥 [{world_id}] TraCI 發生致命錯誤，模擬提前終止: {e}")
#     except traci.TraCIException as e:
#         print(f"\n💥 [{world_id}] TraCI 連接錯誤 (可能 SUMO 已關閉)，模擬提前終止: {e}")
#     except Exception as e:
#         print(f"\n============================================================\n💥💥💥 [{world_id}] 主模擬循環發生致命錯誤 💥💥💥\n錯誤類型: {type(e).__name__}\n錯誤訊息: {e}\n\n---詳細錯誤追蹤 (Traceback) ---\n")
#         traceback.print_exc()
#         print("============================================================\n")
#     finally:
#         print(f"\n[{world_id}] 模擬結束於步驟 {current_simulation_step}。")

#         # --- 最後清理：重新開啟所有外部關閉的 Edge ---
#         is_traci_connected_final = False
#         try:
#             if 'traci' in sys.modules and traci:
#                 try: traci.simulation.getTime(); is_traci_connected_final = True
#                 except (traci.TraCIException, ConnectionResetError, OSError): is_traci_connected_final = False

#                 if is_traci_connected_final:
#                     print(f"[{world_id}] 正在重新開啟 {len(externally_closed_edges)} 個因外部指令關閉的 Edge...")
                    
#                     edges_to_reopen = list(externally_closed_edges)
#                     try: edge_list_at_end = set(traci.edge.getIDList())
#                     except traci.TraCIException: edge_list_at_end = set()

#                     for edge_id in edges_to_reopen:
#                          if edge_id in edge_list_at_end:
#                              try:
#                                  # 【教授建議】: 傳入空清單 '[]' 來重置路權
#                                  traci.edge.setAllowed(edge_id, [])
                                 
#                                  # --- 【教授加回 v7.2】: 清理時重置顏色 ---
#                                  try:
#                                      for i in range(traci.edge.getLaneNumber(edge_id)):
#                                          traci.lane.setColor(f"{edge_id}_{i}", None)
#                                  except traci.TraCIException:
#                                      pass # 清理階段出錯，可以忽略
#                                  # --- 顏色設置結束 ---

#                                  print(f"   ✅ [{world_id}] Reopened edge {edge_id}")
#                              except traci.TraCIException as e: print(f"   ⚠️ [{world_id}] 無法重新開啟 edge {edge_id}: {e}")
#                              except Exception as e: print(f"   💥 [{world_id}] 重新開啟 edge {edge_id} 時發生非預期錯誤: {e}")
#                          if edge_id in externally_closed_edges: externally_closed_edges.remove(edge_id)
#                     externally_closed_edges.clear()

#                     # --- 關閉 TraCI 連接 ---
#                     print(f"[{world_id}] 正在關閉 TraCI 連接...")
#                     traci.close()
#                     print(f"[{world_id}] TraCI 連接已關閉。")
#         except NameError: pass
#         except Exception as final_traci_e: print(f"[{world_id}] 在最終清理 TraCI 時發生錯誤: {final_traci_e}")


#         # --- 斷開 MQTT 連接 ---
#         print(f"[{world_id}] 開始清理 MQTT 資源...")
#         # 【教授修改】斷開兩個 client
#         if 'command_client' in locals() and command_client and hasattr(command_client, 'is_connected') and command_client.is_connected():
#             print(f"[{world_id}] 正在斷開 MQTT Data Client (7883)...")
#             command_client.loop_stop()
#             time.sleep(0.2)
#             command_client.disconnect()
#             print(f"[{world_id}] MQTT Data Client (7883) 已斷開。")
            
#         if 'control_client' in locals() and control_client and hasattr(control_client, 'is_connected') and control_client.is_connected():
#             print(f"[{world_id}] 正在斷開 MQTT Control Client (7884)...")
#             control_client.loop_stop()
#             time.sleep(0.2)
#             control_client.disconnect()
#             print(f"[{world_id}] MQTT Control Client (7884) 已斷開。")

#         if 'vehicle_dispatcher' in locals() and vehicle_dispatcher and hasattr(vehicle_dispatcher, 'mqttc') and vehicle_dispatcher.mqttc.is_connected():
#             print(f"[{world_id}] 正在斷開車輛分派器 MQTT 客戶端 (7884)...")
#             vehicle_dispatcher.disconnect()
#             print(f"[{world_id}] 車輛分派器 MQTT 客戶端 (7884) 已斷開。")
            
#         if 'traci' in sys.modules and not is_traci_connected_final:
#              print(f"[{world_id}] TraCI 已斷開連接。")


#         # --- 打印/生成報告 ---
#         print(f"[{world_id}] 正在生成最終效能報告...")
#         print_performance_report(
#             config, rtf_data or [], vehicle_count_data or [], halting_vehicle_data or [], congestion_data or [],
#             t0_per_vehicle_data or [], t1_per_vehicle_data or [], t2_per_vehicle_data or [], overhead_per_vehicle_data or [],
#             t3_per_step_data or [], reroute_counts_per_step or [], total_reroutes_processed, current_simulation_step
#         )
#         print(f"[{world_id}] 模擬程序完全結束。")


# # 移除 SUMO_HOME 檢查
# if __name__ == '__main__':
#     main()
























# # traffic_simulation/sub_world_sim.py
# # (基於 v7.2.1 修改，實現 MQTT 觸發的「一次性號誌同步」)

# # traffic_simulation/sub_world_sim.py
# # (使用 'getLaneNumber' 邏輯來著色)
# # (v8.12.19 - Hardcode 測試版: 直接呼叫 setParameter API)
# 使用   traci.edge.setDisallowed(edge_id, allowed_classes) 來封閉路段 !  

# import os
# import sys
# import time
# import json
# import queue
# import threading
# import paho.mqtt.client as mqtt
# from paho.mqtt.properties import Properties
# from paho.mqtt.packettypes import PacketTypes
# import statistics
# import traceback
# import signal
# import xml.etree.ElementTree as ET
# from xml.dom import minidom

# # --- SUMO 環境設定 ---
# # 【v8.12.14 - 最終相對路徑修正】
# # 讓腳本自動尋找 traci 函式庫

# # 1. 獲取此腳本 (sim_sub_world.py) 所在的目錄
# #    (即: .../sumo_platform/testbed/traffic_simulation)
# script_dir = os.path.dirname(os.path.abspath(__file__))

# # 2. 往上走兩層，到達專案根目錄 (.../sumo_platform)
# project_root = os.path.dirname(os.path.dirname(script_dir))

# # 3. 建立我們新的函式庫路徑 (.../sumo_platform/tools_lib)
# traci_lib_path = os.path.join(project_root, "tools_lib")

# if not os.path.exists(traci_lib_path):
#     print(f"❌ 致命錯誤：找不到 Traci 函式庫：{traci_lib_path}")
#     print("請確認您已執行『原始碼方案』的階段 2 (下載並解壓縮)")
#     sys.exit(1)
    
# if traci_lib_path not in sys.path:
#     sys.path.insert(0, traci_lib_path)

# try:
#     import traci
#     from traci.exceptions import TraCIException, FatalTraCIError
    
# except ImportError:
#     print("錯誤：無法導入 traci 模組。")
#     print(f"檢查的路徑: {traci_lib_path}")
#     sys.exit(1)


# # --- 導入自訂模組 ---
# try:
#     from traffic_Vehicle import Vehicle
#     from garbage_collector import garbage_collector
#     from traffic_Vehicle_dispatcher import Vehicle_dispatcher
# except ImportError as e:
#     print(f"錯誤：無法導入自訂模組: {e}")
#     print("請確保 traffic_Vehicle.py, garbage_collector.py, traffic_Vehicle_dispatcher.py 與此腳本在同一目錄下。")
#     sys.exit(1)


# # --- v8.12.7 全域常數 ---
# INTER_WORLD_TOPIC = "system/inter_world_hotspots"
# # 【v8.12.7 客製化修正】: 根據需求，僅保留 "passenger"
# DEFAULT_ALLOWED_VCLASSES = ["passenger"]


# # 【v8.12 新增】: MQTT 同步主題
# SYSTEM_REGISTER_TOPIC = "system/worlds/register"
# SYSTEM_TLS_SYNC_TOPIC = "system/tls_sync"
# SYSTEM_TLS_ACK_TOPIC = "system/tls_ack"
# SYSTEM_RESUME_ALL_TOPIC = "system/resume_all"

# # --- 全局變量 ---
# config = {}
# vehicleDict = {}
# resume_event = threading.Event()
# control_client = None
# SIM_STATE = "RUNNING"
# shutdown_flag = threading.Event()


# # ============================================================ #
# # 輔助函式 (v7.0 + v8.12.5)
# # ============================================================ #

# def set_edge_color_compat(edge_id, color):
#     """
#     (v8.12.16 - 偵錯版本) 
#     使用 traci.edge.setParameter，並在設定後立刻讀取回來。
    
#     【v8.12.19 註】: 此函式在此版本中未被呼叫，
#     因為 main() 迴圈中改用直接呼叫 traci API。
#     """
#     global traci, config
    
#     color_string = "" # 預設為重置 (空字串)
#     world_id = config.get('world_id', 'SIM')
    
#     if color is not None:
#         try:
#             # 從 (255, 165, 0, 255) 中提取 R,G,B
#             r, g, b = color[0], color[1], color[2]
#             color_string = f"{r},{g},{b}" # 轉換為 "255,165,0"
#         except (TypeError, IndexError, Exception) as e:
#             print(f"⚠️ [{world_id}] [set_edge_color_compat] 顏色格式錯誤: {color}。錯誤: {e}")
#             return
    
#     try:
#         # --- 1. 嘗試設定顏色 ---
#         traci.edge.setParameter(edge_id, "color", color_string)
        
#         # --- 2. 【偵錯】立刻讀取該參數 ---
#         try:
#             read_back_color = traci.edge.getParameter(edge_id, "color")
#             # 只有在顏色不是重置時才打印，避免洗版
#             if color_string != "":
#                 print(f"💡 [{world_id}] [DEBUG] Edge {edge_id}: "
#                       f"嘗試設定為 '{color_string}', "
#                       f"讀回值為: '{read_back_color}'")
#         except traci.TraCIException as e_get:
#             if color_string != "":
#                 print(f"💡 [{world_id}] [DEBUG] Edge {edge_id}: "
#                       f"嘗試設定為 '{color_string}', "
#                       f"但讀取參數失敗: {e_get}")

#     except traci.TraCIException as e_traci:
#         print(f"⚠️ [{world_id}] [set_edge_color_compat] 設置 Edge {edge_id} 顏色時出錯: {e_traci}")
#     except AttributeError as e_attr:
#         print(f"❌ [{world_id}] [set_edge_color_compat] 發生嚴重屬性錯誤: {e_attr}")
#     except Exception as e_unknown:
#         print(f"❌ [{world_id}] [set_edge_color_compat] G-發生未知錯誤: {e_unknown}")





# def get_edge_id_from_lane_id(lane_id):
#     """ 
#     從 lane_id (如 'edge123_0') 提取 edge_id ('edge123') 
#     """
#     if not lane_id or lane_id.startswith(':'): return None
#     try: return lane_id.rsplit('_', 1)[0]
#     except Exception: return None

# def retrieve_vehicle_state(traci_instance, veh_id, current_step):
#     """ 
#     從 SUMO 獲取指定車輛的詳細狀態 (v7.0 不變) 
#     """
#     try:
#         x, y = traci_instance.vehicle.getPosition(veh_id)
#         lon, lat = traci_instance.simulation.convertGeo(x, y)
#         laneID = traci_instance.vehicle.getLaneID(veh_id)
#         vehicleLength = traci_instance.vehicle.getLength(veh_id)
#         lanePosition = traci_instance.vehicle.getLanePosition(veh_id)
#         speed = traci_instance.vehicle.getSpeed(veh_id)
#         laneLength = 0.0; travelTime = -1.0; maxSpeed = 0.0
#         if laneID and not laneID.startswith(':'):
#             try:
#                 laneLength = traci_instance.lane.getLength(laneID)
#                 travelTime = traci_instance.lane.getTraveltime(laneID)
#                 maxSpeed = traci_instance.lane.getMaxSpeed(laneID)
#             except traci.TraCIException: pass
#         current_route = []; destination_edge = None
#         try:
#             current_route = traci_instance.vehicle.getRoute(veh_id)
#             destination_edge = current_route[-1] if current_route else None
#         except traci.TraCIException: pass
#         next_tls_info = None
#         try:
#             tls_raw_data = traci_instance.vehicle.getNextTLS(veh_id)
#             if tls_raw_data:
#                 tls = tls_raw_data[0]
#                 next_tls_info = {"id": tls[0], "distance": tls[2], "state": tls[3]}
#         except traci.TraCIException: pass
#         connectedLanes = []
#         if laneID and laneID.startswith(":"):
#             try:
#                 links = traci_instance.lane.getLinks(laneID, False)
#                 for link in links: connectedLanes.append(link[0])
#             except traci.TraCIException: pass
#         vehicleState = dict(lat=lat, lon=lon, laneID=laneID, speed=speed, travelTime=travelTime,
#                             lanePosition=lanePosition, vehicleLength=vehicleLength,
#                             connectedLanes=connectedLanes, laneLength=laneLength,
#                             currentRoute=current_route, destinationEdge=destination_edge,
#                             maxSpeed=maxSpeed, current_step=current_step, next_tls=next_tls_info)
#         return vehicleState
#     except traci.TraCIException as e: return None

# # --- 【v8.12.5 修正】: 應用 TLS 狀態的輔助函式 (添加日誌) ---
# def apply_tls_status(traci_conn, tls_data):
#     """
#     (v8.12.5) 將從 Pacer 收到的紅綠燈狀態應用到 'sub_world' (Follower)。
#     (修正: 添加詳細的錯誤日誌)
#     (v8.12.6 註: 此函式必須在主線程中被呼叫)
#     """
#     global config
#     world_id = config.get('world_id', 'SIM')
#     print(f"[{world_id}] [SYNCING] 正在應用 {len(tls_data)} 個紅綠燈狀態...")
#     apply_count = 0
#     failed_tls_ids = []
    
#     # 【v8.12.5 修正】: 獲取當前世界的所有 TLS ID，用於檢查
#     try:
#         local_tls_ids = set(traci_conn.trafficlight.getIDList())
#     except TraCIException as e:
#         print(f"❌ [{world_id}] [SYNCING] 無法獲取本地 TLS 列表: {e}。同步將可能失敗。")
#         local_tls_ids = set()

    
#     for tls_id, status in tls_data.items():
#         try:
#             # 檢查 TLS 是否存在於本地
#             if tls_id not in local_tls_ids:
#                 raise TraCIException(f"TLS ID '{tls_id}' 在 {world_id} 中不存在。")

#             phase_index = status.get("phase_index")
#             remaining_duration = status.get("remaining_duration")
            
#             if phase_index is not None and remaining_duration is not None:
#                 traci_conn.trafficlight.setPhase(tls_id, phase_index)
#                 traci_conn.trafficlight.setPhaseDuration(tls_id, remaining_duration)
#                 apply_count += 1
#             else:
#                 raise TraCIException(f"TLS ID '{tls_id}' 數據不完整 (phase 或 duration 為 None)。")
                
#         except TraCIException as e:
#             # 【v8.12.5 修正】: 移除 pass，改用日誌
#             failed_tls_ids.append(tls_id)
#             print(f"⚠️ [{world_id}] [SYNCING] 應用 TLS '{tls_id}' 狀態失敗: {e}")

#     print(f"✅ [{world_id}] [SYNCING] 成功應用 {apply_count} / {len(tls_data)} 個狀態。")
#     if failed_tls_ids:
#         print(f"    -> {len(failed_tls_ids)} 個紅綠燈應用失敗 (已跳過): {failed_tls_ids}")


# def setup_dispatcher(config_data, world_id):
#     """ 
#     初始化並連接到虛擬 Broker (7884) 的車輛分派器。 (v7.0 不變) 
    
#     (v8.12.6 註): 參數 'config' 變更為 'config_data' 以避免遮蔽全域變數
#     """
#     print(f"[{world_id}] 正在初始化車輛分派器 (Vehicle Dispatcher)...")
#     dispatcher = Vehicle_dispatcher()
#     computers = dict(pc1='127.0.0.1')
#     dispatcher.physicalComputers = computers
#     pc_list = list(dispatcher.physicalComputers.keys())
#     try:
#         dispatcher.connect(config_data['VIRTUAL_BROKER']['host'], config_data['VIRTUAL_BROKER']['port'], world_id)
#         print(f"[{world_id}] 車輛分派器連接成功 (7884)。")
#     except Exception as e:
#         print(f"❌ [{world_id}] 車輛分派器連接失敗 (7884): {e}")
#         return None, []
#     return dispatcher, pc_list

# def start_sumo(config_data, traci_port):
#     """ 
#     啟動 SUMO 模擬實例。 (v7.0 不變) 
    
#     (v8.12.6 註): 參數 'config' 變更為 'config_data' 以避免遮蔽全域變數
#     """
#     world_id_log = config_data.get('world_id', 'SIM')
#     print(f"[{world_id_log}] 正在啟動 SUMO，使用 TraCI Port: {traci_port}...")
#     sumo_binary = config_data.get('SUMO_BINARY', 'sumo-gui') 
#     config_file = config_data.get('SUMO_CONFIG_FILE')
#     if not config_file or not os.path.exists(config_file): raise FileNotFoundError(f"SUMO 配置文件未找到: {config_file}")
    
#     if not os.path.exists(sumo_binary):
#         from shutil import which
#         if which(sumo_binary) is None: 
#             sumo_binary = 'sumo'
#             if which(sumo_binary) is None:
#                 raise FileNotFoundError(f"SUMO 執行檔未找到 (sumo-gui 或 sumo): {config_data.get('SUMO_BINARY')}")
#         else: 
#             sumo_binary = which(sumo_binary)
            
#     sumoCmd = [ sumo_binary, "-c", config_file, 
#                 "--time-to-teleport", "-1", "--ignore-route-errors", "true",
#                 "--no-step-log", "true", "--no-warnings", "true",
#                 "--log", f"sumo_log_{world_id_log}_{time.strftime('%Y%m%d_%H%M%S')}.txt",
#                 "--step-length", "1.0", 
#                 "--default.action-step-length", "1.0"
#                 ]
#     try:
#         traci.start(sumoCmd, port=traci_port, numRetries=20, label=f"TraCI_{world_id_log}")
#         print(f"[{world_id_log}] TraCI.start 成功，已連接到 SUMO。")
#     except Exception as e:
#         print(f"❌ [{world_id_log}] Traci.start 失敗: {e}")
#         raise

# def collect_and_prepare_dispatch_data(current_step, config_data, vehicle_dict, pc_list, pc_counter):
#     """ 
#     收集所有應在此步長發布狀態的車輛，並分配 OBC (pc)。 (v7.0 不變) 
    
#     (v8.12.6 註): 參數 'config' 變更為 'config_data' 以避免遮蔽全域變數
#     """
#     vehicles_to_dispatch_this_step = []
#     vehicle_states_this_step = {}
#     publish_period = config_data['PUBLISH_PERIOD_STEPS']
#     try: current_vehicle_ids = set(traci.vehicle.getIDList())
#     except traci.TraCIException: return [], {}, pc_counter
#     for veh_id in current_vehicle_ids:
#         if veh_id not in vehicle_dict: vehicle_dict[veh_id] = Vehicle(veh_id)
#         vehicle = vehicle_dict[veh_id]
#         if vehicle.physicalComputerMapping is None and pc_list:
#             pc_index = pc_counter % len(pc_list)
#             vehicle.physicalComputerMapping = pc_list[pc_index]
#             pc_counter += 1
#         should_publish = (publish_period == 1) or \
#                          (vehicle.last_publish_step == 0 and current_step >= 1) or \
#                          (current_step >= vehicle.last_publish_step + publish_period)
#         if should_publish: vehicles_to_dispatch_this_step.append(veh_id)
#     vehicles_to_actually_dispatch = []
#     if vehicles_to_dispatch_this_step:
#         for veh_id in vehicles_to_dispatch_this_step:
#             state = retrieve_vehicle_state(traci, veh_id, current_step)
#             if state is not None:
#                 vehicle_states_this_step[veh_id] = state
#                 vehicles_to_actually_dispatch.append(veh_id)
#                 if veh_id in vehicle_dict: vehicle_dict[veh_id].last_publish_step = current_step
#     return vehicles_to_actually_dispatch, vehicle_states_this_step, pc_counter

# def wait_for_acks(dispatcher, target_count):
#     """ 
#     等待 OBC 回傳 ACK，確保同步。 (v7.0 不變) 
#     """
#     global config
#     if target_count <= 0 or not dispatcher: return
#     timeout = config.get('ACK_TIMEOUT', 5.0)
#     start_time = time.perf_counter()
#     waited_time = 0
#     sleep_interval = 0.005
#     while dispatcher.ack_count < target_count and waited_time < timeout:
#         time.sleep(sleep_interval)
#         waited_time = time.perf_counter() - start_time
#     if dispatcher.ack_count < target_count: print(f"⚠️ [{config.get('world_id', 'SIM')}] 等待 ACK 超時！預期 {target_count}, 收到 {dispatcher.ack_count}。")
#     dispatcher.ack_count = 0

# def update_rtf_monitor(rtf_state, config_data, current_step, time_elapsed_for_step, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, step_timings, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data):
#     """ 
#     更新 RTF 效能監控數據。 (v7.0 不變) 
    
#     (v8.12.6 註): 參數 'config' 變更為 'config_data' 以避免遮蔽全域變數
#     """
#     global vehicleDict
#     world_id = config_data.get('world_id', 'SIM')
#     if not rtf_state.get('active', False) and current_step >= config_data['SIMULATION_START_STEP']:
#         rtf_state['active'] = True
#     if rtf_state.get('active', False):
#         current_rtf = 1.0 / time_elapsed_for_step if time_elapsed_for_step > 1e-9 else float('inf')
#         rtf_data.append(current_rtf)
#         current_vehicle_count = 0; halting_vehicles = 0
#         try:
#             current_vehicle_count = traci.vehicle.getIDCount()
#             if current_vehicle_count > 0:
#                 all_vehicle_ids = traci.vehicle.getIDList()
#                 halting_vehicles = sum(1 for veh_id in all_vehicle_ids if traci.vehicle.getSpeed(veh_id) < 0.1)
#         except traci.TraCIException:
#             current_vehicle_count = len(vehicleDict); halting_vehicles = 0
#         congestion_percentage = (halting_vehicles / current_vehicle_count * 100) if current_vehicle_count > 0 else 0.0
#         if current_vehicle_count >= 0:
#             congestion_data.append(congestion_percentage)
#             halting_vehicle_data.append(halting_vehicles)
#             vehicle_count_data.append(current_vehicle_count)
            
#         t0 = step_timings.get('T0_SumoStep', 0); t1 = step_timings.get('T1_DataCollection', 0)
#         t2 = step_timings.get('T2_RoundTripWait', 0); t3 = step_timings.get('T3_Rerouting', 0)
#         t4 = step_timings.get('T4_SimControl', 0); measured_total = t0 + t1 + t2 + t3 + t4
#         script_overhead = max(0.0, time_elapsed_for_step - measured_total)
#         processed_vehicles = step_timings.get('Processed_Vehicles', 0)
#         if processed_vehicles > 0:
#             t0_avg = t0 / processed_vehicles; t1_avg = t1 / processed_vehicles
#             t2_avg = t2 / processed_vehicles; overhead_avg = script_overhead / processed_vehicles
#             if all(t >= 0 for t in [t0_avg, t1_avg, t2_avg, overhead_avg]):
#                 t0_per_vehicle_data.append(t0_avg * 1000); t1_per_vehicle_data.append(t1_avg * 1000)
#                 t2_per_vehicle_data.append(t2_avg * 1000); overhead_per_vehicle_data.append(overhead_avg * 1000)
#     return rtf_state


# def generate_xml_report(filename, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_data, t1_data, t2_data, overhead_data, t3_data, reroute_counts, total_reroutes, total_steps):
#     """ 
#     生成 XML 格式的效能報告。 (v7.0 不變) 
#     """
#     global config
#     root = ET.Element("PerformanceReport")
#     summary_node = ET.SubElement(root, "MacroscopicSummary")
#     if rtf_data:
#         rtf_node = ET.SubElement(summary_node, "RealTimeFactor")
#         ET.SubElement(rtf_node, "Unit").text = "Steps_per_Second"
#         try:
#             ET.SubElement(rtf_node, "Mean").text = f"{statistics.mean(rtf_data):.4f}"
#             ET.SubElement(rtf_node, "Median").text = f"{statistics.median(rtf_data):.4f}"
#             ET.SubElement(rtf_node, "Max").text = f"{max(rtf_data):.4f}"
#             ET.SubElement(rtf_node, "Min").text = f"{min(rtf_data):.4f}"
#         except (statistics.StatisticsError, ValueError): pass
#     if vehicle_count_data:
#         vc_node = ET.SubElement(summary_node, "VehicleCount")
#         try:
#             ET.SubElement(vc_node, "Mean").text = f"{statistics.mean(vehicle_count_data):.2f}"
#             ET.SubElement(vc_node, "Max").text = f"{max(vehicle_count_data)}"
#         except (statistics.StatisticsError, ValueError): pass
#     reroute_summary_node = ET.SubElement(summary_node, "ReroutingOverallStats")
#     ET.SubElement(reroute_summary_node, "TotalReroutesProcessed").text = str(total_reroutes)
#     avg_req_per_step = total_reroutes / total_steps if total_steps > 0 else 0
#     ET.SubElement(reroute_summary_node, "AverageRequestsPerSimulationStep").text = f"{avg_req_per_step:.4f}"
#     micro_summary_node = ET.SubElement(root, "MicroscopicSummary")
#     micro_summary_node.set("Unit", "Milliseconds")
#     def add_stats_node(parent, name, data):
#         mean = 0.0
#         if data:
#             node = ET.SubElement(parent, name)
#             try:
#                 mean = statistics.mean(data)
#                 ET.SubElement(node, "Mean").text = f"{mean:.4f}"
#                 if len(data) > 1: ET.SubElement(node, "StdDev").text = f"{statistics.stdev(data):.4f}"
#                 else: ET.SubElement(node, "StdDev").text = "N/A"
#             except (statistics.StatisticsError, ValueError): pass
#         return mean
#     mean_t0 = add_stats_node(micro_summary_node, "T0_SUMO_Internal_Step", t0_data)
#     mean_t1 = add_stats_node(micro_summary_node, "T1_DataCollection", t1_data)
#     mean_t2 = add_stats_node(micro_summary_node, "T2_RoundTripWait", t2_data)
#     mean_overhead = add_stats_node(micro_summary_node, "T_Overhead", overhead_data)
#     if any(m > 0 for m in [mean_t0, mean_t1, mean_t2, mean_overhead]):
#         total_node = ET.SubElement(micro_summary_node, "Total_Per_Vehicle_Time")
#         ET.SubElement(total_node, "Mean").text = f"{mean_t0 + mean_t1 + mean_t2 + mean_overhead:.4f}"
#     if t3_data:
#         t3_batch_node = ET.SubElement(micro_summary_node, "T3_Rerouting_Batch")
#         t3_batch_node.set("Description", "Time to process a batch of reroute requests per step")
#         try:
#             mean_t3_batch = statistics.mean(t3_data)
#             ET.SubElement(t3_batch_node, "Mean").text = f"{mean_t3_batch:.4f}"
#             if len(t3_data) > 1: ET.SubElement(t3_batch_node, "StdDev").text = f"{statistics.stdev(t3_data):.4f}"
#             else: ET.SubElement(t3_batch_node, "StdDev").text = "N/A"
#             ET.SubElement(t3_batch_node, "Max").text = f"{max(t3_data):.4f}"; ET.SubElement(t3_batch_node, "Min").text = f"{min(t3_data):.4f}"
#             total_t3_time_ms = sum(t3_data)
#             avg_per_veh_ms = total_t3_time_ms / total_reroutes if total_reroutes > 0 else 0
#             per_veh_node = ET.SubElement(micro_summary_node, "T3_Rerouting_PerVehicle")
#             ET.SubElement(per_veh_node, "Mean").text = f"{avg_per_veh_ms:.6f}"
#         except (statistics.StatisticsError, ValueError): pass
#     xml_string = ET.tostring(root, 'utf-8');
#     try: pretty_xml_string = minidom.parseString(xml_string).toprettyxml(indent="    ")
#     except Exception: pretty_xml_string = xml_string.decode('utf-8')
#     try:
#         with open(filename, "w", encoding='utf-8') as f: f.write(pretty_xml_string)
#         print(f"\n✅ [{config.get('world_id', 'SIM')}] 效能報告已成功生成至檔案: {filename}")
#     except IOError as e: print(f"\n❌ [{config.get('world_id', 'SIM')}] 無法寫入效能報告檔案 {filename}: {e}")



# def print_performance_report(config_data, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data, t3_per_step_data, reroute_counts_per_step, total_reroutes_processed, total_simulation_steps):
#     """ 
#     在終端打印最終的效能報告。 (v7.0 不變) 
    
#     (v8.12.6 註): 參數 'config' 變更為 'config_data' 以避免遮蔽全域變數
#     """
#     world_id = config_data.get('world_id', 'SIM'); print("\n" + "="*50 + f"\n===== [{world_id}] 📊 最終效能綜合報告 📊 =====\n" + "="*50)
#     if not rtf_data: print("未收集到足夠的 RTF 測試數據，無法生成報告。" + "\n" + "="*50); return

#     def print_stats(label, data, unit=""):
#         if not data: print(f" - {label}: 無數據"); return
#         try:
#             mean = statistics.mean(data)
#             median = statistics.median(data)
#             maximum = max(data)
#             minimum = min(data)
#             print(f" - {label}:")
#             print(f"   - 平均值 (Mean):   {mean:.4f}{unit}")
#             print(f"   - 中位數 (Median): {median:.4f}{unit}")
#             print(f"   - 最高/最低:       {maximum:.4f}{unit} / {minimum:.4f}{unit}")
#             if len(data) > 1:
#                 stdev = statistics.stdev(data)
#                 print(f"   - 標準差 (StdDev): {stdev:.4f}{unit}")
#             else:
#                 print(f"   - 標準差 (StdDev): N/A (數據點不足)")
#         except (statistics.StatisticsError, ValueError, TypeError) as e: print(f" - 計算 {label} 統計時發生錯誤: {e}")

#     print("\n---  瞬時RTF (步/秒) 效能 ---"); print_stats("RTF", rtf_data, unit=" Steps/Sec")
#     print("\n---  車輛數統計 (測試期間) ---")
#     if vehicle_count_data:
#         try: print(f" - 平均車輛數: {statistics.mean(vehicle_count_data):.2f}"); print(f" - 最高車輛數:   {max(vehicle_count_data)}")
#         except (statistics.StatisticsError, ValueError) as e: print(f" - 計算車輛數統計時發生錯誤: {e}")
#     else: print(" - 無車輛數數據")
#     print("\n---  壅塞率 (%) 統計 ---"); print_stats("壅塞率", congestion_data, unit="%")
#     print("\n---  停止車輛數統計 ---")
#     if halting_vehicle_data:
#         try: print(f" - 平均停止車輛數: {statistics.mean(halting_vehicle_data):.2f}"); print(f" - 最高停止車輛數:   {max(halting_vehicle_data)}")
#         except (statistics.StatisticsError, ValueError) as e: print(f" - 計算停止車輛數統計時發生錯誤: {e}")
#     else: print(" - 無停止車輛數數據")

#     print("\n---  單車處理效能穩定性 (毫秒/輛) ---")
#     if t0_per_vehicle_data:
#         def print_perf_stats(label, data):
#             mean = 0.0; stdev_str = "N/A"
#             if data:
#                 try: 
#                     mean = statistics.mean(data)
#                     if len(data) > 1: stdev_str = f"{statistics.stdev(data):.4f} ms"
#                 except (statistics.StatisticsError, ValueError) : pass
#             print(f" - {label}: 平均值: {mean:.4f} ms, 標準差: {stdev_str}")
        
#         try:
#             print_perf_stats("T0 (SUMO內部計算)", t0_per_vehicle_data)
#             print_perf_stats("T1 (SUMO資訊擷取)", t1_per_vehicle_data)
#             print_perf_stats("T2 (分派至OBC並等待ACK)", t2_per_vehicle_data)
#             print_perf_stats("T_Overhead (腳本行政開銷)", overhead_per_vehicle_data)
#             all_data_present = all([t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data])
#             if all_data_present:
#                 try:
#                     total_avg = sum(statistics.mean(d) for d in [t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data])
#                     print(f" - -------------------------------------------------")
#                     print(f" - 單車平均總耗時:                   {total_avg:.4f} ms")
#                 except statistics.StatisticsError: print(" - 無法計算單車平均總耗時 (數據不足)")
#             else: print(" - 部分效能數據缺失，無法計算單車平均總耗時。")
#         except (ValueError) as e: print(f" - 計算單車效能統計時發生錯誤: {e}")
#     else: print(" - 未收集到單車處理時間數據。")

#     print("\n---  T3 Reroute 請求處理效能 ---")
#     if not t3_per_step_data: print(" - 模擬期間未執行任何 Reroute 操作。")
#     else:
#         try:
#             print(f" [總體統計]"); print(f" - 模擬期間總處理請求數: {total_reroutes_processed} 次")
#             avg_req_per_step = total_reroutes_processed / total_simulation_steps if total_simulation_steps > 0 else 0
#             print(f" - 全域平均請求數:       {avg_req_per_step:.4f} 次 / 每個模擬步長")
#             print(f"\n [T3 批次處理耗時 (毫秒/批次)]")
#             mean_t3=statistics.mean(t3_per_step_data); max_t3=max(t3_per_step_data); min_t3=min(t3_per_step_data)
#             print(f" - 平均耗時: {mean_t3:.4f} ms/批次"); print(f" - 最長/最短: {max_t3:.4f} / {min_t3:.4f} ms")
#             if len(t3_per_step_data) > 1: print(f" - 標準差:   {statistics.stdev(t3_per_step_data):.4f} ms")
#             total_t3_time_ms = sum(t3_per_step_data)
#             avg_per_vehicle_ms = total_t3_time_ms / total_reroutes_processed if total_reroutes_processed > 0 else 0
#             print(f"\n [單車 Reroute 平均耗時 (毫秒/輛)]"); print(f" - 平均耗時: {avg_per_vehicle_ms:.6f} ms/輛 (總耗時 / 總請求數)")
#         except (statistics.StatisticsError, ValueError) as e: print(f" - 計算 Reroute 效能統計時發生錯誤: {e}")

#     print("\n" + "="*50 + "\n")
#     generate_xml_report(config_data['OUTPUT_XML_FILE'], rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data, t3_per_step_data, reroute_counts_per_step, total_reroutes_processed, total_simulation_steps)


# def connect_mqtt(host, port, client_id, on_message_callback, topics_to_subscribe, smart_rerouting_enabled, world_id):
#     """ 
#     通用 MQTT 連接器 (v7.0 不變)
#     """
#     print(f"[{world_id}] 正在連接 MQTT Broker {host}:{port} (Client ID: {client_id})...")
#     client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
#     client.user_data_set({"world_id": world_id})
#     client.on_message = on_message_callback

#     def on_connect(client, userdata, flags, rc, properties):
#         """ MQTT 連線成功時的回調函式 """
#         if rc == 0:
#             print(f"✅ MQTT Client '{client._client_id}' ({host}:{port}) 連接成功。")
#             for topic in topics_to_subscribe: 
#                 print(f"    -> 訂閱: {topic}")
#                 client.subscribe(topic)
            
#             # v8.11 MOD: smart_rerouting_enabled *不是* None 才會廣播
#             if smart_rerouting_enabled is not None: 
#                 if userdata["world_id"] == "main_world":
#                     print(f"📢 正在廣播全域設定：智慧 Reroute -> {smart_rerouting_enabled}"); 
#                     config_payload = json.dumps({"smart_rerouting_enabled": smart_rerouting_enabled}); 
#                     client.publish("system/config", config_payload, qos=1, retain=True)

#         else:
#             try: reason_name = mqtt.ReasonCodes(rc).getName()
#             except: reason_name = "Unknown"
#             print(f"❌ MQTT Client '{client._client_id}' ({host}:{port}) 連接失敗，返回碼: {rc} ({reason_name})")

#     def on_disconnect(client, userdata, flags, rc, properties):
#         """ MQTT 意外斷線時的回調函式 """
#         if rc != 0:
#             try: reason_name = mqtt.ReasonCodes(rc).getName()
#             except: reason_name = "Unknown"
#             print(f"⚠️ MQTT Client '{client._client_id}' ({host}:{port}) 意外斷開連接，返回碼: {rc} ({reason_name})。")

#     client.on_connect = on_connect
#     client.on_disconnect = on_disconnect

#     try:
#         client.connect(host, port, keepalive=60)
#         client.loop_start()
#         return client
#     except Exception as e:
#         print(f"❌ MQTT Client '{client_id}' ({host}:{port}) 連接時發生錯誤: {e}")
#         return None

# # --- 【v8.11 新增】: 用於手動恢復的輸入線程 ---
# def wait_for_resume_input(world_id, client):
#     """
#     在一個單獨的線程中等待使用者按下 [Enter] 鍵。
#     """
#     global resume_event, shutdown_flag, SIM_STATE
    
#     # 等待進入 WAITING_FOR_RESUME 狀態
#     while SIM_STATE != "WAITING_FOR_RESUME" and not shutdown_flag.is_set():
#         time.sleep(0.5)

#     if shutdown_flag.is_set():
#         print(f"[{world_id}] 輸入線程：偵測到關閉信號，即將退出。")
#         return

#     print(f"\n================================================================")
#     print(f"    🏁 [{world_id}] 已收到 Pacer 的 ACK。同步準備就緒。")
#     print(f"    請在此終端機按下 [Enter] 鍵")
#     print(f"    以觸發 *兩個* 世界的模擬恢復運行。")
#     print(f"================================================================")
    
#     try:
#         # 啟動一個子線程來監聽 input()
#         def get_input():
#             try:
#                 input() # 阻塞, 等待 Enter
#                 resume_event.set() # 觸發事件
#             except EOFError:
#                 if not shutdown_flag.is_set():
#                     print(f"[{world_id}] 輸入線程被中斷。")
#                     resume_event.set() # 同樣觸發，讓主迴圈決定
#             except Exception as e:
#                 if not shutdown_flag.is_set():
#                     print(f"[{world_id}] 輸入線程錯誤: {e}")
#                     resume_event.set()

#         input_thread = threading.Thread(target=get_input, daemon=True)
#         input_thread.start()

#         while not resume_event.is_set() and not shutdown_flag.is_set():
#             time.sleep(0.1) # 非阻塞地等待事件

#         if shutdown_flag.is_set():
#              print(f"[{world_id}] 輸入線程：在等待 Enter 時收到關閉信號。")
#              return

#         # [Enter] 鍵已被按下
#         if SIM_STATE == "WAITING_FOR_RESUME":
#             print(f"⌨️  [{world_id}] [Enter] 鍵已按下！正在發送「全部恢復」指令...")
#             if client and client.is_connected():
#                 client.publish(SYSTEM_RESUME_ALL_TOPIC, json.dumps({"command": "RESUME", "world_id": world_id}), qos=1)
#             # on_command_message 會處理自己的狀態切換
#         else:
#             print(f"[{world_id}] 模擬已恢復，無需再次按鍵。")
            
#     except Exception as e:
#         if not shutdown_flag.is_set():
#             print(f"[{world_id}] 'wait_for_resume_input' 發生錯誤: {e}")


# # ============================================================ #
# # 全域訊號處理 (v8.12.6)
# # ============================================================ #
# def signal_handler(signum, frame):
#     """
#     (v8.12.6) 訊號處理函式 (例如 Ctrl+C)。
    
#     設置全域的 shutdown_flag，以通知主迴圈
#     應在下一個迭代開始前停止。
#     """
#     global shutdown_flag, resume_event, config
    
#     world_id_log = "sub_world"
#     try:
#         if config:
#             world_id_log = config.get('world_id', 'sub_world')
#     except NameError:
#         pass
        
#     print(f"\n[{world_id_log}] 捕獲到信號 {signum} ({signal.Signals(signum).name})，設置關閉標誌...")
#     shutdown_flag.set()
#     resume_event.set() # v8.12.6: 釋放 input() 線程


# # ============================================================ #
# # 
# #  MAIN 函式 (v8.12.8 教授修正版)
# # 
# # ============================================================ #
# def main():
#     """
#     主函式，啟動並運行 sub_world 模擬。
#     """
#     # --- !! 配置區 !! ---
#     world_id = "sub_world" # <--- 設定為 sub_world
#     traci_port = 8814  # <--- 設定為 sub_world 的端口
    
#     # --- 【v8.12.6 修正】: 宣告存取全域變數 ---
#     global SIM_STATE, config, vehicleDict, shutdown_flag, resume_event, control_client, traci
    
#     SIM_STATE = "RUNNING"
    
#     vehicle_dispatcher = None
#     command_client = None
#     # control_client 已在全域宣告
    
#     # --- 基本設定 (v8.12.6) ---
#     config = {
#         'world_id': world_id,
#         'PHYSICAL_BROKER': {'host': '127.0.0.1', 'port': 7883}, # Data Broker
#         'VIRTUAL_BROKER': {'host': '127.0.0.1', 'port': 7884}, # Control Broker
#         # 'SUMO_BINARY': "/usr/bin/sumo-gui", 
#         'SUMO_BINARY': "sumo-gui",
#         'SUMO_CONFIG_FILE': os.path.join(os.path.dirname(os.path.abspath(__file__)), "osm.sumocfg_incident.xml"), # <--- 使用 sub_world 的 config
#         'TRACI_PORT': traci_port,
#         'PUBLISH_PERIOD_STEPS': 1,
#         'RTF_PRINT_INTERVAL_STEPS': 100,
#         'RSU_PUBLISH_INTERVAL_STEPS': 5,
#         'SIMULATION_START_STEP': 10,
#         'SIMULATION_END_STEP': 3600,
#         'OUTPUT_XML_FILE': f'report_{world_id}_{time.strftime("%Y%m%d_%H%M%S")}.xml',
#         'ACK_TIMEOUT': 5.0
#     }
#     # --- 功能開關 (v7.2.1 不變) ---
#     ENABLE_PERCEPTION_SYSTEM = True
#     ENABLE_SMART_REROUTING = True
#     ENABLE_EXTERNAL_CONTROL = True
#     # --- !! 配置結束 !! ---

#     print(f"=================================================\n🚀 模擬世界啟動中... World ID: [{world_id}], TraCI Port: [{traci_port}]\n=================================================")
    
#     # --- 初始化 Dispatcher (v8.12.6) ---
#     vehicle_dispatcher, pc_list = setup_dispatcher(config, world_id)
#     if vehicle_dispatcher is None:
#         print(f"❌ [{world_id}] 無法初始化 Vehicle Dispatcher (7884)，終止模擬。")
#         return

#     # --- 啟動 SUMO (v8.12.8 修正) ---
#     try:
#         start_sumo(config, config['TRACI_PORT'])
#         print(f"✅ [{world_id}] SUMO 模擬已啟動！")

#         # --- 【v8.12.8 修正】: 偵錯區塊已 *移動* 至此處 ---
#         # 必須在 traci.start() 成功後才能呼叫
#         print("="*60)
#         print(f"DEBUG [sub_world]: 實際載入的 TraCI 版本: {traci.getVersion()}")
#         print(f"DEBUG [sub_world]: 實際載入的 TraCI 路徑: {traci.__file__}")
#         print("="*60)
#         # --- 偵錯區塊結束 ---

#     except Exception as e:
#         print(f"❌ [{world_id}] 啟動 SUMO 失敗: {e}")
#         if vehicle_dispatcher: vehicle_dispatcher.disconnect()
#         return

#     # --- 初始化 Queues 和狀態 (v8.12.6 修正) ---
#     reroute_requests_queue = queue.Queue()
#     simulation_control_queue = queue.Queue() 
#     tls_sync_queue = queue.Queue() # 【v8.12.6】: 線程安全修正
#     externally_closed_edges = set()

#     # --- 【v8.12.6 關鍵修改】: MQTT 指令回調函式 ---
#     def on_command_message(client, userdata, msg):
#         """ 
#         處理來自 MQTT 的指令 (可來自 7883 或 7884)。
#         """
#         # 【v8.12.6 MOD】: SIM_STATE 是全域變數
#         global SIM_STATE, resume_event
        
#         try:
#             current_world_id = userdata["world_id"]
            
#             # (Flow 5) Reroute 請求 (來自 7883)
#             expected_reroute_topic = f"worlds/{current_world_id}/reroute_request"
#             if msg.topic == expected_reroute_topic:
#                 if ENABLE_SMART_REROUTING and SIM_STATE == "RUNNING": # v8.12 MOD: 僅在運行時處理
#                     payload_str = msg.payload.decode('utf-8')
#                     if not payload_str: return
#                     payload = json.loads(payload_str)
#                     if isinstance(payload, dict) and 'veh_id' in payload:
#                         reroute_requests_queue.put(payload)

#             # (Flow 8) 外部 Hotspot 情報 (來自 7884)
#             elif msg.topic == INTER_WORLD_TOPIC and ENABLE_EXTERNAL_CONTROL and SIM_STATE == "RUNNING": # v8.12 MOD: 僅在運行時處理
#                 payload_str = msg.payload.decode('utf-8')
#                 if not payload_str: return
#                 payload = json.loads(payload_str)
#                 source_world = payload.get("source_world")
#                 if source_world and isinstance(source_world, str) and source_world != current_world_id:
#                     lane_id = payload.get("lane_id")
#                     status = payload.get("status")
#                     edge_id = get_edge_id_from_lane_id(lane_id)
#                     if edge_id and status in ["CONGESTED", "CLEAR"]:
#                         command = "CLOSE_EDGE" if status == "CONGESTED" else "OPEN_EDGE"
#                         reason = f"EXTERNAL_{status}"
#                         if status == "CONGESTED":
#                             reason = f"EXTERNAL_CONGESTED_{payload.get('congestion_level', 'UNKNOWN')}"
#                         control_command = {"command": command, "edge_id": edge_id, "source_world": source_world, "reason": reason}
#                         simulation_control_queue.put(control_command)
                
#             # --- 【v8.12.6 線程安全修正】: 處理來自 Pacer 的同步指令 ---
#             elif msg.topic == SYSTEM_TLS_SYNC_TOPIC:
#                 if SIM_STATE == "RUNNING":
#                     print(f"🔔 [{current_world_id}] 收到 Pacer 的紅綠燈同步指令！")
#                     try:
#                         payload_str = msg.payload.decode('utf-8')
#                         tls_data = json.loads(payload_str)
                        
#                         # 1. 【線程安全】: 將資料放入佇列，讓主線程處理
#                         tls_sync_queue.put(tls_data)
                        
#                         # 2. 暫停主迴圈
#                         print(f"    -> [{current_world_id}] Follower 暫停，等待主線程應用同步...")
#                         SIM_STATE = "PAUSED_FOR_SYNC" 
                        
#                     except Exception as e:
#                         print(f"❌ [{current_world_id}] 解析紅綠燈同步數據時出錯: {e}")
#                         # 即使解析失敗，也嘗試恢復，避免卡死
#                         time.sleep(1)
#                         SIM_STATE = "RUNNING"
#                 else:
#                     print(f"⚠️ [{current_world_id}] 在非 RUNNING 狀態 ({SIM_STATE}) 收到 TLS_SYNC，已忽略。")
                        
#             # --- 【v8.12 新增】: 處理來自 Pacer 或自己的手動恢復指令 ---
#             elif msg.topic == SYSTEM_RESUME_ALL_TOPIC:
#                 if SIM_STATE == "WAITING_FOR_RESUME":
#                     print(f"🏁 [{current_world_id}] 收到 [Enter] 恢復指令，Follower 恢復運行！")
#                     SIM_STATE = "RUNNING"
#                     resume_event.set() # 確保 input 線程不會卡住
#                 elif SIM_STATE == "PAUSED_FOR_SYNC":
#                     # 處理一種邊界情況：Pacer 發送了 RESUME，但 Follower 還在 PAUSED_FOR_SYNC
#                     print(f"🏁 [{current_world_id}] 在 PAUSED_FOR_SYNC 狀態收到 RESUME，強制恢復運行！")
#                     SIM_STATE = "RUNNING"
#                     resume_event.set()

#         except (json.JSONDecodeError, UnicodeDecodeError, IndexError, KeyError, AttributeError) as e:
#             print(f"[{userdata.get('world_id','?')}] 處理指令時發生錯誤 ({msg.topic}, Payload: '{msg.payload.decode('utf-8', errors='ignore')}'): {e}")


#     # --- Data Client (7883) (v7.2.1 不變) ---
#     topics_to_subscribe_data = []
#     if ENABLE_SMART_REROUTING: 
#         topics_to_subscribe_data.append(f"worlds/{world_id}/reroute_request")

#     command_client = connect_mqtt(
#         config['PHYSICAL_BROKER']['host'], config['PHYSICAL_BROKER']['port'],
#         f"SimCmdHandler_Data_{world_id}_{int(time.time())}",
#         on_command_message, 
#         topics_to_subscribe_data,
#         None, 
#         world_id
#     )
#     if command_client is None:
#         if vehicle_dispatcher: vehicle_dispatcher.disconnect()
#         return
#     print(f"[{world_id}] 資料指令接收器 (7883) 已啟動...")
    
#     # --- Control Client (7884) (v8.12.6 修改) ---
#     # v8.12.6: control_client 已是全域
#     topics_to_subscribe_control = []
#     if ENABLE_EXTERNAL_CONTROL: 
#         topics_to_subscribe_control.append(INTER_WORLD_TOPIC)
        
#     # 【v8.12 新增】: Follower 必須監聽這兩個
#     topics_to_subscribe_control.append(SYSTEM_TLS_SYNC_TOPIC)
#     topics_to_subscribe_control.append(SYSTEM_RESUME_ALL_TOPIC) 
    
#     control_client = connect_mqtt(
#         config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'],
#         f"SimCmdHandler_Control_{world_id}_{int(time.time())}",
#         on_command_message, 
#         topics_to_subscribe_control,
#         None, 
#         world_id
#     )
#     if control_client is None:
#         if command_client: command_client.disconnect()
#         if vehicle_dispatcher: vehicle_dispatcher.disconnect()
#         return
#     print(f"[{world_id}] 平台控制/同步 接收器 (7884) 已啟動...")

#     # --- 子世界註冊 (v7.2.1 邏輯, 這是「喊到」) ---
#     print(f"[{world_id}] 等待 1 秒...")
#     time.sleep(1.0)
#     print(f"[{world_id}] 發布上線註冊訊息 (7884)...")
#     register_payload = json.dumps({"world_id": world_id, "status": "online", "timestamp": time.time()})
#     try:
#         if control_client and control_client.is_connected():
#             control_client.publish(SYSTEM_REGISTER_TOPIC, register_payload, qos=1)
#             print(f"[{world_id}] 註冊訊息已發布至 (7884)。")
#         else: 
#             print(f"⚠️ [{world_id}] Control Client (7884) 未連接，無法發布註冊訊息。")
#     except Exception as e: 
#         print(f"❌ [{world_id}] 發布註冊訊息 (7884) 時出錯: {e}")

#     # --- 初始化模擬狀態和數據收集 (v8.12.6) ---
#     # v8.12.6: vehicleDict 已是全域
#     vehicleDict.clear()
#     current_simulation_step = 0
#     pc_assignment_counter = 0

#     rtf_state = {'active': False}
#     rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data = [], [], [], []
#     t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data = [], [], [], []
#     t3_per_step_data, reroute_counts_per_step, total_reroutes_processed = [], [], 0

#     print("\n" + "="*30 + f"\n[{world_id}] RTF 效能測試模組已準備就緒。\n" + "="*30)

#     # --- 優雅關閉處理 (v8.12.6) ---
#     # v8.12.6: shutdown_flag 和 signal_handler 已是全域
#     signal.signal(signal.SIGINT, signal_handler)
#     signal.signal(signal.SIGTERM, signal_handler)

#     # ============================================================ #
#     # === v8.12.8 主模擬循環 (狀態機) ===
#     # ============================================================ #
#     try:
#         while not shutdown_flag.is_set():
            
#             # --- 【v8.12 狀態機】: 運行中 ---
#             if SIM_STATE == "RUNNING":
                
#                 # --- (v7.2.1 迴圈的 *完整* 內容) ---
#                 try:
#                     current_sim_time_check = traci.simulation.getTime()
#                     if traci.simulation.getMinExpectedNumber() <= 0 and current_simulation_step > 0:
#                         print(f"[{world_id}] 模擬中已無車輛 (步長 {current_simulation_step})，結束模擬。")
#                         break
#                 except (traci.TraCIException, ConnectionResetError, OSError) as conn_err:
#                     print(f"[{world_id}] TraCI 連接錯誤 ({type(conn_err).__name__})，終止模擬。")
#                     break
#                 if current_simulation_step >= config['SIMULATION_END_STEP']:
#                     print(f"[{world_id}] 達到模擬結束步長 {config['SIMULATION_END_STEP']}，結束模擬。")
#                     break

#                 step_start_time = time.perf_counter()
#                 step_timings = {}

#                 # --- 1. 處理 T4 (v8.12.7 修正) ---
#                 t4_start = time.perf_counter()
#                 control_commands_processed_this_step = 0
#                 if ENABLE_EXTERNAL_CONTROL:
#                     current_edge_list = None
#                     while not simulation_control_queue.empty():
#                         try: command_data = simulation_control_queue.get_nowait()
#                         except queue.Empty: break
#                         edge_id = command_data.get("edge_id"); command = command_data.get("command"); source = command_data.get("source_world", "UNKNOWN")
#                         if not edge_id or not command: continue
#                         if current_edge_list is None:
#                             try: current_edge_list = traci.edge.getIDList()
#                             except traci.TraCIException: current_edge_list = []
#                         if edge_id not in current_edge_list: continue
                        
#                         # 【v8.12.7 修正】: 從全域常數讀取
#                         allowed_classes = DEFAULT_ALLOWED_VCLASSES
                        
#                         try:
#                             if command == "CLOSE_EDGE":
#                                 if edge_id not in externally_closed_edges:
#                                     print(f"🕹️ [{world_id}] <- (來自 {source} on 7884) 關閉 Edge {edge_id}")
                                    
#                                     traci.edge.setDisallowed(edge_id, allowed_classes) # <-- 保持你原有的註解
                                    
#                                     # 【v8.12.19 教授修改】: 依照要求，改為直接呼叫 traci API
#                                     traci.edge.setParameter(edge_id, "color", "255,0,0") # 寫死為紅色
                                    
#                                     externally_closed_edges.add(edge_id)
#                                     control_commands_processed_this_step += 1
                                    
#                             elif command == "OPEN_EDGE":
#                                 if edge_id in externally_closed_edges:
#                                     print(f"🕹️ [{world_id}] <- (來自 {source} on 7884) 開啟 Edge {edge_id}")
#                                     traci.edge.setAllowed(edge_id, allowed_classes)
                                    
#                                     # 【v8.12.19 教授修改】: 依照要求，改為直接呼叫 traci API (空字串為重置顏色)
#                                     traci.edge.setParameter(edge_id, "color", "") # 空字串為重置顏色
                                    
#                                     externally_closed_edges.remove(edge_id)
#                                     control_commands_processed_this_step += 1
                                    
#                         except traci.TraCIException as e: print(f"⚠️ [{world_id}] 執行 SUMO 指令出錯 ({command} on {edge_id}): {e}")
#                 t4_end = time.perf_counter()
#                 step_timings['T4_SimControl'] = t4_end - t4_start
#                 step_timings['control_commands_processed'] = control_commands_processed_this_step

#                 # --- 2. 執行 T0 (v7.2.1 邏輯) ---
#                 t0_start = time.perf_counter()
#                 traci.simulationStep()
#                 t0_end = time.perf_counter()
#                 current_simulation_step += 1
#                 step_timings['T0_SumoStep'] = t0_end - t0_start

#                 # --- 3. 發布 RSU (v7.2.1 邏輯) ---
#                 if ENABLE_PERCEPTION_SYSTEM and current_simulation_step % config['RSU_PUBLISH_INTERVAL_STEPS'] == 0:
#                     rsu_raw_data = {}
#                     try:
#                         all_detectors = traci.inductionloop.getIDList()
#                         if all_detectors:
#                             for det_id in all_detectors:
#                                 try:
#                                     lane_id = traci.inductionloop.getLaneID(det_id)
#                                     mean_speed = traci.inductionloop.getLastStepMeanSpeed(det_id)
#                                     vehicle_count = traci.inductionloop.getLastStepVehicleNumber(det_id)
#                                     if lane_id and not lane_id.startswith(':') and mean_speed >= 0:
#                                         rsu_raw_data[lane_id] = {"mean_speed": mean_speed, "vehicle_count": vehicle_count}
#                                 except traci.TraCIException: continue
#                             if rsu_raw_data:
#                                 if control_client and control_client.is_connected():
#                                     control_client.publish(f"worlds/{world_id}/rsu/raw_data", json.dumps(rsu_raw_data), qos=0)
#                     except traci.TraCIException: pass

#                 # --- 4. 處理 T3 (v7.2.1 邏輯) ---
#                 t3_duration_sec, reroutes_this_step, avg_time_per_veh_ms = 0, 0, 0.0
#                 if ENABLE_SMART_REROUTING:
#                     t3_start = time.perf_counter()
#                     processed_reroutes_in_batch = 0
#                     current_vehicle_list = []
#                     try: current_vehicle_list = traci.vehicle.getIDList()
#                     except traci.TraCIException: pass
#                     while not reroute_requests_queue.empty() and processed_reroutes_in_batch < 1000:
#                         try: request = reroute_requests_queue.get_nowait()
#                         except queue.Empty: break
#                         veh_id_to_reroute = request.get('veh_id')
#                         if veh_id_to_reroute and veh_id_to_reroute in current_vehicle_list:
#                             try:
#                                 traci.vehicle.rerouteTraveltime(veh_id_to_reroute)
#                                 reroutes_this_step += 1
#                             except traci.TraCIException: pass
#                         processed_reroutes_in_batch += 1
#                     t3_end = time.perf_counter()
#                     t3_duration_sec = t3_end - t3_start
#                     if reroutes_this_step > 0:
#                         avg_time_per_veh_ms = (t3_duration_sec * 1000) / reroutes_this_step
#                     if processed_reroutes_in_batch > 0:
#                         t3_per_step_data.append(t3_duration_sec * 1000)
#                         reroute_counts_per_step.append(reroutes_this_step)
#                     total_reroutes_processed += reroutes_this_step
#                 step_timings['T3_Rerouting'] = t3_duration_sec
#                 step_timings['reroute_count'] = reroutes_this_step
#                 step_timings['reroute_avg_ms'] = avg_time_per_veh_ms

#                 # --- 5. 垃圾回收 (v7.2.1 邏輯) ---
#                 try:
#                     is_traci_connected_gc = False
#                     try: traci.simulation.getTime(); is_traci_connected_gc = True
#                     except (traci.TraCIException, ConnectionResetError, OSError): is_traci_connected_gc = False
#                     if is_traci_connected_gc:
#                         garbage_collector(config['PHYSICAL_BROKER']['host'], config['PHYSICAL_BROKER']['port'],
#                                           config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'],
#                                           traci.simulation, vehicleDict, world_id)
#                 except Exception as gc_e: print(f"[{world_id}] Error during garbage collection: {gc_e}")

#                 # --- 6. 收集 T1 (v7.2.1 邏輯) ---
#                 t1_start = time.perf_counter()
#                 vehicles_to_dispatch, vehicle_states, pc_assignment_counter = collect_and_prepare_dispatch_data(
#                     current_simulation_step, config, vehicleDict, pc_list, pc_assignment_counter
#                 )
#                 t1_end = time.perf_counter()
#                 step_timings['T1_DataCollection'] = t1_end - t1_start
#                 step_timings['Processed_Vehicles'] = len(vehicles_to_dispatch)

#                 # --- 7. 處理 T2 (v7.2.1 邏輯) ---
#                 ack_target_count = len(vehicles_to_dispatch)
#                 t2_duration = 0.0
#                 if ack_target_count > 0:
#                     t2_start = time.perf_counter()
#                     dispatched_count_actual = 0
#                     for veh_id in vehicles_to_dispatch:
#                         if veh_id in vehicle_states:
#                             vehicle = vehicleDict.get(veh_id)
#                             if not vehicle or not vehicle.physicalComputerMapping: continue
#                             pc = vehicle.physicalComputerMapping
#                             state_data = vehicle_states[veh_id]
#                             dispatch_topic = f"{pc}_{world_id}"
#                             try:
#                                 if vehicle_dispatcher and vehicle_dispatcher.mqttc and vehicle_dispatcher.mqttc.is_connected():
#                                     vehicle_dispatcher.dispatch_vehicle(dispatch_topic, veh_id, state_data)
#                                     dispatched_count_actual += 1
#                             except Exception as dispatch_e: print(f"[{world_id}] Error dispatching vehicle {veh_id}: {dispatch_e}")
#                     if dispatched_count_actual > 0: wait_for_acks(vehicle_dispatcher, dispatched_count_actual)
#                     t2_end = time.perf_counter()
#                     t2_duration = t2_end - t2_start
#                 step_timings['T2_RoundTripWait'] = t2_duration

#                 # --- 8. 更新 RTF (v7.2.1 邏輯) ---
#                 step_end_time = time.perf_counter()
#                 time_elapsed_for_step = step_end_time - step_start_time
#                 rtf_state = update_rtf_monitor(
#                     rtf_state, config, current_simulation_step, time_elapsed_for_step,
#                     rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, step_timings,
#                     t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data
#                 )
            
#             # --- 【v8.12.6 線程安全修正】: 暫停並應用同步 ---
#             elif SIM_STATE == "PAUSED_FOR_SYNC":
#                 try:
#                     # 1. 從佇列中獲取 TLS 數據 (如果 MQTT 線程還沒放入，會在這裡等待)
#                     tls_data = tls_sync_queue.get(timeout=0.1) # 等待 0.1 秒
                    
#                     # 2. 【線程安全】: 由主線程安全地呼叫 TraCI
#                     apply_tls_status(traci, tls_data)
                    
#                     # 3. 發送 ACK
#                     print(f"    -> [{world_id}] 同步完成，發送 ACK...")
#                     if control_client and control_client.is_connected():
#                         control_client.publish(SYSTEM_TLS_ACK_TOPIC, json.dumps({"status": "OK", "world_id": world_id}), qos=1)
                    
#                     # 4. 進入等待恢復的狀態
#                     SIM_STATE = "WAITING_FOR_RESUME"
#                     print(f"    -> [{world_id}] 已發送 ACK，等待手動 [Enter] 恢復...")
                    
#                     # 5. 觸發「等待 Enter」的線程
#                     resume_event.clear() # 重置事件
#                     input_thread = threading.Thread(target=wait_for_resume_input, args=(world_id, control_client), daemon=True)
#                     input_thread.start()

#                 except queue.Empty:
#                     # 佇列中沒有資料，繼續 sleep
#                     time.sleep(0.05)
#                 except Exception as e:
#                     print(f"❌ [{world_id}] [PAUSED] 應用同步指令時出錯: {e}")
#                     print(f"    -> 3秒後自動恢復運行...")
#                     time.sleep(3)
#                     SIM_STATE = "RUNNING" # 同步失敗，也要恢復
            
#             # --- 【v8.11 狀態機】: 等待恢復指令 ---
#             elif SIM_STATE == "WAITING_FOR_RESUME":
#                 # 這是主迴圈的「暫停」狀態
#                 time.sleep(0.1) # 降低 CPU 佔用

#             # --- 狀態機結束 ---

#     except KeyboardInterrupt:
#         print(f"\n[{world_id}] 收到關閉信號 (來自主迴圈)，退出主循環...")
#     except FatalTraCIError as e:
#         print(f"\n💥 [{world_id}] TraCI 發生致命錯誤，模擬提前終止: {e}")
#     except traci.TraCIException as e:
#         print(f"\n💥 [{world_id}] TraCI 連接錯誤 (可能 SUMO 已關閉)，模擬提前終止: {e}")
#     except Exception as e:
#         print(f"\n============================================================\n💥💥💥 [{world_Vworld_id}] 主模擬循環發生致命錯誤 💥💥💥\n錯誤類型: {type(e).__name__}\n錯誤訊息: {e}\n\n---詳細錯誤追蹤 (Traceback) ---\n")
#         traceback.print_exc()
#         print("============================================================\n")
    
#     # ============================================================ #
#     # === v8.12.8 清理程序 ===
#     # ============================================================ #
#     finally:
#         print(f"\n[{world_id}] 模擬結束於步驟 {current_simulation_step}。")
#         resume_event.set() # 確保 input 線程不會卡住

#         # --- 最後清理：重新開啟所有外部關閉的 Edge ---
#         is_traci_connected_final = False
#         try:
#             if 'traci' in sys.modules and traci:
#                 try: traci.simulation.getTime(); is_traci_connected_final = True
#                 except (traci.TraCIException, ConnectionResetError, OSError): is_traci_connected_final = False

#                 if is_traci_connected_final:
#                     print(f"[{world_id}] 正在重新開啟 {len(externally_closed_edges)} 個因外部指令關閉的 Edge...")
                    
#                     # 【v8.12.7 修正】: 宣告 allowed_classes
#                     allowed_classes = DEFAULT_ALLOWED_VCLASSES
#                     edges_to_reopen = list(externally_closed_edges)
#                     try: edge_list_at_end = set(traci.edge.getIDList())
#                     except traci.TraCIException: edge_list_at_end = set()

#                     for edge_id in edges_to_reopen:
#                         if edge_id in edge_list_at_end:
#                             try:
#                                 # 【v8.12.7 修正】: 恢復為客製化的 allowed_classes
#                                 traci.edge.setAllowed(edge_id, allowed_classes)
                                
#                                 # 【v8.12.19 教授修改】: 依照要求，改為直接呼叫 traci API (空字串為重置顏色)
#                                 traci.edge.setParameter(edge_id, "color", "") # 空字串為重置顏色
                                
#                                 print(f"    ✅ [{world_id}] Reopened edge {edge_id}")
#                             except traci.TraCIException as e: print(f"    ⚠️ [{world_id}] 無法重新開啟 edge {edge_id}: {e}")
#                     externally_closed_edges.clear()

#                     print(f"[{world_id}] S 正在關閉 TraCI 連接...")
#                     traci.close()
#                     print(f"[{world_id}] TraCI 連接已關閉。")
#         except NameError: pass
#         except Exception as final_traci_e: print(f"[{world_id}] 在最終清理 TraCI 時發生錯誤: {final_traci_e}")


#         # --- 斷開 MQTT 連接 ---
#         print(f"[{world_id}] 開始清理 MQTT 資源...")
#         if 'command_client' in locals() and command_client and command_client.is_connected():
#             print(f"[{world_id}] S 正在斷開 MQTT Data Client (7883)...")
#             command_client.loop_stop(); time.sleep(0.1); command_client.disconnect()
            
#         if 'control_client' in locals() and control_client and control_client.is_connected():
#             print(f"[{world_id}] S 正在斷開 MQTT Control Client (7884)...")
#             control_client.loop_stop(); time.sleep(0.1); control_client.disconnect()

#         if 'vehicle_dispatcher' in locals() and vehicle_dispatcher and hasattr(vehicle_dispatcher, 'mqttc') and vehicle_dispatcher.mqttc.is_connected():
#             print(f"[{world_id}] S 正在斷開車輛分派器 MQTT 客戶端 (7884)...")
#             vehicle_dispatcher.disconnect()
            
#         if 'traci' in sys.modules and not is_traci_connected_final:
#             print(f"[{world_id}] TraCI 已斷開連接。")

#         # --- 打印/生成報告 ---
#         print(f"[{world_id}] 正在生成最終效能報告...")
#         print_performance_report(
#             config, rtf_data or [], vehicle_count_data or [], halting_vehicle_data or [], congestion_data or [],
#             t0_per_vehicle_data or [], t1_per_vehicle_data or [], t2_per_vehicle_data or [], overhead_per_vehicle_data or [],
#             t3_per_step_data or [], reroute_counts_per_step or [], total_reroutes_processed, current_simulation_step
#         )
#         print(f"[{world_id}] 模擬程序完全結束。")


# # 移除 SUMO_HOME 檢查
# if __name__ == '__main__':
#     # (v8.12.6) 初始化全域變數
#     config = {}
#     vehicleDict = {}
#     resume_event = threading.Event()
#     control_client = None
#     SIM_STATE = "RUNNING"
#     shutdown_flag = threading.Event() 
    
#     main()























# traffic_simulation/sub_world_sim.py
# traffic_simulation/sub_world_sim.py
# 使用  traci.lane.setAllowed 進行封路 !  


# traffic_simulation/sub_world_sim.py
# (v8.12.24 - 控制器版)
# (1. 使用 v1 (方案 B) 的 traci.lane.setAllowed 進行封路)
# (2. 刪除無用的 set_edge_color_compat 函式)
# (3. 移除本地 input() 邏輯，改為監聽 controller.py)


import os
import sys
import time
import json
import queue
import threading
import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import statistics
import traceback
import signal
import xml.etree.ElementTree as ET
from xml.dom import minidom

# --- SUMO 環境設定 ---
# 【v8.12.14 - 最終相對路徑修正】
# 讓腳本自動尋找 traci 函式庫

# 1. 獲取此腳本 (sim_sub_world.py) 所在的目錄
#    (即: .../sumo_platform/testbed/traffic_simulation)
script_dir = os.path.dirname(os.path.abspath(__file__))

# 2. 往上走兩層，到達專案根目錄 (.../sumo_platform)
project_root = os.path.dirname(os.path.dirname(script_dir))

# 3. 建立我們新的函式庫路徑 (.../sumo_platform/tools_lib)
traci_lib_path = os.path.join(project_root, "tools_lib")

if not os.path.exists(traci_lib_path):
    print(f"❌ 致命錯誤：找不到 Traci 函式庫：{traci_lib_path}")
    print("請確認您已執行『原始碼方案』的階段 2 (下載並解壓縮)")
    sys.exit(1)
    
if traci_lib_path not in sys.path:
    sys.path.insert(0, traci_lib_path)

try:
    import traci
    from traci.exceptions import TraCIException, FatalTraCIError
    
except ImportError:
    print("錯誤：無法導入 traci 模組。")
    print(f"檢查的路徑: {traci_lib_path}")
    sys.exit(1)


# --- 導入自訂模組 ---
try:
    from traffic_Vehicle import Vehicle
    from garbage_collector import garbage_collector
    from traffic_Vehicle_dispatcher import Vehicle_dispatcher
except ImportError as e:
    print(f"錯誤：無法導入自訂模組: {e}")
    print("請確保 traffic_Vehicle.py, garbage_collector.py, traffic_Vehicle_dispatcher.py 與此腳本在同一目錄下。")
    sys.exit(1)


# --- v8.12.7 全域常數 ---
INTER_WORLD_TOPIC = "system/inter_world_hotspots"
# 【v8.12.7 客製化修正】: 根據需求，僅保留 "passenger"
DEFAULT_ALLOWED_VCLASSES = ["passenger"]

# 【v8.12 新增】: MQTT 同步主題
SYSTEM_REGISTER_TOPIC = "system/worlds/register"
SYSTEM_TLS_SYNC_TOPIC = "system/tls_sync"
SYSTEM_TLS_ACK_TOPIC = "system/tls_ack"
SYSTEM_RESUME_ALL_TOPIC = "system/resume_all"
SYSTEM_PAUSE_ALL_TOPIC = "system/pause_all" # 【v8.12.24 新增】

# --- 全局變量 ---
config = {}
vehicleDict = {}
# 【v8.12.24 刪除】: resume_event 已被移除
control_client = None
SIM_STATE = "RUNNING"
shutdown_flag = threading.Event()


# ============================================================ #
# 輔助函式 (v7.0 + v8.12.5)
# ============================================================ #

# 【v8.12.22 刪除】: set_edge_color_compat 函式已被移除

def get_edge_id_from_lane_id(lane_id):
    """ 
    @教授註解: 從 lane_id (如 'edge123_0') 提取 edge_id ('edge123') 
    """
    if not lane_id or lane_id.startswith(':'): return None
    try: return lane_id.rsplit('_', 1)[0]
    except Exception: return None

def retrieve_vehicle_state(traci_instance, veh_id, current_step):
    """ 
    @教授註解: 從 SUMO 獲取指定車輛的詳細狀態 (v7.0 不變) 
    """
    try:
        x, y = traci_instance.vehicle.getPosition(veh_id)
        lon, lat = traci_instance.simulation.convertGeo(x, y)
        laneID = traci_instance.vehicle.getLaneID(veh_id)
        vehicleLength = traci_instance.vehicle.getLength(veh_id)
        lanePosition = traci_instance.vehicle.getLanePosition(veh_id)
        speed = traci_instance.vehicle.getSpeed(veh_id)
        laneLength = 0.0; travelTime = -1.0; maxSpeed = 0.0
        if laneID and not laneID.startswith(':'):
            try:
                laneLength = traci_instance.lane.getLength(laneID)
                travelTime = traci_instance.lane.getTraveltime(laneID)
                maxSpeed = traci_instance.lane.getMaxSpeed(laneID)
            except traci.TraCIException: pass
        current_route = []; destination_edge = None
        try:
            current_route = traci_instance.vehicle.getRoute(veh_id)
            destination_edge = current_route[-1] if current_route else None
        except traci.TraCIException: pass
        next_tls_info = None
        try:
            tls_raw_data = traci_instance.vehicle.getNextTLS(veh_id)
            if tls_raw_data:
                tls = tls_raw_data[0]
                next_tls_info = {"id": tls[0], "distance": tls[2], "state": tls[3]}
        except traci.TraCIException: pass
        connectedLanes = []
        if laneID and laneID.startswith(":"):
            try:
                links = traci_instance.lane.getLinks(laneID, False)
                for link in links: connectedLanes.append(link[0])
            except traci.TraCIException: pass
        vehicleState = dict(lat=lat, lon=lon, laneID=laneID, speed=speed, travelTime=travelTime,
                            lanePosition=lanePosition, vehicleLength=vehicleLength,
                            connectedLanes=connectedLanes, laneLength=laneLength,
                            currentRoute=current_route, destinationEdge=destination_edge,
                            maxSpeed=maxSpeed, current_step=current_step, next_tls=next_tls_info)
        return vehicleState
    except traci.TraCIException as e: return None

def apply_tls_status(traci_conn, tls_data):
    """
    @教授註解: (v8.12.5) 將從 Pacer 收到的紅綠燈狀態應用到 'sub_world' (Follower)。
    """
    global config
    world_id = config.get('world_id', 'SIM')
    print(f"[{world_id}] [SYNCING] 正在應用 {len(tls_data)} 個紅綠燈狀態...")
    apply_count = 0
    failed_tls_ids = []
    
    try:
        local_tls_ids = set(traci_conn.trafficlight.getIDList())
    except TraCIException as e:
        print(f"❌ [{world_id}] [SYNCING] 無法獲取本地 TLS 列表: {e}。同步將可能失敗。")
        local_tls_ids = set()

    
    for tls_id, status in tls_data.items():
        try:
            if tls_id not in local_tls_ids:
                raise TraCIException(f"TLS ID '{tls_id}' 在 {world_id} 中不存在。")

            phase_index = status.get("phase_index")
            remaining_duration = status.get("remaining_duration")
            
            if phase_index is not None and remaining_duration is not None:
                traci_conn.trafficlight.setPhase(tls_id, phase_index)
                traci_conn.trafficlight.setPhaseDuration(tls_id, remaining_duration)
                apply_count += 1
            else:
                raise TraCIException(f"TLS ID '{tls_id}' 數據不完整 (phase 或 duration 為 None)。")
                
        except TraCIException as e:
            failed_tls_ids.append(tls_id)
            print(f"⚠️ [{world_id}] [SYNCING] 應用 TLS '{tls_id}' 狀態失敗: {e}")

    print(f"✅ [{world_id}] [SYNCING] 成功應用 {apply_count} / {len(tls_data)} 個狀態。")
    if failed_tls_ids:
        print(f"    -> {len(failed_tls_ids)} 個紅綠燈應用失敗 (已跳過): {failed_tls_ids}")


def setup_dispatcher(config_data, world_id):
    """ 
    @教授註解: 初始化並連接到虛擬 Broker (7884) 的車輛分派器。 (v7.0 不變) 
    """
    print(f"[{world_id}] 正在初始化車輛分派器 (Vehicle Dispatcher)...")
    dispatcher = Vehicle_dispatcher()
    computers = dict(pc1='127.0.0.1')
    dispatcher.physicalComputers = computers
    pc_list = list(dispatcher.physicalComputers.keys())
    try:
        dispatcher.connect(config_data['VIRTUAL_BROKER']['host'], config_data['VIRTUAL_BROKER']['port'], world_id)
        print(f"[{world_id}] 車輛分派器連接成功 (7884)。")
    except Exception as e:
        print(f"❌ [{world_id}] 車輛分派器連接失敗 (7884): {e}")
        return None, []
    return dispatcher, pc_list

def start_sumo(config_data, traci_port):
    """ 
    @教授註解: 啟動 SUMO 模擬實例。 (v7.0 不變) 
    """
    world_id_log = config_data.get('world_id', 'SIM')
    print(f"[{world_id_log}] 正在啟動 SUMO，使用 TraCI Port: {traci_port}...")
    sumo_binary = config_data.get('SUMO_BINARY', 'sumo-gui') 
    config_file = config_data.get('SUMO_CONFIG_FILE')
    if not config_file or not os.path.exists(config_file): raise FileNotFoundError(f"SUMO 配置文件未找到: {config_file}")
    
    if not os.path.exists(sumo_binary):
        from shutil import which
        if which(sumo_binary) is None: 
            sumo_binary = 'sumo'
            if which(sumo_binary) is None:
                raise FileNotFoundError(f"SUMO 執行檔未找到 (sumo-gui 或 sumo): {config_data.get('SUMO_BINARY')}")
        else: 
            sumo_binary = which(sumo_binary)
            
    sumoCmd = [ sumo_binary, "-c", config_file, 
                "--time-to-teleport", "-1", "--ignore-route-errors", "true",
                "--no-step-log", "true", "--no-warnings", "true",
                "--log", f"sumo_log_{world_id_log}_{time.strftime('%Y%m%d_%H%M%S')}.txt",
                "--step-length", "1.0", 
                "--default.action-step-length", "1.0"
                ]
    try:
        traci.start(sumoCmd, port=traci_port, numRetries=20, label=f"TraCI_{world_id_log}")
        print(f"[{world_id_log}] TraCI.start 成功，已連接到 SUMO。")
    except Exception as e:
        print(f"❌ [{world_id_log}] Traci.start 失敗: {e}")
        raise

def collect_and_prepare_dispatch_data(current_step, config_data, vehicle_dict, pc_list, pc_counter):
    """ 
    @教授註解: 收集所有應在此步長發布狀態的車輛，並分配 OBC (pc)。 (v7.0 不變) 
    """
    vehicles_to_dispatch_this_step = []
    vehicle_states_this_step = {}
    publish_period = config_data['PUBLISH_PERIOD_STEPS']
    try: current_vehicle_ids = set(traci.vehicle.getIDList())
    except traci.TraCIException: return [], {}, pc_counter
    for veh_id in current_vehicle_ids:
        if veh_id not in vehicle_dict: vehicle_dict[veh_id] = Vehicle(veh_id)
        vehicle = vehicle_dict[veh_id]
        if vehicle.physicalComputerMapping is None and pc_list:
            pc_index = pc_counter % len(pc_list)
            vehicle.physicalComputerMapping = pc_list[pc_index]
            pc_counter += 1
        should_publish = (publish_period == 1) or \
                         (vehicle.last_publish_step == 0 and current_step >= 1) or \
                         (current_step >= vehicle.last_publish_step + publish_period)
        if should_publish: vehicles_to_dispatch_this_step.append(veh_id)
    vehicles_to_actually_dispatch = []
    if vehicles_to_dispatch_this_step:
        for veh_id in vehicles_to_dispatch_this_step:
            state = retrieve_vehicle_state(traci, veh_id, current_step)
            if state is not None:
                vehicle_states_this_step[veh_id] = state
                vehicles_to_actually_dispatch.append(veh_id)
                if veh_id in vehicle_dict: vehicle_dict[veh_id].last_publish_step = current_step
    return vehicles_to_actually_dispatch, vehicle_states_this_step, pc_counter

def wait_for_acks(dispatcher, target_count):
    """ 
    @教授註解: 等待 OBC 回傳 ACK，確保同步。 (v7.0 不變) 
    """
    global config
    if target_count <= 0 or not dispatcher: return
    timeout = config.get('ACK_TIMEOUT', 5.0)
    start_time = time.perf_counter()
    waited_time = 0
    sleep_interval = 0.005
    while dispatcher.ack_count < target_count and waited_time < timeout:
        time.sleep(sleep_interval)
        waited_time = time.perf_counter() - start_time
    if dispatcher.ack_count < target_count: print(f"⚠️ [{config.get('world_id', 'SIM')}] 等待 ACK 超時！預期 {target_count}, 收到 {dispatcher.ack_count}。")
    dispatcher.ack_count = 0

def update_rtf_monitor(rtf_state, config_data, current_step, time_elapsed_for_step, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, step_timings, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data):
    """ 
    @教授註解: 更新 RTF 效能監控數據。 (v7.0 不變) 
    """
    global vehicleDict
    world_id = config_data.get('world_id', 'SIM')
    if not rtf_state.get('active', False) and current_step >= config_data['SIMULATION_START_STEP']:
        rtf_state['active'] = True
    if rtf_state.get('active', False):
        current_rtf = 1.0 / time_elapsed_for_step if time_elapsed_for_step > 1e-9 else float('inf')
        rtf_data.append(current_rtf)
        current_vehicle_count = 0; halting_vehicles = 0
        try:
            current_vehicle_count = traci.vehicle.getIDCount()
            if current_vehicle_count > 0:
                all_vehicle_ids = traci.vehicle.getIDList()
                halting_vehicles = sum(1 for veh_id in all_vehicle_ids if traci.vehicle.getSpeed(veh_id) < 0.1)
        except traci.TraCIException:
            current_vehicle_count = len(vehicleDict); halting_vehicles = 0
        congestion_percentage = (halting_vehicles / current_vehicle_count * 100) if current_vehicle_count > 0 else 0.0
        if current_vehicle_count >= 0:
            congestion_data.append(congestion_percentage)
            halting_vehicle_data.append(halting_vehicles)
            vehicle_count_data.append(current_vehicle_count)
            
        t0 = step_timings.get('T0_SumoStep', 0); t1 = step_timings.get('T1_DataCollection', 0)
        t2 = step_timings.get('T2_RoundTripWait', 0); t3 = step_timings.get('T3_Rerouting', 0)
        t4 = step_timings.get('T4_SimControl', 0); measured_total = t0 + t1 + t2 + t3 + t4
        script_overhead = max(0.0, time_elapsed_for_step - measured_total)
        processed_vehicles = step_timings.get('Processed_Vehicles', 0)
        if processed_vehicles > 0:
            t0_avg = t0 / processed_vehicles; t1_avg = t1 / processed_vehicles
            t2_avg = t2 / processed_vehicles; overhead_avg = script_overhead / processed_vehicles
            if all(t >= 0 for t in [t0_avg, t1_avg, t2_avg, overhead_avg]):
                t0_per_vehicle_data.append(t0_avg * 1000); t1_per_vehicle_data.append(t1_avg * 1000)
                t2_per_vehicle_data.append(t2_avg * 1000); overhead_per_vehicle_data.append(overhead_avg * 1000)
    return rtf_state


def generate_xml_report(filename, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_data, t1_data, t2_data, overhead_data, t3_data, reroute_counts, total_reroutes, total_steps):
    """ 
    @教授註解: 生成 XML 格式的效能報告。 (v7.0 不變) 
    """
    global config
    root = ET.Element("PerformanceReport")
    summary_node = ET.SubElement(root, "MacroscopicSummary")
    if rtf_data:
        rtf_node = ET.SubElement(summary_node, "RealTimeFactor")
        ET.SubElement(rtf_node, "Unit").text = "Steps_per_Second"
        try:
            ET.SubElement(rtf_node, "Mean").text = f"{statistics.mean(rtf_data):.4f}"
            ET.SubElement(rtf_node, "Median").text = f"{statistics.median(rtf_data):.4f}"
            ET.SubElement(rtf_node, "Max").text = f"{max(rtf_data):.4f}"
            ET.SubElement(rtf_node, "Min").text = f"{min(rtf_data):.4f}"
        except (statistics.StatisticsError, ValueError): pass
    if vehicle_count_data:
        vc_node = ET.SubElement(summary_node, "VehicleCount")
        try:
            ET.SubElement(vc_node, "Mean").text = f"{statistics.mean(vehicle_count_data):.2f}"
            ET.SubElement(vc_node, "Max").text = f"{max(vehicle_count_data)}"
        except (statistics.StatisticsError, ValueError): pass
    reroute_summary_node = ET.SubElement(summary_node, "ReroutingOverallStats")
    ET.SubElement(reroute_summary_node, "TotalReroutesProcessed").text = str(total_reroutes)
    avg_req_per_step = total_reroutes / total_steps if total_steps > 0 else 0
    ET.SubElement(reroute_summary_node, "AverageRequestsPerSimulationStep").text = f"{avg_req_per_step:.4f}"
    micro_summary_node = ET.SubElement(root, "MicroscopicSummary")
    micro_summary_node.set("Unit", "Milliseconds")
    def add_stats_node(parent, name, data):
        mean = 0.0
        if data:
            node = ET.SubElement(parent, name)
            try:
                mean = statistics.mean(data)
                ET.SubElement(node, "Mean").text = f"{mean:.4f}"
                if len(data) > 1: ET.SubElement(node, "StdDev").text = f"{statistics.stdev(data):.4f}"
                else: ET.SubElement(node, "StdDev").text = "N/A"
            except (statistics.StatisticsError, ValueError): pass
        return mean
    mean_t0 = add_stats_node(micro_summary_node, "T0_SUMO_Internal_Step", t0_data)
    mean_t1 = add_stats_node(micro_summary_node, "T1_DataCollection", t1_data)
    mean_t2 = add_stats_node(micro_summary_node, "T2_RoundTripWait", t2_data)
    mean_overhead = add_stats_node(micro_summary_node, "T_Overhead", overhead_data)
    if any(m > 0 for m in [mean_t0, mean_t1, mean_t2, mean_overhead]):
        total_node = ET.SubElement(micro_summary_node, "Total_Per_Vehicle_Time")
        ET.SubElement(total_node, "Mean").text = f"{mean_t0 + mean_t1 + mean_t2 + mean_overhead:.4f}"
    if t3_data:
        t3_batch_node = ET.SubElement(micro_summary_node, "T3_Rerouting_Batch")
        t3_batch_node.set("Description", "Time to process a batch of reroute requests per step")
        try:
            mean_t3_batch = statistics.mean(t3_data)
            ET.SubElement(t3_batch_node, "Mean").text = f"{mean_t3_batch:.4f}"
            if len(t3_data) > 1: ET.SubElement(t3_batch_node, "StdDev").text = f"{statistics.stdev(t3_data):.4f}"
            else: ET.SubElement(t3_batch_node, "StdDev").text = "N/A"
            ET.SubElement(t3_batch_node, "Max").text = f"{max(t3_data):.4f}"; ET.SubElement(t3_batch_node, "Min").text = f"{min(t3_data):.4f}"
            total_t3_time_ms = sum(t3_data)
            avg_per_veh_ms = total_t3_time_ms / total_reroutes if total_reroutes > 0 else 0
            per_veh_node = ET.SubElement(micro_summary_node, "T3_Rerouting_PerVehicle")
            ET.SubElement(per_veh_node, "Mean").text = f"{avg_per_veh_ms:.6f}"
        except (statistics.StatisticsError, ValueError): pass
    xml_string = ET.tostring(root, 'utf-8');
    try: pretty_xml_string = minidom.parseString(xml_string).toprettyxml(indent="    ")
    except Exception: pretty_xml_string = xml_string.decode('utf-8')
    try:
        with open(filename, "w", encoding='utf-8') as f: f.write(pretty_xml_string)
        print(f"\n✅ [{config.get('world_id', 'SIM')}] 效能報告已成功生成至檔案: {filename}")
    except IOError as e: print(f"\n❌ [{config.get('world_id', 'SIM')}] 無法寫入效能報告檔案 {filename}: {e}")



def print_performance_report(config_data, rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data, t3_per_step_data, reroute_counts_per_step, total_reroutes_processed, total_simulation_steps):
    """ 
    @教授註解: 在終端打印最終的效能報告。 (v7.0 不變) 
    """
    world_id = config_data.get('world_id', 'SIM'); print("\n" + "="*50 + f"\n===== [{world_id}] 📊 最終效能綜合報告 📊 =====\n" + "="*50)
    if not rtf_data: print("未收集到足夠的 RTF 測試數據，無法生成報告。" + "\n" + "="*50); return

    def print_stats(label, data, unit=""):
        if not data: print(f" - {label}: 無數據"); return
        try:
            mean = statistics.mean(data)
            median = statistics.median(data)
            maximum = max(data)
            minimum = min(data)
            print(f" - {label}:")
            print(f"   - 平均值 (Mean):   {mean:.4f}{unit}")
            print(f"   - 中位數 (Median): {median:.4f}{unit}")
            print(f"   - 最高/最低:       {maximum:.4f}{unit} / {minimum:.4f}{unit}")
            if len(data) > 1:
                stdev = statistics.stdev(data)
                print(f"   - 標準差 (StdDev): {stdev:.4f}{unit}")
            else:
                print(f"   - 標準差 (StdDev): N/A (數據點不足)")
        except (statistics.StatisticsError, ValueError, TypeError) as e: print(f" - 計算 {label} 統計時發生錯誤: {e}")

    print("\n---  瞬時RTF (步/秒) 效能 ---"); print_stats("RTF", rtf_data, unit=" Steps/Sec")
    print("\n---  車輛數統計 (測試期間) ---")
    if vehicle_count_data:
        try: print(f" - 平均車輛數: {statistics.mean(vehicle_count_data):.2f}"); print(f" - 最高車輛數:   {max(vehicle_count_data)}")
        except (statistics.StatisticsError, ValueError) as e: print(f" - 計算車輛數統計時發生錯誤: {e}")
    else: print(" - 無車輛數數據")
    print("\n---  壅塞率 (%) 統計 ---"); print_stats("壅塞率", congestion_data, unit="%")
    print("\n---  停止車輛數統計 ---")
    if halting_vehicle_data:
        try: print(f" - 平均停止車輛數: {statistics.mean(halting_vehicle_data):.2f}"); print(f" - 最高停止車輛數:   {max(halting_vehicle_data)}")
        except (statistics.StatisticsError, ValueError) as e: print(f" - 計算停止車輛數統計時發生錯誤: {e}")
    else: print(" - 無停止車輛數數據")

    print("\n---  單車處理效能穩定性 (毫秒/輛) ---")
    if t0_per_vehicle_data:
        def print_perf_stats(label, data):
            mean = 0.0; stdev_str = "N/A"
            if data:
                try: 
                    mean = statistics.mean(data)
                    if len(data) > 1: stdev_str = f"{statistics.stdev(data):.4f} ms"
                except (statistics.StatisticsError, ValueError) : pass
            print(f" - {label}: 平均值: {mean:.4f} ms, 標準差: {stdev_str}")
        
        try:
            print_perf_stats("T0 (SUMO內部計算)", t0_per_vehicle_data)
            print_perf_stats("T1 (SUMO資訊擷取)", t1_per_vehicle_data)
            print_perf_stats("T2 (分派至OBC並等待ACK)", t2_per_vehicle_data)
            print_perf_stats("T_Overhead (腳本行政開銷)", overhead_per_vehicle_data)
            all_data_present = all([t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data])
            if all_data_present:
                try:
                    total_avg = sum(statistics.mean(d) for d in [t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data])
                    print(f" - -------------------------------------------------")
                    print(f" - 單車平均總耗時:                   {total_avg:.4f} ms")
                except statistics.StatisticsError: print(" - 無法計算單車平均總耗時 (數據不足)")
            else: print(" - 部分效能數據缺失，無法計算單車平均總耗時。")
        except (ValueError) as e: print(f" - 計算單車效能統計時發生錯誤: {e}")
    else: print(" - 未收集到單車處理時間數據。")

    print("\n---  T3 Reroute 請求處理效能 ---")
    if not t3_per_step_data: print(" - 模擬期間未執行任何 Reroute 操作。")
    else:
        try:
            print(f" [總體統計]"); print(f" - 模擬期間總處理請求數: {total_reroutes_processed} 次")
            avg_req_per_step = total_reroutes_processed / total_simulation_steps if total_simulation_steps > 0 else 0
            print(f" - 全域平均請求數:       {avg_req_per_step:.4f} 次 / 每個模擬步長")
            print(f"\n [T3 批次處理耗時 (毫秒/批次)]")
            mean_t3=statistics.mean(t3_per_step_data); max_t3=max(t3_per_step_data); min_t3=min(t3_per_step_data)
            print(f" - 平均耗時: {mean_t3:.4f} ms/批次"); print(f" - 最長/最短: {max_t3:.4f} / {min_t3:.4f} ms")
            if len(t3_per_step_data) > 1: print(f" - 標準差:   {statistics.stdev(t3_per_step_data):.4f} ms")
            total_t3_time_ms = sum(t3_per_step_data)
            avg_per_vehicle_ms = total_t3_time_ms / total_reroutes_processed if total_reroutes_processed > 0 else 0
            print(f"\n [單車 Reroute 平均耗時 (毫秒/輛)]"); print(f" - 平均耗時: {avg_per_vehicle_ms:.6f} ms/輛 (總耗時 / 總請求數)")
        except (statistics.StatisticsError, ValueError) as e: print(f" - 計算 Reroute 效能統計時發生錯誤: {e}")

    print("\n" + "="*50 + "\n")
    generate_xml_report(config_data['OUTPUT_XML_FILE'], rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data, t3_per_step_data, reroute_counts_per_step, total_reroutes_processed, total_simulation_steps)


def connect_mqtt(host, port, client_id, on_message_callback, topics_to_subscribe, smart_rerouting_enabled, world_id):
    """ 
    @教授註解: 通用 MQTT 連接器 (v7.0 不變)
    """
    print(f"[{world_id}] 正在連接 MQTT Broker {host}:{port} (Client ID: {client_id})...")
    client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    client.user_data_set({"world_id": world_id})
    client.on_message = on_message_callback

    def on_connect(client, userdata, flags, rc, properties):
        """ MQTT 連線成功時的回調函式 """
        if rc == 0:
            print(f"✅ MQTT Client '{client._client_id}' ({host}:{port}) 連接成功。")
            for topic in topics_to_subscribe: 
                print(f"    -> 訂閱: {topic}")
                client.subscribe(topic)
            
            if smart_rerouting_enabled is not None: 
                if userdata["world_id"] == "main_world":
                    print(f"📢 正在廣播全域設定：智慧 Reroute -> {smart_rerouting_enabled}"); 
                    config_payload = json.dumps({"smart_rerouting_enabled": smart_rerouting_enabled}); 
                    client.publish("system/config", config_payload, qos=1, retain=True)

        else:
            try: reason_name = mqtt.ReasonCodes(rc).getName()
            except: reason_name = "Unknown"
            print(f"❌ MQTT Client '{client._client_id}' ({host}:{port}) 連接失敗，返回碼: {rc} ({reason_name})")

    def on_disconnect(client, userdata, flags, rc, properties):
        """ MQTT 意外斷線時的回調函式 """
        if rc != 0:
            try: reason_name = mqtt.ReasonCodes(rc).getName()
            except: reason_name = "Unknown"
            print(f"⚠️ MQTT Client '{client._client_id}' ({host}:{port}) 意外斷開連接，返回碼: {rc} ({reason_name})。")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        return client
    except Exception as e:
        print(f"❌ MQTT Client '{client_id}' ({host}:{port}) 連接時發生錯誤: {e}")
        return None

# 【v8.12.24 刪除】: wait_for_resume_input 函式已被移除


# ============================================================ #
# 全域訊號處理 (v8.12.6)
# ============================================================ #
def signal_handler(signum, frame):
    """
    @教授註解: (v8.12.6) 訊號處理函式 (例如 Ctrl+C)。
    """
    global shutdown_flag, config
    
    world_id_log = "sub_world"
    try:
        if config:
            world_id_log = config.get('world_id', 'sub_world')
    except NameError:
        pass
        
    print(f"\n[{world_id_log}] 捕獲到信號 {signum} ({signal.Signals(signum).name})，設置關閉標誌...")
    shutdown_flag.set()
    # 【v8.12.24 刪除】: resume_event.set() 已被移除


# ============================================================ #
# 
#  MAIN 函式 (v8.12.24 教授修改版)
# 
# ============================================================ #
def main():
    """
    @教授註解: 主函式，啟動並運行 sub_world 模擬。
    """
    # --- !! 配置區 !! ---
    world_id = "sub_world" # <--- 設定為 sub_world
    traci_port = 8814  # <--- 設定為 sub_world 的端口
    
    # --- 【v8.12.24】: 狀態機 ---
    global SIM_STATE # SIM_STATE 必須是全域，才能被 on_command_message 修改
    SIM_STATE = "RUNNING"
    is_user_pause_logged = False # 用於在 PAUSED_FOR_USER 狀態下只打印一次提示
    
    # --- 【v8.12.6 修正】: 宣告存取全域變數 ---
    global config, vehicleDict, shutdown_flag, control_client, traci
    
    vehicle_dispatcher = None
    command_client = None
    # control_client 已在全域宣告
    
    # --- 基本設定 (v8.12.6) ---
    config = {
        'world_id': world_id,
        'PHYSICAL_BROKER': {'host': '127.0.0.1', 'port': 7883}, # Data Broker
        'VIRTUAL_BROKER': {'host': '127.0.0.1', 'port': 7884}, # Control Broker
        'SUMO_BINARY': "sumo-gui",
        'SUMO_CONFIG_FILE': os.path.join(os.path.dirname(os.path.abspath(__file__)), "osm.sumocfg_incident.xml"), # <--- 使用 sub_world 的 config
        'TRACI_PORT': traci_port,
        'PUBLISH_PERIOD_STEPS': 1,
        'RTF_PRINT_INTERVAL_STEPS': 100,
        'RSU_PUBLISH_INTERVAL_STEPS': 5,
        'SIMULATION_START_STEP': 10,
        'SIMULATION_END_STEP': 3600,
        'OUTPUT_XML_FILE': f'report_{world_id}_{time.strftime("%Y%m%d_%H%M%S")}.xml',
        'ACK_TIMEOUT': 5.0
    }
    # --- 功能開關 (v7.2.1 不變) ---
    ENABLE_PERCEPTION_SYSTEM = True
    ENABLE_SMART_REROUTING = True
    ENABLE_EXTERNAL_CONTROL = True
    # --- !! 配置結束 !! ---

    print(f"=================================================\n🚀 模擬世界啟動中... World ID: [{world_id}], TraCI Port: [{traci_port}]\n=================================================")
    
    # --- 初始化 Dispatcher (v8.12.6) ---
    vehicle_dispatcher, pc_list = setup_dispatcher(config, world_id)
    if vehicle_dispatcher is None:
        print(f"❌ [{world_id}] 無法初始化 Vehicle Dispatcher (7884)，終止模擬。")
        return

    # --- 啟動 SUMO (v8.12.8 修正) ---
    try:
        start_sumo(config, config['TRACI_PORT'])
        print(f"✅ [{world_id}] SUMO 模擬已啟動！")

        print("="*60)
        print(f"DEBUG [sub_world]: 實際載入的 TraCI 版本: {traci.getVersion()}")
        print(f"DEBUG [sub_world]: 實際載入的 TraCI 路徑: {traci.__file__}")
        print("="*60)

    except Exception as e:
        print(f"❌ [{world_id}] 啟動 SUMO 失敗: {e}")
        if vehicle_dispatcher: vehicle_dispatcher.disconnect()
        return

    # --- 初始化 Queues 和狀態 (v8.12.6 修正) ---
    reroute_requests_queue = queue.Queue()
    simulation_control_queue = queue.Queue() 
    tls_sync_queue = queue.Queue() # 【v8.12.6】: 線程安全修正
    externally_closed_edges = set()

    # --- 【v8.12.24 關鍵修改】: MQTT 指令回調函式 ---
    def on_command_message(client, userdata, msg):
        """ 
        @教授註解: 處理來自 MQTT 的指令 (可來自 7883 或 7884)。
        """
        # 【v8.12.24 MOD】: SIM_STATE 是全域變數
        global SIM_STATE
        # is_user_pause_logged 是 main() 的區域變數
        nonlocal is_user_pause_logged 
        
        try:
            current_world_id = userdata["world_id"]
            
            # (Flow 5) Reroute 請求 (來自 7883)
            expected_reroute_topic = f"worlds/{current_world_id}/reroute_request"
            if msg.topic == expected_reroute_topic:
                if ENABLE_SMART_REROUTING and SIM_STATE == "RUNNING":
                    payload_str = msg.payload.decode('utf-8')
                    if not payload_str: return
                    payload = json.loads(payload_str)
                    if isinstance(payload, dict) and 'veh_id' in payload:
                        reroute_requests_queue.put(payload)

            # (Flow 8) 外部 Hotspot 情報 (來自 7884)
            elif msg.topic == INTER_WORLD_TOPIC and ENABLE_EXTERNAL_CONTROL and SIM_STATE == "RUNNING":
                payload_str = msg.payload.decode('utf-8')
                if not payload_str: return
                payload = json.loads(payload_str)
                source_world = payload.get("source_world")
                if source_world and isinstance(source_world, str) and source_world != current_world_id:
                    lane_id = payload.get("lane_id")
                    status = payload.get("status")
                    edge_id = get_edge_id_from_lane_id(lane_id)
                    if edge_id and status in ["CONGESTED", "CLEAR"]:
                        command = "CLOSE_EDGE" if status == "CONGESTED" else "OPEN_EDGE"
                        reason = f"EXTERNAL_{status}"
                        if status == "CONGESTED":
                            reason = f"EXTERNAL_CONGESTED_{payload.get('congestion_level', 'UNKNOWN')}"
                        control_command = {"command": command, "edge_id": edge_id, "source_world": source_world, "reason": reason}
                        simulation_control_queue.put(control_command)
                
            # (Flow 9) 處理來自 Pacer 的同步指令
            elif msg.topic == SYSTEM_TLS_SYNC_TOPIC:
                if SIM_STATE == "RUNNING":
                    print(f"🔔 [{current_world_id}] 收到 Pacer 的紅綠燈同步指令！")
                    try:
                        payload_str = msg.payload.decode('utf-8')
                        tls_data = json.loads(payload_str)
                        
                        tls_sync_queue.put(tls_data)
                        
                        print(f"    -> [{current_world_id}] Follower 暫停，等待主線程應用同步...")
                        SIM_STATE = "PAUSED_FOR_SYNC" 
                        
                    except Exception as e:
                        print(f"❌ [{current_world_id}] 解析紅綠燈同步數據時出錯: {e}")
                        time.sleep(1)
                        SIM_STATE = "RUNNING"
                else:
                    print(f"⚠️ [{current_world_id}] 在非 RUNNING 狀態 ({SIM_STATE}) 收到 TLS_SYNC，已忽略。")
                        
            # (Flow 10) 【v8.12.24 修改】: 處理來自控制器的「恢復」指令
            elif msg.topic == SYSTEM_RESUME_ALL_TOPIC:
                if SIM_STATE == "WAITING_FOR_RESUME" or SIM_STATE == "PAUSED_FOR_USER":
                    print(f"🏁 [{current_world_id}] 收到 [Enter] 恢復指令，Follower 恢復運行！")
                    SIM_STATE = "RUNNING"
                    is_user_pause_logged = False # 重置日誌標記

            # (Flow 11) 【v8.12.24 新增】: 處理來自控制器的「暫停」指令
            elif msg.topic == SYSTEM_PAUSE_ALL_TOPIC:
                if SIM_STATE == "RUNNING":
                    print(f"⏸️ [{current_world_id}] 收到 [Enter] 暫停指令，Follower 已暫停。")
                    SIM_STATE = "PAUSED_FOR_USER"
                    is_user_pause_logged = True # 立即標記，避免主迴圈重複打印

        except (json.JSONDecodeError, UnicodeDecodeError, IndexError, KeyError, AttributeError) as e:
            print(f"[{userdata.get('world_id','?')}] 處理指令時發生錯誤 ({msg.topic}, Payload: '{msg.payload.decode('utf-8', errors='ignore')}'): {e}")


    # --- Data Client (7883) (v7.2.1 不變) ---
    topics_to_subscribe_data = []
    if ENABLE_SMART_REROUTING: 
        topics_to_subscribe_data.append(f"worlds/{world_id}/reroute_request")

    command_client = connect_mqtt(
        config['PHYSICAL_BROKER']['host'], config['PHYSICAL_BROKER']['port'],
        f"SimCmdHandler_Data_{world_id}_{int(time.time())}",
        on_command_message, 
        topics_to_subscribe_data,
        None, 
        world_id
    )
    if command_client is None:
        if vehicle_dispatcher: vehicle_dispatcher.disconnect()
        return
    print(f"[{world_id}] 資料指令接收器 (7883) 已啟動...")
    
    # --- Control Client (7884) (v8.12.24 修改) ---
    topics_to_subscribe_control = []
    if ENABLE_EXTERNAL_CONTROL: 
        topics_to_subscribe_control.append(INTER_WORLD_TOPIC)
        
    # 【v8.12.24 修改】: 訂閱所有控制主題
    topics_to_subscribe_control.append(SYSTEM_TLS_SYNC_TOPIC)
    topics_to_subscribe_control.append(SYSTEM_RESUME_ALL_TOPIC) 
    topics_to_subscribe_control.append(SYSTEM_PAUSE_ALL_TOPIC)
    
    control_client = connect_mqtt(
        config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'],
        f"SimCmdHandler_Control_{world_id}_{int(time.time())}",
        on_command_message, 
        topics_to_subscribe_control,
        None, 
        world_id
    )
    if control_client is None:
        if command_client: command_client.disconnect()
        if vehicle_dispatcher: vehicle_dispatcher.disconnect()
        return
    print(f"[{world_id}] 平台控制/同步 接收器 (7884) 已啟動...")

    # --- 子世界註冊 (v7.2.1 邏輯, 這是「喊到」) ---
    print(f"[{world_id}] 等待 1 秒...")
    time.sleep(1.0)
    print(f"[{world_id}] 發布上線註冊訊息 (7884)...")
    register_payload = json.dumps({"world_id": world_id, "status": "online", "timestamp": time.time()})
    try:
        if control_client and control_client.is_connected():
            control_client.publish(SYSTEM_REGISTER_TOPIC, register_payload, qos=1)
            print(f"[{world_id}] 註冊訊息已發布至 (7884)。")
        else: 
            print(f"⚠️ [{world_id}] Control Client (7884) 未連接，無法發布註冊訊息。")
    except Exception as e: 
        print(f"❌ [{world_id}] 發布註冊訊息 (7884) 時出錯: {e}")

    # --- 初始化模擬狀態和數據收集 (v8.12.6) ---
    vehicleDict.clear()
    current_simulation_step = 0
    pc_assignment_counter = 0

    rtf_state = {'active': False}
    rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data = [], [], [], []
    t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data = [], [], [], []
    t3_per_step_data, reroute_counts_per_step, total_reroutes_processed = [], [], 0

    print("\n" + "="*30 + f"\n[{world_id}] RTF 效能測試模組已準備就緒。\n" + "="*30)

    # --- 優雅關閉處理 (v8.12.6) ---
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # ============================================================ #
    # === v8.12.24 主模擬循環 (狀態機) ===
    # ============================================================ #
    try:
        while not shutdown_flag.is_set():
            
            # --- 【v8.12 狀態機】: 運行中 ---
            if SIM_STATE == "RUNNING":
                
                try:
                    current_sim_time_check = traci.simulation.getTime()
                    if traci.simulation.getMinExpectedNumber() <= 0 and current_simulation_step > 0:
                        print(f"[{world_id}] 模擬中已無車輛 (步長 {current_simulation_step})，結束模擬。")
                        break
                except (traci.TraCIException, ConnectionResetError, OSError) as conn_err:
                    print(f"[{world_id}] TraCI 連接錯誤 ({type(conn_err).__name__})，終止模擬。")
                    break
                if current_simulation_step >= config['SIMULATION_END_STEP']:
                    print(f"[{world_id}] 達到模擬結束步長 {config['SIMULATION_END_STEP']}，結束模擬。")
                    break

                step_start_time = time.perf_counter()
                step_timings = {}

                # --- 1. 處理 T4 (【v8.12.22 方案 B】) ---
                t4_start = time.perf_counter()
                control_commands_processed_this_step = 0
                if ENABLE_EXTERNAL_CONTROL:
                    current_edge_list = None
                    while not simulation_control_queue.empty():
                        try: command_data = simulation_control_queue.get_nowait()
                        except queue.Empty: break
                        edge_id = command_data.get("edge_id"); command = command_data.get("command"); source = command_data.get("source_world", "UNKNOWN")
                        if not edge_id or not command: continue
                        if current_edge_list is None:
                            try: current_edge_list = traci.edge.getIDList()
                            except traci.TraCIException: current_edge_list = []
                        if edge_id not in current_edge_list: continue
                        
                        allowed_classes = DEFAULT_ALLOWED_VCLASSES
                        
                        try:
                            if command == "CLOSE_EDGE":
                                if edge_id not in externally_closed_edges:
                                    print(f"🕹️ [{world_id}] <- (來自 {source} on 7884) 關閉 Edge {edge_id}")
                                    
                                    lane_count = traci.edge.getLaneNumber(edge_id)
                                    for i in range(lane_count):
                                        lane_id = f"{edge_id}_{i}"
                                        traci.lane.setAllowed(lane_id, []) 

                                    externally_closed_edges.add(edge_id)
                                    control_commands_processed_this_step += 1
                                    
                            elif command == "OPEN_EDGE":
                                if edge_id in externally_closed_edges:
                                    print(f"🕹️ [{world_id}] <- (來自 {source} on 7884) 開啟 Edge {edge_id}")
                                    
                                    lane_count = traci.edge.getLaneNumber(edge_id)
                                    for i in range(lane_count):
                                        lane_id = f"{edge_id}_{i}"
                                        traci.lane.setAllowed(lane_id, allowed_classes) 
                                    
                                    externally_closed_edges.remove(edge_id)
                                    control_commands_processed_this_step += 1
                                    
                        except traci.TraCIException as e: print(f"⚠️ [{world_id}] 執行 SUMO 指令出錯 ({command} on {edge_id}): {e}")
                t4_end = time.perf_counter()
                step_timings['T4_SimControl'] = t4_end - t4_start
                step_timings['control_commands_processed'] = control_commands_processed_this_step

                # --- 2. 執行 T0 (v7.2.1 邏輯) ---
                t0_start = time.perf_counter()
                traci.simulationStep()
                t0_end = time.perf_counter()
                current_simulation_step += 1
                step_timings['T0_SumoStep'] = t0_end - t0_start

                # --- 3. 發布 RSU (v7.2.1 邏輯) ---
                if ENABLE_PERCEPTION_SYSTEM and current_simulation_step % config['RSU_PUBLISH_INTERVAL_STEPS'] == 0:
                    rsu_raw_data = {}
                    try:
                        all_detectors = traci.inductionloop.getIDList()
                        if all_detectors:
                            for det_id in all_detectors:
                                try:
                                    lane_id = traci.inductionloop.getLaneID(det_id)
                                    mean_speed = traci.inductionloop.getLastStepMeanSpeed(det_id)
                                    vehicle_count = traci.inductionloop.getLastStepVehicleNumber(det_id)
                                    if lane_id and not lane_id.startswith(':') and mean_speed >= 0:
                                        rsu_raw_data[lane_id] = {"mean_speed": mean_speed, "vehicle_count": vehicle_count}
                                except traci.TraCIException: continue
                            if rsu_raw_data:
                                if control_client and control_client.is_connected():
                                    control_client.publish(f"worlds/{world_id}/rsu/raw_data", json.dumps(rsu_raw_data), qos=0)
                    except traci.TraCIException: pass

                # --- 4. 處理 T3 (v7.2.1 邏輯) ---
                t3_duration_sec, reroutes_this_step, avg_time_per_veh_ms = 0, 0, 0.0
                if ENABLE_SMART_REROUTING:
                    t3_start = time.perf_counter()
                    processed_reroutes_in_batch = 0
                    current_vehicle_list = []
                    try: current_vehicle_list = traci.vehicle.getIDList()
                    except traci.TraCIException: pass
                    while not reroute_requests_queue.empty() and processed_reroutes_in_batch < 1000:
                        try: request = reroute_requests_queue.get_nowait()
                        except queue.Empty: break
                        veh_id_to_reroute = request.get('veh_id')
                        if veh_id_to_reroute and veh_id_to_reroute in current_vehicle_list:
                            try:
                                traci.vehicle.rerouteTraveltime(veh_id_to_reroute)
                                reroutes_this_step += 1
                            except traci.TraCIException: pass
                        processed_reroutes_in_batch += 1
                    t3_end = time.perf_counter()
                    t3_duration_sec = t3_end - t3_start
                    if reroutes_this_step > 0:
                        avg_time_per_veh_ms = (t3_duration_sec * 1000) / reroutes_this_step
                    if processed_reroutes_in_batch > 0:
                        t3_per_step_data.append(t3_duration_sec * 1000)
                        reroute_counts_per_step.append(reroutes_this_step)
                    total_reroutes_processed += reroutes_this_step
                step_timings['T3_Rerouting'] = t3_duration_sec
                step_timings['reroute_count'] = reroutes_this_step
                step_timings['reroute_avg_ms'] = avg_time_per_veh_ms

                # --- 5. 垃圾回收 (v7.2.1 邏輯) ---
                try:
                    is_traci_connected_gc = False
                    try: traci.simulation.getTime(); is_traci_connected_gc = True
                    except (traci.TraCIException, ConnectionResetError, OSError): is_traci_connected_gc = False
                    if is_traci_connected_gc:
                        garbage_collector(config['PHYSICAL_BROKER']['host'], config['PHYSICAL_BROKER']['port'],
                                          config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'],
                                          traci.simulation, vehicleDict, world_id)
                except Exception as gc_e: print(f"[{world_id}] Error during garbage collection: {gc_e}")

                # --- 6. 收集 T1 (v7.2.1 邏輯) ---
                t1_start = time.perf_counter()
                vehicles_to_dispatch, vehicle_states, pc_assignment_counter = collect_and_prepare_dispatch_data(
                    current_simulation_step, config, vehicleDict, pc_list, pc_assignment_counter
                )
                t1_end = time.perf_counter()
                step_timings['T1_DataCollection'] = t1_end - t1_start
                step_timings['Processed_Vehicles'] = len(vehicles_to_dispatch)

                # --- 7. 處理 T2 (v7.2.1 邏輯) ---
                ack_target_count = len(vehicles_to_dispatch)
                t2_duration = 0.0
                if ack_target_count > 0:
                    t2_start = time.perf_counter()
                    dispatched_count_actual = 0
                    for veh_id in vehicles_to_dispatch:
                        if veh_id in vehicle_states:
                            vehicle = vehicleDict.get(veh_id)
                            if not vehicle or not vehicle.physicalComputerMapping: continue
                            pc = vehicle.physicalComputerMapping
                            state_data = vehicle_states[veh_id]
                            dispatch_topic = f"{pc}_{world_id}"
                            try:
                                if vehicle_dispatcher and vehicle_dispatcher.mqttc and vehicle_dispatcher.mqttc.is_connected():
                                    vehicle_dispatcher.dispatch_vehicle(dispatch_topic, veh_id, state_data)
                                    dispatched_count_actual += 1
                            except Exception as dispatch_e: print(f"[{world_id}] Error dispatching vehicle {veh_id}: {dispatch_e}")
                    if dispatched_count_actual > 0: wait_for_acks(vehicle_dispatcher, dispatched_count_actual)
                    t2_end = time.perf_counter()
                    t2_duration = t2_end - t2_start
                step_timings['T2_RoundTripWait'] = t2_duration

                # --- 8. 更新 RTF (v7.2.1 邏輯) ---
                step_end_time = time.perf_counter()
                time_elapsed_for_step = step_end_time - step_start_time
                rtf_state = update_rtf_monitor(
                    rtf_state, config, current_simulation_step, time_elapsed_for_step,
                    rtf_data, vehicle_count_data, halting_vehicle_data, congestion_data, step_timings,
                    t0_per_vehicle_data, t1_per_vehicle_data, t2_per_vehicle_data, overhead_per_vehicle_data
                )
            
            # --- 【v8.12.24 修改】: 暫停並應用同步 ---
            elif SIM_STATE == "PAUSED_FOR_SYNC":
                try:
                    # 1. 從佇列中獲取 TLS 數據
                    tls_data = tls_sync_queue.get(timeout=0.1)
                    
                    # 2. 【線程安全】: 由主線程安全地呼叫 TraCI
                    apply_tls_status(traci, tls_data)
                    
                    # 3. 發送 ACK
                    print(f"    -> [{world_id}] 同步完成，發送 ACK...")
                    if control_client and control_client.is_connected():
                        control_client.publish(SYSTEM_TLS_ACK_TOPIC, json.dumps({"status": "OK", "world_id": world_id}), qos=1)
                    
                    # 4. 進入等待恢復的狀態
                    SIM_STATE = "WAITING_FOR_RESUME"
                    print(f"    -> [{world_id}] 已發送 ACK。等待 [CONTROLLER] 恢復指令...")
                    
                    # 5. 【v8.12.24 刪除】: 移除 input_thread 啟動邏輯
                    
                except queue.Empty:
                    time.sleep(0.05) # 佇列中沒有資料，繼續 sleep
                except Exception as e:
                    print(f"❌ [{world_id}] [PAUSED] 應用同步指令時出錯: {e}")
                    print(f"    -> 3秒後自動恢復運行...")
                    time.sleep(3)
                    SIM_STATE = "RUNNING"
            
            # --- 【v8.12.24 修改】: 等待恢復 或 等待使用者暫停 ---
            elif (SIM_STATE == "WAITING_FOR_RESUME" or
                  SIM_STATE == "PAUSED_FOR_USER"):
                
                # 如果是使用者觸發的暫停，只打印一次
                if SIM_STATE == "PAUSED_FOR_USER" and not is_user_pause_logged:
                    print(f"⏸️ [{world_id}] 模擬已暫停。請至 [CONTROLLER] 終端機按 [Enter] 恢復。")
                    is_user_pause_logged = True

                time.sleep(0.1) # 降低 CPU 佔用

            # --- 狀態機結束 ---

    except KeyboardInterrupt:
        print(f"\n[{world_id}] 收到關閉信號 (來自主迴圈)，退出主循環...")
    except FatalTraCIError as e:
        print(f"\n💥 [{world_id}] TraCI 發生致命錯誤，模擬提前終止: {e}")
    except traci.TraCIException as e:
        print(f"\n💥 [{world_id}] TraCI 連接錯誤 (可能 SUMO 已關閉)，模擬提前終止: {e}")
    except Exception as e:
        print(f"\n============================================================\n💥💥💥 [{world_id}] 主模擬循環發生致命錯誤 💥💥💥\n錯誤類型: {type(e).__name__}\n錯誤訊息: {e}\n\n---詳細錯誤追蹤 (Traceback) ---\n")
        traceback.print_exc()
        print("============================================================\n")
    
    # ============================================================ #
    # === v8.12.8 清理程序 ===
    # ============================================================ #
    finally:
        print(f"\n[{world_id}] 模擬結束於步驟 {current_simulation_step}。")
        # 【v8.12.24 刪除】: resume_event.set() 已被移除

        # --- 【v8.12.22 方案 B】: 最終清理 ---
        is_traci_connected_final = False
        try:
            if 'traci' in sys.modules and traci:
                try: traci.simulation.getTime(); is_traci_connected_final = True
                except (traci.TraCIException, ConnectionResetError, OSError): is_traci_connected_final = False

                if is_traci_connected_final:
                    print(f"[{world_id}] 正在重新開啟 {len(externally_closed_edges)} 個因外部指令關閉的 Edge...")
                    
                    allowed_classes = DEFAULT_ALLOWED_VCLASSES
                    
                    edges_to_reopen = list(externally_closed_edges)
                    try: edge_list_at_end = set(traci.edge.getIDList())
                    except traci.TraCIException: edge_list_at_end = set()

                    for edge_id in edges_to_reopen:
                        if edge_id in edge_list_at_end:
                            try:
                                # --- 【v8.12.22 方案 B】 邏輯 ---
                                lane_count = traci.edge.getLaneNumber(edge_id)
                                for i in range(lane_count):
                                    lane_id = f"{edge_id}_{i}"
                                    traci.lane.setAllowed(lane_id, allowed_classes) # 恢復
                                
                                print(f"    ✅ [{world_id}] Reopened edge {edge_id}")
                            except traci.TraCIException as e: print(f"    ⚠️ [{world_id}] 無法重新開啟 edge {edge_id}: {e}")
                    externally_closed_edges.clear()

                    print(f"[{world_id}] S 正在關閉 TraCI 連接...")
                    traci.close()
                    print(f"[{world_id}] TraCI 連接已關閉。")
        except NameError: pass
        except Exception as final_traci_e: print(f"[{world_id}] 在最終清理 TraCI 時發生錯誤: {final_traci_e}")


        # --- 斷開 MQTT 連接 ---
        print(f"[{world_id}] 開始清理 MQTT 資源...")
        if 'command_client' in locals() and command_client and command_client.is_connected():
            print(f"[{world_id}] S 正在斷開 MQTT Data Client (7883)...")
            command_client.loop_stop(); time.sleep(0.1); command_client.disconnect()
            
        if 'control_client' in locals() and control_client and control_client.is_connected():
            print(f"[{world_id}] S 正在斷開 MQTT Control Client (7884)...")
            control_client.loop_stop(); time.sleep(0.1); control_client.disconnect()

        if 'vehicle_dispatcher' in locals() and vehicle_dispatcher and hasattr(vehicle_dispatcher, 'mqttc') and vehicle_dispatcher.mqttc.is_connected():
            print(f"[{world_id}] S 正在斷開車輛分派器 MQTT 客戶端 (7884)...")
            vehicle_dispatcher.disconnect()
            
        if 'traci' in sys.modules and not is_traci_connected_final:
            print(f"[{world_id}] TraCI 已斷開連接。")

        # --- 打印/生成報告 ---
        print(f"[{world_id}] 正在生成最終效能報告...")
        print_performance_report(
            config, rtf_data or [], vehicle_count_data or [], halting_vehicle_data or [], congestion_data or [],
            t0_per_vehicle_data or [], t1_per_vehicle_data or [], t2_per_vehicle_data or [], overhead_per_vehicle_data or [],
            t3_per_step_data or [], reroute_counts_per_step or [], total_reroutes_processed, current_simulation_step
        )
        print(f"[{world_id}] 模擬程序完全結束。")


# 移除 SUMO_HOME 檢查
if __name__ == '__main__':
    # (v8.12.24) 初始化全域變數
    config = {}
    vehicleDict = {}
    # 【v8.12.24 刪除】: resume_event 已被移除
    control_client = None
    SIM_STATE = "RUNNING"
    shutdown_flag = threading.Event() 
    
    main()