# monitors/MessageHandler.py

import paho.mqtt.client as mqtt
import ast
import json

def on_connect(client, userdata, flags, reason_code, properties):
    print(f'{client._client_id} connected.')
    client.subscribe("road_segment_status")

def on_message(client, userdata, msg):
    topic = msg.topic    
    payload = msg.payload.decode('utf-8')
    road_segment = ast.literal_eval(payload)
    topic = f"{road_segment['current_veh_id']}_subscriber"
    mqttc.publish(topic=topic, payload=payload) # publish to vehicle

client_id = "MessageHandler"
mqttc = mqtt.Client(client_id= client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
mqttc.on_connect = on_connect
mqttc.on_message = on_message

mqttc.connect("localhost", 7883, 60)

mqttc.loop_forever()