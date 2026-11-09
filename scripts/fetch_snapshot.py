"""One-off job snapshot: pull current DE / ML / DS / SWE roles from the
H-1B-sponsor boards, read each JD, and write the ones requiring <= 3 years
of experience to data/snapshot.csv (newest first, then by fit score).

No email, no site rebuild, no change to seen_jobs. Safe to run anytime:
    python -m scripts.fetch_snapshot
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import datetime as dt
from pathlib import Path

from src.jobs import ats
from src.jobs import h1b_greenhouse as hg
from src.ranking import fit_ranker as fr

OUT = Path(__file__).resolve().parent.parent / "data" / "snapshot.csv"


def _category(title: str) -> str:
    t = title.lower()
    if "data scien" in t:
        return "DS"
    if any(k in t for k in ("machine learning", "ml ", "ml/", "mlops", "ml ops", "ai engineer", "ai/ml")):
        return "ML"
    if any(k in t for k in ("data", "analytics", "etl", "business intelligence", "bi engineer")):
        return "DE"
    return "SWE"


def main() -> None:
    jobs = hg.daily_fresh_swe(us_only=True, include_aggregator=False, include_custom=True)
    print(f"Fetched {len(jobs)} roles that pass the title/US filters")

    def _jd(j):
        try:
            j["_jd"] = ats.description(j) or ""
        except Exception:
            j["_jd"] = ""
        return j

    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        jobs = list(ex.map(_jd, jobs))

    kept, no_sponsor, too_senior = [], 0, 0
    for j in jobs:
        jd = j.pop("_jd", "")
        if fr.says_no_sponsorship(jd):
            no_sponsor += 1
            continue
        yrs = fr._years_required(jd)
        if fr.too_senior(yrs):
            too_senior += 1
            continue
        score, reason = fr.keyword_fit(j["title"], j["company"], jd)
        kept.append({
            "category": _category(j["title"]),
            "company": j["company"],
            "title": j["title"],
            "location": j.get("location", ""),
            "years_required": "" if yrs is None else yrs,
            "new_grad_title": "yes" if j.get("new_grad") else "",
            "fit_score": score,
            "fit_reason": reason,
            "updated_at": j.get("updated_at", ""),
            "has_jd": "yes" if jd else "",
            "url": j.get("url", ""),
        })

    kept.sort(key=lambda r: (r["updated_at"] or "", r["fit_score"]), reverse=True)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(kept[0].keys()) if kept else ["empty"])
        w.writeheader()
        w.writerows(kept)
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} kept {len(kept)} | dropped "
          f"{no_sponsor} no-sponsorship, {too_senior} requiring >{fr.MAX_YEARS_REQUIRED} yrs")


if __name__ == "__main__":
    main()
