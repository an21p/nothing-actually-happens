from datetime import datetime, timedelta

SNAPSHOT_MAX_DISTANCE_HOURS = 12

def at_creation(created_at: datetime, price_history: list[dict]) -> tuple[float, datetime] | None:
    if not price_history:
        return None
    first = price_history[0]
    return (first["no_price"], first["timestamp"])

def price_threshold(created_at: datetime, price_history: list[dict], threshold: float) -> tuple[float, datetime] | None:
    for point in price_history:
        if point["no_price"] <= threshold:
            return (point["no_price"], point["timestamp"])
    return None

def time_snapshot(created_at: datetime, price_history: list[dict], offset_hours: int) -> tuple[float, datetime] | None:
    if not price_history:
        return None
    target = created_at + timedelta(hours=offset_hours)
    max_distance = timedelta(hours=SNAPSHOT_MAX_DISTANCE_HOURS)
    closest = None
    closest_distance = None
    for point in price_history:
        distance = abs(point["timestamp"] - target)
        if distance > max_distance:
            continue
        if closest_distance is None or distance < closest_distance:
            closest = point
            closest_distance = distance
    if closest is None:
        return None
    return (closest["no_price"], closest["timestamp"])

def best_price(created_at: datetime, price_history: list[dict]) -> tuple[float, datetime] | None:
    if not price_history:
        return None
    best = min(price_history, key=lambda p: p["no_price"])
    return (best["no_price"], best["timestamp"])

STRATEGIES = {
    "at_creation": {"fn": at_creation, "params": [{}]},
    "threshold": {
        "fn": price_threshold,
        "params": [{"threshold": t} for t in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]],
    },
    "snapshot": {
        "fn": time_snapshot,
        "params": [{"offset_hours": h} for h in [24, 48, 168]],
    },
    "best_price": {"fn": best_price, "params": [{}]},
}
