#!/usr/bin/env python3
"""Join the 7 day census transactions against contract logs into three tiers:

  1. submitted  — every flashExecutionBid (including silently skipped)
  2. outcome    — RelayFeeCollected / RelayBidFailed / no log
  3. kind       — top_of_block (1 hash) vs backrun (>=2 hashes)

Reads files already on disk (logs.ndjson, census_txs.ndjson). No RPC.

  export FL_OUT=./out
  nice -n 19 ionice -c3 python3 fastlane_census_7d.py --mon-usd 0.02657
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(os.environ.get("FL_OUT", str(Path.cwd() / "out")))
WEI = 10**18
TOPIC_PAID = "0x17f45ae963f99b4d1929ba44f0acd3d95021fd4ccf3ec9af9d3dcdb7417274bd"
TOPIC_FAILED = "0xbe877e9fd96672907d8df80a513570f0220a522480acbe4c0e8b2c63af9fbec2"


def key(tx_hash: str) -> int:
    """First 64 bits of the tx hash — enough for ~3.7M items (collision ~3e-7)."""
    return int(tx_hash[2:18], 16)


def day(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mon-usd", type=float, required=True)
    ap.add_argument("--out-dir", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out_dir)

    # Dedup by (txHash, logIndex) in case a scan was killed and restarted.
    paid_wei: dict[int, int] = {}
    failed: set[int] = set()
    seen_log: set[tuple[int, int]] = set()
    n_logs = 0
    n_log_dup = 0
    with (out / "logs.ndjson").open() as fh:
        for line in fh:
            d = json.loads(line)
            n_logs += 1
            t0 = d["topics"][0]
            k = key(d["transactionHash"])
            uid = (k, int(d["logIndex"], 16))
            if uid in seen_log:
                n_log_dup += 1
                continue
            seen_log.add(uid)
            if t0 == TOPIC_PAID:
                paid_wei[k] = paid_wei.get(k, 0) + int(d["data"], 16)
            elif t0 == TOPIC_FAILED:
                failed.add(k)
    del seen_log

    kind_n: Counter = Counter()
    kind_paid_n: Counter = Counter()
    kind_paid_wei: Counter = Counter()
    kind_failed_n: Counter = Counter()
    kind_silent_n: Counter = Counter()
    nhash_n: Counter = Counter()
    bid_declared: Counter = Counter()
    by_searcher_wei: Counter = Counter()
    by_searcher_n: Counter = Counter()
    by_target_wei: Counter = Counter()
    by_day_n: Counter = Counter()
    by_day_declared: Counter = Counter()
    flags: Counter = Counter()
    blocks: set[int] = set()
    seen_tx: set[int] = set()
    declared_by_outcome: Counter = Counter()
    gas_ceiling_wei = 0
    n_census = 0
    n_census_dup = 0
    declared_total = 0

    with (out / "census_txs.ndjson").open() as fh:
        for line in fh:
            d = json.loads(line)
            k = key(d["tx"])
            if k in seen_tx:
                n_census_dup += 1
                continue
            seen_tx.add(k)
            n_census += 1
            kind = d.get("kind") or "unknown"
            kind_n[kind] += 1
            nhash_n[d.get("n_hashes", 0)] += 1
            blocks.add(d["block"])
            bw = d.get("bid_wei") or 0
            declared_total += bw
            bid_declared[bw] += 1
            dd = day(d["ts"])
            by_day_n[dd] += 1
            by_day_declared[dd] += bw
            gas_ceiling_wei += d["gas_limit"] * d["gas_price_wei"]
            flags["execute_on_loss"] += 1 if d.get("execute_on_loss") else 0
            flags["pay_bid_on_fail"] += 1 if d.get("pay_bid_on_fail") else 0

            w = paid_wei.get(k)
            if w is not None:
                kind_paid_n[kind] += 1
                kind_paid_wei[kind] += w
                by_searcher_wei[d["from"]] += w
                by_searcher_n[d["from"]] += 1
                by_target_wei[d.get("searcher_to") or "?"] += w
                declared_by_outcome["paid"] += bw
            elif k in failed:
                kind_failed_n[kind] += 1
                declared_by_outcome["failed"] += bw
            else:
                kind_silent_n[kind] += 1
                declared_by_outcome["silent"] += bw

    usd = a.mon_usd
    paid_total = sum(kind_paid_wei.values())

    vals = sorted(bid_declared)
    cum, half, median_bid = 0, n_census / 2, 0
    for v in vals:
        cum += bid_declared[v]
        if cum >= half:
            median_bid = v
            break

    res = {
        "window_days": 7,
        "mon_usd": usd,
        "n_logs": n_logs,
        "n_log_dup_dropped": n_log_dup,
        "n_census_tx": n_census,
        "n_census_dup_dropped": n_census_dup,
        "n_blocks_with_bid": len(blocks),
        "outcome": {
            "paid_tx": sum(kind_paid_n.values()),
            "failed_tx": sum(kind_failed_n.values()),
            "silent_tx": sum(kind_silent_n.values()),
        },
        "by_kind": {
            k: {
                "n": kind_n[k],
                "paid": kind_paid_n[k],
                "failed": kind_failed_n[k],
                "silent": kind_silent_n[k],
                "paid_mon": kind_paid_wei[k] / WEI,
                "paid_usd": kind_paid_wei[k] / WEI * usd,
            }
            for k in kind_n
        },
        "n_hashes_hist": dict(nhash_n.most_common(10)),
        "bid_declared": {
            "total_mon": declared_total / WEI,
            "median_wei": median_bid,
            "median_mon": median_bid / WEI,
            "top_values": [
                {"wei": v, "mon": v / WEI, "count": c}
                for v, c in bid_declared.most_common(8)
            ],
            "distinct_values": len(bid_declared),
            "by_outcome_mon": {k: v / WEI for k, v in declared_by_outcome.items()},
            "mean_declared_mon": {
                "paid": declared_by_outcome["paid"] / WEI / max(sum(kind_paid_n.values()), 1),
                "failed": declared_by_outcome["failed"] / WEI / max(sum(kind_failed_n.values()), 1),
                "silent": declared_by_outcome["silent"] / WEI / max(sum(kind_silent_n.values()), 1),
            },
        },
        "paid": {
            "total_mon": paid_total / WEI,
            "total_usd": paid_total / WEI * usd,
            "per_day_usd": paid_total / WEI * usd / 7,
            "mean_per_paid_tx_mon": (paid_total / max(sum(kind_paid_n.values()), 1)) / WEI,
        },
        "gas_ceiling": {
            "note": "gas_limit x gas_price is a CEILING, not measured gasUsed",
            "total_mon": gas_ceiling_wei / WEI,
            "total_usd": gas_ceiling_wei / WEI * usd,
            "per_day_usd": gas_ceiling_wei / WEI * usd / 7,
        },
        "searchers": {
            "distinct_from": len(by_searcher_n),
            "distinct_searcher_to": len(by_target_wei),
            "top_from": [
                {"addr": k, "paid_mon": v / WEI, "paid_usd": v / WEI * usd,
                 "n_paid": by_searcher_n[k], "share_pct": 100 * v / max(paid_total, 1)}
                for k, v in by_searcher_wei.most_common(10)
            ],
            "top_searcher_to": [
                {"addr": k, "paid_mon": v / WEI, "share_pct": 100 * v / max(paid_total, 1)}
                for k, v in by_target_wei.most_common(10)
            ],
        },
        "flags": dict(flags),
        "by_day": {
            d: {"n_tx": by_day_n[d], "declared_mon": by_day_declared[d] / WEI}
            for d in sorted(by_day_n)
        },
    }

    p = out / "census_7d_tiers.json"
    p.write_text(json.dumps(res, indent=2))

    top5 = sum(x["share_pct"] for x in res["searchers"]["top_from"][:5])
    print(f"logs={n_logs:,}  census_tx={n_census:,}  blocks_with_bid={len(blocks):,}")
    print(f"paid={res['outcome']['paid_tx']:,}  failed={res['outcome']['failed_tx']:,}  "
          f"silent={res['outcome']['silent_tx']:,}")
    for k, v in sorted(res["by_kind"].items(), key=lambda x: -x[1]["n"]):
        print(f"  kind={k:14s} n={v['n']:>9,}  paid={v['paid']:>9,}  "
              f"failed={v['failed']:>8,}  silent={v['silent']:>8,}  ${v['paid_usd']:,.0f}")
    print(f"duplicates dropped: log={n_log_dup:,}  census={n_census_dup:,}")
    print(f"declared_total={res['bid_declared']['total_mon']:,.2f} MON  "
          f"median={res['bid_declared']['median_mon']:.9f} MON")
    mo = res["bid_declared"]["mean_declared_mon"]
    for st in ("paid", "failed", "silent"):
        print(f"  declared[{st:6s}] total={declared_by_outcome[st]/WEI:>14,.2f} MON  "
              f"mean={mo[st]:.6f} MON")
    print(f"paid_total={res['paid']['total_mon']:,.2f} MON = ${res['paid']['total_usd']:,.0f} "
          f"({res['paid']['per_day_usd']:,.0f}/day)")
    print(f"gas_ceiling=${res['gas_ceiling']['per_day_usd']:,.0f}/day (CEILING)")
    print(f"searchers: from={res['searchers']['distinct_from']:,} "
          f"to={res['searchers']['distinct_searcher_to']:,}  top5={top5:.1f}%")
    print(f"-> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
