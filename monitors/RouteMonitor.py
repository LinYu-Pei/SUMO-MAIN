# monitors/RouteMonitor.py

import paho.mqtt.client as mqtt
import ast
import re
import time
import multiprocessing
from multiprocessing.pool import ThreadPool
import threading
import redis
import sys
import queue
import json

pool = redis.ConnectionPool(host='localhost', port=6379, decode_responses=True, db=0)
r = redis.Redis(connection_pool=pool)
thread_pool = ThreadPool(processes=800)

mutex = threading.Lock()
condition = threading.Condition(mutex)

arrivedIDList = []

status_lock = threading.Lock()
status = {}

vehicles_info_redis = {}

''' Query Redis and maintain a hashtable to keep track of each lane'''
def queryRedis():
    while True:
        keys = r.scan_iter(count=500)
        with condition:
            for veh_id in keys:
                vehicle_info = r.hgetall(veh_id)
                if not vehicle_info:
                    continue
                vehicle_info['veh_id'] = veh_id
                laneID = vehicle_info['laneID']

                # 清除該 veh_id 的舊資料
                for laneID_key in list(vehicles_info_redis.keys()):
                    vehicles_info_redis[laneID_key] = [vehicle for vehicle in vehicles_info_redis[laneID_key] if vehicle['veh_id'] != veh_id]
                    if len(vehicles_info_redis[laneID_key]) == 0:
                        vehicles_info_redis.pop(laneID_key)

                # 更新 laneID 的資料
                if laneID not in vehicles_info_redis:
                    vehicles_info_redis[laneID] = []
                vehicles_info_redis[laneID].append(vehicle_info)

            condition.notify_all()
        time.sleep(1)

def compute_road_segment_status(current_vehicle_info):    
    polygon = ast.literal_eval(current_vehicle_info['geofence'])    
    road_segment = {}

    with condition: 
        condition.wait()
        vehicles_list = vehicles_info_redis.get(current_vehicle_info["laneID"])
        
        if not road_segment:
            road_segment['current_veh_id'] = current_vehicle_info['veh_id']
            road_segment['laneID'] = current_vehicle_info['laneID']
            road_segment['connectedLanes'] = current_vehicle_info['connectedLanes']
            road_segment['laneLength'] = current_vehicle_info['laneLength']
            road_segment['lanePosition'] = current_vehicle_info['lanePosition']
            road_segment['travelTime'] = current_vehicle_info['travelTime']
            road_segment['speed'] = float(current_vehicle_info['speed'])
            road_segment['count'] = 1
            tmp_list = []
            tmp_list.append(current_vehicle_info['veh_id'])
            road_segment['vehicles'] = tmp_list
        if vehicles_list:
            for vehicle in vehicles_list:
                if vehicle['veh_id'] == current_vehicle_info['veh_id']:
                    continue
                lon = float(vehicle['lon'])
                lat = float(vehicle['lat'])
                point = tuple([lon,lat])
                result = is_point_in_polygon(point, polygon)
                if result: 
                    road_segment['speed'] += float(vehicle['speed'])
                    road_segment['count'] += 1
                    tmp_list = road_segment['vehicles'] 
                    tmp_list.append(vehicle["veh_id"]) 
                    road_segment['vehicles'] = tmp_list 
                     
    road_segment['avg_speed'] = road_segment['speed'] / road_segment['count']    
    mqttc.publish(topic="road_segment_status", payload=json.dumps(road_segment)) # inform MessageHandler
    pass

def is_point_in_polygon(point, polygon):
    """
    使用射線法來判斷點是否在多邊形內   
    :param point: (longitude, latitude)
    :param polygon: [(longitude1, latitude1), (longitude2, latitude2), ...]
    :return: True if the point is in the polygon, False otherwise
    """
    x, y = point
    n = len(polygon)
    inside = False
    
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside

def process_arrived_ids(arrivedIDs):
    with condition:
        for arrivedID in arrivedIDs:
            # vehicles_info_redis.pop(arrivedID)
            for laneID_key in list(vehicles_info_redis.keys()):
                    vehicles_info_redis[laneID_key] = [vehicle for vehicle in vehicles_info_redis[laneID_key] if vehicle['veh_id'] != arrivedID]
                    if len(vehicles_info_redis[laneID_key]) == 0:
                        vehicles_info_redis.pop(laneID_key)
        condition.notify_all()

def on_connect(client, userdata, flags, reason_code, properties):
    print(f'{client._client_id} connected.')
    client.subscribe("RouteMonitor")
    client.subscribe("arrivedIDList")
    client.subscribe("lane_status")
    client.subscribe("ambulance_query")

def on_message(client, userdata, msg):
    topic = msg.topic    
    payload = msg.payload.decode('utf-8')

    if topic == 'arrivedIDList':
        arrivedIDs = ast.literal_eval(payload)
        arrivedIDList.extend(arrivedIDs)
        thread_pool.apply_async(process_arrived_ids, args=(arrivedIDs,))                
                      
    elif topic == 'RouteMonitor':
        current_vehicle_info = ast.literal_eval(payload)  
        thread_pool.apply_async(compute_road_segment_status, args=(current_vehicle_info,))
      
    elif topic == 'lane_status':
        lane_status = ast.literal_eval(payload)
        with status_lock:
            for key, value in lane_status.items():
                status[f'{key}'] = f'{value}'
    
    elif topic == 'ambulance_query':
        connectedLanes = ast.literal_eval(payload)
        with status_lock:
            for connectedLane in connectedLanes:
                if status.get(connectedLane) == 'busy':
                    mqttc.publish(topic="ambulance_reroute", payload="ambulance_reroute") # publish to ambulance
                    return
               
      
client_id = "RouteMonitor"
mqttc = mqtt.Client(client_id= client_id, callback_api_version=mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
mqttc.on_connect = on_connect
mqttc.on_message = on_message

mqttc.connect("localhost", 7883, 60)

t = threading.Thread(target = queryRedis)
t.start()

mqttc.loop_forever()