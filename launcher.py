import subprocess
import os
import sys

# 獲取當前腳本的絕對路徑，並以此為基礎構建其他腳本的路徑
current_dir = os.path.dirname(os.path.abspath(__file__))
normal_world_path = os.path.join(current_dir, 'traffic_simulation', 'normal_world.py')
disaster_world_path = os.path.join(current_dir, 'traffic_simulation', 'disaster_world.py')

print(f"啟動 normal_world.py: {normal_world_path}")
print(f"啟動 disaster_world.py: {disaster_world_path}")

# 使用 subprocess.Popen 在背景啟動兩個腳本
# 注意：這裡我們不等待它們完成，讓它們獨立運行
try:
    normal_process = subprocess.Popen([sys.executable, normal_world_path])
    disaster_process = subprocess.Popen([sys.executable, disaster_world_path])

    print("launcher.py 已啟動 normal_world.py 和 disaster_world.py。")
    print("請檢查各自的 SUMO GUI 視窗是否彈出。")
    print("您可以手動關閉 SUMO GUI 視窗來結束模擬。")

    # 為了讓 launcher 保持運行，直到子進程結束 (可選，如果希望 launcher 立即退出則不需要)
    # normal_process.wait()
    # disaster_process.wait()

except Exception as e:
    print(f"啟動腳本時發生錯誤: {e}")
