# traffic_simulation/garbage_collector.py

import paho.mqtt.client as mqtt

# 【教授修改】函式簽名新增 world_id，並修正 traci_instance 參數名
def garbage_collector(physical_mqtt_server, physical_mqtt_port, virtual_mqtt_server, virtual_mqtt_port, traci_simulation, vehicleDict, world_id):
    """
    負責收集已抵達終點的車輛ID，並透過 MQTT 通知相關後端服務進行清理。
    這個函式現在是 world-aware 的。

    Args:
        physical_mqtt_server (str): Data Broker (7883) 的主機地址。
        physical_mqtt_port (int): Data Broker (7883) 的端口。
        virtual_mqtt_server (str): Control Broker (7884) 的主機地址。
        virtual_mqtt_port (int): Control Broker (7884) 的端口。
        traci_simulation: SUMO TraCI 的 simulation 模組實例。
        vehicleDict (dict): 主模擬腳本中維護的車輛字典。
        world_id (str): 當前模擬世界 ID。
    """
    
    # 從 traci.simulation 獲取已抵達車輛列表
    arrivedIDList = traci_simulation.getArrivedIDList()

    # 如果沒有車輛抵達，則無需執行任何操作，直接返回
    if not arrivedIDList:
        return

    # 【教授修改】使用 world_id 創建唯一的 Client ID
    client_id = f"garbage_collector_{world_id}"
    garbage_collector_client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5)
    
    try:
        # 1. 通知 VehicleStateMonitor 清理 Redis 快取
        # 連接到 Data Broker (port 7883)
        garbage_collector_client.connect(physical_mqtt_server, physical_mqtt_port)
        
        # 【教授修改】發布到帶有命名空間的 arrivedIDList 主題
        arrived_topic = f"worlds/{world_id}/arrivedIDList"
        garbage_collector_client.publish(topic=arrived_topic, payload=str(arrivedIDList))
        garbage_collector_client.disconnect()

        # 2. 通知對應的 OBC (physicalComputer) 清理車輛實例
        # 連接到 Control Broker (port 7884)
        garbage_collector_client.connect(virtual_mqtt_server, virtual_mqtt_port)
        
        for ID in arrivedIDList:
            if ID in vehicleDict:
                vehicle = vehicleDict[ID]
                pc = vehicle.physicalComputerMapping # 獲取這輛車被分派到的 pc 名稱 (例如 "pc1")
                
                if pc:
                    # 【教授修改】組合出帶有 world_id 的專屬斷連主題
                    disconnection_topic = f"{pc}_{world_id}_vehicle_disconnection"
                    garbage_collector_client.publish(topic=disconnection_topic, payload=ID)
        
        garbage_collector_client.disconnect()
    
    except Exception as e:
        print(f"Garbage Collector ({world_id}) 發生錯誤: {e}")
    finally:
        # 確保即使出錯也能嘗試停止 loop
        if garbage_collector_client.is_connected():
            garbage_collector_client.loop_stop()
            garbage_collector_client.disconnect()