# on_board_computer/physicalComputer.py

import paho.mqtt.client as mqtt
from Vehicle import Vehicle
from Vehicle_subscriber import Vehicle_subscriber
import json
import random
import time

# --- 全域字典 ---
subscriberDict = dict()
vehicleDict = dict()

# --- 全域設定變數 ---
SMART_REROUTING_ENABLED = True

# --- MQTT 客戶端定義 (保持不變) ---
shared_publisher_client = mqtt.Client(
    client_id=f"SharedPublisher_PC_{random.randint(100,999)}", 
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    protocol=mqtt.MQTTv5
)
global_info_client = mqtt.Client(
    client_id=f"GlobalInfoSubscriber_PC_{random.randint(100,999)}",
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    protocol=mqtt.MQTTv5
)
vehicle_specific_client = mqtt.Client(
    client_id=f"VehicleSpecificSubscriber_PC_{random.randint(100,999)}", 
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2, 
    protocol=mqtt.MQTTv5
)

# --- MQTT 回呼函式 (Callbacks) ---

def on_global_info_connect(client, userdata, flags, reason_code, properties):
    """
    當宏觀資訊訂閱者 (global_info_client) 連接到 Broker 時的回呼函式。
    它會訂閱該世界專屬的全局路況主題。
    """
    world_id = userdata["world_id"]
    if reason_code == 0:
        # 【教授修改】訂閱帶有命名空間的專屬主題
        topic = f'worlds/{world_id}/global_road_status'
        client.subscribe(topic)
        print(f"✅ Global Info Subscriber 已訂閱: {topic}")
    else:
        print(f"❌ Global Info Subscriber 連線失敗, code: {reason_code}")

def on_global_info_message(client, userdata, msg):
    """
    當收到宏觀路況訊息時的回呼函式。
    它會將收到的路況快照廣播給由此實體電腦管理的所有車輛決策核心 (Vehicle_subscriber)。
    """
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    if topic.endswith('global_road_status'):
        if not subscriberDict: return
        for sub in list(subscriberDict.values()):
            sub.handle_macro_message(topic, payload)

def on_vehicle_specific_connect(client, userdata, flags, reason_code, properties):
    """
    當車輛專屬訊息訂閱者 (vehicle_specific_client) 連接到 Broker 時的回呼函式。
    主要用於確認連線狀態。
    """
    if reason_code != 0:
        print(f"❌ Vehicle Specific Subscriber 連線失敗, code: {reason_code}")

def on_vehicle_specific_message(client, userdata, msg):
    """
    當收到車輛專屬主題的訊息時的回呼函式。
    這通常用於點對點的訊息傳遞，此處將訊息轉發給對應的車輛決策核心。
    """
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    subscriber_id_from_topic = topic.split('/')[-1]
    if subscriber_id_from_topic in subscriberDict:
        subscriber = subscriberDict[subscriber_id_from_topic]
        subscriber.handle_macro_message(topic, payload)

def on_commander_connect(client, userdata, flags, reason_code, properties):
    """
    當指令接收者 (commander_client) 連接到 Broker 時的回呼函式。
    它會訂閱來自 SUMO 主控制器的車輛分派主題、車輛斷連主題以及全局系統配置主題。
    """
    world_id = userdata["world_id"]
    pc_name = userdata["pc_name"]

    if reason_code == 0:
        print(f'✅ Commander ({client._client_id}) connected.')
        # 【教授修改】訂閱帶有 world_id 的專屬分派主題
        dispatch_topic = f"{pc_name}_{world_id}"
        disconnection_topic = f"{pc_name}_{world_id}_vehicle_disconnection"
        
        client.subscribe(dispatch_topic)
        print(f"✅ Commander 已訂閱分派主題: {dispatch_topic}")
        client.subscribe(disconnection_topic)
        print(f"✅ Commander 已訂閱斷連主題: {disconnection_topic}")
        
        client.subscribe("system/config")
        print(f"✅ Commander 已訂閱全域設定: system/config")
    else:
        print(f"❌ Commander 連線失敗, code: {reason_code}")

def on_commander_message(client, userdata, msg):
    """
    處理來自 SUMO 主控制器指令的核心函式。
    - 監聽 `system/config` 來動態啟用或關閉智慧繞路功能。
    - 監聽車輛分派主題：當新車輛被分配到此電腦時，創建對應的 Vehicle 和 Vehicle_subscriber 實例。
    - 監聽車輛斷連主題：當車輛抵達終點時，清理對應的實例和資源。
    - 更新車輛的即時狀態並觸發其決策邏輯。
    """
    global SMART_REROUTING_ENABLED, vehicle_specific_client
    world_id = userdata["world_id"]
    topic = msg.topic
    payload = msg.payload.decode('utf-8')
    
    if topic == "system/config":
        try:
            config_data = json.loads(payload)
            if 'smart_rerouting_enabled' in config_data:
                new_status = config_data['smart_rerouting_enabled']
                if new_status != SMART_REROUTING_ENABLED:
                    SMART_REROUTING_ENABLED = new_status
                    status_text = "啟用" if SMART_REROUTING_ENABLED else "關閉"
                    print(f"⚙️ [Config] 收到全域設定：感知決策系統已「{status_text}」。")
                    for sub in subscriberDict.values():
                        sub.smart_rerouting_enabled = SMART_REROUTING_ENABLED
        except Exception as e:
            print(f"Error processing system config: {e}")
        return

    # 【教授修改】判斷是否是發給自己的分派主題
    if topic.startswith("pc1_") and not topic.endswith("_vehicle_disconnection"):
        veh_id = payload
        properties = msg.properties
        vehicleState = {}

        if properties and properties.UserProperty:
            for prop in properties.UserProperty:
                if prop[0] == 'vehicleState':
                    try:
                        vehicleState = json.loads(prop[1])
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"警告: 無法解析來自 UserProperty 的 vehicleState: {prop[1]}，錯誤: {e}")
                        return
                    break
        if not vehicleState: return

        if veh_id not in vehicleDict:
            print(f"➕ [OBU生成] 偵測到新車輛 {veh_id}，正在創建實例...")
            vehicle = Vehicle(veh_id, world_id)
            vehicleDict[veh_id] = vehicle
            
            if SMART_REROUTING_ENABLED:
                print(f"     🧠 -> 感知決策系統已啟用，為 {veh_id} 創建決策大腦 (Vehicle_subscriber)...")
                subscriber_id = f'{veh_id}_subscriber'
                vehicle_length = vehicleState.get('vehicleLength', 5.0) 
                subscriber = Vehicle_subscriber(subscriber_id, vehicle_length, shared_publisher_client, SMART_REROUTING_ENABLED, world_id)
                subscriberDict[subscriber_id] = subscriber
                
                # 【教授修改】訂閱帶有命名空間的車輛專屬主題
                vehicle_specific_topic = f"worlds/{world_id}/{subscriber_id}"
                vehicle_specific_client.subscribe(vehicle_specific_topic)
                print(f"     ✅ 已為 {veh_id} 訂閱: {vehicle_specific_topic}")
            else:
                print(f"     -> 感知決策系統已關閉，{veh_id} 將只作為數據發布者。")

        vehicle = vehicleDict[veh_id]
        vehicle.vehicleState = vehicleState
        vehicle.publish_state(shared_publisher_client)
        
        subscriber_id = f'{veh_id}_subscriber'
        if SMART_REROUTING_ENABLED and subscriber_id in subscriberDict:
            subscriber = subscriberDict[subscriber_id]
            subscriber.update_realtime_state(vehicleState)

        client.publish(topic="ack", payload="c")

    elif topic.endswith("_vehicle_disconnection"):
        veh_id = payload
        if veh_id in vehicleDict:
            del vehicleDict[veh_id]

        subscriber_id = f'{veh_id}_subscriber'
        if subscriber_id in subscriberDict:
            if vehicle_specific_client.is_connected():
                vehicle_specific_topic = f"worlds/{world_id}/{subscriber_id}"
                vehicle_specific_client.unsubscribe(vehicle_specific_topic)
            del subscriberDict[subscriber_id]
        
        print(f"➖ [OBU回收] 車輛 {veh_id} 抵達終點並已清理。")

if __name__ == '__main__':
    # 【教授修改】直接在這裡「寫死」這個腳本的身份
    world_id = "main_world"
    pc_name = "pc1"

    print(f"=================================================")
    print(f"💻 OBC 啟動中... 所屬世界 ID: [{world_id}]")
    print(f"=================================================")

    shared_publisher_client.connect("127.0.0.1", 7883, 60)
    shared_publisher_client.loop_start()
    print("OBC 共用 Publisher 已啟動。")

    global_info_client.user_data_set({"world_id": world_id})
    global_info_client.on_connect = on_global_info_connect
    global_info_client.on_message = on_global_info_message
    global_info_client.connect("127.0.0.1", 7883, 60)
    global_info_client.loop_start()

    vehicle_specific_client.on_connect = on_vehicle_specific_connect
    vehicle_specific_client.on_message = on_vehicle_specific_message
    vehicle_specific_client.connect("127.0.0.1", 7883, 60)
    vehicle_specific_client.loop_start()

    commander_client = mqtt.Client(
        client_id=f"physicalComputer_{world_id}_{random.randint(100,999)}", 
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2, 
        protocol=mqtt.MQTTv5
    )
    commander_client.user_data_set({"world_id": world_id, "pc_name": pc_name})
    commander_client.on_connect = on_commander_connect
    commander_client.on_message = on_commander_message
    commander_client.connect("127.0.0.1", 7884, 3600)
    
    print(f"OBC 主程式已啟動，等待來自 SUMO 主控制器 ({world_id}) 的指令...")
    commander_client.loop_forever()