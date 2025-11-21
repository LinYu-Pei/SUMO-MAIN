#  traffic_simulation/traffic_Vehicle.py
# 【最終重構版】: 重構為單純的車輛狀態資料容器

class Vehicle:
    """
    代表一個在 SUMO 模擬中的車輛實體。
    在主模擬腳本 (如 main_world_sim.py) 中，此類別被用作一個簡單的資料容器，
    以追蹤每輛車的兩個關鍵狀態：
    - physicalComputerMapping: 該車輛被分配到哪個實體電腦 (OBC) 上運行。
    - last_publish_step: 該車輛上次發布其狀態數據的模擬步長。
    """
    def __init__(self, veh_id):
        """
        初始化 Vehicle 物件。

        Args:
            veh_id (str): 車輛的唯一 ID。
        """
        self.veh_id = veh_id
        
        self._last_publish_step = 0
        self._physicalComputerMapping = None
    
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