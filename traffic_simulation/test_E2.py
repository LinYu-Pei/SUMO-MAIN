import traci
import time

# --- 設定 ---
SUMO_CONFIG_FILE = "osm.sumocfg.xml" # 換成你的sumocfg檔案名稱
DETECTOR_ID_TO_TEST = "det_1076843363#0_4" # 換成一個你想測試的、真實存在的偵測器ID

# 啟動SUMO
traci.start(["sumo", "-c", SUMO_CONFIG_FILE])

print(f"--- 開始測試偵測器: {DETECTOR_ID_TO_TEST} ---")

try:
    # 讓模擬跑幾步，累積一些數據
    for step in range(1000):
        traci.simulationStep()
        
        # 每10步查詢一次數據並印出
        if step % 10 == 0:
            # 透過TraCI，直接查詢該偵測器的平均速度
            mean_speed = traci.lanearea.getLastStepMeanSpeed(DETECTOR_ID_TO_TEST)
            
            # 透過TraCI，直接查詢該偵測器的佔有率
            occupancy = traci.lanearea.getLastStepOccupancy(DETECTOR_ID_TO_TEST)
            
            print(f"模擬步長 {step}:")
            print(f"  - 平均速度 (Mean Speed): {mean_speed:.2f} m/s")
            print(f"  - 時間佔有率 (Occupancy): {occupancy:.2f} %")
            print("-" * 20)
            
            # 讓你有時間可以看到輸出
            time.sleep(0.1) 

finally:
    # 結束模擬
    traci.close()
    print("--- 測試結束 ---")