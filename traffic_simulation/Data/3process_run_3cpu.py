import pandas as pd
import matplotlib.pyplot as plt
import re
import os

# --- 1. Data Preparation (Reading from file) ---
# Define the log file name to be read
log_filename = 'Vehcle_X2_3CPU_RUN_3Process.log'

# Check if the file exists
if not os.path.exists(log_filename):
    print(f"Error: Log file '{log_filename}' not found.")
    print("Please ensure the log file is in the same directory as this Python script, or provide the correct file path.")
    exit()

# Read the file content
try:
    with open(log_filename, 'r', encoding='utf-8') as f:
        log_data = f.read()
except Exception as e:
    print(f"An error occurred while reading the file: {e}")
    exit()

# --- 2. Data Parsing and Cleaning ---
# Define the mapping from CPU ID to process name.
cpu_map = {
    15: 'Backend',
    14: 'OBU',
    13: 'Main'
}

# Use regular expressions to extract valid data lines
lines = log_data.strip().split('\n')
data_lines = []
for line in lines:
    if re.match(r'^\d{2}時\d{2}分\d{2}秒', line) and 'python3' in line:
        line = line.replace('時', ':').replace('分', ':').replace('秒', '')
        data_lines.append(line)

if not data_lines:
    print("Error: No data rows matching the required format were found in the log file.")
    print("Please check the contents of the log file.")
    exit()
    
from io import StringIO
data_io = StringIO("\n".join(data_lines))
df = pd.read_csv(data_io, sep=r'\s+', header=None)

df = df.iloc[:, :9]
df.columns = ['Timestamp', 'UID', 'PID', '%usr', '%system', '%guest', '%wait', '%CPU', 'CPU']

# Convert data types to numeric
numeric_cols = ['%usr', '%system', '%guest', '%wait', '%CPU']
for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce')

df['CPU'] = pd.to_numeric(df['CPU'], errors='coerce')
df.dropna(inplace=True)
df['CPU'] = df['CPU'].astype(int)

# Create the ProcessName column based on the 'CPU' column
df['ProcessName'] = df['CPU'].map(cpu_map)

df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='%H:%M:%S')
start_time = df['Timestamp'].min()
df['Time_sec'] = (df['Timestamp'] - start_time).dt.total_seconds()


# --- 3. Plotting Charts ---

# Define consistent colors for the simplified view
colors = {
    'CPU Usage': '#1f77b4',         # Blue
    'I/O Wait': '#d62728'          # Red (to highlight)
}

# --- Chart 1: Overlapping Area Chart ---
fig1, axes = plt.subplots(3, 1, figsize=(15, 12), sharex=True)
fig1.suptitle('4,400-Vehicle Simulation CPU Usage', fontsize=20, y=0.98) # Increased y for spacing

for i, (cpu_id, name) in enumerate(cpu_map.items()):
    ax = axes[i]
    process_df = df[df['CPU'] == cpu_id].copy().sort_values('Time_sec')
    
    if process_df.empty:
        ax.text(0.5, 0.5, f'No data for CPU {cpu_id}', horizontalalignment='center', verticalalignment='center')
        ax.set_title(f'Process: {name} (on CPU {cpu_id})', fontsize=14)
        continue

    x = process_df['Time_sec']
    active_usage = process_df['%usr'] + process_df['%system']
    io_wait = process_df['%wait']
    
    ax.fill_between(x, active_usage, color=colors['CPU Usage'], label='CPU Usage', alpha=0.7)
    ax.fill_between(x, io_wait, color=colors['I/O Wait'], label='I/O Wait', alpha=0.6)
    
    ax.axhline(y=70, color='gold', linestyle='--', linewidth=2)
    
    ax.set_title(f'Process: {name} (on CPU {cpu_id})', fontsize=14)
    ax.set_ylabel('CPU Time (%)', fontsize=12)
    
    # MODIFICATION: Removed individual legends from subplots
    # ax.legend(loc='upper left') 
    
    ax.grid(True, linestyle='--', alpha=0.6)
    ax.set_ylim(0, 100)

axes[-1].set_xlabel('Execution Time (seconds)', fontsize=12)

# --- MODIFICATION START: Create a single, shared legend for the entire figure ---
handles, labels = axes[0].get_legend_handles_labels()
fig1.legend(handles, labels, loc='upper center', bbox_to_anchor=(0.5, 0.93), ncol=2, fontsize=12)
# --- MODIFICATION END ---

plt.tight_layout(rect=[0, 0, 1, 0.92]) # Adjust rect to prevent title/legend from overlapping
plt.show()


# --- Chart 2: Simplified Grouped Bar Chart ---
avg_df = df.groupby('ProcessName')[['%usr', '%system', '%wait']].mean().reindex(cpu_map.values())
plot_df = pd.DataFrame(index=avg_df.index)
plot_df['CPU Usage'] = avg_df['%usr'] + avg_df['%system']
plot_df['I/O Wait'] = avg_df['%wait']
reverse_cpu_map = {name: cpu for cpu, name in cpu_map.items()}
new_labels = [f"{name} (CPU {reverse_cpu_map[name]})" for name in plot_df.index]
plot_df.index = new_labels

fig2, ax2 = plt.subplots(figsize=(12, 8))
plot_df.plot(kind='bar', ax=ax2, color=[colors['CPU Usage'], colors['I/O Wait']], width=0.8, legend=False)
ax2.set_title('Average 4,400-Vehicle Simulation CPU Usage', fontsize=18)
ax2.set_ylabel('Average CPU Time (%)', fontsize=12)
ax2.set_xlabel('Process (on specific CPU Core)', fontsize=12)
ax2.tick_params(axis='x', rotation=0, labelsize=11, pad=5)
ax2.grid(axis='y', linestyle='--', alpha=0.7)

# We add the legend back here, but placed outside the plot
ax2.legend(title='CPU Time Category', bbox_to_anchor=(1.02, 1), loc='upper left', borderaxespad=0.)

for p in ax2.patches:
    if p.get_height() > 0.1:
        ax2.annotate(f"{p.get_height():.2f}", 
                       (p.get_x() + p.get_width() / 2., p.get_height()), 
                       ha='center', va='center', 
                       xytext=(0, 9), 
                       textcoords='offset points')
plt.tight_layout()
plt.show()

print("Chart generation complete.")