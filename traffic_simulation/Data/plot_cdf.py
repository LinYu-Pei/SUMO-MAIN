import re
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict
import sys

# --- 【教授新增】PID 與其對應名稱的字典 ---
# 在這裡定義你想要的圖例標籤
PID_LABELS = {
    1584283: "SUMO",
    3350478: "OBU",
    3901667: "Cloud Server",
}

def parse_pidstat_log(log_file_path):
    """
    解析 pidstat 的日誌檔案，為每個 PID 提取 %CPU 數據。
    """
    cpu_data = defaultdict(list)
    line_regex = re.compile(r"^\S+\s+\d+\s+(\d+)\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+[\d\.]+\s+([\d\.]+)")

    print(f"Reading log file: {log_file_path}...")
    try:
        with open(log_file_path, 'r') as f:
            for line in f:
                if "PID" in line or line.strip() == "" or line.startswith("Linux"):
                    continue
                
                match = line_regex.search(line)
                if match:
                    pid = int(match.group(1))
                    cpu_percent = float(match.group(2))
                    cpu_data[pid].append(cpu_percent)
    except FileNotFoundError:
        print(f"Error: File not found at '{log_file_path}'. Please check the name and path.")
        sys.exit(1)
        
    print("File parsed successfully!")
    for pid, readings in cpu_data.items():
        # 使用我們定義的字典來顯示名稱
        label_name = PID_LABELS.get(pid, f"Unknown PID {pid}")
        print(f"  - {label_name} (PID {pid}): Collected {len(readings)} data points.")
        
    return cpu_data

def plot_cdf(data_dict):
    """
    接收解析後的數據字典，並繪製所有 PID 的 CPU 使用率 CDF 圖。
    """
    if not data_dict:
        print("No data available for plotting.")
        return

    plt.style.use('seaborn-v0_8-darkgrid')
    fig, ax = plt.subplots(figsize=(12, 8))

    print("\nCalculating and plotting CDF...")
    for pid, cpu_readings in data_dict.items():
        sorted_data = np.sort(cpu_readings)
        y_cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)
        
        # --- 【教授修改】使用字典中的名稱作為圖例標籤 ---
        # .get() 方法可以在字典中找不到 PID 時，提供一個預設值
        label_name = PID_LABELS.get(pid, f'PID {pid}')
        ax.plot(sorted_data, y_cdf, marker='.', linestyle='none', ms=4, label=label_name)

    # --- 所有標籤均為英文 ---
    ax.set_title('CDF of CPU Utilization by Process', fontsize=16)
    ax.set_xlabel('CPU Utilization (%)', fontsize=12)
    ax.set_ylabel('Cumulative Probability', fontsize=12)
    ax.legend(title="Process Name", fontsize=10)
    
    ax.set_xlim(left=0)
    ax.set_ylim(0, 1.05)
    ax.grid(True, which='both', linestyle='--', linewidth=0.5)
    
    print("Plotting complete!")
    plt.show()

if __name__ == '__main__':
    LOG_FILE = 'full_system_cpu.log'
    
    # 步驟 1: 解析日誌
    parsed_data = parse_pidstat_log(LOG_FILE)
    
    # 步驟 2: 繪製圖表
    plot_cdf(parsed_data)