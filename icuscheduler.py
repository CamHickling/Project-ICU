from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import requests
import pandas as pd
from dotenv import load_dotenv

# ==========================================
# CONFIGURATION
# ==========================================
current_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=current_dir / "intervals.env")

ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID")
API_KEY = os.getenv("INTERVALS_API_KEY")

CSV_FILE = current_dir / "intervals_events_processed.csv"
BASE_URL = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}"

# ==========================================
# SCHEDULING PARAMETERS
# ==========================================
# Target block starts next Monday
TODAY = datetime.now().date()
DAYS_UNTIL_MONDAY = (7 - TODAY.weekday()) % 7 or 7
BLOCK_START_DATE = TODAY + timedelta(days=DAYS_UNTIL_MONDAY)
NUM_WEEKS = 8

def load_historical_data(filepath: Path) -> pd.DataFrame:
    """Load and prepare historical CSV data."""
    if not filepath.exists():
        raise FileNotFoundError(f"Cannot find {filepath}. Run icufetch.py first.")
    
    df = pd.read_csv(filepath)
    df["start_date_local"] = pd.to_datetime(df["start_date_local"])
    df["date"] = df["start_date_local"].dt.date
    df["day_of_week"] = df["start_date_local"].dt.dayofweek
    return df

def extract_base_template(df: pd.DataFrame, target_start: datetime.date, num_weeks: int = 8) -> pd.DataFrame:
    """
    Extract the exact 8-week block from 52 weeks (1 year) ago,
    aligned to start on Monday.
    """
    # 52 weeks ago
    last_year_start = target_start - timedelta(weeks=52)
    last_year_end = last_year_start + timedelta(weeks=num_weeks)
    
    mask = (
        (df["date"] >= last_year_start) & 
        (df["date"] < last_year_end) & 
        (df["category"].isin(["ACTIVITY", "WORKOUT"]))
    )
    historical_block = df[mask].copy().sort_values("start_date_local")
    
    print(f"Extracted {len(historical_block)} sessions from {last_year_start} to {last_year_end}.")
    return historical_block, last_year_start

def generate_workout_description(name: str, duration_min: float, load: float, sport: str) -> str:
    """
    Build structured workout markup that Intervals.icu parses for zones and TSS.
    """
    dur = int(duration_min) if duration_min and duration_min > 0 else 60
    
    # Generic intelligent templates based on session duration & intensity
    intensity = (load / (dur / 60)) if dur > 0 else 50
    
    if sport == "Ride" or sport == "VirtualRide":
        if intensity > 85:  # High Intensity / Intervals
            return (
                f"High Intensity Session\n"
                f"- 15m 60%\n"
                f"Main Set 4x\n"
                f"- 4m 110%\n"
                f"- 3m 50%\n"
                f"Cool Down\n"
                f"- 10m 55%"
            )
        elif intensity > 65:  # Sweet Spot / Tempo
            return (
                f"Tempo / Sweet Spot Work\n"
                f"- 15m 60%\n"
                f"- {max(20, dur - 30)}m 85%\n"
                f"- 15m 55%"
            )
        else:  # Aerobic Endurance / Recovery
            return (
                f"Aerobic Endurance Ride\n"
                f"- {dur}m 65%"
            )
    elif sport == "Run":
        return f"Aerobic Run\n- {dur}m Pace: Zone 2"
    elif sport == "WeightTraining":
        return "Strength & Mobility Routine\n- Full body compound & core stability"
    else:
        return f"{name}\n- Planned duration: {dur} min"

def build_new_schedule(historical_block: pd.DataFrame, last_year_start: datetime.date, target_start: datetime.date, mode: str = "progressive") -> list:
    """
    Maps historical dates to new block dates and applies periodization multipliers.
    """
    new_plan = []
    
    # 3:1 periodization multipliers for an 8-week block:
    # W1: 1.0x, W2: 1.05x, W3: 1.10x, W4 (Deload): 0.65x
    # W5: 1.08x, W6: 1.14x, W7: 1.20x, W8 (Deload): 0.70x
    periodization_multipliers = [1.00, 1.05, 1.10, 0.65, 1.08, 1.14, 1.20, 0.70]

    for _, row in historical_block.iterrows():
        orig_date = row["date"]
        days_offset = (orig_date - last_year_start).days
        week_idx = min(days_offset // 7, NUM_WEEKS - 1)
        
        new_date = target_start + timedelta(days=days_offset)
        
        mult = periodization_multipliers[week_idx] if mode == "progressive" else 1.0
        
        adj_load = round((row["load"] or 50) * mult, 1)
        adj_duration = round((row["moving_time_min"] or 60) * (mult if mult < 1.0 else 1.0 + (mult - 1.0) * 0.5), 1)
        
        desc = generate_workout_description(row["name"], adj_duration, adj_load, row["type"])

        new_plan.append({
            "name": row["name"] or f"{row['type']} Session",
            "type": row["type"],
            "category": "WORKOUT",
            "start_date_local": f"{new_date}T08:00:00",
            "target": "POWER" if "Ride" in str(row["type"]) else "HR",
            "planned_load": adj_load,
            "planned_duration_min": adj_duration,
            "description": desc,
            "week_num": week_idx + 1
        })
        
    return new_plan

def push_to_intervals(plan: list):
    """POST plan items to Intervals.icu calendar."""
    print(f"\nUploading {len(plan)} workouts to Intervals.icu...")
    uploaded = 0
    for session in plan:
        payload = {
            "category": session["category"],
            "type": session["type"],
            "name": session["name"],
            "start_date_local": session["start_date_local"],
            "description": session["description"],
            "target": session["target"],
        }
        res = requests.post(
            f"{BASE_URL}/events",
            auth=("API_KEY", API_KEY),
            json=payload
        )
        if res.status_code in (200, 201):
            uploaded += 1
            print(f"[{session['start_date_local'][:10]}] Scheduled: {session['name']}")
        else:
            print(f"Failed {session['start_date_local'][:10]}: {res.status_code} - {res.text}")
            
    print(f"\nCompleted: {uploaded}/{len(plan)} events pushed successfully.")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print(f"Planning 8-Week Training Block")
    print(f"Start Date: {BLOCK_START_DATE} | End Date: {BLOCK_START_DATE + timedelta(weeks=NUM_WEEKS)}")
    
    df = load_historical_data(CSV_FILE)
    historical_block, last_year_start = extract_base_template(df, BLOCK_START_DATE, NUM_WEEKS)
    
    if historical_block.empty:
        print(f"Warning: No activities found between {last_year_start} and {last_year_start + timedelta(weeks=NUM_WEEKS)}.")
        print("Check if you had recorded data for this period last year.")
        exit()

    # Generate progressive schedule
    scheduled_workouts = build_new_schedule(
        historical_block, 
        last_year_start, 
        BLOCK_START_DATE, 
        mode="progressive"
    )
    
    # Export draft to CSV for inspection
    plan_df = pd.DataFrame(scheduled_workouts)
    output_path = current_dir / "generated_2month_training_plan.csv"
    plan_df.to_csv(output_path, index=False)
    print(f"\nDraft schedule exported to: '{output_path.name}'")
    
    # Print Block Summary
    print("\n--- PROJECTED WEEKLY BREAKDOWN ---")
    summary = plan_df.groupby("week_num").agg(
        total_sessions=("name", "count"),
        total_load=("planned_load", "sum"),
        total_hours=("planned_duration_min", lambda m: round(m.sum() / 60, 1))
    ).reset_index()
    print(summary.to_string(index=False))

    # Safety Prompt before pushing to API
    print("\n" + "="*50)
    confirm = input("Would you like to push these events directly to your Intervals.icu calendar? (yes/no): ").strip().lower()
    if confirm in ("yes", "y"):
        push_to_intervals(scheduled_workouts)
    else:
        print("Skipped upload. You can review and tweak 'generated_2month_training_plan.csv' first.")