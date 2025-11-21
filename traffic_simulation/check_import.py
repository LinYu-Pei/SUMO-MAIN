import os
import sys

# --- 1. 手動載入我們未毀損的 'tools_lib' 函式庫 ---
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
traci_lib_path = os.path.join(project_root, "tools_lib") # 這是 1.24.0 的 tools_lib

if not os.path.exists(traci_lib_path):
    print(f"❌ 找不到函式庫：{traci_lib_path}")
    sys.exit(1)
if traci_lib_path not in sys.path:
    sys.path.insert(0, traci_lib_path)

try:
    import traci
    print(f"✅ 成功載入 Traci 函式庫: {traci.__file__}")
except ImportError:
    print(f"❌ 無法導入 Traci 函式庫 (路徑: {traci_lib_path})")
    sys.exit(1)

# --- 2. 連接到 pip 安裝的 'sumo-gui' 主程式 ---
# 我們需要一個最小的 config 檔案來啟動
# 請確保 "osm.sumocfg.xml" 存在於 "traffic_simulation" 目錄中

sumo_binary = "sumo-gui" # 來自 pip install eclipse-sumo==1.24.0
config_file = "osm.sumocfg.xml" # 您的主世界 config
traci_port = 8900 # 使用一個新的埠

sumoCmd = [sumo_binary, "-c", config_file]

try:
    traci.start(sumoCmd, port=traci_port, label="Traci_Check")
    print(f"✅ 成功連接到 {sumo_binary}")
    
    # --- 3. 執行最終檢查 ---
    # 檢查 'traci.lane' 物件是否 *真的* 擁有了 'setColor' 函式
    
    has_getLaneNumber = hasattr(traci.edge, 'getLaneNumber')
    has_setColor = hasattr(traci.lane, 'setColor')

    print("\n--- 診斷報告 ---")
    print(f"traci.edge 是否有 'getLaneNumber'?  {has_getLaneNumber}")
    print(f"traci.lane 是否有 'setColor'?       {has_setColor}")
    
    if not has_setColor:
        print("\n❌ 診斷確認：")
        print("我們載入了正確的函式庫，但 pip 安裝的 sumo-gui 主程式是毀損的。")
        print("它在連接時並未提供 'lane.setColor' 函式。")

    traci.close()

except Exception as e:
    print(f"\n❌ 連接或啟動失敗: {e}")
    print("請確保您在 (sumo_env) 虛擬環境中，並且 eclipse-sumo==1.24.0 已安裝。")