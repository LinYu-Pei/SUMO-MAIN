# 檔名: cli.py (使用者介面 A)
# 功能: 提供一個互動式的終端介面，讓我們可以方便地下達指令。

import json
import paho.mqtt.publish as publish

# --- 設定區 ---
# MQTT Broker 的位址和通訊埠
BROKER = "127.0.0.1"
PORT = 7883

# --- 輔助函式區 ---
def publish_command(topic: str, payload: dict):
    """
    將指令打包成 JSON 格式並發布到指定的 MQTT 主題。

    Args:
        topic (str): 要發布到的 MQTT 主題。
        payload (dict): 要發送的指令內容 (Python 字典)。
    """
    try:
        # 將 Python 字典轉換成 JSON 格式的字串
        payload_str = json.dumps(payload)
        # 使用 paho.mqtt 的 single 函式來發布單一訊息，它會自動連線、發布、然後斷開，非常適合我們的遙控器
        publish.single(
            topic,
            payload=payload_str,
            hostname=BROKER,
            port=PORT,
            qos=1,  # 確保訊息至少會被傳遞一次
        )
        print(f"    指令已發送: {payload} 到 {topic}")
    except ConnectionRefusedError:
        print(f"    [錯誤] 發送失敗！無法連線到 {BROKER}:{PORT}。請確認 MQTT Broker 是否已啟動。")
    except Exception as e:
        print(f"    [錯誤] 發送時發生未知錯誤: {e}")

# --- 主程式區 ---
def main() -> None:
    """
    主程式入口，包含互動式介面迴圈。
    """
    print("==========================================")
    print("===            指令控制台             ===")
    print("==========================================")
    print(f"目標 Broker: {BROKER}:{PORT}")
    print("提示：在任何時候都可以按 Ctrl+C 離開程式。")

    # 建立一個無限迴圈，讓使用者可以一直操作
    while True:
        try:
            # --- 主選單 ---
            print("\n" + "="*42)
            print("請選擇要執行的操作：")
            print("  1: Change Lane (變換車道)")
            print("  2: Change Edge (變更途經路段)")
            print("  exit: 離開程式")
            choice = input("請輸入選項 [1, 2, exit]: ").strip()

            if choice.lower() == 'exit':
                break

            # --- 處理換道 (Change Lane) ---
            if choice == '1':
                print("\n--- 模式: 批次變換車道 ---")
                veh_ids_str = input("請輸入車輛 ID (多個請用空格分開): ")
                veh_ids = veh_ids_str.split()

                lanes_str = input(f"請為這 {len(veh_ids)} 輛車輸入對應的目標車道索引 (用空格分開): ")
                lane_indices = lanes_str.split()

                if len(veh_ids) != len(lane_indices):
                    print("  [錯誤] 輸入的車輛數量和車道數量不匹配！請重新操作。")
                    continue

                duration_str = input("請輸入統一的變換車道持續時間 (秒) [預設為 6]: ")
                duration = int(duration_str) if duration_str else 6
                
                print("-" * 20)
                # 使用 zip() 將兩個列表「配對」，然後一次處理所有指令
                for veh_id, lane_index_str in zip(veh_ids, lane_indices):
                    try:
                        # 組合 Payload 和 Topic
                        payload = {
                            "cmd": "change_lane",
                            "lane_index": int(lane_index_str),
                            "duration": duration,
                        }
                        topic = f"commands/vehicle/{veh_id.strip()}"
                        # 呼叫我們寫好的輔助函式來發送指令
                        publish_command(topic, payload)
                    except ValueError:
                        print(f"    [錯誤] 車道索引 '{lane_index_str}' 不是一個有效的數字。")
                print("-" * 20)
            
            # --- 處理換路段 (Change Edge) ---
            elif choice == '2':
                print("\n--- 模式: 批次變更途經路段 ---")
                veh_ids_str = input("請輸入車輛 ID (多個請用空格分開): ")
                veh_ids = veh_ids_str.split()

                edges_str = input(f"請為這 {len(veh_ids)} 輛車輸入對應的目標路段 ID (用空格分開): ")
                edge_ids = edges_str.split()

                if len(veh_ids) != len(edge_ids):
                    print("  [錯誤] 輸入的車輛數量和路段數量不匹配！請重新操作。")
                    continue
                
                print("-" * 20)
                # 使用 zip() 進行配對並發送
                for veh_id, edge_id in zip(veh_ids, edge_ids):
                    payload = {
                        "cmd": "change_edge",
                        "edge_id": edge_id.strip(),
                    }
                    topic = f"commands/vehicle/{veh_id.strip()}"
                    publish_command(topic, payload)
                print("-" * 20)

            else:
                print("  [提示] 無效的選項，請重新輸入。")

        except (KeyboardInterrupt, EOFError):
            # 處理使用者按下 Ctrl+C 或 Ctrl+D 的情況
            break

    print("\n控制台已關閉。")

# --- 程式進入點 ---
# 確保這個腳本是直接被執行，而不是被匯入
if __name__ == "__main__":
    main()