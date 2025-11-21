# traffic_simulation/controller.py
# (v8.12.24 - 全域控制器)
# 
# 職責：
# 1. 作為一個獨立的終端機執行。
# 2. 連接到 7884 (Control Broker)。
# 3. 監聽使用者的 [Enter] 按鍵。
# 4. 廣播「全部恢復」或「全部暫停」指令給所有模擬世界。

import os
import sys
import time
import json
import threading
import paho.mqtt.client as mqtt
import signal

# --- 全域常數 ---
VIRTUAL_BROKER = {'host': '127.0.0.1', 'port': 7884}
CONTROLLER_ID = f"Global_Controller_{int(time.time())}"
WORLD_ID = "CONTROLLER" # 此腳本的日誌標籤

SYSTEM_RESUME_ALL_TOPIC = "system/resume_all"
SYSTEM_PAUSE_ALL_TOPIC = "system/pause_all"

# --- 全域變數 ---
shutdown_flag = threading.Event()
# 【關鍵】: 模擬啟動後會立刻因 TLS 同步而暫停，
# 因此控制器的初始狀態必須是 "PAUSED"，
# 這樣使用者的第一次按鍵才會是「恢復」。
global_sim_state = "PAUSED"


def signal_handler(signum, frame):
    """
    @教授註解:
    捕獲 Ctrl+C (SIGINT) 或終止信號 (SIGTERM)。
    設置全域的 shutdown_flag，以通知主迴圈
    應在 input() 阻塞解除後安全退出。
    """
    global shutdown_flag
    if not shutdown_flag.is_set():
        print(f"\n[{WORLD_ID}] 捕獲到信號 {signum}，設置關閉標誌...")
        print(f"[{WORLD_ID}] 請再按一次 [Enter] 鍵以結束程式。")
        shutdown_flag.set()

def connect_mqtt(host, port, client_id):
    """
    @教授註解:
    建立一個簡單的 MQTT 客戶端，只用於「發布 (Publish)」。
    它不需要監聽任何主題。
    """
    client = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    
    def on_connect(client, userdata, flags, rc, properties):
        if rc == 0:
            print(f"✅ [{WORLD_ID}] MQTT 控制器連接成功 ({host}:{port})。")
        else:
            print(f"❌ [{WORLD_ID}] MQTT 連接失敗，返回碼: {rc}")

    def on_disconnect(client, userdata, flags, rc, properties):
        if rc != 0 and not shutdown_flag.is_set():
            print(f"⚠️ [{WORLD_ID}] MQTT 意外斷開連接。")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    try:
        client.connect(host, port, keepalive=60)
        client.loop_start()
        return client
    except Exception as e:
        print(f"❌ [{WORLD_ID}] MQTT 連接時發生錯誤: {e}")
        return None

def main():
    """
    @教授註解:
    主函式。
    運行一個無限迴圈，等待使用者的 input()。
    根據當前的 global_sim_state 來切換發布「暫停」或「恢復」。
    """
    global global_sim_state # 宣告我們將修改全域狀態變數

    # --- 1. 註冊訊號處理 ---
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # --- 2. 連接 MQTT ---
    client = connect_mqtt(
        VIRTUAL_BROKER['host'], 
        VIRTUAL_BROKER['port'], 
        CONTROLLER_ID
    )
    
    if not client:
        print(f"[{WORLD_ID}] 無法連接到 MQTT Broker，程式終止。")
        return

    print(f"✅ [{WORLD_ID}] 全域控制器已啟動。")
    print(f"   您可以隨時在此終端機按下 [Ctrl+C] (可能需要按 Enter 觸發) 來結束程式。")

    try:
        # --- 3. 主控制迴圈 ---
        while not shutdown_flag.is_set():
            try:
                # --- A. 根據當前狀態顯示提示 ---
                if global_sim_state == "PAUSED":
                    print("\n" + "="*50)
                    print("⏸️   模擬已暫停 (PAUSED)")
                    print("  -> 請按 [Enter] 鍵以「恢復 (RESUME)」所有世界...")
                    prompt_action = "RESUME"
                else: # "RUNNING"
                    print("\n" + "="*50)
                    print("▶️   模擬正在運行 (RUNNING)")
                    print("  -> 請按 [Enter] 鍵以「暫停 (PAUSE)」所有世界...")
                    prompt_action = "PAUSE"

                # --- B. 阻塞並等待使用者輸入 ---
                input() # 程式會停在這裡，直到使用者按下 [Enter]

                # --- C. 檢查是否在等待時被 Ctrl+C 中斷 ---
                if shutdown_flag.is_set():
                    # 如果是因為 signal_handler 而解除阻塞
                    print(f"[{WORLD_ID}] 偵測到關閉信號，正在退出主迴圈...")
                    break

                # --- D. 根據狀態發送指令並切換狀態 ---
                if prompt_action == "RESUME":
                    print("...正在發送「全部恢復」指令 (RESUME)...")
                    payload = json.dumps({"source": "controller", "command": "RESUME"})
                    client.publish(SYSTEM_RESUME_ALL_TOPIC, payload, qos=1)
                    global_sim_state = "RUNNING" # 切換狀態
                else: # "PAUSE"
                    print("...正在發送「全部暫停」指令 (PAUSE)...")
                    payload = json.dumps({"source": "controller", "command": "PAUSE"})
                    client.publish(SYSTEM_PAUSE_ALL_TOPIC, payload, qos=1)
                    global_sim_state = "PAUSED" # 切換狀態
                        
            except (KeyboardInterrupt, EOFError):
                # 當 Ctrl+C 在 input() 期間被按下時，會觸發此異常
                if not shutdown_flag.is_set():
                     print(f"\n[{WORLD_ID}] 收到中斷信號... 結束中...")
                     shutdown_flag.set()
                break # 退出 while 迴圈
            except Exception as e:
                if not shutdown_flag.is_set():
                    print(f"\n💥 [{WORLD_ID}] 主迴圈發生未知錯誤: {e}")
                    time.sleep(1)

    finally:
        # --- 4. 清理 ---
        print(f"\n[{WORLD_ID}] 正在斷開 MQTT (7884)...")
        if client and client.is_connected():
            client.loop_stop()
            client.disconnect()
        print(f"[{WORLD_ID}] 控制器已關閉。")


if __name__ == "__main__":
    main()