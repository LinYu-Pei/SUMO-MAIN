import traci 


# - sumo-gui：開啟圖形介面
# - -c osm.sumocfg.xml：指定(-c) 模擬的設定檔
# - -S：step-by-step 模式，不自動前進，每一步都等 Python 指令推進
traci.start(["sumo-gui" , "-c", "osm.sumocfg.xml", "-S"])

for step in range(1000): #總共模擬 1000 個 step

    if step == 10 :
        traci.vehicle.setSpeed('Veh0', 5) # 對編號為 'veh0' 的車輛強制設定速度為 5 m/s（約 18 km/h）

    if step == 20 :
        traci.vehicle.changeLane('Veh0',1,50)
    
    traci.simulationStep()

traci.close()
