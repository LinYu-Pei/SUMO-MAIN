#traffic_simulation / garbage_collector.py

import paho.mqtt.client as mqtt

def garbage_collector(physical_mqtt_server, physical_mqtt_port, virtual_mqtt_server, virtual_mqtt_port, traci_simulation, vehicleDict):
    arrivedIDList = traci_simulation.getArrivedIDList()

    garbage_collector = mqtt.Client(client_id="garbage_collector", protocol=mqtt.MQTTv5)
    if len(arrivedIDList) > 0:
        garbage_collector.connect(physical_mqtt_server, physical_mqtt_port)
        garbage_collector.publish(topic="arrivedIDList", payload=str(arrivedIDList)) # inform RouteMonitor to keep track of arrivedIDList
        garbage_collector.disconnect()

    garbage_collector.connect(virtual_mqtt_server, virtual_mqtt_port)
    
    for ID in arrivedIDList:
            vehicle = vehicleDict[ID]
            pc = vehicle.physicalComputerMapping
            garbage_collector.publish(topic=f"{pc}_vehicle_disconnection", payload=ID)       
            # vehicle.disconnect()            
            # print(f"{ID} arrived")

    garbage_collector.disconnect()
    
