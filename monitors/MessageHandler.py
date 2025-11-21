# monitors/MessageHandler.py

import paho.mqtt.client as mqtt
import ast
import json

def on_connect(client, userdata, flags, reason_code, properties):
    """
    當 MQTT 客戶端成功連接到 Broker 時的回呼函式。
    連接成功後，會訂閱所有世界（使用 '+' 萬用字元）的路況狀態主題。
    """
    print(f"'{client._client_id}' connected.")
    # 【教授修改】使用萬用字元訂閱所有世界的 road_segment_status
    topic = "worlds/+/road_segment_status"
    client.subscribe(topic)
    print(f"✅ MessageHandler 已訂閱: {topic}")

def on_message(client, userdata, msg):
    """
    當收到任何已訂閱主題的訊息時的回呼函式。
    此函式會解析收到的路段狀態訊息，並將其轉發到對應車輛的專屬主題，
    供車載電腦 (OBC) 進行後續處理。
    """
    try:
        topic_parts = msg.topic.split('/')
        # 期望的主題格式: "worlds/{world_id}/road_segment_status"
        if len(topic_parts) == 3 and topic_parts[0] == 'worlds' and topic_parts[2] == 'road_segment_status':
            world_id = topic_parts[1]
        else:
            print(f"⚠️ 收到未知格式的主題: {msg.topic}")
            return
            
        payload = msg.payload.decode('utf-8')
        road_segment = ast.literal_eval(payload)
        
        # 【教授修改】組合出帶有命名空間的目標主題
        target_topic = f"worlds/{world_id}/{road_segment['current_veh_id']}_subscriber"
        
        # 使用全域的 mqttc client 來發布
        mqttc.publish(topic=target_topic, payload=payload)
        # print(f"轉發訊息至: {target_topic}") # 可選的除錯日誌
        
    except (UnicodeDecodeError, ValueError, SyntaxError, KeyError) as e:
        print(f"處理訊息時發生錯誤: {e}, Topic: {msg.topic}, Payload: {msg.payload.decode('utf-8', errors='ignore')}")

client_id = "MessageHandler_Global" # 這是一個全域服務，所以只有一個
mqttc = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
mqttc.on_connect = on_connect
mqttc.on_message = on_message

mqttc.connect("localhost", 7883, 60)
print("🚀 全域 MessageHandler 已啟動...")
mqttc.loop_forever()