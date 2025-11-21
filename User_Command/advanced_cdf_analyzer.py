import re
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from statsmodels.nonparametric.smoothers_lowess import lowess

# ---              使用者設定區 (USER CONFIGURATION)              ---
# ---  你未來只需要修改這個區塊 ---

# 1. 設定要分析的日誌檔案，以及它們在圖例中顯示的名稱
LOG_FILES_CONFIG = {
    'simulation_x.log': 'Scenario: 1.0X',
    'simulation_x1.5.log': 'Scenario: 1.5X',
    'simulation_x2.log': 'Scenario: 2.0X'
}

# 2. 設定輸出的圖表的檔案名稱
OUTPUT_FILENAME = 'RTF_Filled_Trend_Chart.png'

# 3. 圖表 X 軸（車輛數）的最大值與刻度間隔
X_AXIS_VEHICLE_LIMIT = 5500
X_AXIS_TICK_INTERVAL = 250

# ---          腳本核心邏輯區 (無需修改)          ---

def parse_log_file(filepath: str) -> pd.DataFrame:
    """解析單一的日誌檔案，提取步長、車輛數、RTF。"""
    if not os.path.exists(filepath):
        print(f"❌ 錯誤：找不到日誌檔案 '{filepath}'，已跳過。")
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"❌ 錯誤：無法讀取檔案 '{filepath}'。原因: {e}")
        return None
    
    pattern = re.compile(
        r"步驟 (?P<step_num>\d+): 當前車輛數 (?P<current_vehicles>[\d,]+).*?瞬時RTF: (?P<rtf>[\d.]+)"
    )
    all_data = [
        {k: float(v.replace(',', '')) for k, v in match.groupdict().items()}
        for match in pattern.finditer(content)
    ]
    if not all_data:
        print(f"⚠️ 警告：在 '{filepath}' 中找不到有效的數據。")
        return None
    print(f"✅ 成功從 '{filepath}' 解析出 {len(all_data)} 筆數據。")
    return pd.DataFrame(all_data)


def generate_rtf_trend_plot(data_dict: dict, output_filename: str):
    """產生帶有填充區域和平均值標註的 RTF 平滑趨勢線圖"""
    plt.style.use('seaborn-v0_8-whitegrid')
    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
    colors = plt.cm.get_cmap('tab10', len(LOG_FILES_CONFIG))

    print("\n正在產生 RTF 趨勢圖...")
    for i, (filepath, label) in enumerate(LOG_FILES_CONFIG.items()):
        df = data_dict.get(filepath)
        if df is not None and not df.empty and len(df) > 5: # 至少需要幾個點才能平滑
            # 確保數據按車輛數排序
            df_sorted = df.sort_values('current_vehicles').dropna(subset=['current_vehicles', 'rtf'])
            
            # 使用 lowess 計算平滑曲線的 (x, y) 座標 (frac 越小線條越貼近原始數據)
            smoothed = lowess(df_sorted['rtf'], df_sorted['current_vehicles'], frac=0.4)
            x_smooth, y_smooth = smoothed[:, 0], smoothed[:, 1]
            
            # --- 繪製平滑曲線 ---
            ax.plot(x_smooth, y_smooth, label=label, color=colors(i), linewidth=3)
            
            # --- 繪製填充區域 ---
            ax.fill_between(x_smooth, y_smooth, color=colors(i), alpha=0.2)
            
            # --- 標註平均 RTF ---
            avg_rtf = df['rtf'].mean()
            last_x = x_smooth[-1]
            last_y = y_smooth[-1]
            
            ax.text(
                last_x + 50, # 在線條末端右側一點的位置
                last_y, 
                f"Avg: {avg_rtf:.2f}", # 標註文字內容
                color=colors(i),
                fontweight='bold',
                fontsize=12,
                verticalalignment='center' # 垂直置中對齊
            )
            
        elif df is not None:
             print(f"⚠️ 警告: '{filepath}' 的數據不足以繪製趨勢線，已跳過。")

    ax.set_title('RTF Trend vs. Total Vehicle Count', fontsize=18)
    ax.set_xlabel('Current Number of Vehicles in Simulation', fontsize=14)
    ax.set_ylabel('Instantaneous RTF (steps/sec)', fontsize=14)
    
    ax.set_xlim(0, X_AXIS_VEHICLE_LIMIT)
    ax.set_ylim(bottom=0)
    ax.set_xticks(np.arange(0, X_AXIS_VEHICLE_LIMIT + 1, X_AXIS_TICK_INTERVAL))
    
    plt.xticks(rotation=45)
    ax.legend(fontsize=12)
    fig.tight_layout()

    try:
        plt.savefig(output_filename)
        print(f"✅ 圖表已成功儲存至: {output_filename}")
    except Exception as e:
        print(f"❌ 錯誤：儲存圖表 '{output_filename}' 失敗。原因: {e}")
    plt.close(fig)


def main():
    """主執行函式"""
    all_data_frames = {fp: parse_log_file(fp) for fp in LOG_FILES_CONFIG.keys()}
    
    if all(df is None for df in all_data_frames.values()):
        print("\n所有檔案都無法成功讀取或解析，程式即將結束。")
        return
        
    generate_rtf_trend_plot(all_data_frames, OUTPUT_FILENAME)
    
    print("\n分析完成！")

if __name__ == '__main__':
    main()