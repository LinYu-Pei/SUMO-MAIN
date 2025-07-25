# on_board_computer/physicalComputer.py

import paho.mqtt.client as mqtt
from Vehicle import Vehicle
from Vehicle_subscriber import Vehicle_subscriber
import ast
import json
import time

vehicleDict = dict()

def on_connect(client, userdata, flags, reason_code, properties):
    print(f'{client._client_id} connected.')
    client.subscribe("pc1")
    client.subscribe("pc1_vehicle_disconnection")

def on_message(client, userdata, msg):
    topic = msg.topic
    if topic == "pc1":   
        veh_id = msg.payload.decode('utf-8')        
        properties = msg.properties 
        geofenceInfo = {} 

        if properties:
            user_properties = properties.UserProperty        
            if user_properties:
                for prop in user_properties:                
                    geofenceInfo = ast.literal_eval(prop[1])

        if veh_id in vehicleDict:
            vehicle = vehicleDict[veh_id]
        else:
            vehicle = Vehicle(veh_id)
            vehicleDict[veh_id] = vehicle
            vehicle.connect(physical_mqtt_server='127.0.0.1', physical_mqtt_port=7883,virtual_mqtt_server='127.0.0.1', virtual_mqtt_port=7884)    
        
        vehicle.geofenceInfo = geofenceInfo        
        vehicle.publishGeoFence()        
        client.publish(topic="ack",payload="c")
        

    elif topic == "pc1_vehicle_disconnection":
        veh_id = msg.payload.decode('utf-8')
        vehicle = vehicleDict[veh_id]
        vehicle.disconnect()            
        print(f"{veh_id} arrived")
    

if __name__ == '__main__':
    client_id = "physicalComputer_1"
    mqttc = mqtt.Client(client_id= client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message

    mqttc.connect("127.0.0.1", 7884, 3600)

    mqttc.loop_forever()
