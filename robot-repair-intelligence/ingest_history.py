import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from hindsight_client import Hindsight


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("HINDSIGHT_API_KEY")
BASE_URL = os.getenv(
    "HINDSIGHT_BASE_URL",
    "https://api.hindsight.vectorize.io",
)
BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "robot-maintenance")

DATA_FILE = Path("data/repair_history.json")


# ---------------------------------------------------------
# Validation
# ---------------------------------------------------------

def validate_record(record: dict, index: int) -> None:
    required_fields = [
        "case_id",
        "date",
        "robot_id",
        "robot_model",
        "fault_code",
        "fault_description",
        "symptoms",
        "operating_conditions",
        "technician",
        "diagnostic_action",
        "repair_action",
        "outcome",
        "downtime_hours",
        "technician_notes",
        "parts_involved",
        "synthetic",
    ]

    missing = [field for field in required_fields if field not in record]

    if missing:
        raise ValueError(
            f"Record {index + 1} ({record.get('case_id', 'unknown')}) "
            f"is missing fields: {missing}"
        )

    if record["robot_model"] != "AeroTech AT-600":
        raise ValueError(
            f"{record['case_id']}: unexpected robot model"
        )

    if record["synthetic"] is not True:
        raise ValueError(
            f"{record['case_id']}: synthetic must be true"
        )


def load_dataset() -> list[dict]:
    if not DATA_FILE.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATA_FILE.resolve()}"
        )

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in {DATA_FILE}: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise ValueError("repair_history.json must contain a JSON array")

    case_ids = set()

    for index, record in enumerate(data):
        if not isinstance(record, dict):
            raise ValueError(
                f"Record {index + 1} is not a JSON object"
            )

        validate_record(record, index)

        case_id = record["case_id"]

        if case_id in case_ids:
            raise ValueError(f"Duplicate case_id: {case_id}")

        case_ids.add(case_id)

    return data


# ---------------------------------------------------------
# Convert repair case → memory
# ---------------------------------------------------------

def build_memory_content(record: dict) -> str:
    conditions = record["operating_conditions"]

    symptoms = "\n".join(
        f"- {symptom}"
        for symptom in record["symptoms"]
    )

    parts = ", ".join(record["parts_involved"])

    recurrence = record.get("time_to_recurrence_hours")

    if recurrence is None:
        recurrence_text = "No recurrence documented during verification."
    else:
        recurrence_text = (
            f"Fault recurred after approximately "
            f"{recurrence} operating hours."
        )

    return f"""
Maintenance case {record['case_id']}.

Date: {record['date']}
Robot: {record['robot_id']}
Model: {record['robot_model']}
Fault code: {record['fault_code']}

Fault description:
{record['fault_description']}

Symptoms:
{symptoms}

Operating conditions:
- Ambient temperature: {conditions.get('ambient_temperature_c')} C
- Load: {conditions.get('load_percent')}%
- Runtime: {conditions.get('runtime_hours')} hours
- Cycle count: {conditions.get('cycle_count')}

Technician:
{record['technician']}

Diagnostic action:
{record['diagnostic_action']}

Repair action:
{record['repair_action']}

Outcome:
{record['outcome']}

Recurrence:
{recurrence_text}

Downtime:
{record['downtime_hours']} hours

Technician notes:
{record['technician_notes']}

Parts involved:
{parts}

This is a completely synthetic maintenance record for the fictional AeroTech AT-600.
""".strip()


# ---------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------

def main() -> int:
    if not API_KEY:
        print("ERROR: HINDSIGHT_API_KEY is missing from .env")
        return 1

    records = load_dataset()

    print(f"Loaded {len(records)} repair records.")
    print(f"Target Hindsight bank: {BANK_ID}")
    print()

    client = Hindsight(
        base_url=BASE_URL,
        api_key=API_KEY,
    )

    successful = 0

    try:
        for number, record in enumerate(records, start=1):
            content = build_memory_content(record)

            metadata = {
                "case_id": str(record["case_id"]),
                "robot_id": str(record["robot_id"]),
                "robot_model": str(record["robot_model"]),
                "fault_code": str(record["fault_code"]),
                "outcome": str(record["outcome"]),
                "date": str(record["date"]),
                "synthetic": "true",
            }

            tags = [
                "robot-maintenance",
                record["fault_code"],
                record["outcome"],
                record["robot_id"],
            ]

            print(
                f"[{number:02d}/{len(records)}] "
                f"Retaining {record['case_id']} "
                f"| {record['fault_code']} "
                f"| {record['outcome']}"
            )

            response = client.retain(
                bank_id=BANK_ID,
                content=content,
                metadata=metadata,
                tags=tags,
            )

            successful += 1

        print()
        print("=" * 60)
        print("INGESTION COMPLETE")
        print("=" * 60)
        print(f"Records processed successfully: {successful}")
        print(f"Hindsight bank: {BANK_ID}")

    except Exception as exc:
        print()
        print("=" * 60)
        print("INGESTION FAILED")
        print("=" * 60)
        print(f"Processed before failure: {successful}")
        print(f"Error type: {type(exc).__name__}")
        print(f"Error: {exc}")
        return 1

    finally:
        close_method = getattr(client, "close", None)

        if callable(close_method):
            close_method()

    return 0


if __name__ == "__main__":
    sys.exit(main())