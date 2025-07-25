# 檔名: computing.py (計算核心 D)
# 功能: 接收來自 controller.py 的參數，使用 sumolib 的 Dijkstra 演算法進行專業的路線規劃。

import os
import sys

# --- SUMO 環境設定 ---
# 確保 Python 找得到 sumolib 模組
if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    # 如果找不到 SUMO_HOME，程式無法運作，直接退出
    sys.exit("please declare environment variable 'SUMO_HOME'")
import sumolib

class Computing:
    """
    計算核心類別：使用 sumolib 進行專業的路線規劃。
    """
    def __init__(self, sumo_net_object):
        """
        在物件被建立時，就先把地圖檔讀取進來並解析，以備後用。
        這個一次性的讀取可以大大提高後續規劃的效率。
        """
        
        try:
            # 使用 sumolib 讀取路網檔案
            self.net = sumo_net_object
            print("[D] 準備好每台車出場都有地圖。")
        except Exception as e:
            # 如果讀取地圖失敗，這是嚴重錯誤，直接終止程式
            print(f"[D] [嚴重錯誤] 讀取地圖檔案失敗: {e}")
            sys.exit(1)

    def plan_change_lane(self, veh_id: str, lane_index: int, duration: int) -> dict:
        """
        規劃一個標準格式的「換道行動指令書」。
        這個函式相對單純，主要是將參數打包成標準字典格式。
        """
        print(f"    -> [D] 正在為 {veh_id} 規劃換道...")
        return {
            "type": "change_lane",
            "veh_id": veh_id,
            "lane_index": lane_index,
            "duration": duration
        }

    def plan_change_edge(self, veh_id: str, current_edge: str, target_edge: str, final_destination: str) -> dict | None:
        """
        使用 Dijkstra 演算法規劃一條從「當前 -> 指定途經點 -> 原終點」的無縫新路線。
        這是本系統最核心的計算邏輯。
        """
        # --- 日誌優化：清楚顯示規劃的起點、途經點和終點 ---
        print(f"    -> [D] 正在為 {veh_id} 規劃智慧銜接路線...")
        print(f"         - 當前路段: {current_edge}")
        print(f"         - 途經路段: {target_edge}")
        print(f"         - 原始終點: {final_destination}")
        
        try:   
            # --- 第一段：從「當前位置」到「目標途經點」---
            # 使用 self.net.getShortestPath 這個內建的 Dijkstra 演算法來找最短路徑
            path_to_target, _ = self.net.getShortestPath(
                self.net.getEdge(current_edge),
                self.net.getEdge(target_edge)
            )
            # 如果找不到路徑，就回報錯誤並返回 None
            if not path_to_target:
                print(f"         [錯誤] 找不到從「當前」到「途經」的路徑。")
                return None

            # --- 第二段：從「目標途經點」到「原始終點」---
            path_to_final, _ = self.net.getShortestPath(
                self.net.getEdge(target_edge),
                self.net.getEdge(final_destination)
            )
            if not path_to_final:
                print(f"         [錯誤] 找不到從「途經」到「終點」的路徑。")
                return None

            # --- 組合兩段路徑 ---
            # 將路徑物件轉換成路段 ID 的列表
            part1_edges = [edge.getID() for edge in path_to_target]
            # 第二段路徑要去掉第一個元素，因為它就是 target_edge，會跟第一段的結尾重複
            part2_edges = [edge.getID() for edge in path_to_final][1:]
            
            # 將兩段路徑列表合併成一條完整的無縫新路線
            complete_new_route = part1_edges + part2_edges
            
            # --- 日誌優化：只顯示摘要，不顯示完整藍圖 ---
            print(f"         [成功] 規劃完成！新路線總共包含 {len(complete_new_route)} 個路段。")

            # 回傳標準格式的「換路行動指令書」
            return {
                "type": "change_route",
                "veh_id": veh_id,
                "edge_list": complete_new_route
            }
        except Exception as e:
            # 捕捉可能發生的任何錯誤，例如 getEdge 時找不到路段 ID
            print(f"         [錯誤] 規劃路線時發生未知錯誤: {e}")
            return None
