# on_board_computer/Vehicle.py

from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import json
import datetime

class Vehicle:
    # 】__init__ 函式新增 world_id 參數
    def __init__(self, veh_id, world_id):
        """
        初始化一個 Vehicle 物件。

        Args:
            veh_id (str): 車輛的唯一 ID。
            world_id (str): 車輛所屬的世界 ID。
        """
        self.veh_id = veh_id
        self.world_id = world_id # 儲存 world_id
        self._vehicleState = {}

    @property
    def vehicleState(self):
        return self._vehicleState

    @vehicleState.setter
    def vehicleState(self, state):
        self._vehicleState = state

    def publish_state(self, shared_publisher_client):
        """
        將車輛的當前狀態發布到 MQTT Broker。
        狀態數據被打包到 MQTT v5 的 User Properties 中，而核心位置資訊則在 payload 中。
        發布的主題是根據車輛所屬的 world_id 動態生成的。

        Args:
            shared_publisher_client: 用於發布訊息的共享 MQTT 客戶端實例。
        """
        vehicleState = self.vehicleState
        if not vehicleState or not shared_publisher_client:
            return

        currentTime = datetime.datetime.now()
        publish_properties = Properties(PacketTypes.PUBLISH)
        
        publish_properties.UserProperty = [
            ("time", str(currentTime)),
            ("laneID", str(vehicleState.get('laneID'))),
            ("speed", str(vehicleState.get('speed'))),
            ("laneLength", str(vehicleState.get('laneLength'))),
            ("travelTime", str(vehicleState.get('travelTime'))),
            ("lanePosition", str(vehicleState.get('lanePosition'))),
            ("connectedLanes", str(vehicleState.get('connectedLanes'))),
            ("currentRoute", json.dumps(vehicleState.get('currentRoute'))),
            ("destinationEdge", str(vehicleState.get('destinationEdge'))),
            ("maxSpeed", str(vehicleState.get('maxSpeed'))),
            ("current_step", str(vehicleState.get('current_step')))
        ]

        payload_dict = dict(veh_id=self.veh_id, lat=vehicleState.get('lat', ''), lon=vehicleState.get('lon', ''))
        publish_payload = json.dumps(payload_dict)
        
        # 發布到帶有命名空間的主題
        topic = f"worlds/{self.world_id}/vehicle/state"
        shared_publisher_client.publish(topic=topic, payload=publish_payload, properties=publish_properties, qos=0)