#on_board_computer /Vehicle_subscriber.py

import paho.mqtt.client as mqtt
import multiprocessing
import threading
import select
import time
import ast
import math
import json

class Vehicle_subscriber:
    def __init__(self, veh_id, vehicleLength, virtual_mqtt_server, virtual_mqtt_port):
        self.veh_id = veh_id
        self.vehicleLength = vehicleLength
        self.virtual_mqtt_server = virtual_mqtt_server
        self.virtual_mqtt_port = virtual_mqtt_port
        self.subscribe_status = False
        self.avg_speed = 0 
        self.vehicle_count = 0
        self.history_avg_speed = [0, 0]
        self.history_vehicle_count = [0,0]
        self.lane = dict(laneID='', laneLength=50, end_to_end_delay= -1)
        self.segment_number = 0    
        self.stop_event = threading.Event()

    def on_connect(self, client, userdata, flags, reason_code, properties):
       if reason_code == 0:
           print(f"{self.veh_id} Connection: {reason_code}")
       else:
           print("Connection failed, reason code: ", reason_code)
    
    def disconnect(self):             
        self.sub_client.disconnect()

    def on_disconnect(self, client, userdata, reason_code, properties):
        if reason_code == 0:
            print(f"{self.veh_id} disonnected:", reason_code)            
        else:
            print(f"{self.veh_id} disonnected error:", reason_code)
        
        # Signal the thread to stop
        self.stop_event.set()
      
    def handle_network_loop(self, epoll, sock_fd):
        # Track the time to manage PINGREQ sending
        last_ping_time = time.time()
        ping_interval = 60  # Default keepalive interval for MQTT
        try:
            while not self.stop_event.is_set():
                # Poll for events
                events = epoll.poll(1)

                for fd, event in events:
                    if fd == sock_fd:
                        if event & select.EPOLLIN:
                            self.sub_client.loop_read()
                        if event & select.EPOLLOUT:
                            self.sub_client.loop_write()
                        if event & select.EPOLLERR:
                            self.sub_client.loop_misc()
                
                # Periodically call loop_misc to handle PINGREQ and other misc tasks
                current_time = time.time()
                if current_time - last_ping_time >= ping_interval:
                    self.sub_client.loop_misc()
                    last_ping_time = current_time

                # Sleep for a short period to avoid busy-waiting
                time.sleep(0.5)

        finally:
            # Clean up
            try:
                epoll.unregister(sock_fd)
            except Exception:
                pass     
            epoll.close()
            self.sub_client.disconnect()

    def connect(self,mqtt_server, mqtt_port):        
        self.sub_client = mqtt.Client(
            client_id=self.veh_id, protocol=mqtt.MQTTv5)
        self.sub_client._connect_timeout = 60.0  
        self.sub_client.on_connect = self.on_connect    
        self.sub_client.on_disconnect = self.on_disconnect
        self.sub_client.on_message = self.on_message
        self.sub_client.connect(mqtt_server, mqtt_port, keepalive = 3600)
        self.sub_client.subscribe(f'{self.veh_id}')
        if self.veh_id == 'ambulance_subscriber':        
            self.sub_client.subscribe('ambulance_reroute') # receive from RouteMonitor
        # Create an epoll object
        epoll = select.epoll()
        # Register the MQTT socket with the epoll object for read and write events
        sock_fd = self.sub_client.socket().fileno()
        epoll.register(sock_fd, select.EPOLLIN | select.EPOLLOUT | select.EPOLLERR)
        t = threading.Thread(target=self.handle_network_loop, args=[epoll, sock_fd])
        t.start()
        self.subscribe_status = True       


    def computeRoadStatus(self, road_segment):               
        is_vehicle_in_junction = road_segment['laneID'].startswith(":")
        laneLength = float(road_segment['laneLength'])
        lanePosition = float(road_segment['lanePosition'])
        if not is_vehicle_in_junction:
            segment_length = laneLength / 3
            segment_number = math.ceil(lanePosition / segment_length)
            if self.lane['laneID'] != road_segment['laneID']: # catch lane changing without passing a junction
                self.segment_number = segment_number
                self.history_avg_speed = [0, 0]
                self.history_vehicle_count = [0,0]

            if 'history_avg_speed' in road_segment: # update history avg speed and vehicle count to vehicles 
                n = segment_number - 2                
                self.history_avg_speed[n] = road_segment['history_avg_speed']
                self.history_vehicle_count[n] =  road_segment['history_vehicle_count']
                return

            if segment_number > 1 and self.segment_number < segment_number: # if segment number changes, current vehicle publishes the history avg speed and vehicle counts in the previous segment to all vehicles within its current segment
                history_vehicle_count = self.vehicle_count 
                self.history_avg_speed[segment_number-2] = self.avg_speed
                self.history_vehicle_count[segment_number-2] = history_vehicle_count

                road_segment['history_avg_speed'] = self.avg_speed
                road_segment['history_vehicle_count'] = history_vehicle_count 
                for vehicle in road_segment['vehicles']:
                    if vehicle != road_segment['current_veh_id']:                 
                        topic = f'{vehicle}_subscriber'                    
                        payload = json.dumps(road_segment)
                        self.sub_client.publish(topic=topic, payload=payload)            
            
            self.segment_number = segment_number 
            self.avg_speed = road_segment['avg_speed']
            self.vehicle_count = road_segment['count']            
            self.lane['laneID'] = road_segment['laneID']
            self.lane['laneLength'] = float(road_segment['laneLength'])
            self.lane['end_to_end_delay'] = float(road_segment['travelTime'])
    
        else:
            vehicle_count = sum(self.history_vehicle_count) + self.vehicle_count

            if vehicle_count == 0:
                vehicle_count = 1

            weighted_total_vehicles = math.ceil(vehicle_count / 3)
            
            total_speed = sum(speed * count for speed, count in zip(self.history_avg_speed, self.history_vehicle_count))
            average_speed = total_speed / vehicle_count            
            density = (weighted_total_vehicles * (self.vehicleLength + average_speed / 2) ) / self.lane['laneLength']
            threshold = (3.6 * self.lane['laneLength']) / self.lane['end_to_end_delay']

            if average_speed < threshold and density > 0.8:                
                lane_status = {self.lane['laneID']: 'busy'}                 
                payload = json.dumps(lane_status)
                self.sub_client.publish(topic="lane_status", payload=payload)
            else:
                lane_status = {self.lane['laneID']: 'idle'}
                payload = json.dumps(lane_status)
                self.sub_client.publish(topic="lane_status", payload=payload)
            
            if self.veh_id == 'ambulance_subscriber':                
                print(f"{self.veh_id} is in junction {self.lane['laneID']}, connected lanes: {type(road_segment['connectedLanes'])}")                               
                self.sub_client.publish(topic="ambulance_query", payload=road_segment['connectedLanes'])

            self.history_avg_speed = [0, 0]
            self.history_vehicle_count = [0,0]
           

    def on_message(self ,client, userdata, msg): 
        if msg.topic == 'ambulance_reroute':
            print('ambulance_reroute')
            try:
                ambulance_reroute_notifier = mqtt.Client(client_id="ambulance_reroute_notifier", protocol=mqtt.MQTTv5)
                ambulance_reroute_notifier._connect_timeout = 60.0 
                ambulance_reroute_notifier.connect(self.virtual_mqtt_server, self.virtual_mqtt_port, keepalive = 60)
                ambulance_reroute_notifier.publish(topic="ambulance_reroute", payload="r")
            except:
                pass 
        else:
            payload = msg.payload.decode('utf-8')
            road_segment = ast.literal_eval(payload)
            self.computeRoadStatus(road_segment)
  


   
