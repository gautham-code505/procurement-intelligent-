import json
import uuid
from datetime import datetime
from typing import List, Dict, Any

from core.domain.models import OperationalEvent
from core.services.coordination import AdaptiveCoordinationService

class DeterministicSimulator:
    def __init__(self, coordination_service: AdaptiveCoordinationService):
        self.coordination_service = coordination_service
        self.event_queue = []

    def load_scenario(self, scenario_file: str):
        with open(scenario_file, "r") as f:
            data = json.load(f)
            
        for ev in data.get("events", []):
            self.event_queue.append({
                "timestamp": datetime.fromisoformat(ev["timestamp"]),
                "source": ev.get("source", "SIMULATOR"),
                "event_type": ev["event_type"],
                "metadata": ev.get("metadata", {})
            })
            
        # Sort chronologically
        self.event_queue.sort(key=lambda x: x["timestamp"])

    def run(self):
        outputs = []
        for raw_event in self.event_queue:
            # Advance time to this event
            current_time = raw_event["timestamp"]
            
            event = OperationalEvent(
                event_id=f"SIM-{uuid.uuid4()}",
                timestamp=current_time,
                source=raw_event["source"],
                event_type=raw_event["event_type"],
                metadata=raw_event["metadata"]
            )
            
            # Process the event through the service
            self.coordination_service.process_event(event)
            
            # We can capture state or recommendation here if needed
            # For demonstration, we just execute.
            outputs.append(f"[{current_time}] Processed {event.event_type}")
            
        return outputs
