import csv
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

FILENAME = "usage.jsonl"
DEFAULT_RETAIN_DAYS = 90

_session_id = None


def _path():
    override = os.getenv("HAZZEL_USAGE_FILE")
    if override:
        return Path(override)
    from hazzel import config
    return config.CONFIG_DIR / FILENAME


def session_id():
    global _session_id
    if not _session_id:
        _session_id = uuid.uuid4().hex[:12]
    return _session_id


def _retain_days():
    try:
        from hazzel import config
        days = config.get_usage_retain_days()
        if isinstance(days, int) and days > 0:
            return days
    except Exception:
        pass
    return DEFAULT_RETAIN_DAYS


def append(record):
    entry = dict(record or {})
    entry["ts"] = float(entry.get("ts") or time.time())
    entry.setdefault("session_id", session_id())
    if os.getenv("PYTEST_CURRENT_TEST") and not os.getenv("HAZZEL_USAGE_FILE"):
        return entry
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        return None
    trim()
    return entry


def _read_all():
    path = _path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def trim(retain_days=None):
    days = retain_days or _retain_days()
    cutoff = time.time() - days * 86400
    records = _read_all()
    kept = [r for r in records if float(r.get("ts") or 0) >= cutoff]
    if len(kept) == len(records):
        return 0
    path = _path()
    try:
        path.write_text("".join(json.dumps(r) + "\n" for r in kept), encoding="utf-8")
    except OSError:
        return 0
    return len(records) - len(kept)


def _day_start(days_back=0):
    day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return day.timestamp() - days_back * 86400


def summarize(records):
    total = {"input": 0, "output": 0, "cached": 0, "cost": 0.0, "unknown": 0, "calls": 0, "sessions": set()}
    for r in records or []:
        try:
            total["input"] += int(r.get("input_tokens") or 0)
            total["output"] += int(r.get("output_tokens") or 0)
            total["cached"] += int(r.get("cached_input_tokens") or 0)
            total["calls"] += 1
            sid = r.get("session_id")
            if sid:
                total["sessions"].add(sid)
            cost = r.get("cost_usd")
            if cost is None:
                total["unknown"] += 1
            else:
                total["cost"] += float(cost)
        except (TypeError, ValueError):
            continue
    total["cost"] = round(total["cost"], 6)
    total["sessions"] = len(total["sessions"])
    return total


def query(since_ts=None):
    records = _read_all()
    if since_ts is not None:
        records = [r for r in records if float(r.get("ts") or 0) >= since_ts]
    return records


def range_totals(name):
    name = (name or "").lower()
    if name == "today":
        return summarize(query(_day_start(0)))
    if name == "week":
        return summarize(query(_day_start(6)))
    if name == "month":
        return summarize(query(_day_start(29)))
    return None


def session_total(sid=None):
    sid = sid or session_id()
    return summarize([r for r in _read_all() if r.get("session_id") == sid])


def by_model(records):
    groups = {}
    for r in records or []:
        key = (str(r.get("provider") or "unknown"), str(r.get("model") or "unknown"))
        agg = groups.setdefault(key, {"input": 0, "output": 0, "cached": 0, "cost": 0.0, "unknown": 0, "calls": 0})
        try:
            agg["input"] += int(r.get("input_tokens") or 0)
            agg["output"] += int(r.get("output_tokens") or 0)
            agg["cached"] += int(r.get("cached_input_tokens") or 0)
            agg["calls"] += 1
            cost = r.get("cost_usd")
            if cost is None:
                agg["unknown"] += 1
            else:
                agg["cost"] += float(cost)
        except (TypeError, ValueError):
            continue
    for agg in groups.values():
        agg["cost"] = round(agg["cost"], 6)
    return groups


def export_json(path):
    try:
        Path(path).write_text(json.dumps(_read_all(), indent=2) + "\n", encoding="utf-8")
        return True, None
    except OSError as error:
        return False, str(error)


def export_csv(path):
    fields = ["ts", "session_id", "provider", "model", "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens", "estimated", "cost_usd"]
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for r in _read_all():
                writer.writerow({k: r.get(k) for k in fields})
        return True, None
    except OSError as error:
        return False, str(error)


def clear():
    records = _read_all()
    try:
        _path().unlink()
    except OSError:
        pass
    return len(records)


def budget_warnings(session_cost, daily_cost):
    try:
        from hazzel import config
        budget = config.get_budget()
    except Exception:
        return []
    out = []
    try:
        warn_at = float((budget or {}).get("warn_at_pct", 80) or 80)
    except (TypeError, ValueError):
        warn_at = 80
    for label, spent, limit in (("session", session_cost, (budget or {}).get("session_usd")), ("daily", daily_cost, (budget or {}).get("daily_usd"))):
        try:
            limit = float(limit) if limit is not None else None
        except (TypeError, ValueError):
            continue
        if limit is None or limit <= 0:
            continue
        pct = (float(spent or 0) / limit) * 100
        if pct >= warn_at:
            out.append(f"{label} spend ${float(spent or 0):,.2f} is {pct:.0f}% of your ${limit:,.2f} budget")
    return out
