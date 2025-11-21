# on_board_computer/Vehicle_subscriber.py

import paho.mqtt.client as mqtt
import json
import random
import time

class Vehicle_subscriber:
    # 【教授修改】__init__ 函式新增 world_id 參數
    def __init__(self, veh_id, vehicleLength, shared_mqtt_client, smart_rerouting_enabled=True, world_id="default_world"):
        """
        初始化車載電腦 (OBC) 的決策核心。
        每個 OBC 實例對應到一個特定的車輛。

        Args:
            veh_id (str): 車輛的訂閱者 ID (通常是 '車輛ID_subscriber')。
            vehicleLength (float): 車輛長度。
            shared_mqtt_client: 用於發布訊息的共享 MQTT 客戶端。
            smart_rerouting_enabled (bool): 是否啟用智慧繞路功能的開關。
            world_id (str): 此 OBC 所屬的世界 ID。
        """
        self.veh_id = veh_id
        self.base_veh_id = self.veh_id.replace("_subscriber", "")
        self.vehicleLength = vehicleLength
        self.shared_client = shared_mqtt_client
        self.smart_rerouting_enabled = smart_rerouting_enabled
        self.world_id = world_id # 儲存 world_id
        self.macro_road_status = {}
        self.realtime_state = {}
        self.current_obu_state = "Initializing"
        
        # --- 決策行為參數 ---
        self.last_reroute_request_step = 0
        self.REROUTE_COOLDOWN_STEPS = 10 
        self.SUGGESTION_ACCEPT_PROBABILITY = 0.5

        # --- 卡死診斷計數器 ---
        self.stuck_at_green_light_counter = 0
        self.STUCK_AT_GREEN_THRESHOLD_STEPS = 5
        self.generic_stuck_counter = 0
        self.GENERIC_STUCK_THRESHOLD_STEPS = 51

        self.last_update_step = 0
        self.STOP_THRESHOLD_MS = 0.1
        self.DYNAMIC_SPEED_FACTOR = 0.4

    def update_realtime_state(self, new_state):
        """
        從 physicalComputer 更新車輛的即時狀態，並觸發決策邏輯。
        
        Args:
            new_state (dict): 包含最新車輛狀態的字典。
        """
        self.realtime_state = new_state
        self.run_decision_logic()

    def handle_macro_message(self, topic, payload):
        """
        處理來自 RouteMonitor 的宏觀路況訊息。
        
        Args:
            topic (str): 訊息的主題。
            payload (str): 訊息的內容 (JSON 格式)。
        """
        try:
            # 【教授修改】主題判斷現在要用 .endswith()
            if topic.endswith('global_road_status'):
                status_data = json.loads(payload)
                self.macro_road_status = status_data.get('road_status', {})
                self.run_decision_logic()
        except Exception as e:
            print(f"處理宏觀訊息時出錯 ({self.veh_id}, {topic}): {e}")

    def run_decision_logic(self):
        """
        OBC 的核心決策函式，在每次狀態更新或收到新路況時運行。
        它會：
        1. 根據自身速度和交通號誌，更新自身的 OBU 狀態 (如 FreeFlow, StoppedInTraffic)。
        2. 檢查當前車道是否有強制繞行指令。
        3. 自我診斷是否卡在某處 (如綠燈、一般道路)。
        4. 預測未來路徑是否會遇到壅塞，並根據機率決定是否提前繞路。
        """
        try:
            current_step = int(self.realtime_state.get('current_step', 0))
            if not current_step or not self.smart_rerouting_enabled: return

            new_obu_state = self._get_self_obu_state()
            if new_obu_state != self.current_obu_state:
                self.current_obu_state = new_obu_state
                print(f"🧠 [{self.world_id}-OBC-{self.base_veh_id}] 狀態更新: {self.current_obu_state} (步長: {current_step})") 
                self._publish_perception_report()

            current_lane_id = self.realtime_state.get('laneID', '')
            if current_lane_id and current_lane_id in self.macro_road_status:
                lane_status = self.macro_road_status[current_lane_id]
                if lane_status.get("action") == "MandatoryReroute":
                    if (current_step - self.last_reroute_request_step) >= self.REROUTE_COOLDOWN_STEPS:
                        print(f"✅ [{self.world_id}-OBC-{self.base_veh_id}] 因收到 '{current_lane_id}' 的『強制繞行』廣播而請求 reroute！")
                        self._request_reroute_and_report_anomaly("On_Mandatory_Lane_Broadcast")
                        return

            if self._decide_self_stuck_anomaly(current_step):
                return

            self._decide_predictive_reroute()
            
            self.last_update_step = current_step
        
        except Exception as e:
            print(f"🔥🔥🔥 [{self.world_id}-OBC-{self.base_veh_id}] 核心決策邏輯發生致命錯誤! 🔥🔥🔥")
            import traceback
            traceback.print_exc()
            print(f"觸發錯誤時的車輛狀態: {self.realtime_state}")

    def _decide_predictive_reroute(self):
        """
        預測性繞路決策。
        檢查未來幾個路口的宏觀路況，如果遇到「建議繞路」或「強制繞路」的路段，
        則根據設定的機率或規則決定是否提前請求繞路。
        """
        current_step = int(self.realtime_state.get('current_step', 0))
        if (current_step - self.last_reroute_request_step) < self.REROUTE_COOLDOWN_STEPS:
            return

        worst_action, problematic_lane = self._get_future_path_worst_status(lookahead=3)
        should_reroute = False
        reason = ""

        if worst_action == "MandatoryReroute":
            should_reroute = True
            reason = "Accepted_MandatoryReroute"
            print(f"   [OBC-{self.base_veh_id}] 預測到前方路徑 '{problematic_lane}' 有嚴重壅塞，立即執行 reroute！")
        elif worst_action == "SuggestReroute":
            if random.random() < self.SUGGESTION_ACCEPT_PROBABILITY:
                should_reroute = True
                reason = "Accepted_SuggestReroute"
                print(f" [OBC-{self.base_veh_id}] 預測到前方路徑 '{problematic_lane}' 有繞行建議，隨機決策：接受！")
            else:
                print(f" [OBC-{self.base_veh_id}] 預測到前方路徑 '{problematic_lane}' 有繞行建議，隨機決策：忽略。")

        if should_reroute:
            self._request_reroute_and_report_anomaly(reason)
    
    def _decide_self_stuck_anomaly(self, current_step):
        """
        自我卡死診斷。
        透過計數器偵測車輛是否在綠燈時卡住不動，或在非紅燈情況下滯留過久。
        如果滿足條件，則觸發繞路請求。
        """
        is_stopped = self.current_obu_state in ["NormalRedLightStop", "StuckAtGreenLight", "StoppedInTraffic"]
        steps_passed = current_step - self.last_update_step if self.last_update_step > 0 else 1

        if self.current_obu_state == "StuckAtGreenLight":
            self.stuck_at_green_light_counter += steps_passed
        else:
            self.stuck_at_green_light_counter = 0

        if self.stuck_at_green_light_counter >= self.STUCK_AT_GREEN_THRESHOLD_STEPS:
            print(f"🚨 [OBC-{self.base_veh_id}][自我診斷] 在綠燈處卡住超過 {self.STUCK_AT_GREEN_THRESHOLD_STEPS} 步！")
            self._request_reroute_and_report_anomaly("StuckAtGreenLightSensor")
            self.stuck_at_green_light_counter = 0
            return True
            
        if is_stopped and self.current_obu_state != "NormalRedLightStop":
            self.generic_stuck_counter += steps_passed
        else:
            self.generic_stuck_counter = 0
            
        if self.generic_stuck_counter >= self.GENERIC_STUCK_THRESHOLD_STEPS:
            print(f"🆘 [OBC-{self.base_veh_id}][自我診斷] 在原地滯留超過 {self.GENERIC_STUCK_THRESHOLD_STEPS} 步！")
            self._request_reroute_and_report_anomaly("GenericStuckSensor")
            self.generic_stuck_counter = 0
            return True
        return False

    def _request_reroute_and_report_anomaly(self, reason="Unknown"):
        """
        向主模擬控制器發出繞路請求，並在必要時將自身所在車道標記為「繁忙」。
        包含一個冷卻機制，防止在短時間內重複發送請求。
        """
        current_step = int(self.realtime_state.get('current_step', 0))
        if (current_step - self.last_reroute_request_step) < self.REROUTE_COOLDOWN_STEPS: return
        
        print(f"🚀 [{self.world_id}-OBC-{self.base_veh_id}] 正在向主控制器發出 reroute 請求 (原因: {reason})。")
        
        reroute_request = {"veh_id": self.base_veh_id}
        
        reroute_topic = f"worlds/{self.world_id}/reroute_request" #
        self.shared_client.publish(reroute_topic, json.dumps(reroute_request))
        
        if "Sensor" in reason or "Stuck" in reason:
            my_lane = self.realtime_state.get('laneID')
            if my_lane and not my_lane.startswith(":"):
                sanitized_lane_id = my_lane.replace('#', '_').replace('+', '_')
                warning_topic = f"worlds/{self.world_id}/lanes/status/{sanitized_lane_id}"
                warning_payload = json.dumps({"status": "busy", "source": f"{self.base_veh_id}_{reason}"})
                self.shared_client.publish(warning_topic, warning_payload, qos=1)
        
        self.last_reroute_request_step = current_step

    def _get_self_obu_state(self):
        """
        根據車輛的即時速度和前方交通號誌狀態，判斷自身的 OBU 狀態。
        
        Returns:
            str: OBU 狀態 (例如 "FreeFlow", "StuckAtGreenLight")。
        """
        speed = float(self.realtime_state.get('speed', '0'))
        lane_max_speed = float(self.realtime_state.get('maxSpeed', '30'))
        tls_perception = self.realtime_state.get("tls_perception", {})
        is_tls_visible = tls_perception.get("is_visible", False)
        tls_state = tls_perception.get("state", None)
        if speed < self.STOP_THRESHOLD_MS:
            if is_tls_visible and tls_state:
                if any(c in tls_state.lower() for c in ['r', 'y']): return "NormalRedLightStop"
                elif any(c in tls_state.lower() for c in ['g', 'G']): return "StuckAtGreenLight" 
                else: return "StoppedInTraffic"
            else: return "StoppedInTraffic"
        dynamic_threshold = lane_max_speed * self.DYNAMIC_SPEED_FACTOR
        if speed >= dynamic_threshold: return "FreeFlow"
        else: return "SlowTraffic"

    def _publish_perception_report(self):
        """
        將自身的 OBU 狀態作為一個「感知報告」發布出去，供 RouteMonitor 進行分析。
        """
        report = {
            "veh_id": self.base_veh_id, "timestamp": time.time(),
            "lane_id": self.realtime_state.get('laneID'), "obu_state": self.current_obu_state,
            "speed_ms": self.realtime_state.get('speed', 0)
        }
        # 發布到帶有命名空間的主題
        topic = f"worlds/{self.world_id}/vehicles/perception/report"
        self.shared_client.publish(topic, json.dumps(report), qos=0)

    def _get_future_path_worst_status(self, lookahead=3):
        """
        檢查預計行駛路徑上未來數個路段的宏觀路況。

        Args:
            lookahead (int): 要檢查的未來路段數量。
        
        Returns:
            tuple: (最差的行動建議, 有問題的車道 ID)。
        """
        current_route = self.realtime_state.get('currentRoute', [])
        current_lane_id = self.realtime_state.get('laneID', '')
        if not current_route or not current_lane_id or current_lane_id.startswith(":"): return "Monitor", None
        current_edge_id = current_lane_id.split('_')[0]
        try:
            current_index = current_route.index(current_edge_id)
            path_to_check = current_route[current_index + 1 : current_index + 1 + lookahead]
            if not path_to_check: return "Monitor", None
            worst_action, worst_priority, problematic_lane = "Monitor", 5, None
            for edge in path_to_check:
                lane_to_check = f"{edge}_0" 
                lane_info = self.macro_road_status.get(lane_to_check, {})
                action, priority = lane_info.get("action", "Monitor"), lane_info.get("priority", 5)
                if priority < worst_priority:
                    worst_priority, worst_action, problematic_lane = priority, action, lane_to_check
            return worst_action, problematic_lane
        except ValueError: 
            return "Monitor", None



