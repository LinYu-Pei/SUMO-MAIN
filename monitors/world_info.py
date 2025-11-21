# monitors/world_info.py (輸出簡化版)

import paho.mqtt.client as mqtt
import json
import time
import random

# --- 設定 ---
BROKER_ADDRESS = "localhost"
BROKER_PORT = 7883
GLOBAL_STATUS_TOPIC_WILDCARD = "worlds/+/global_road_status"

def on_connect(client, userdata, flags, reason_code, properties):
    """
    當 MQTT 客戶端成功連接到 Broker 時的回呼函式。
    連接成功後，會訂閱所有世界（使用 '+' 萬用字元）的全局路況狀態主題。
    """
    if reason_code == 0:
        print("✅ 成功連接到 MQTT Broker！")
        client.subscribe(GLOBAL_STATUS_TOPIC_WILDCARD)
        print(f"📡 正在監聽全域路況快照: '{GLOBAL_STATUS_TOPIC_WILDCARD}'")
    else:
        print(f"❌ 連接失敗，返回碼: {reason_code}")

def on_message(client, userdata, msg):
    """
    當收到任何來自 'worlds/+/global_road_status' 主題的訊息時的回呼函式。
    此函式的主要功能是將接收到的路況快照以易於閱讀的格式打印到控制台，
    方便開發者即時監控各個模擬世界的路況變化。
    """
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        
        topic_parts = msg.topic.split('/')
        world_id = topic_parts[1] if len(topic_parts) > 1 else "unknown_world"
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        
        print("\n" + "="*50) # 保留分隔線
        print(f"🔥 [{timestamp}] 收到來自 [{world_id}] 的路況快照！")
        
        road_status = data.get('road_status', {})
        
        if not road_status:
            print(f"   -> 狀態: [{world_id}] 路況解除 (CLEAR)")
        else:
            print(f"   -> 偵測到 {len(road_status)} 條需注意的路段:")
            # 【教授修改】: 簡化路段資訊的打印格式
            for lane_id, status in road_status.items():
                final_state = status.get('final_state', 'N/A')
                action = status.get('action', 'N/A')
                # 直接打印 路段ID: 狀態 (行動建議)
                print(f"      - {lane_id}: {final_state} ({action})")

        # 【教授修改】: 註解掉打印原始 Payload 的部分
        # print("--- 原始 Payload ---")
        # print(json.dumps(data, indent=2, ensure_ascii=False))
        print("="*50) # 保留分隔線
        
    except (json.JSONDecodeError, UnicodeDecodeError, IndexError) as e:
        print(f"⚠️ 解析訊息時發生錯誤: {e}")
        print(f"原始 Topic: {msg.topic}")
        print(f"原始 Payload: {msg.payload}")


if __name__ == "__main__":
    client_id = f"Global_Status_Monitor_{random.randint(100, 999)}"
    print(f"🚀 啟動全域路況快照監控 (Client ID: {client_id})...")
    
    client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    
    client.on_connect = on_connect
    client.on_message = on_message
    
    try:
        client.connect(BROKER_ADDRESS, BROKER_PORT, 60)
        client.loop_forever()
        
    except KeyboardInterrupt:
        print("\n🛑 收到中斷指令，正在關閉監控中心...")
        client.disconnect()
        print("✅ 監控中心已關閉。")
    except Exception as e:
        print(f"💥 發生未預期的錯誤: {e}")
