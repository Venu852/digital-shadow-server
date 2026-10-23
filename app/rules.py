"""Pure scoring rules shared by the read APIs. No database or Flask access here."""
import math

MIN_GROUP = 3
CONTEXT_DAMP = 15
TEAM_ACTION_THRESHOLD = 30
CONTEXT_TAGS = ('None', 'Exam week', 'Deadline crunch', 'Product launch', 'Holiday or break')

# Ordered: earlier signals win ties
SIGNALS = (
    {
        "key": "switching",
        "label": "App switching",
        "self": "You are switching between apps more often than your usual.",
        "manager": "Switching between apps is more frequent than baseline.",
        "action": "Reduce open workload and consolidate tasks into one view.",
    },
    {
        "key": "session",
        "label": "Session length",
        "self": "Your time in a single app is shorter than usual.",
        "manager": "Time in a single app is shorter than baseline.",
        "action": "Adjust pacing and shorten the next module.",
    },
    {
        "key": "checks",
        "label": "Phone checks",
        "self": "You are picking up the phone more often than your baseline.",
        "manager": "Phone pick-ups are more frequent than baseline.",
        "action": "Insert a short break prompt and lighten the task queue.",
    },
    {
        "key": "screen",
        "label": "Screen time",
        "self": "Screen-on time is above your usual for this time of day.",
        "manager": "Screen-on time is above baseline for this time of day.",
        "action": "Plan shorter focus blocks with a short break between them.",
    },
    {
        "key": "steadiness",
        "label": "Motion steadiness",
        "self": "Phone handling is less steady than usual.",
        "manager": "Phone handling is less steady than baseline.",
        "action": "Lower task difficulty and surface guided hints.",
    },
)
SIGNAL_KEYS = tuple(s["key"] for s in SIGNALS)
SIGNALS_BY_KEY = {s["key"]: s for s in SIGNALS}

EXPLAIN_NOTE = (
    "This reading says behaviour is changing direction. It never states a diagnosis, "
    "a mental-health condition, or a performance judgement."
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
    return "No defined horizon: trend is stable or improving"

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
