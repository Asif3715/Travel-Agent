from __future__ import annotations


def estimate_budget(total_budget: int, travelers: int, nights: int) -> dict:
    base_nights = max(nights, 1)
    per_day = max(total_budget // max(base_nights * max(travelers, 1), 1), 1)
    breakdown = {
        "stay": round(per_day * 0.4),
        "food": round(per_day * 0.3),
        "transport": round(per_day * 0.15),
        "activities": round(per_day * 0.15),
    }
    estimated_total = sum(breakdown.values()) * base_nights * max(travelers, 1)
    return {
        "currency": "USD",
        "target": total_budget,
        "estimated_total": estimated_total,
        "breakdown": breakdown,
        "per_person_per_day": per_day,
    }
