# monitors/GeofenceMonitor.py

import paho.mqtt.client as mqtt
import ast
import re
import json
import redis

pool = redis.ConnectionPool(host='localhost', port=6379, decode_responses=True, db=0)
r = redis.Redis(connection_pool=pool)
pipe = r.pipeline()

def on_connect(client, userdata, flags, reason_code, properties):
    print(f'{client._client_id} connected.')
    client.subscribe("geofence")
    client.subscribe("arrivedIDList")

def on_message(client, userdata, msg):
    topic = msg.topic    
    payload = msg.payload.decode('utf-8')

    if topic == 'arrivedIDList':
      arrivedIDs = ast.literal_eval(payload)
      for arrivedID in arrivedIDs:        
        pipe.delete(arrivedID)
        pipe.execute()

    elif topic == 'geofence':
        # payload = msg.payload.decode('utf-8')
        vehicle_info = eval(payload)    
        properties = msg.properties    
        if properties:
            user_properties = properties.UserProperty        
            if user_properties:
                for prop in user_properties:
                    key = prop[0]
                    value = prop[1]                
                    vehicle_info[key] = value    

                r.hset(vehicle_info['veh_id'], mapping = {
                    'lat': vehicle_info['lat'],
                    'lon': vehicle_info['lon'],
                    'geofence': vehicle_info['geofence'],
                    'time': vehicle_info['time'],
                    'laneID': vehicle_info['laneID'],
                    'speed': vehicle_info['speed'],
                    'laneLength' : vehicle_info['laneLength'],
                    'travelTime' : vehicle_info['travelTime'],
                    'lanePosition': vehicle_info['lanePosition'],
                    'connectedLanes': vehicle_info['connectedLanes']                  
                })

                current_vehicle_info = json.dumps(vehicle_info)
            
            
                mqttc.publish(topic="RouteMonitor", payload=current_vehicle_info) # inform RouteMonitor
          

        else:
            print("No properties found")
       
    
client_id = "GeofenceMonitor"
mqttc = mqtt.Client(client_id= client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
mqttc.on_connect = on_connect
mqttc.on_message = on_message

mqttc.connect("localhost", 7883, 60)

mqttc.loop_forever()