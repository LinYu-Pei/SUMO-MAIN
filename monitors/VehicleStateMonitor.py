# monitors/VehicleStateMonitor.py

import paho.mqtt.client as mqtt
import json
import redis
import argparse
import ast

pool = redis.ConnectionPool(host='localhost', port=6379, decode_responses=True, db=0)
r = redis.Redis(connection_pool=pool)
pipe = r.pipeline()

def on_connect(client, userdata, flags, reason_code, properties):
    """
    當 MQTT 客戶端成功連接到 Broker 時的回呼函式。
    連接後，會訂閱該世界專屬的車輛狀態主題和車輛抵達列表主題。
    """
    world_id = userdata["world_id"]
    print(f"'{client._client_id}' connected.")
    
    vehicle_state_topic = f"worlds/{world_id}/vehicle/state"
    arrived_list_topic = f"worlds/{world_id}/arrivedIDList"
    
    client.subscribe(vehicle_state_topic)
    print(f"✅ Subscribed to {vehicle_state_topic}")
    client.subscribe(arrived_list_topic)
    print(f"✅ Subscribed to {arrived_list_topic}")

def on_message(client, userdata, msg):
    """
    處理所有已訂閱 MQTT 主題訊息的回呼函式。
    - 如果是 'arrivedIDList' 主題，它會解析抵達的車輛 ID 並從 Redis 中刪除它們的快取。
    - 如果是 'vehicle/state' 主題，它會解析車輛的詳細狀態並將其儲存或更新到 Redis 的 Hash 中。
    """
    topic = msg.topic
    payload = msg.payload.decode('utf-8')

    if topic.endswith('/arrivedIDList'):
        try:
            arrivedIDs = ast.literal_eval(payload)
            if arrivedIDs:
                for arrivedID in arrivedIDs:
                    pipe.delete(arrivedID)
                pipe.execute()
        except (ValueError, SyntaxError) as e:
            print(f"Error decoding arrivedIDList payload: {payload}, Error: {e}")

    elif topic.endswith('/vehicle/state'):
        try:
            vehicle_info = json.loads(payload)
        except json.JSONDecodeError:
            print(f"Error decoding vehicle/state payload: {payload}")
            return
            
        properties = msg.properties
        if properties and properties.UserProperty:
            for key, value in properties.UserProperty:
                vehicle_info[key] = value

        r.hset(vehicle_info['veh_id'], mapping={
            'lat': str(vehicle_info.get('lat', '')),
            'lon': str(vehicle_info.get('lon', '')),
            'time': str(vehicle_info.get('time', '')),
            'laneID': str(vehicle_info.get('laneID', '')),
            'speed': str(vehicle_info.get('speed', '')),
            'laneLength': str(vehicle_info.get('laneLength', '')),
            'travelTime': str(vehicle_info.get('travelTime', '')),
            'lanePosition': str(vehicle_info.get('lanePosition', '')),
            'connectedLanes': str(vehicle_info.get('connectedLanes', []))
        })

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Vehicle State Monitor for a specific SUMO world")
    parser.add_argument('--world-id', type=str, required=True, help='The ID of the world this monitor is for')
    args = parser.parse_args()
    world_id = args.world_id

    client_id = f"VehicleStateMonitor_{world_id}"
    print(f"=================================================")
    print(f"📈 VehicleStateMonitor 啟動中... 監聽世界 ID: [{world_id}]")
    print(f"=================================================")
    
    mqttc = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    mqttc.user_data_set({"world_id": world_id})
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message

    mqttc.connect("localhost", 7883, 60)
    mqttc.loop_forever()