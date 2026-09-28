"""
Persistent usage ledger + budget guard (E7).

Rates live in pricing.json (editable). Ledger survives restarts.
ECO may hard-stop; EVENT only warns.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import config

log = logging.getLogger("ledger")
_lock = threading.Lock()

_DEFAULT_PRICING = {
    "stt_usd_per_minute": 0.024,       # Speech-to-Text v1 streaming standard approx
    "translate_usd_per_million_chars": 20.0,  # Translation v2 Basic approx
    "notes": "Edit these to match current Google list prices. Estimates only.",
}


def _load_json(path: Path, default: dict) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Could not read %s: %s", path, exc)
    return dict(default)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class UsageLedger:
    def __init__(self) -> None:
        self.pricing = _load_json(config.PRICING_PATH, _DEFAULT_PRICING)
        if not config.PRICING_PATH.is_file():
            _save_json(config.PRICING_PATH, self.pricing)
        self._data = _load_json(
            config.LEDGER_PATH,
            {
                "created": datetime.now(timezone.utc).isoformat(),
                "days": {},
                "totals": {"stt_seconds": 0.0, "translate_chars": 0, "est_usd": 0.0},
                "override_until": None,
            },
        )

    def _today(self) -> dict:
        key = date.today().isoformat()
        days = self._data.setdefault("days", {})
        if key not in days:
            days[key] = {
                "stt_seconds": 0.0,
                "stt_by_lang": {},
                "stt_by_profile": {},
                "translate_chars": 0,
                "est_usd": 0.0,
                "warnings": [],
            }
        return days[key]

    def _estimate_add(self, stt_s: float = 0.0, chars: int = 0) -> float:
        rate_min = float(self.pricing.get("stt_usd_per_minute", 0.024))
        rate_mchar = float(self.pricing.get("translate_usd_per_million_chars", 20.0))
        return (stt_s / 60.0) * rate_min + (chars / 1_000_000.0) * rate_mchar

    def record_stt(self, seconds: float, language: str, profile: str) -> None:
        if seconds <= 0:
            return
        with _lock:
            day = self._today()
            day["stt_seconds"] += seconds
            day["stt_by_lang"][language] = day["stt_by_lang"].get(language, 0.0) + seconds
            day["stt_by_profile"][profile] = day["stt_by_profile"].get(profile, 0.0) + seconds
            cost = self._estimate_add(stt_s=seconds)
            day["est_usd"] += cost
            self._data["totals"]["stt_seconds"] += seconds
            self._data["totals"]["est_usd"] += cost
            _save_json(config.LEDGER_PATH, self._data)

    def record_translate(self, chars: int) -> None:
        if chars <= 0:
            return
        with _lock:
            day = self._today()
            day["translate_chars"] += chars
            cost = self._estimate_add(chars=chars)
            day["est_usd"] += cost
            self._data["totals"]["translate_chars"] += chars
            self._data["totals"]["est_usd"] += cost
            _save_json(config.LEDGER_PATH, self._data)

    def snapshot(self) -> dict:
        with _lock:
            day = self._today()
            totals = self._data["totals"]
            daily_pct = (day["est_usd"] / config.DAILY_BUDGET_USD * 100) if config.DAILY_BUDGET_USD else 0
            total_pct = (totals["est_usd"] / config.TOTAL_BUDGET_USD * 100) if config.TOTAL_BUDGET_USD else 0
            return {
                "today": {
                    "stt_seconds": round(day["stt_seconds"], 1),
                    "translate_chars": day["translate_chars"],
                    "est_usd": round(day["est_usd"], 4),
                    "budget_pct": round(daily_pct, 1),
                },
                "total": {
                    "stt_seconds": round(totals["stt_seconds"], 1),
                    "translate_chars": totals["translate_chars"],
                    "est_usd": round(totals["est_usd"], 4),
                    "budget_pct": round(total_pct, 1),
                },
                "daily_budget_usd": config.DAILY_BUDGET_USD,
                "total_budget_usd": config.TOTAL_BUDGET_USD,
                "hard_stop": config.BUDGET_HARD_STOP,
                "profile": config.PROFILE,
                "mode": config.MODE,
            }

    def allow_google(self) -> tuple[bool, str | None]:
        """Returns (ok, warning_or_block_message)."""
        if config.is_cache_mode():
            return True, None
        snap = self.snapshot()
        daily = snap["today"]["budget_pct"]
        total = snap["total"]["budget_pct"]
        override = self._data.get("override_until")
        if override:
            try:
                if datetime.fromisoformat(override) > datetime.now(timezone.utc):
                    return True, "Budget override active"
            except ValueError:
                pass

        msg = None
        level = max(daily, total)
        if level >= 100:
            msg = (
                f"Budget exhausted (today {daily:.0f}% / total {total:.0f}%). "
                "ECO hard-stop active." if config.BUDGET_HARD_STOP
                else f"Budget at {level:.0f}% — EVENT continues with captions."
            )
            if config.BUDGET_HARD_STOP:
                return False, msg
            return True, msg
        if level >= 90:
            msg = f"Budget warning: {level:.0f}% of limit used."
        elif level >= 70:
            msg = f"Budget notice: {level:.0f}% of limit used."
        return True, msg

    def activate_override(self, hours: float = 4.0) -> None:
        with _lock:
            until = datetime.now(timezone.utc).timestamp() + hours * 3600
            self._data["override_until"] = datetime.fromtimestamp(until, timezone.utc).isoformat()
            _save_json(config.LEDGER_PATH, self._data)


ledger = UsageLedger()
