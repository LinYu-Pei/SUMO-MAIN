# 檔名: on_board_computer/Vehicle.py (註解優化版)

from shapely.geometry import Polygon, Point, box
from pyproj import CRS, Transformer
from shapely.ops import transform
from shapely.affinity import rotate
import paho.mqtt.client as mqtt
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import json
import datetime
import threading
from traffic_Vehicle_subscriber import Vehicle_subscriber

class Vehicle:
    """
    代表一個獨立的車載單元 (OBU)。
    負責管理自身的 MQTT 發布客戶端 (pub_client) 和訂閱客戶端 (vehicle_subscriber)，
    並處理地理圍欄的計算與發布。
    """
    def __init__(self, veh_id):
        """初始化 Vehicle 物件"""
        self.veh_id = veh_id      
        self.physical_mqtt_server = None
        self.physical_mqtt_port = None
        self.virtual_mqtt_server = None
        self.virtual_mqtt_port = None
        
        self.pub_client = None
        self.vehicle_subscriber = None
        
        self.subscribe_status = False
        self._last_publish_step = 0
        self._geofenceInfo = {}
        self._physicalComputerMapping = None

    def connect(self, physical_mqtt_server, physical_mqtt_port, virtual_mqtt_server, virtual_mqtt_port):
        """建立並連線此車輛的 MQTT 發布客戶端"""
        self.physical_mqtt_server = physical_mqtt_server
        self.physical_mqtt_port = physical_mqtt_port
        self.virtual_mqtt_server = virtual_mqtt_server
        self.virtual_mqtt_port = virtual_mqtt_port
        
        self.pub_client = mqtt.Client(client_id=self.veh_id, protocol=mqtt.MQTTv5)
        self.pub_client.on_connect = self.on_connect
        self.pub_client.on_disconnect = self.on_disconnect      
        print(f"{self.veh_id} 正在連線至 Broker {physical_mqtt_server}:{physical_mqtt_port}")
        self.pub_client.connect(physical_mqtt_server, physical_mqtt_port, keepalive=3600)
        return 0

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """發布客戶端的 on_connect 回呼函式"""
        if reason_code == 0:
            print(f"發布者 '{self.veh_id}' 連線成功。")
        else:
            print(f"發布者 '{self.veh_id}' 連線失敗，代碼: {reason_code}")

    def disconnect(self):
        """斷開此車輛的所有 MQTT 連線"""
        if self.pub_client and self.pub_client.is_connected():
            self.pub_client.disconnect()
        if self.vehicle_subscriber:
            self.vehicle_subscriber.disconnect()

    def on_disconnect(self, client, userdata, reason_code, properties):
        """發布客戶端的 on_disconnect 回呼函式"""
        if reason_code == 0:
            print(f"發布者 '{self.veh_id}' 已斷線。")
        else:
            print(f"發布者 '{self.veh_id}' 斷線時發生錯誤，代碼: {reason_code}")
    
    # --- Properties ---
    @property
    def physicalComputerMapping(self):
        return self._physicalComputerMapping
    @physicalComputerMapping.setter
    def physicalComputerMapping(self, pc):
        self._physicalComputerMapping = pc

    @property
    def last_publish_step(self):
        return self._last_publish_step
    @last_publish_step.setter
    def last_publish_step(self, step):
        self._last_publish_step = step

    @property
    def geofenceInfo(self):
        return self._geofenceInfo
    @geofenceInfo.setter
    def geofenceInfo(self, info):
        self._geofenceInfo = info

    def publishGeoFence(self):
        """計算地理圍欄並發布，同時確保訂閱者已啟動"""
        geofenceInfo = self.geofenceInfo
        
        # 我們之前已將計算方式改為圓形
        radius_in_meters = geofenceInfo['width']
        geofence = self.circle_geodesic_point_buffer(lat=geofenceInfo['lat'], lon=geofenceInfo['lon'], radius=radius_in_meters)
        
        # 準備 MQTT payload 和 properties
        currentTime = datetime.datetime.now()
        publish_properties = Properties(PacketTypes.PUBLISH)
        publish_properties.UserProperty = [
            ("geofence", str(geofence)),
            ("time", str(currentTime)),
            ("laneID", str(geofenceInfo['laneID'])),
            ("speed", str(geofenceInfo['speed'])),
            # --- ↓↓↓ 已修改，補全所有 properties ↓↓↓ ---
            ("laneLength", str(geofenceInfo['laneLength'])),
            ("travelTime", str(geofenceInfo['travelTime'])),
            ("lanePosition", str(geofenceInfo['lanePosition'])),
            ("connectedLanes", str(geofenceInfo['connectedLanes']))
        ]
        
        payload_dict = dict(veh_id=self.veh_id, lat=geofenceInfo['lat'], lon=geofenceInfo['lon'])
        publish_payload = json.dumps(payload_dict)        
              
        self.pub_client.publish(topic="geofence", payload=publish_payload, properties=publish_properties)
    
        # 確保訂閱者只被建立和連線一次
        if not self.subscribe_status:
            print(f"為 '{self.veh_id}' 首次建立訂閱者...")
            subscriber_id = f'{self.veh_id}_subscriber'
            self.vehicle_subscriber = Vehicle_subscriber(
                subscriber_id, 
                geofenceInfo['vehicleLength'], 
                self.virtual_mqtt_server, 
                self.virtual_mqtt_port
            )
            self.vehicle_subscriber.connect(self.physical_mqtt_server, self.physical_mqtt_port)
            self.subscribe_status = True

    ''' 計算圓形的地理圍欄 '''
    def circle_geodesic_point_buffer(self, lat, lon, radius):
        # Azimuthal equidistant projection
        aeqd_proj = CRS.from_proj4(
            f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0")
        tfmr = Transformer.from_proj(aeqd_proj, aeqd_proj.geodetic_crs)
        buf = Point(0, 0).buffer(radius)  # distance in metres
        return transform(tfmr.transform, buf).exterior.coords[:]

    ''' 計算矩形的地理圍欄 (此函式保留備用，但不再被呼叫)'''
    def rectangle_geodesic_point_buffer(self, lat, lon, width, roatateAngle, height=15):
        # Azimuthal equidistant projection
        aeqd_proj = CRS.from_proj4(
            f"+proj=aeqd +lat_0={lat} +lon_0={lon} +x_0=0 +y_0=0")
        tfmr = Transformer.from_proj(aeqd_proj.geodetic_crs, aeqd_proj)
        projected_point = transform(tfmr.transform, Point(lon, lat))
        # Create a rectangle centered at the projected point
        minx = projected_point.x - (width / 2)
        maxx = projected_point.x + (width / 2)
        miny = projected_point.y - (height / 2)
        maxy = projected_point.y + (height / 2)
        projected_rect = box(minx, miny, maxx, maxy)
        # Rotate the rectangle by the specified angle      
        rotated_rect = rotate(projected_rect, roatateAngle, origin='center', use_radians=False)
        # Transform the rotated rectangle back to geodetic coordinates
        tfmr_inv = Transformer.from_proj(aeqd_proj, aeqd_proj.geodetic_crs)
        geodetic_rect = transform(
            tfmr_inv.transform, rotated_rect).exterior.coords[:]
        return geodetic_rect
    
    def publish(self):
        self.pub_client.publish(
            topic="keepAlive", payload="i")