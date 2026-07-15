import json
import os

dashboard_path = 'infra/grafana/provisioning/dashboards/benchmark.json'
with open(dashboard_path, 'r') as f:
    dashboard = json.load(f)

# Find the main panels
panels = dashboard.get('panels', [])
if len(panels) >= 2:
    latency_panel = panels[0]
    logs_panel = panels[1]
    
    targets = latency_panel.get('targets', [])
    if len(targets) == 4:
        # We have the 4 targets (Total, STT, LLM, TTS)
        # Create 4 separate panels
        titles = ["Total E2E Latency", "STT Latency", "LLM Latency", "TTS Latency"]
        grid_positions = [
            {"h": 8, "w": 6, "x": 0, "y": 0},
            {"h": 8, "w": 6, "x": 6, "y": 0},
            {"h": 8, "w": 6, "x": 0, "y": 8},
            {"h": 8, "w": 6, "x": 6, "y": 8}
        ]
        
        new_panels = []
        for i in range(4):
            # Deep copy the base panel structure
            new_panel = json.loads(json.dumps(latency_panel))
            new_panel['id'] = i + 10  # Ensure unique IDs
            new_panel['title'] = titles[i]
            new_panel['gridPos'] = grid_positions[i]
            
            # Keep only the specific target
            target = targets[i]
            target['refId'] = 'A' # Standardize refId to A for single query panels
            new_panel['targets'] = [target]
            
            new_panels.append(new_panel)
            
        # Update logs panel position to fit nicely beside the 2x2 grid
        logs_panel['gridPos'] = {"h": 16, "w": 12, "x": 12, "y": 0}
        
        # Assemble new panels list
        dashboard['panels'] = new_panels + [logs_panel]
        
        # Save back
        with open(dashboard_path, 'w') as f:
            json.dump(dashboard, f, indent=2)
        print("Successfully split dashboard panels.")
    else:
        print("Error: Expected 4 targets in the latency panel.")
else:
    print("Error: Could not find the expected panels.")
