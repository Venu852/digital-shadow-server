"""Pure scoring rules shared by the read APIs. No database or Flask access here."""
import math

MIN_GROUP = 3
CONTEXT_DAMP = 15
# A group's displayed drift at or above this produces a group suggestion
SUGGESTION_THRESHOLD = 30
# A person's latest displayed drift at or above this produces personal suggestions
PERSONAL_SUGGESTION_THRESHOLD = 20
CONTEXT_TAGS = ('None', 'Exam week', 'Travel', 'Holiday or break', 'Busy period', 'New routine')

# Ordered: earlier signals win ties. "action" is the group suggestion shown to the coordinator;
# "personal" is shown only to the person.
SIGNALS = (
    {
        "key": "switching",
        "label": "App switching",
        "self": "You are switching between apps more often than your usual.",
        "manager": "App switching is above the group's baseline.",
        "action": "Reduce parallel tasks so people can stay with one thing longer.",
        "personal": "Try checking messages at set times instead of switching all day.",
    },
    {
        "key": "session",
        "label": "Session length",
        "self": "Your time in a single app is shorter than usual.",
        "manager": "Time in a single app is shorter than baseline.",
        "action": "Protect longer uninterrupted blocks; cut interruptions and hand-offs.",
        "personal": "Try one longer, uninterrupted block today, even 25 minutes.",
    },
    {
        "key": "checks",
        "label": "Phone checks",
        "self": "You are picking up the phone more often than your baseline.",
        "manager": "Phone pick-ups are more frequent than baseline.",
        "action": "Batch non-urgent updates and pings into set times.",
        "personal": "Try leaving the phone out of reach for one hour.",
    },
    {
        "key": "screen",
        "label": "Screen time",
        "self": "Your screen-on time is above your usual.",
        "manager": "Screen-on time is above baseline.",
        "action": "Avoid long back-to-back screen sessions; encourage short breaks.",
        "personal": "Try a short screen-free break between long stretches.",
    },
    {
        "key": "night",
        "label": "Late-night use",
        "self": "You are using the phone more between midnight and 5am than usual.",
        "manager": "Late-night phone use is above baseline.",
        "action": "Avoid late-evening requests and deadlines; keep after-hours messages to a minimum.",
        "personal": "Try putting the phone away 30 minutes earlier tonight.",
    },
    {
        "key": "timing",
        "label": "Routine timing",
        "self": "Your phone day is starting or ending at different times than usual.",
        "manager": "Daily start and end times are shifting from baseline.",
        "action": "Keep meeting and deadline times steady; avoid sudden schedule changes.",
        "personal": "Try keeping your first and last phone use of the day closer to your usual times.",
    },
)
SIGNAL_KEYS = tuple(s["key"] for s in SIGNALS)
SIGNALS_BY_KEY = {s["key"]: s for s in SIGNALS}

EXPLAIN_NOTE = (
    "This reading says your phone-use rhythm is shifting. It never states a diagnosis, "
    "a mental-health condition, or a judgement about you."
)

def round_half_up(value):
    # Python's round() is banker's rounding; scores round .5 up
    return int(math.floor(value + 0.5))

def status_for(score):
    if score < 20:
        return {"label": "Stable", "band": "stable"}
    if score < 45:
        return {"label": "Early drift", "band": "early"}
    if score < 70:
        return {"label": "Elevated drift", "band": "elevated"}
    return {"label": "High drift", "band": "high"}

def horizon_for(displayed_series):
    if len(displayed_series) < 4:
        return "Not enough days yet"
    slope = displayed_series[-1] - displayed_series[-4]
    if slope > 8:
        return "2 to 3 weeks if the trend continues"
    if slope > 2:
        return "4 to 6 weeks if the trend continues"
    return "No defined trend: stable or improving"

def display_drift(drift_raw, context_applies):
    """Context tags (exam week etc.) explain some drift, so the shown value is damped."""
    if context_applies:
        return max(0, drift_raw - CONTEXT_DAMP)
    return drift_raw

def factor_breakdown(levels, voice):
    total = sum(levels[key] for key in SIGNAL_KEYS)
    factors = [{
        "key": s["key"],
        "label": s["label"],
        "level": levels[s["key"]],
        "pct": round_half_up(levels[s["key"]] / total * 100) if total else 0,
        "cause": s[voice],
    } for s in SIGNALS]
    # Stable sort keeps SIGNALS order for equal levels
    return sorted(factors, key=lambda f: f["level"], reverse=True)

def top_signal(levels):
    return max(SIGNAL_KEYS, key=lambda key: (levels[key], -SIGNAL_KEYS.index(key)))

def personal_suggestions(levels, limit=2):
    """Nudges for the signals with the highest levels; ties follow SIGNALS order."""
    ranked = sorted(SIGNALS, key=lambda s: levels[s["key"]], reverse=True)[:limit]
    return [{
        "signal": s["key"],
        "label": s["label"],
        "text": s["personal"],
        "because": s["self"],
    } for s in ranked]
