import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("HINDSIGHT_API_KEY")
BASE_URL = os.getenv(
    "HINDSIGHT_BASE_URL",
    "https://api.hindsight.vectorize.io",
)
BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "robot-maintenance")

if not API_KEY:
    print("ERROR: HINDSIGHT_API_KEY is missing from .env")
    sys.exit(1)


reflect_mission = """
You are an industrial robotic maintenance decision-support agent
for the fictional AeroTech AT-600.

Help a human maintenance technician choose the next diagnostic
action using historical repair outcomes stored in memory.

Use historical evidence rather than generic assumptions.

Distinguish:
- successful repairs
- failed repairs
- temporary successes
- unresolved cases

Prioritize historical cases that match:
- fault code
- robot
- axis
- symptoms
- operating conditions
- previous repair history

Treat recurrence as evidence that a previous repair was not a
durable resolution.

Do not assume that a component is the root cause simply because
replacement succeeded in another case.

When evidence is conflicting or insufficient, explicitly state the
uncertainty and recommend another diagnostic test before unnecessary
component replacement.

Never claim certainty when the stored evidence does not support it.

All maintenance records are synthetic.
""".strip()


payload = {
    "updates": {
        "reflect_mission": reflect_mission
    }
}

url = f"{BASE_URL}/v1/default/banks/{BANK_ID}/config"

request = urllib.request.Request(
    url=url,
    data=json.dumps(payload).encode("utf-8"),
    method="PATCH",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
)

try:
    with urllib.request.urlopen(request, timeout=30) as response:
        result = response.read().decode("utf-8")

    print("=" * 60)
    print("BANK CONFIGURATION UPDATED")
    print("=" * 60)
    print(result)

except urllib.error.HTTPError as exc:
    print("=" * 60)
    print("HINDSIGHT HTTP ERROR")
    print("=" * 60)
    print("Status:", exc.code)
    print(exc.read().decode("utf-8", errors="replace"))
    sys.exit(1)

except urllib.error.URLError as exc:
    print("=" * 60)
    print("CONNECTION ERROR")
    print("=" * 60)
    print(exc)
    sys.exit(1)