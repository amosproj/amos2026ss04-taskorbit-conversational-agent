import json

dashboard_path = 'infra/grafana/provisioning/dashboards/benchmark.json'

with open(dashboard_path, 'r') as f:
    dashboard = json.load(f)

panels = dashboard.get('panels', [])
if len(panels) < 2:
    print("Error: Could not find panels.")
    exit(1)

# Extract a metric panel template (e.g. the first one)
template_panel = None
logs_panel = None

for p in panels:
    if p.get('type') == 'timeseries':
        template_panel = p
    elif p.get('type') == 'logs':
        logs_panel = p

if not template_panel or not logs_panel:
    print("Error: Missing required panel types.")
    exit(1)

metrics = [
    {"title": "Total E2E Latency", "field": "latency_ms_cumulative_total", "short": "Total E2E"},
    {"title": "STT Latency", "field": "latency_ms_stt_processing", "short": "STT"},
    {"title": "LLM Latency", "field": "latency_ms_llm_call", "short": "LLM"},
    {"title": "TTS Latency", "field": "latency_ms_tts_synthesis", "short": "TTS"},
    {"title": "LLM API Latency (Network)", "field": "latency_ms_llm_api", "short": "LLM API"},
    {"title": "Tool Call Latency", "field": "latency_ms_tool_call", "short": "Tool Call"},
    {"title": "Voice Turn Latency", "field": "latency_ms_voice_turn", "short": "Voice Turn"}
]

grid_positions = [
    {"h": 8, "w": 8, "x": 0, "y": 0},
    {"h": 8, "w": 8, "x": 8, "y": 0},
    {"h": 8, "w": 8, "x": 16, "y": 0},
    {"h": 8, "w": 8, "x": 0, "y": 8},
    {"h": 8, "w": 8, "x": 8, "y": 8},
    {"h": 8, "w": 8, "x": 16, "y": 8},
    {"h": 16, "w": 8, "x": 0, "y": 16}  # Taller Voice Turn panel to match Logs panel height
]

new_panels = []
for i, metric in enumerate(metrics):
    new_panel = json.loads(json.dumps(template_panel))
    new_panel['id'] = i + 20
    new_panel['title'] = metric['title']
    new_panel['gridPos'] = grid_positions[i]
    
    # Update query
    target = new_panel['targets'][0]
    target['expr'] = f'avg by (config_label) (avg_over_time({{job="benchmark"}} | json | unwrap {metric["field"]} | __error__="" [$__interval]))'
    target['legendFormat'] = f"{metric['short']} - {{{{config_label}}}}"
    new_panel['targets'] = [target]
    
    new_panels.append(new_panel)

# Position Logs panel at the bottom right
logs_panel['gridPos'] = {"h": 16, "w": 16, "x": 8, "y": 16}

dashboard['panels'] = new_panels + [logs_panel]

with open(dashboard_path, 'w') as f:
    json.dump(dashboard, f, indent=2)

print("Successfully expanded dashboard to 7 metric panels + logs.")
