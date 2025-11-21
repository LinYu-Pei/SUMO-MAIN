SUMO 分散式車輛智慧決策平台 v2.0 (2025)
1. 專案概覽 (Overview)
本專案是一個基於 SUMO、MQTT 和 Python 的高階交通模擬平台。其核心目標是研究在分散式架構下，個別的車載單元 (On-Board Unit, OBU) 如何融合自身的即時感測數據與後端提供的全域路況資訊，來做出智慧化的駕駛決策。系統能夠模擬從車輛自我狀態感知、異常情況上報，到後端數據融合、發布全球指令，再到車輛接收指令後執行動態路徑規劃的完整閉環。

核心技術
模擬器: SUMO (Simulation of Urban MObility)

通訊中介: Mosquitto (或任何相容的 MQTT Broker)

後端邏輯: Python 3.x

狀態快取: Redis

2. 專案特色 (Features)
分散式架構: 模擬真實世界中，運算發生在獨立的車輛 (OBU) 和中央伺服器上。

多源數據融合: 後端 RouteMonitor 能夠融合來自車輛 (OBU) 和路邊單元 (RSU) 的數據，做出更精準的交通判斷。

OBU 自我感知與決策: 每輛車的「大腦」(Vehicle_subscriber) 能獨立判斷自身狀態 (如：綠燈卡死、交通緩慢)，並主動上報或請求幫助。

分級應急響應: 後端根據壅塞嚴重程度，發布不同等級的指令 (監控、建議繞行、強制繞行)。

機率性決策模型: OBU 對於「建議繞行」指令，會以一定的機率決定是否採納，使模擬更貼近真實的人類駕駛行為。

詳細的性能監控: 主程式內建 RTF (Real-Time Factor) 監控模組，可詳細剖析模擬每一步的性能瓶頸。

高可配置性: 可透過主程式中的開關，一鍵啟用或關閉整個智慧感知系統，方便進行對照實驗。

3. 程式碼結構 (Code Structure)
.
├── monitors/                     # 後端監控與決策中心
│   ├── VehicleStateMonitor.py    # (原GeofenceMonitor) 監聽車輛狀態並寫入Redis
│   ├── RouteMonitor.py           # 核心！融合數據，判斷路況，發布指令
│   └── MessageHandler.py         # 輔助性的訊息轉發器
│
├── on_board_computer/            # 車載電腦 (OBU) 模擬
│   ├── physicalComputer.py       # OBU 實例的管理器，模擬實體運算節點
│   ├── Vehicle.py                # 車輛的數據模型與狀態發布器
│   └── Vehicle_subscriber.py     # 車輛的「決策大腦」
│
└── traffic_simulation/           # SUMO 模擬控制核心
    ├── RetriveVehiclePos_distributed_v1.py  # 專案主啟動腳本
    ├── traffic_Vehicle_dispatcher.py        # SUMO數據的分派器
    ├── traffic_Vehicle.py                   # SUMO車輛在主程式中的狀態容器
    └── garbage_collector.py                 # 已抵達車輛的資源回收器

4. 系統架構 (System Architecture)
本系統由四個主要部分組成，透過兩層 MQTT Broker 進行通訊，以區分「模擬控制層」和「V2X通訊層」。

[此處強烈建議繪製一張詳細的架構圖，清晰展示各元件和數據流]

A. 交通模擬核心 (Traffic Simulation Core) - traffic_simulation/
負責驅動 SUMO 模擬，是所有數據的源頭。

RetriveVehiclePos_distributed_v1.py

主要職責: 專案的主入口與驅動核心。它負責啟動 SUMO、在每一模擬步中從 TraCI 提取所有車輛的即時狀態，並協調所有其他模組的運作。

發布主題: system/config (廣播全域設定), rsu/raw_data (發布RSU數據)

訂閱主題: reroute_request (接收OBU的重路由請求), sumo/control/lane (預留的車道控制介面)

traffic_Vehicle_dispatcher.py

主要職責: 作為模擬核心與OBU管理器之間的中介橋樑。它將主程式收集到的車輛狀態數據包 (vehicleState)，透過虛擬 Broker 分派給指定的 physicalComputer。

發布主題: pc1 (發給OBC管理器)

訂閱主題: ack (接收OBC管理器的處理完成確認)

garbage_collector.py

主要職責: 定期檢查並清理已抵達終點的車輛資源，通知後端和OBC管理器釋放相關數據。

發布主題: arrivedIDList (通知後端清理Redis), pc1_vehicle_disconnection (通知OBC管理器清理物件)

B. 車載電腦 (On-Board Computer, OBC) - on_board_computer/
模擬分散在每輛車上的運算單元，是決策的主要執行者。

physicalComputer.py

主要職責: 模擬一個「實體電腦」或運算節點，負責管理多個 OBU 實例。它從虛擬 Broker 接收車輛數據，並動態創建、更新或銷毀對應的 Vehicle 和 Vehicle_subscriber 物件。

訂閱主題: pc1 (接收新車輛/狀態), pc1_vehicle_disconnection (接收車輛銷毀指令), system/config (接收全域設定), global_road_status (接收全域路況)

Vehicle.py

主要職責: 代表一輛車的數據模型，是OBU的「物理層」。它將 physicalComputer 傳遞過來的詳細狀態，發布到實體 Broker，供後端系統使用。

發布主題: vehicle/state (發布自身詳細狀態)

Vehicle_subscriber.py

主要職責: 車輛的**「決策大腦」**。它融合自身的即時狀態 (realtime_state) 和接收到的宏觀路況 (macro_road_status)，進行自主決策。

發布主題: vehicles/perception/report (發布自我感知結果), reroute_request (請求重新規劃路徑), lanes/status/... (上報異常)

C. 監控與融合中心 (Monitoring & Fusion Center) - monitors/
系統的後端服務，負責從全域視角進行監控、分析和決策。

VehicleStateMonitor.py

主要職責: 扮演「全域車輛狀態資料庫」的角色。它訂閱所有車輛發布的狀態訊息，並將最新的數據寫入 Redis 快取。

訂閱主題: vehicle/state, arrivedIDList

RouteMonitor.py

主要職責: 系統的**「融合決策中心」**。它從多個來源收集數據，執行複雜的融合邏輯來判斷路段的壅塞狀態，並生成具有行動建議的全域路況指令。

訂閱主題: rsu/raw_data, vehicles/perception/report, lanes/status/#

發布主題: global_road_status

MessageHandler.py

主要職責: 一個通用的訊息轉發器。它訂閱 road_segment_status，並將其轉發到以車輛ID命名的特定主題上。

訂閱主題: road_segment_status

發布主題: {veh_id}_subscriber (動態主題)

D. 通訊骨幹 (Communication Backbone)
實體 Broker (Physical Broker, Port 7883): 模擬真實世界的 V2X (Vehicle-to-Everything) 通訊。所有 OBU、RSU 和後端監控中心之間的通訊都在此進行。

虛擬 Broker (Virtual Broker, Port 7884): 用於模擬器與分散式運算節點之間的內部控制與數據分派。將模擬控制流與V2X通訊流分離，使架構更清晰。

5. 核心工作流程 (Core Workflow)
一個典型的「壅塞感知 -> 繞行決策」流程如下：

數據收集:

機制: RetriveVehiclePos... 在 t 時刻從 SUMO TraCI 取得車輛 veh_A 的完整狀態，打包成 vehicleState 字典。

數據分派:

機制: traffic_Vehicle_dispatcher 將 veh_A 的 vehicleState 發布至 MQTT 主題 pc1 (on Virtual Broker :7884)。

OBU 實例化:

機制: physicalComputer 監聽到 pc1 主題的訊息，為 veh_A 創建或更新其對應的 Vehicle 和 Vehicle_subscriber 物件。

狀態廣播:

機制: veh_A 的 Vehicle 物件將其詳細狀態 vehicleState 發布至 MQTT 主題 vehicle/state (on Physical Broker :7883)。

狀態存檔與自我感知:

機制:

VehicleStateMonitor 監聽到 vehicle/state，將 veh_A 的最新狀態寫入 Redis。

同時，veh_A 的 Vehicle_subscriber (大腦) 根據自身速度過慢，判斷出自己處於 SlowTraffic 狀態。

感知上報:

機制: veh_A 的 Vehicle_subscriber 將 { "veh_id": "veh_A", "obu_state": "SlowTraffic", ... } 的感知報告發布至 vehicles/perception/report 主題。

後端融合決策:

機制: RouteMonitor 收集到多個來源於路段 lane_X 的 SlowTraffic 報告，融合判斷後，發布一條 global_road_status 訊息，將 lane_X 的狀態標記為 UnderObservation。

接收指令與預測:

機制: veh_A 的 Vehicle_subscriber 收到 global_road_status。它檢查自己規劃的未來路徑 (currentRoute)，發現將會經過 lane_X。

執行 Reroute:

機制: RouteMonitor 發現 lane_X 狀況惡化，將其狀態升級為 SuggestReroute。veh_A 的大腦接收到新指令後，根據其內部的 SUGGESTION_ACCEPT_PROBABILITY 機率，決定請求繞行，並發布訊息到 reroute_request 主題。

模擬器更新路徑:

機制: RetriveVehiclePos... 監聽到 reroute_request 主題，捕獲到 veh_A 的請求，並呼叫 traci.vehicle.rerouteTraveltime("veh_A") 命令 SUMO 為該車輛重新規劃一條最快路徑。

6. 安裝與執行
前置需求
SUMO (v1.10.0 或更高版本)

Python (v3.8 或更高版本)

Redis Server

Mosquitto MQTT Broker (或其他 MQTT v5 相容 Broker)

安裝 Python 依賴
pip install paho-mqtt redis

啟動步驟
啟動 Redis Server (redis-server)。

啟動兩個 MQTT Broker 實例，分別監聽 7883 和 7884 連接埠。

在獨立的終端中，依序啟動 monitors/ 和 on_board_computer/ 目錄下的所有 Python 服務。

# 終端 1
python monitors/VehicleStateMonitor.py
# 終端 2
python monitors/RouteMonitor.py
# 終端 3
python monitors/MessageHandler.py
# 終端 4
python on_board_computer/physicalComputer.py

最後，執行主程式以啟動 SUMO 模擬：

# 終端 5
python traffic_simulation/RetriveVehiclePos_distributed_v1.py

系統配置
主要的實驗開關位於 traffic_simulation/RetriveVehiclePos_distributed_v1.py 的 main 函式中：

ENABLE_PERCEPTION_SYSTEM: (布林值) 全域開關，控制是否啟用整個智慧感知與決策系統。

ENABLE_BATCH_CLOSURE: (布林值) 是否在模擬特定時間點，執行批次封路以進行壓力測試。

config 字典: 包含所有路徑、連接埠等重要設定。

7. 未來可改進方向
數據序列化優化: 將 on_board_computer/Vehicle.py 中使用 UserProperty 傳遞大量字串的方式，改為將 vehicleState 字典直接 json.dumps 後作為 payload 發送，以提高效率。

異步ACK機制: 將 RetriveVehiclePos... 中的同步等待 wait_for_acks 改為更高效的異步機制，以提高大規模模擬下的性能。

服務合併: 評估 MessageHandler.py 的必要性，考慮將其功能合併到 RouteMonitor 中以簡化架構。

設定檔外部化: 將 config 字典和各種硬編碼的閾值（如 EVENT_EXPIRATION_SECONDS）移到獨立的 config.json 或 config.yaml 檔案中，方便管理。