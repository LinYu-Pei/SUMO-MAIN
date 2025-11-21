# traffic_simulation/traffic_Vehicle_dispatcher.py

import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import json
import threading

class Vehicle_dispatcher:
    """
    車輛分派器，負責將從 SUMO 獲取的車輛狀態數據轉發到對應的實體電腦 (OBC) 實例。
    它也負責接收來自 OBC 的 ACK 確認訊息，以實現模擬同步。
    """
    def __init__(self):
        """初始化 Vehicle_dispatcher 物件。"""
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
        """線程安全地獲取當前收到的 ACK 計數。"""
        with self._ack_count_lock:
            return self._ack_count
    
    @ack_count.setter
    def ack_count(self, value):
        """線程安全地設置 ACK 計數器 (重置或遞增)。"""
        with self._ack_count_lock:
            if value == 0:
                self._ack_count = 0
            else:
                self._ack_count += 1

    def get_vehicle_dispatch_mapping(self,veh_id):
        """(未被使用) 獲取特定車輛被分配到哪個實體電腦。"""
        with self.lock:
            mapping = self._vehicleDispatchMapping
            for pc in mapping:
                veh_list = mapping[pc]
                if veh_id in veh_list:
                    return pc
            return None
    
    def set_vehicle_dispatch_mapping(self, pc, veh_id):
        """(未被使用) 記錄車輛到實體電腦的分配映射。"""
        with self.lock:
            if pc not in self._vehicleDispatchMapping:
                tmp_list = []
                tmp_list.append(veh_id)
                self._vehicleDispatchMapping[pc] = tmp_list
            else:
                veh_list = self._vehicleDispatchMapping[pc]
                veh_list.append(veh_id) 

    def update_vehicle_dispatch_mapping(self, veh_id):
        """(未被使用) 當車輛離開時，更新分配映射。"""
        with self.lock:
            mapping = self._vehicleDispatchMapping 
            for pc in mapping:
                veh_list = mapping[pc]
                if veh_id in veh_list:
                    veh_list.remove(veh_id)
                    break
    
    def dispatch_vehicle(self, pc, veh_id, vehicleState):
        """
        將單一車輛的狀態數據分派 (發布) 到指定的實體電腦主題。

        Args:
            pc (str): 目標實體電腦的主題。
            veh_id (str): 車輛 ID。
            vehicleState (dict): 車輛的狀態數據字典。
        """
        publish_properties = Properties(PacketTypes.PUBLISH)
        publish_properties.UserProperty = ("vehicleState", json.dumps(vehicleState))
        self.mqttc.publish(
            topic=pc, payload=veh_id, properties=publish_properties)
        pass
    
    def on_disconnect(self, client, flags, userdata, reason_code, properties):
        """當與 MQTT Broker 斷開連線時的回呼函式。"""
        if reason_code == 0:
            print(f"'{client._client_id}' disonnected:", reason_code)
            self.mqttc.loop_stop()
        else:
            print(f"'{client._client_id}' disonnected error:", reason_code)

    def disconnect(self):
        """手動斷開 MQTT 連線。"""   
        print('disconnect')       
        self.mqttc.disconnect()      

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """
        當成功連接到 MQTT Broker 時的回呼函式。
        連接後，會訂閱 ACK 主題以接收來自 OBC 的確認。
        """
        client.subscribe("ack")
        if reason_code == 0:
            print(f"'{client._client_id}' Connection Success.")
        else:
            print(f"'{client._client_id}' Connection failed, reason code: ", reason_code)

    # 【教授修改】connect 函式增加 world_id 參數
    def connect(self, mqtt_server, mqtt_port, world_id):
        """
        連接到 MQTT Broker。

        Args:
            mqtt_server (str): Broker 的主機地址。
            mqtt_port (int): Broker 的端口。
            world_id (str): 用於創建唯一客戶端 ID 的世界 ID。
        """
        # 【教授修改】使用 f-string 根據 world_id 創建獨一無二的 client_id
        client_id = f"vehicleDispatcher_{world_id}"
        self.mqttc = mqtt.Client(client_id=client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        self.mqttc.on_connect = self.on_connect
        self.mqttc.on_disconnect = self.on_disconnect
        self.mqttc.on_message = self.on_message
        self.mqttc.connect(mqtt_server, mqtt_port, 3600)
        self.mqttc.loop_start()

    def on_message(self, client, userdata, msg):
        """
        處理已訂閱主題訊息的回呼函式。
        當收到 'ack' 主題的訊息時，遞增 ACK 計數器。
        """
        topic = msg.topic
        if topic == 'ack':         
            self.ack_count += 1