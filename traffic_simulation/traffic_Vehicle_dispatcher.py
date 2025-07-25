#simulation / traffic_Vehicle_dispatcher.py

import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import json
import threading

class Vehicle_dispatcher:
    def __init__(self):
        self._physicalComputers = {} # computers in the physical part
        self.lock = threading.Lock()
        self._vehicleDispatchMapping = {} # keep track of vehcile dispatch mapping 
        self._ack_count_lock = threading.Lock()       
        self._ack_count = 0
    
    @property
    def physicalComputers(self):
        return self._physicalComputers

    @physicalComputers.setter
    def physicalComputers(self, computers):
        self._physicalComputers = computers    
    
    @property
    def ack_count(self):
        with self._ack_count_lock:
            return self._ack_count
    
    @ack_count.setter
    def ack_count(self, value):
        with self._ack_count_lock:
            if value == 0:
                self._ack_count = 0
            else:
                self._ack_count += 1

    def get_vehicle_dispatch_mapping(self,veh_id):
        with self.lock:
            mapping = self._vehicleDispatchMapping
            for pc in mapping:
                veh_list = mapping[pc]
                if veh_id in veh_list:
                    return pc
            return None
    
    def set_vehicle_dispatch_mapping(self, pc, veh_id):
        with self.lock:
            if pc not in self._vehicleDispatchMapping:
                tmp_list = []
                tmp_list.append(veh_id)
                self._vehicleDispatchMapping[pc] = tmp_list
            else:
                veh_list = self._vehicleDispatchMapping[pc]
                veh_list.append(veh_id) 

    def update_vehicle_dispatch_mapping(self, veh_id):
        with self.lock:
            mapping = self._vehicleDispatchMapping 
            for pc in mapping:
                veh_list = mapping[pc]
                if veh_id in veh_list:
                    veh_list.remove(veh_id)
                    break
    
    def dispatch_vehicle(self, pc, veh_id, geofenceInfo):
        publish_properties = Properties(PacketTypes.PUBLISH)
        publish_properties.UserProperty = ("geofenceInfo", json.dumps(geofenceInfo))
        self.mqttc.publish(
            topic=pc, payload=veh_id, properties=publish_properties)
        pass
    
    def on_disconnect(self, client, flags, userdata, reason_code, properties):
        if reason_code == 0:
            print(f"{client._client_id} disonnected:", reason_code)
            self.mqttc.loop_stop()
        else:
            print(f"{client._client_id} disonnected error:", reason_code)

    def disconnect(self):  
        print('disconnect')         
        self.mqttc.disconnect()    

    def on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe("vehicleDispatch")
        client.subscribe("ack")
        if reason_code == 0:
            print(f"{client._client_id} Connection: {reason_code}")
        else:
            print("Connection failed, reason code: ", reason_code)

    def connect(self, mqtt_server, mqtt_port):
        self.mqttc = mqtt.Client(client_id="vehicleDispatcher", callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.connect(mqtt_server, mqtt_port, 3600)
        self.mqttc.loop_start()

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        if topic == 'ack':            
            self.ack_count += 1
        # payload = msg.payload.decode('utf-8')
       