# 檔案名稱：test_libsumo.py

import sys
import os

print("--- 開始 libsumo 導入測試 ---")

# 1. 打印原始的 sys.path，看看 Python 預設會去哪裡找東西
print("\n[原始搜尋路徑 sys.path]:")
for p in sys.path:
    print(f" - {p}")

# 2. 強制加入 SUMO tools 的路徑
# 我們已經確認 SUMO tools 的正確路徑是 /usr/share/sumo/tools
SUMO_TOOLS_PATH = '/usr/share/sumo/tools'

# 家教註解 (核心修改): 我們這次不用 .append() 加到結尾，
# 而是用 .insert(0, ...) 強制把我們的路徑加到「第一順位」，
# 讓 Python 優先從這裡尋找，避免其他路徑的干擾。
if SUMO_TOOLS_PATH not in sys.path:
    sys.path.insert(0, SUMO_TOOLS_PATH)
    print(f"\n[+] 已將 '{SUMO_TOOLS_PATH}' 加入到搜尋路徑的【最頂端】。")
else:
    print(f"\n[*] '{SUMO_TOOLS_PATH}' 已經在搜尋路徑中。")

# 3. 再次打印 sys.path，確認修改成功
print("\n[修改後的搜尋路徑 sys.path]:")
for p in sys.path:
    print(f" - {p}")

# 4. 進行最終測試
try:
    print("\n>>> 正在嘗試 `import libsumo`...")
    import libsumo
    print(">>> 🟢 成功！`libsumo` 導入成功！")
    
    # 順便測試 traci，因為 libsumo 會用到它
    print("\n>>> 正在嘗試 `import traci`...")
    import traci
    print(">>> 🟢 成功！`traci` 導入成功！")

except Exception as e:
    print(f"\n>>> 🔴 失敗！導入時發生錯誤:")
    # 印出詳細的錯誤追蹤訊息
    import traceback
    traceback.print_exc()

print("\n--- 測試結束 ---")