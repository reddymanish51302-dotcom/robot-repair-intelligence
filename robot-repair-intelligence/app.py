import json
import os
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from hindsight_client import Hindsight


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

API_KEY = os.getenv("HINDSIGHT_API_KEY")

BASE_URL = os.getenv(
    "HINDSIGHT_BASE_URL",
    "https://api.hindsight.vectorize.io",
)

BANK_ID = os.getenv(
    "HINDSIGHT_BANK_ID",
    "robot-maintenance",
)

DATA_FILE = Path("data") / "repair_history.json"


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="AeroTech Maintenance Intelligence",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# STYLE
# ============================================================

# CSS does not suffer from the markdown bug as badly as raw HTML divs, 
# but we keep it flush left for safety.
st.markdown(
    """
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 3rem;
}
.hero {
    border: 1px solid rgba(128,128,128,0.25);
    border-radius: 16px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 1.2rem;
}
.hero-title {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1.1;
}
.hero-subtitle {
    margin-top: 0.4rem;
    opacity: 0.7;
}
.metric-card {
    border: 1px solid rgba(128,128,128,0.22);
    border-radius: 12px;
    padding: 0.9rem;
    min-height: 90px;
}
.metric-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    opacity: 0.6;
}
.metric-value {
    font-size: 1.1rem;
    font-weight: 750;
    margin-top: 0.3rem;
}
.section-title {
    font-size: 1.25rem;
    font-weight: 750;
    margin-top: 1rem;
    margin-bottom: 0.7rem;
}
.memory-card {
    border: 1px solid rgba(128,128,128,0.22);
    border-radius: 12px;
    padding: 0.85rem 1rem;
    margin-bottom: 0.6rem;
}
.memory-case {
    font-weight: 750;
    font-size: 1rem;
}
.memory-sub {
    opacity: 0.7;
    font-size: 0.85rem;
    margin-top: 0.2rem;
}
.trace-box {
    border: 1px solid rgba(128,128,128,0.22);
    border-radius: 12px;
    padding: 1rem;
}
.trace-step {
    
    font-size: 0.84rem;
    line-height: 1.7;
}
.small-text {
    font-size: 0.82rem;
    opacity: 0.68;
}
</style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# BASIC VALIDATION
# ============================================================

if not API_KEY:
    st.error("HINDSIGHT_API_KEY is missing from your .env file.")
    st.stop()

if not DATA_FILE.exists():
    st.error(f"Dataset not found:\n{DATA_FILE.resolve()}")
    st.stop()

try:
    with DATA_FILE.open("r", encoding="utf-8") as file:
        repair_history = json.load(file)
except json.JSONDecodeError as exc:
    st.error(f"Invalid JSON in repair_history.json: {exc}")
    st.stop()
except OSError as exc:
    st.error(f"Could not read repair_history.json: {exc}")
    st.stop()

if not isinstance(repair_history, list):
    st.error("repair_history.json must contain a JSON array.")
    st.stop()


# ============================================================
# HINDSIGHT CLIENT
# ============================================================


def get_hindsight_client():
    return Hindsight(
        base_url=BASE_URL,
        api_key=API_KEY,
    )


# ============================================================
# HELPERS
# ============================================================

def get_robot_ids():
    return sorted(
        {record["robot_id"] for record in repair_history if "robot_id" in record}
    )

def get_fault_codes():
    return sorted(
        {record["fault_code"] for record in repair_history if "fault_code" in record}
    )

def outcome_symbol(outcome):
    value = outcome.strip().lower()
    if value == "success": return "✓"
    if value == "failure": return "✕"
    if value == "temporary success": return "~"
    if value == "unresolved": return "?"
    return "•"

def extract_case_ids(memories):
    case_ids = set()
    for memory in memories or []:
        text = getattr(memory, "text", "") or ""
        matches = re.findall(r"\b(?:RC-\d{4}|LIVE-\d{8}-\d{6})\b", text)
        case_ids.update(matches)
    return sorted(case_ids)

def build_query(robot_id, fault_code, axis, symptoms, ambient_temperature, load_percent, tool_inertia, recent_maintenance):
    symptoms_text = "\n".join(f"- {item}" for item in symptoms if item.strip())
    return f"""
CURRENT MAINTENANCE INCIDENT

Robot:
{robot_id}

Model:
AeroTech AT-600

Fault code:
{fault_code}

Axis:
{axis}

Symptoms:
{symptoms_text}

Operating conditions:
- Ambient temperature: {ambient_temperature} C
- Load: {load_percent}%
- Tool/inertia context: {tool_inertia}

Recent maintenance/context:
{recent_maintenance}

TASK

Determine the most defensible NEXT DIAGNOSTIC ACTION using the maintenance experience available in Hindsight.
This is decision support for a human technician.

RULES

1. Prefer historical cases matching the current robot, fault, axis, symptoms, and operating conditions.
2. Compare Success, Failure, Temporary Success, and Unresolved historical cases.
3. A failed repair is evidence about that historical attempt and its context. Do not generalize that a component can never work.
4. A successful repair is evidence, not proof that the same repair is correct for the current incident.
5. Do not invent a root cause.
6. Prefer diagnostic evidence before unnecessary component replacement when multiple causes remain plausible.
7. Clearly distinguish historical evidence from current-case inference.
8. Clearly state uncertainty.
9. Use specific historical case IDs.
10. Do not claim an approach is universally effective or universally ineffective.
11. All records are synthetic.

Return these fields:
recommended_action
reason
historical_evidence
avoid_repeating
uncertainty
""".strip()


# ============================================================
# RESPONSE SCHEMA
# ============================================================

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_action": {"type": "string"},
        "reason": {"type": "string"},
        "historical_evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string"},
                    "outcome": {"type": "string"},
                    "relevance": {"type": "string"},
                },
                "required": ["case_id", "outcome", "relevance"],
            },
        },
        "avoid_repeating": {
            "type": "array",
            "items": {"type": "string"},
        },
        "uncertainty": {"type": "string"},
    },
    "required": ["recommended_action", "reason", "historical_evidence", "avoid_repeating", "uncertainty"],
}


# ============================================================
# ANALYZE WITH HINDSIGHT
# ============================================================

def analyze_with_hindsight(robot_id, fault_code, axis, symptoms, ambient_temperature, load_percent, tool_inertia, recent_maintenance, use_memory):
    client = get_hindsight_client()
    query = build_query(
        robot_id=robot_id, fault_code=fault_code, axis=axis, symptoms=symptoms,
        ambient_temperature=ambient_temperature, load_percent=load_percent,
        tool_inertia=tool_inertia, recent_maintenance=recent_maintenance,
    )
    
    if use_memory:
        tags = [fault_code, robot_id]
    else:
        tags = ["__memory_off_demo__"]

    response = client.reflect(
        bank_id=BANK_ID,
        query=query,
        tags=tags,
        tags_match="all_strict",
        budget="low",
        max_tokens=1000,
        response_schema=RESPONSE_SCHEMA,
        include_facts=True,
    )
    return response


# ============================================================
# SAVE TECHNICIAN FEEDBACK
# ============================================================

def save_feedback(incident, recommended_action, technician_action, outcome, technician_notes):
    client = get_hindsight_client()
    now = datetime.now(timezone.utc)
    case_id = f"LIVE-{now.strftime('%Y%m%d-%H%M%S')}"
    symptoms_text = "\n".join(f"- {item}" for item in incident["symptoms"])

    content = f"""
LIVE MAINTENANCE EXPERIENCE

Case ID:
{case_id}

Date:
{now.date().isoformat()}

Robot:
{incident["robot_id"]}

Model:
AeroTech AT-600

Fault code:
{incident["fault_code"]}

Axis:
{incident["axis"]}

Symptoms:
{symptoms_text}

Operating conditions:
- Ambient temperature: {incident["ambient_temperature"]} C
- Load: {incident["load_percent"]}%
- Tool/inertia context: {incident["tool_inertia"]}

Recent maintenance/context:
{incident["recent_maintenance"]}

Previous agent recommendation:
{recommended_action}

Technician action actually performed:
{technician_action}

Observed outcome:
{outcome}

Technician notes:
{technician_notes}

This is a synthetic maintenance experience.
The observed outcome is the actual result of the technician action.
The previous agent recommendation is context and is not proof that the action was correct.
""".strip()

    metadata = {
        "case_id": case_id,
        "robot_id": incident["robot_id"],
        "robot_model": "AeroTech AT-600",
        "fault_code": incident["fault_code"],
        "outcome": outcome,
        "date": now.date().isoformat(),
        "synthetic": "true",
        "source": "live-ui-feedback",
    }

    tags = [
        incident["fault_code"],
        incident["robot_id"],
        outcome,
        "live-feedback",
    ]

    response = client.retain(
        bank_id=BANK_ID,
        content=content,
        metadata=metadata,
        tags=tags,
    )
    return case_id, response


# ============================================================
# SESSION STATE
# ============================================================

if "response" not in st.session_state:
    st.session_state.response = None
if "analysis" not in st.session_state:
    st.session_state.analysis = None
if "incident" not in st.session_state:
    st.session_state.incident = None
if "feedback_saved" not in st.session_state:
    st.session_state.feedback_saved = False
if "feedback_case_id" not in st.session_state:
    st.session_state.feedback_case_id = None


# ============================================================
# HEADER
# ============================================================

# FLUSH LEFT HTML FIX
st.markdown(
    """
<div class="hero">
<div class="hero-title">
AeroTech Maintenance Intelligence
</div>
<div class="hero-subtitle">
Outcome-driven maintenance memory for the fictional AeroTech AT-600
</div>
</div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown("### Memory control")
    memory_mode = st.toggle("Use Hindsight memory", value=True)

    if memory_mode:
        st.success("Hindsight memory: ON")
    else:
        st.warning("Hindsight memory: OFF")

    st.divider()
    st.markdown("### Memory bank")
    st.code(BANK_ID)

    # FLUSH LEFT HTML FIX
    st.markdown(
        """
<div class="small-text">
ON = historical maintenance experience is retrieved.
<br><br>
OFF = controlled baseline with zero historical memory facts retrieved.
</div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()
    st.markdown("### Local dataset")
    st.write(f"Repair records loaded: **{len(repair_history)}**")
    st.caption("Changing the switch does not delete or modify memory.")


# ============================================================
# CURRENT INCIDENT
# ============================================================

st.markdown(
    '<div class="section-title">1 · Current incident</div>',
    unsafe_allow_html=True,
)

robot_ids = get_robot_ids()
fault_codes = get_fault_codes()

col1, col2, col3 = st.columns(3)

with col1:
    default_robot = "AT600-RB-104" if "AT600-RB-104" in robot_ids else robot_ids[0]
    robot_id = st.selectbox("Robot", robot_ids, index=robot_ids.index(default_robot))

with col2:
    default_fault = "ERR-SV-402" if "ERR-SV-402" in fault_codes else fault_codes[0]
    fault_code = st.selectbox("Fault code", fault_codes, index=fault_codes.index(default_fault))

with col3:
    axis = st.text_input("Axis", value="Axis 2")


# ============================================================
# INCIDENT FORM
# ============================================================

with st.form("incident_form"):
    col1, col2, col3 = st.columns(3)

    with col1:
        ambient_temperature = st.number_input("Ambient temperature (°C)", min_value=-20.0, max_value=80.0, value=36.0, step=1.0)

    with col2:
        load_percent = st.number_input("Load (%)", min_value=0.0, max_value=100.0, value=82.0, step=1.0)

    with col3:
        tool_inertia = st.selectbox("Tool / inertia context", [
            "Relatively high tool inertia", "Normal tool inertia", "Low tool inertia", "Recently changed tool", "Unknown",
        ])

    symptoms_text = st.text_area(
        "Symptoms",
        value=(
            "feedback instability during high-speed deceleration\n"
            "short jitter before stop\n"
            "high-frequency position-error spikes\n"
            "intermittent feedback mismatch"
        ),
        height=125,
    )

    recent_maintenance = st.text_area(
        "Recent maintenance / context",
        value="Current incident follows repeated historical ERR-SV-402 occurrences on this robot.",
        height=95,
    )

    button_label = "Analyze with Hindsight" if memory_mode else "Analyze without Memory"
    analyze_button = st.form_submit_button(button_label, type="primary", use_container_width=True)


# ============================================================
# ANALYZE
# ============================================================

if analyze_button:
    symptoms = [line.strip() for line in symptoms_text.splitlines() if line.strip()]
    incident = {
        "robot_id": robot_id, "fault_code": fault_code, "axis": axis,
        "symptoms": symptoms, "ambient_temperature": ambient_temperature,
        "load_percent": load_percent, "tool_inertia": tool_inertia,
        "recent_maintenance": recent_maintenance,
    }

    st.session_state.incident = incident
    st.session_state.response = None
    st.session_state.analysis = None
    st.session_state.feedback_saved = False
    st.session_state.feedback_case_id = None

    with st.spinner("Analyzing the maintenance incident..."):
        try:
            response = analyze_with_hindsight(
                robot_id=robot_id, fault_code=fault_code, axis=axis, symptoms=symptoms,
                ambient_temperature=ambient_temperature, load_percent=load_percent,
                tool_inertia=tool_inertia, recent_maintenance=recent_maintenance, use_memory=memory_mode,
            )
            st.session_state.response = response
            structured = response.structured_output

            if isinstance(structured, dict):
                st.session_state.analysis = structured
            else:
                st.error("Hindsight returned no structured output.")

        except Exception as exc:
            st.session_state.response = None
            st.session_state.analysis = None
            st.error(f"Hindsight analysis failed: {type(exc).__name__}: {exc}")


# ============================================================
# RESULTS
# ============================================================

analysis = st.session_state.analysis
response = st.session_state.response
incident = st.session_state.incident

if analysis and incident:

    st.markdown(
        '<div class="section-title">2 · Maintenance recommendation</div>',
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)

    with m1:
        st.markdown(
            f"""
<div class="metric-card">
<div class="metric-label">
Robot
</div>
<div class="metric-value">
{escape(str(incident["robot_id"]))}
</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    with m2:
        st.markdown(
            f"""
<div class="metric-card">
<div class="metric-label">
Fault
</div>
<div class="metric-value">
{escape(str(incident["fault_code"]))}
</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    with m3:
        st.markdown(
            f"""
<div class="metric-card">
<div class="metric-label">
Axis
</div>
<div class="metric-value">
{escape(str(incident["axis"]))}
</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    with m4:
        memory_status = "ON" if memory_mode else "OFF"
        st.markdown(
            f"""
<div class="metric-card">
<div class="metric-label">
Memory
</div>
<div class="metric-value">
{escape(memory_status)}
</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.write("")

    left_col, right_col = st.columns([1.5, 0.8], gap="large")

    with left_col:
        st.markdown("#### Next diagnostic action")
        st.info(analysis.get("recommended_action", "No recommendation returned."))

        st.markdown("#### Why")
        st.write(analysis.get("reason", "No reasoning returned."))

        st.markdown("#### Uncertainty")
        st.warning(analysis.get("uncertainty", "No uncertainty statement returned."))

    with right_col:
        st.markdown("#### Memory trace")

        memories = getattr(response.based_on, "memories", []) if response and response.based_on else []
        case_ids = extract_case_ids(memories)

        st.metric("Memory facts used", len(memories))
        st.metric("Distinct cases referenced", len(case_ids))

        # FLUSH LEFT HTML FIX
        st.markdown(
            """
<div class="trace-box">
<div class="trace-step">
Current incident
<br>↓<br>
Hindsight Recall
<br>↓<br>
Historical maintenance memory
<br>↓<br>
Hindsight Reflect
<br>↓<br>
Recommendation
</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()

    st.markdown(
        '<div class="section-title">3 · Historical evidence</div>',
        unsafe_allow_html=True,
    )

    evidence = analysis.get("historical_evidence", [])

    if evidence:
        for item in evidence:
            case_id = item.get("case_id", "Unknown")
            outcome = item.get("outcome", "Unknown")
            relevance = item.get("relevance", "")
            symbol = outcome_symbol(outcome)

            safe_case_id = escape(str(case_id))
            safe_outcome = escape(str(outcome))
            safe_relevance = escape(str(relevance))

            # FLUSH LEFT HTML FIX
            st.markdown(
                f"""
<div class="memory-card">
<div class="memory-case">
{escape(symbol)} {safe_case_id} &nbsp;&nbsp; {safe_outcome}
</div>
<div class="memory-sub">
{safe_relevance}
</div>
</div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.caption("No structured historical evidence returned.")

    avoid_items = analysis.get("avoid_repeating", [])

    if avoid_items:
        with st.expander("Approaches not to repeat blindly", expanded=False):
            for item in avoid_items:
                st.write(f"• {item}")

    if memories:
        with st.expander("Open raw Hindsight memory trace", expanded=False):
            for index, memory in enumerate(memories[:20], start=1):
                memory_type = escape(str(getattr(memory, "type", "unknown")))
                st.markdown(f"**Memory {index} · {memory_type}**")
                st.write(getattr(memory, "text", ""))
                st.divider()


    # ========================================================
    # SECTION 4 — FEEDBACK LOOP
    # ========================================================

    st.markdown(
        '<div class="section-title">4 · Record the actual technician outcome</div>',
        unsafe_allow_html=True,
    )
    st.caption("The observed result becomes a new synthetic maintenance experience in Hindsight.")

    with st.form("feedback_form"):
        technician_action = st.text_area(
            "Action actually performed",
            value=analysis.get("recommended_action", ""),
            height=100,
        )
        outcome = st.selectbox("Observed outcome", ["Success", "Failure", "Temporary Success", "Unresolved"])
        technician_notes = st.text_area("Technician notes", placeholder="Describe what actually happened after the action.", height=120)

        save_feedback_button = st.form_submit_button(
            "Save outcome to Hindsight", type="primary", use_container_width=True, disabled=st.session_state.feedback_saved,
        )

    if save_feedback_button:
        if not technician_action.strip():
            st.error("Enter the action actually performed.")
        elif not technician_notes.strip():
            st.error("Enter technician notes describing the actual outcome.")
        else:
            with st.spinner("Storing the new maintenance experience..."):
                try:
                    case_id, _ = save_feedback(
                        incident=incident,
                        recommended_action=analysis.get("recommended_action", ""),
                        technician_action=technician_action,
                        outcome=outcome,
                        technician_notes=technician_notes,
                    )
                    st.session_state.feedback_saved = True
                    st.session_state.feedback_case_id = case_id
                except Exception as exc:
                    st.error(f"Could not save feedback: {type(exc).__name__}: {exc}")

    if st.session_state.feedback_saved:
        st.success("New maintenance experience stored in Hindsight.")
        st.code(st.session_state.feedback_case_id)
        st.caption("Run Analyze again to test the updated memory.")