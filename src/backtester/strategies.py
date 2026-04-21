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

def limit(created_at: datetime, price_history: list[dict], threshold: float) -> tuple[float, datetime] | None:
    """Simulated limit-order fill at exactly `threshold`.

    Fires only on a true crossing: price must have been observed strictly
    above threshold at some earlier snapshot and then touch or drop below it.
    Markets that open at-or-below threshold are skipped — we never could
    have rested that limit order before the market began.
    """
    seen_above = False
    for point in price_history:
        if not seen_above:
            if point["no_price"] > threshold:
                seen_above = True
            continue
        if point["no_price"] <= threshold:
            return (threshold, point["timestamp"])
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

STRATEGIES = {
    "at_creation": {"fn": at_creation, "params": [{}]},
    "threshold": {
        "fn": price_threshold,
        "params": [{"threshold": t} for t in [0.20, 0.30, 0.40, 0.50, 0.60]],
    },
    "limit": {
        "fn": limit,
        "params": [{"threshold": t} for t in [0.20, 0.30, 0.40, 0.50, 0.60]],
    },
    "snapshot": {
        "fn": time_snapshot,
        "params": [
            {"offset_hours": h}
            for h in [2, 4, 6, 8, 12, 16, 20, 24, 48, 168]
        ],
    },
}
