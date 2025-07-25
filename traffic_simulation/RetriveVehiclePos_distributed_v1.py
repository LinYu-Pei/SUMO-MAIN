# 檔名: RetriveVehiclePos_distributed_v1.py (函式化重構版)
# 描述: 將主迴圈內的邏輯拆分為獨立的函式，大幅提升可讀性和可維護性。

import os
import sys
import time

# --- SUMO 環境設定 ---
if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import traci

# --- 導入自訂模組 ---
from traffic_Vehicle import Vehicle
from garbage_collector import garbage_collector
from traffic_Vehicle_dispatcher import Vehicle_dispatcher

# ============================================================
# 輔助函式 (此區塊為新增或從主程式中提取)
# ============================================================



def retrieve_SUMO_vehicle_info(traci, veh_id):
    """從 SUMO 獲取單一車輛的關鍵數據 (保持不變)"""
    x, y = traci.vehicle.getPosition(veh_id)      
    lon, lat = traci.simulation.convertGeo(x, y)
    laneID = traci.vehicle.getLaneID(veh_id)
    vehicleLength = traci.vehicle.getLength(veh_id)
    lanePosition = traci.vehicle.getLanePosition(veh_id)      
    speed = traci.vehicle.getSpeed(veh_id) * 3.6
    laneAngle = traci.lane.getAngle(laneID)      
    laneLength = traci.lane.getLength(laneID)
    travelTime= traci.lane.getTraveltime(laneID)
    connectedLanes = []
    if laneID.startswith(":"):
        for connectedLane in traci.lane.getLinks(laneID, False):
            connectedLanes.append(connectedLane[0])
            
    geofenceInfo = dict(
        lat=lat, lon=lon, laneID=laneID, width=laneLength/3, laneAngle=laneAngle, 
        speed=speed, travelTime=travelTime, lanePosition=lanePosition, 
        vehicleLength=vehicleLength, connectedLanes=connectedLanes,
        laneLength=laneLength  # <--- ✨ 已修改
    )
    return geofenceInfo



def setup_dispatcher(config):
    """初始化並連線 Vehicle Dispatcher"""
    print("正在初始化 Vehicle Dispatcher...")
    dispatcher = Vehicle_dispatcher()
    computers = dict(pc1='127.0.0.1')
    dispatcher.physicalComputers = computers
    pc_list = list(dispatcher.physicalComputers.keys())
    dispatcher.connect(config['VIRTUAL_BROKER']['host'], config['VIRTUAL_BROKER']['port'])
    return dispatcher, pc_list



def start_sumo(config):
    """啟動 SUMO 並建立 TraCI 連線"""
    print("正在啟動 SUMO...")
    sumoCmd = [
        config['SUMO_BINARY'], "-c", config['SUMO_CONFIG_FILE'],
        "-d", "1000", "--ignore-route-errors",
        
    ]
    traci.start(sumoCmd, port=config['TRACI_PORT'])
    print("Simulation Start!")



def process_vehicle_dispatching(current_step, config, vehicle_dict, pc_list, dispatcher, pc_counter):
    """
    處理車輛數據的收集與分派。
    此函式包含原始碼中的步驟 C 和 D。
    """
    vehicles_to_dispatch_this_step = []
    geofence_infos_this_step = {}

    for veh_id in traci.vehicle.getIDList():
        if veh_id not in vehicle_dict:
            vehicle_dict[veh_id] = Vehicle(veh_id)
        
        vehicle = vehicle_dict[veh_id]

        if vehicle.physicalComputerMapping is None:
            pc_index = pc_counter % len(pc_list)
            vehicle.physicalComputerMapping = pc_list[pc_index]
            pc_counter += 1

        is_first_publish = (vehicle.last_publish_step == 0)
        is_time_to_publish = (current_step >= vehicle.last_publish_step + config['PUBLISH_PERIOD_STEPS'])

        if is_first_publish or is_time_to_publish:
            vehicle.last_publish_step = current_step
            vehicles_to_dispatch_this_step.append(veh_id)
            geofence_infos_this_step[veh_id] = retrieve_SUMO_vehicle_info(traci, veh_id)
    
    if vehicles_to_dispatch_this_step:
        for veh_id in vehicles_to_dispatch_this_step:
            vehicle = vehicle_dict[veh_id]
            pc = vehicle.physicalComputerMapping
            geofenceInfo = geofence_infos_this_step[veh_id]
            dispatcher.dispatch_vehicle(pc, veh_id, geofenceInfo)
            
    return len(vehicles_to_dispatch_this_step), pc_counter



def wait_for_acks(dispatcher, target_count):
    """同步等待所有 ACK 返回 (保留原始功能)"""
    if target_count > 0:
        while dispatcher.ack_count != target_count:
            time.sleep(0.001)
        dispatcher.ack_count = 0



def update_rtf_monitor(rtf_state, config, current_step):
    """更新並打印 RTF 效能數據"""
    current_vehicle_count = traci.vehicle.getIDCount()

    if not rtf_state['active'] and current_vehicle_count >= config['RTF_TEST_START_THRESHOLD']:
        rtf_state['active'] = True
        rtf_state['last_measured_time'] = time.time()
        rtf_state['last_measured_step'] = current_step
        print(f"\n--- [RTF 測試啟動] 當前車輛數: {current_vehicle_count} (>= {config['RTF_TEST_START_THRESHOLD']}) ---")
    elif rtf_state['active'] and current_vehicle_count < config['RTF_TEST_STOP_THRESHOLD']:
        rtf_state['active'] = False
        print(f"--- [RTF 測試結束] 當前車輛數: {current_vehicle_count} (< {config['RTF_TEST_STOP_THRESHOLD']}) ---\n")

    if rtf_state['active']:
        if (current_step - rtf_state['last_measured_step']) >= config['RTF_PRINT_INTERVAL_STEPS']:
            current_time = time.time()
            time_elapsed = current_time - rtf_state['last_measured_time']
            steps_advanced = current_step - rtf_state['last_measured_step']

            if time_elapsed > 0:
                current_rtf = steps_advanced / time_elapsed
                print(f"步驟 {current_step}: 當前車輛數 {current_vehicle_count}, RTF: {current_rtf:.4f} (步/秒)")
            
            rtf_state['last_measured_time'] = current_time
            rtf_state['last_measured_step'] = current_step
    
    return rtf_state # 返回更新後的狀態



# ============================================================
# 主程式進入點
# ============================================================
def main():
    """主執行函式"""
    
    # --- 1. 系統設定 ---
    config = {
        'PHYSICAL_BROKER': {'host': '127.0.0.1', 'port': 7883},
        'VIRTUAL_BROKER': {'host': '127.0.0.1', 'port': 7884},
        'SUMO_BINARY': "/usr/local/bin/sumo-gui",
        'SUMO_CONFIG_FILE': "/home/paul/sumo_platform/testbed/traffic_simulation/osm.sumocfg.xml",
        'TRACI_PORT': 8813,
        'PUBLISH_PERIOD_STEPS': 5,
        'RTF_TEST_START_THRESHOLD': 400,
        'RTF_TEST_STOP_THRESHOLD': 395,
        'RTF_PRINT_INTERVAL_STEPS': 2,
    }

    # --- 2. 初始化 ---
    vehicle_dispatcher, pc_list = setup_dispatcher(config)
    start_sumo(config)
    
    vehicleDict = {}
    current_simulation_step = 0
    pc_assignment_counter = 0

    rtf_state = {
        'active': False,
        'last_measured_time': 0,
        'last_measured_step': 0,
    }
    print("\n" + "="*30 + "\nRTF 效能測試模組已準備就緒。\n" + "="*30)

    # ==========================
    #   主 模 擬 迴 圈
    # ==========================
    while traci.simulation.getMinExpectedNumber() > 0:
        # 步驟 A: 推進模擬
        traci.simulationStep()
        current_simulation_step += 1

        # 步驟 B: 垃圾回收
        garbage_collector(
            physical_mqtt_server=config['PHYSICAL_BROKER']['host'], physical_mqtt_port=config['PHYSICAL_BROKER']['port'],
            virtual_mqtt_server=config['VIRTUAL_BROKER']['host'], virtual_mqtt_port=config['VIRTUAL_BROKER']['port'],
            traci_simulation=traci.simulation, vehicleDict=vehicleDict
        )

        # 步驟 C & D: 收集、處理並分派車輛數據
        ack_target_count, pc_assignment_counter = process_vehicle_dispatching(
            current_simulation_step, config, vehicleDict, pc_list, vehicle_dispatcher, pc_assignment_counter
        )

        # 步驟 E: 等待 ACKs
        wait_for_acks(vehicle_dispatcher, ack_target_count)

        # 步驟 F: 監測 RTF
        rtf_state = update_rtf_monitor(rtf_state, config, current_simulation_step)

    # --- 模擬結束後的清理 ---
    print("Simulation Done!")
    traci.close()


if __name__ == '__main__':
    main()