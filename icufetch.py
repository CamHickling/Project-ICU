from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import requests
import pandas as pd
from dotenv import load_dotenv

# ==========================================
# CREDENTIALS LOADER
# ==========================================
current_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=current_dir / "intervals.env")

ATHLETE_ID = os.getenv("INTERVALS_ATHLETE_ID")
API_KEY = os.getenv("INTERVALS_API_KEY")

if not ATHLETE_ID or not API_KEY:
    raise ValueError(
        f"Missing credentials in {current_dir / 'intervals.env'}. "
        "Ensure INTERVALS_ATHLETE_ID and INTERVALS_API_KEY are set."
    )

# ==========================================
# 2-YEAR DATE WINDOW (TODAY BACK TO -730 DAYS)
# ==========================================
END_DATE = datetime.now().date()
START_DATE = END_DATE - timedelta(days=730)
BASE_URL = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}"

def fetch_intervals_events(start_date: str, end_date: str) -> list:
    """Fetch calendar events (activities, planned workouts, notes)."""
    endpoint = f"{BASE_URL}/events"
    params = {"oldest": start_date, "newest": end_date}
    
    response = requests.get(
        endpoint,
        auth=("API_KEY", API_KEY),
        params=params
    )
    
    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch data: HTTP {response.status_code} - {response.text}"
        )
        
    return response.json()

def process_events_to_dataframe(events: list) -> pd.DataFrame:
    records = []
    for ev in events:
        # Load can appear under icu_training_load or load
        load_val = ev.get("icu_training_load")
        if load_val is None:
            load_val = ev.get("load", 0)

        # Duration: fallback moving_time -> elapsed_time
        duration_sec = ev.get("moving_time") or ev.get("elapsed_time") or 0

        records.append({
            "id": ev.get("id"),
            "name": ev.get("name"),
            "category": ev.get("category"),  # ACTIVITY (completed), WORKOUT (planned), NOTE
            "type": ev.get("type"),          # Ride, VirtualRide, Run, WeightTraining, etc.
            "start_date_local": ev.get("start_date_local"),
            "moving_time_min": round(duration_sec / 60, 1),
            "load": float(load_val) if load_val is not None else 0.0,
            "work_kj": ev.get("icu_joules", 0) / 1000 if ev.get("icu_joules") else None,
            "weighted_avg_watts": ev.get("icu_weighted_avg_watts"),
            "avg_watts": ev.get("icu_average_watts"),
            "avg_hr": ev.get("icu_average_hr"),
            "max_hr": ev.get("icu_max_hr"),
            "intensity": ev.get("icu_intensity"),
        })
        
    df = pd.DataFrame(records)
    if not df.empty:
        df["start_date_local"] = pd.to_datetime(df["start_date_local"])
        df["date"] = df["start_date_local"].dt.date
        df["day_name"] = df["start_date_local"].dt.day_name()
        df["day_of_week"] = df["start_date_local"].dt.dayofweek  # 0=Monday, 6=Sunday
        df["year_week"] = df["start_date_local"].dt.strftime("%Y-W%U")
    return df

def generate_schedule_summary(df: pd.DataFrame):
    # Include completed rides/runs (ACTIVITY) as well as scheduled WORKOUT sessions
    training = df[df["category"].isin(["ACTIVITY", "WORKOUT"])].copy()
    
    if training.empty:
        print("No activities or workouts found. Categories present:", df["category"].value_counts().to_dict())
        return

    print("\n--- ACTIVITY TYPES BREAKDOWN ---")
    print(training["type"].value_counts().to_string())

    print("\n--- TYPICAL DAY-OF-WEEK DISTRIBUTION (2-YEAR AVERAGE) ---")
    dow_summary = training.groupby(["day_of_week", "day_name"]).agg(
        total_sessions=("id", "count"),
        avg_load_per_session=("load", "mean"),
        avg_duration_min=("moving_time_min", "mean"),
        common_type=("type", lambda s: s.mode().iloc[0] if not s.empty else "N/A")
    ).reset_index()
    print(dow_summary.to_string(index=False))

    print("\n--- WEEKLY LOAD & VOLUME BENCHMARKS ---")
    weekly_summary = training.groupby("year_week").agg(
        weekly_load=("load", "sum"),
        weekly_hours=("moving_time_min", lambda m: round(m.sum() / 60, 1)),
        session_count=("id", "count")
    )
    # Filter out empty or near-zero weeks (e.g. offseason or illness) for true training averages
    active_weeks = weekly_summary[weekly_summary["weekly_hours"] > 1.0]

    print(f"Total Weeks Analyzed: {len(weekly_summary)} ({len(active_weeks)} active training weeks)")
    print(f"Average Weekly Load (TSS): {active_weeks['weekly_load'].mean():.1f}")
    print(f"Median Weekly Load (TSS): {active_weeks['weekly_load'].median():.1f}")
    print(f"Average Weekly Volume: {active_weeks['weekly_hours'].mean():.1f} hrs")
    print(f"Peak (90th percentile) Weekly Load: {active_weeks['weekly_load'].quantile(0.90):.1f}")
    print(f"Peak (90th percentile) Weekly Volume: {active_weeks['weekly_hours'].quantile(0.90):.1f} hrs")

if __name__ == "__main__":
    print(f"Querying Intervals.icu for athlete '{ATHLETE_ID}' from {START_DATE} to {END_DATE}...")
    events_data = fetch_intervals_events(str(START_DATE), str(END_DATE))
    print(f"Retrieved {len(events_data)} total entries.")
    
    df = process_events_to_dataframe(events_data)
    df.to_csv(current_dir / "intervals_events_processed.csv", index=False)
    print("Saved processed data to 'intervals_events_processed.csv'.")
    
    generate_schedule_summary(df)