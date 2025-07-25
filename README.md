# 環境建置
1. 請依照SUMO官網教學，將SUMO source code下載並編譯，參考以下連結: https://sumo.dlr.de/docs/Installing/Linux_Build.html

2. 在bashrc中設定以下環境變數:
````
export SUMO_HOME=PATH_TO_YOUR_SUMO_DIRECTORY
export PATH="$SUMO_HOME/bin:$PATH"
ulimit -S -n 100000
````

3. 安裝redis，參考以下連結:
https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/install-redis-on-linux/

4. 在redis.conf中關閉持久化的快照功能，將 ````save "" ```` 加入至redis.conf中配置snapshotting的區塊後重新啟動redis-server。關於redis的持久化功能，參考: https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/

5. 若有需要redis gui，可安裝redisInsight，參考: https://redis.io/docs/latest/operate/redisinsight/install/install-on-desktop/

6. 以下為目前系統使用的python套件版本:
```
redis 5.0.4
sumolib 1.20.0
traci 1.20.0
shapely 2.0.4
pyproj 3.5.0
Paho-mqtt 2.1.0
```

7. 編譯testbed目錄底下的兩個MQTT Brokers，以下是這兩個broker分別使用的port:
```
mosquitto-2.0.15_virtual: 7884
mosquitto-2.0.15_physical: 7883
```

# Testbed 檔案目錄

```
├── monitors
│   ├── GeofenceMonitor.py
│   ├── MessageHandler.py
│   ├── RouteMonitor.py
│   └── monitors.sh
├── mosquitto-2.0.15_physical
├── mosquitto-2.0.15_virtual
├── on_board_computer
│   ├── Vehicle.py
│   ├── Vehicle_subscriber.py
│   └── physicalComputer.py
└── traffic_simulation
    ├── README.md
    ├── RetriveVehiclePos_distributed.py
    ├── Vehicle.py
    ├── Vehicle_dispatcher.py
    ├── Vehicle_subscriber.py
    ├── garbage_collector.py
    ├── new_osm.net.xml
    ├── osm.poly.xml.gz
    ├── osm.sumocfg
    ├── osm.view.xml
    ├── passenger.sampled.rou.xml
    ├── passenger.sampled.rou_bk.xml
    ├── passenger.sampled.rou_micro_benchmark.xml
    ├── tls.xml
```

# 執行

1. 執行redis-cli的 `FLUSHALL` 指令

2. 啟動 `testbed` 目錄底下兩個MQTT Brokers

3. 執行 `testbed/monitors` 目錄底下的 `monitors.sh`

4. 執行 `testbed/on_board_computer` 目錄底下的 `physicalComputer.py`

5. 執行 `testbed/traffic_simulation` 目錄底下的 `RetriveVehiclePos_distributed.py`

Note: 請將 `RetriveVehiclePos_distributed.py` 第46行及47行替換成你sumo-gui的binary以及osm.sumocfg放置的位置

# 補充
SUMO 的教學可參考以下:
1. 官方教學，連結: <https://sumo.dlr.de/docs/Tutorials/index.html>
2. Miscellaneous目錄下的 `輕鬆學SUMO微觀交通模擬軟體.pdf`
3. Traffic Modeling with SUMO: a Tutorial，連結: <https://arxiv.org/abs/2304.05982>

