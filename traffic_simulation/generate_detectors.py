import xml.etree.ElementTree as ET
import os
from xml.dom import minidom

# --- 1. 參數設定區 ---
NET_FILE = "new_osm.net.xml"
OUTPUT_FILE = "detectors.add.xml"
DETECTOR_MAX_LENGTH = 100.0 
DETECTOR_FREQ = "25"
# 新增一個參數，用來指定所有偵測器的輸出檔案
DETECTOR_OUTPUT_FILE = "detector_output.xml" 

def generate_detectors():
    """
    主函式：讀取SUMO路網，並自動生成偵測器設定檔。
    (已修正版本：加入了必要的 'file' 屬性)
    """
    print(f"--- 開始執行偵測器生成腳本 (已修正 file 屬性問題) ---")
    
    if not os.path.exists(NET_FILE):
        print(f"錯誤：找不到路網檔案 '{NET_FILE}'！")
        return

    print(f"正在讀取並解析路網: {NET_FILE}...")
    tree = ET.parse(NET_FILE)
    root = tree.getroot()

    detector_elements = []
    lane_count = 0
    detector_count = 0

    for lane in root.findall(".//lane"):
        lane_count += 1
        lane_id = lane.get("id")
        lane_length = float(lane.get("length"))

        if lane_id.startswith(":"):
            continue
            
        detector_pos = 0.0
        detector_length = 0.0

        if lane_length >= DETECTOR_MAX_LENGTH:
            detector_length = DETECTOR_MAX_LENGTH
            detector_pos = lane_length - DETECTOR_MAX_LENGTH
        else:
            detector_length = lane_length
            detector_pos = 0
        
        if detector_length <= 0.1:
            continue
            
        detector_id = f"det_{lane_id}"
        
        # --- FIX START ---
        # 在這裡為每一個偵測器都加上 "file" 屬性
        det_elem = ET.Element("laneAreaDetector", {
            "id": detector_id,
            "lane": lane_id,
            "pos": f"{detector_pos:.2f}",
            "length": f"{detector_length:.2f}",
            "freq": DETECTOR_FREQ,
            "file": DETECTOR_OUTPUT_FILE  # 加上這一行！
        })
        # --- FIX END ---
        
        detector_elements.append(det_elem)
        detector_count += 1

    print(f"路網解析完成。總共掃描了 {lane_count} 條車道。")
    print(f"根據你的規則，成功為 {detector_count} 條車道生成了偵測器。")

    additional_root = ET.Element("additional")
    for elem in detector_elements:
        additional_root.append(elem)
        
    xml_str = ET.tostring(additional_root, 'utf-8')
    pretty_xml_str = minidom.parseString(xml_str).toprettyxml(indent="    ")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(pretty_xml_str)

    print(f"偵測器檔案已成功寫入至: {OUTPUT_FILE}")
    print(f"--- 腳本執行完畢 ---")

if __name__ == "__main__":
    generate_detectors()