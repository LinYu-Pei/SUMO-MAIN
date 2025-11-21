import re
import os
import pandas as pd
import numpy as np

# ---              使用者設定區 (USER CONFIGURATION)              ---
LOG_FILES_CONFIG = {
    'simulation_x.log': 'Scenario: 1.0X',
    'simulation_x1.5.log': 'Scenario: 1.5X',
    'simulation_x2.log': 'Scenario: 2.0X'
}
# ---          腳本核心邏輯區 (無需修改)          ---

def parse_log_file_for_per_vehicle_cost(filepath: str) -> pd.DataFrame:
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
        r"步驟 (?P<step_num>\d+):.*?"
        r"效能剖析 \(處理 (?P<processed_vehicles>[\d,]+) 輛車\):.*?"
        r"T0 .*?\(平均/輛: (?P<T0_avg_ms>[\d.]+) 毫秒\).*?"
        r"T1 .*?\(平均/輛: (?P<T1_avg_ms>[\d.]+) 毫秒\).*?"
        r"T2 .*?\(平均/輛: (?P<T2_avg_ms>[\d.]+) 毫秒\).*?"
        r"T3 .*?\(平均/輛: (?P<T3_avg_ms>[\d.]+) 毫秒\).*?"
        r"T_Overhead .*?:\s+(?P<T_Overhead_s>[\d.]+) 秒",
        re.DOTALL
    )
    all_data = [
        {k: float(v.replace(',', '')) for k, v in match.groupdict().items()}
        for match in pattern.finditer(content)
    ]
    if not all_data:
        print(f"⚠️ 警告：在 '{filepath}' 中找不到有效的效能數據區塊。")
        return None
    print(f"✅ 成功從 '{filepath}' 解析出 {len(all_data)} 筆數據。")
    df = pd.DataFrame(all_data)
    df['Overhead_per_step_ms'] = df['T_Overhead_s'] * 1000
    return df

def generate_hybrid_latex_table(data_dict: dict):
    """產生並印出學術風格的混合統計 LaTeX 表格"""
    
    # 建立一個空的 DataFrame 來儲存結果
    scenarios = list(LOG_FILES_CONFIG.values())
    metrics_info = {
        'T0 Avg. Time per Veh. (ms)\\footnotemark': 'T0_avg_ms',
        'T1 Avg. Time per Veh. (ms)': 'T1_avg_ms',
        'T2 Avg. Time per Veh. (ms)': 'T2_avg_ms',
        'T3 Avg. Time per Veh. (ms)': 'T3_avg_ms',
        'Overhead per Step (ms)': 'Overhead_per_step_ms'
    }
    
    lines = []
    
    for display_name, col_name in metrics_info.items():
        row_cells = [display_name]
        sub_row_cells = [''] # 第二行的 metric 欄位為空

        for filepath, label in LOG_FILES_CONFIG.items():
            df = data_dict.get(filepath)
            if df is not None and not df.empty:
                data_series = df[col_name].dropna()
                
                # 對 T0 使用 Median/IQR，其他使用 Mean/Std Dev
                if "T0" in display_name:
                    median = data_series.median()
                    q1 = data_series.quantile(0.25)
                    q3 = data_series.quantile(0.75)
                    row_cells.append(f"{median:.2f}  [{q1:.2f} – {q3:.2f}]")
                    sub_row_cells.append('') # T0 第二行為空
                else:
                    mean_val = data_series.mean()
                    std_val = data_series.std()
                    row_cells.append(f"{mean_val:.2f}")
                    sub_row_cells.append(f"\\small{{(σ = {std_val:.2f})}}")

            else:
                row_cells.append("N/A")
                sub_row_cells.append("")
        
        lines.append(" & ".join(row_cells) + " \\\\")
        # 只有非 T0 指標才需要第二行（標準差）
        if "T0" not in display_name and any(cell for cell in sub_row_cells[1:]):
             lines.append(" & ".join(sub_row_cells) + " \\\\")
        
        # 在每個指標塊後增加間距
        lines.append("\\addlinespace")

    # 移除最後一個多餘的 \addlinespace
    if lines and lines[-1] == "\\addlinespace":
        lines.pop()

    # --- 組裝完整的 LaTeX 程式碼 ---
    latex_code = f"""
% 請確保您的 LaTeX 文件開頭 (Preamble) 包含了以下套件
% \\usepackage{{booktabs}}
% \\usepackage{{caption}}

\\begin{{table}}[h!]
\\centering
\\caption{{Component Performance Summary -- Hybrid Statistics (n={len(next(iter(data_dict.values())))} for each scenario)}}
\\label{{tab:hybrid_stats}}
\\begin{{tabular}}{{lccc}}
\\toprule
\\textbf{{Metric}} & \\textbf{{{scenarios[0]}}} & \\textbf{{{scenarios[1]}}} & \\textbf{{{scenarios[2]}}} \\\\
\\midrule
""" + "\n".join(lines) + """
\\bottomrule
\\end{{tabular}}
\\footnotetext{{For T0, values are presented as: \\textbf{{Median [25th percentile – 75th percentile]}}. This robust metric is used due to the high volatility caused by simulation overhead, which makes the mean and standard deviation misleading. For all other metrics, values are presented as: \\textbf{{Mean (σ = Standard Deviation)}}.}}
\\end{{table}}
"""
    print("\n--- LaTeX Code for Hybrid Statistics Table ---")
    print(latex_code)


def main():
    """主執行函式"""
    all_data_frames = {fp: parse_log_file_for_per_vehicle_cost(fp) for fp in LOG_FILES_CONFIG.keys()}
    
    if all(df is None for df in all_data_frames.values()):
        print("\n所有檔案都無法成功讀取或解析，程式即將結束。")
        return
        
    generate_hybrid_latex_table(all_data_frames)

if __name__ == '__main__':
    main()