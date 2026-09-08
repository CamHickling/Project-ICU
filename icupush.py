import json
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

# Load credentials from .env
current_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=current_dir / ".env")

ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID")
API_KEY = os.getenv("INTERVALS_API_KEY")

if not ATHLETE_ID or not API_KEY:
    raise ValueError("Missing INTERVALS_ATHLETE_ID or INTERVALS_API_KEY in .env")

BASE_URL = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}"

def push_workout_to_intervals(workout: dict) -> dict:
    """
    Push a single planned workout event to the Intervals.icu calendar.
    """
    endpoint = f"{BASE_URL}/events"
    
    # Intervals.icu parses 'description' automatically to calculate load & zones
    payload = {
        "category": workout.get("category", "WORKOUT"),
        "type": workout.get("type", "Ride"),
        "name": workout.get("name", "Planned Workout"),
        "start_date_local": workout.get("start_date_local"),
        "description": workout.get("description", ""),
        "moving_time": workout.get("moving_time"),       # optional: duration in seconds
        "target": workout.get("target", "POWER"),        # POWER, HR, or PACE
    }
    
    # Clean out None values
    payload = {k: v for k, v in payload.items() if v is not None}
    
    response = requests.post(
        endpoint,
        auth=("API_KEY", API_KEY),
        json=payload
    )
    
    if response.status_code not in (200, 201):
        print(f"Failed to post '{workout.get('name')}': {response.status_code} - {response.text}")
        return None
        
    res_data = response.json()
    print(f"Created '{res_data.get('name')}' on {res_data.get('start_date_local')} (Event ID: {res_data.get('id')})")
    return res_data

def push_workout_plan(plan: list):
    """
    Iterate through a workout list and push each to the calendar.
    """
    created_events = []
    for item in plan:
        res = push_workout_to_intervals(item)
        if res:
            created_events.append(res)
    print(f"\nUploaded {len(created_events)}/{len(plan)} workouts successfully.")
    return created_events

if __name__ == "__main__":
    # Example training block data structure
    sample_plan = [
        {
            "name": "VO2 Max 4x4m",
            "type": "Ride",
            "start_date_local": "2026-09-15T09:00:00",
            "target": "POWER",
            "description": (
                "Warm Up\n"
                "- 15m 60%\n\n"
                "Main Set 4x\n"
                "- 4m 115%\n"
                "- 3m 50%\n\n"
                "Cool Down\n"
                "- 10m 55%"
            )
        },
        {
            "name": "Mid-Week Endurance",
            "type": "Ride",
            "start_date_local": "2026-09-17T07:30:00",
            "target": "POWER",
            "description": (
                "Steady Aerobic Base\n"
                "- 90m 68%"
            )
        },
        {
            "name": "Threshold 3x10m",
            "type": "Ride",
            "start_date_local": "2026-09-19T10:00:00",
            "target": "POWER",
            "description": (
                "Warm Up\n"
                "- 20m 60-75%\n\n"
                "Main Set 3x\n"
                "- 10m 98%\n"
                "- 5m 55%\n\n"
                "Cool Down\n"
                "- 15m 50%"
            )
        }
    ]

    push_workout_plan(sample_plan)