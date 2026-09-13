#!/usr/bin/env python3
"""Measure the FastLane MEV auction plus chain wide priority fees over a >=7 day window.

Reads a local block+receipt archive (zstd jsonl chunks). Does not call
eth_getLogs or eth_getBlockByNumber on a live tip.

Required environment:
  FL_ARCHIVE   directory of blocks_<lo>_<hi>.jsonl.zst chunks
Optional:
  FL_OUT       output directory (default: ./out)

Example:
  export FL_ARCHIVE=/path/to/archive/chunks
  nice -n 19 ionice -c3 python3 fastlane_auction_7d.py --follow-progress --days 7
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keccak256 import keccak256  # noqa: E402

_ARCHIVE_ENV = os.environ.get("FL_ARCHIVE", "").strip()
if not _ARCHIVE_ENV:
    print("FATAL: set FL_ARCHIVE to the directory of zstd block+receipt chunks", file=sys.stderr)
    raise SystemExit(2)
ARCHIVE = Path(_ARCHIVE_ENV)
OUT = Path(os.environ.get("FL_OUT", str(Path.cwd() / "out")))
FASTLANE = "0xd32edf6642d917dbbe7b8bf8e5d6f5df6a9fff58"
CHAIN_ID = 143
WINDOW_SEC = 7 * 86_400
CHUNK_RE = re.compile(r"^blocks_(\d+)_(\d+)\.jsonl\.zst$")
WEI = 10**18
BATCH = 64  # zst files per zstd invocation


def topic(sig: str) -> str:
    return "0x" + keccak256(sig.encode()).hex()


def selector(sig: str) -> str:
    return "0x" + keccak256(sig.encode()).hex()[:8]


EV = {
    "RelayFeeCollected": topic("RelayFeeCollected(address,uint64,uint256)"),
    "RelayBidFailed": topic("RelayBidFailed(address,bytes)"),
    "RelayWithdrawStuckNativeToken": topic("RelayWithdrawStuckNativeToken(address,uint256)"),
    "RelayWithdrawStuckERC20": topic("RelayWithdrawStuckERC20(address,address,uint256)"),
}
TOPIC_SET = {v.lower() for v in EV.values()}
TOPIC_NAME = {v.lower(): k for k, v in EV.items()}
SEL_BID = selector("flashExecutionBid(uint256,bytes32[],uint256,bool,bool,address,bytes)")


def utc(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunk_index() -> list[tuple[int, int, Path]]:
    idx = []
    for e in os.scandir(ARCHIVE):
        m = CHUNK_RE.match(e.name)
        if not m:
            continue
        idx.append((int(m.group(1)), int(m.group(2)), Path(e.path)))
    idx.sort()
    return idx


def first_line_ts(path: Path) -> tuple[int, int]:
    """(block, ts) of the first record in a chunk."""
    p = subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE)
    assert p.stdout is not None
    line = p.stdout.readline()
    p.kill()
    r = json.loads(line)
    b = r.get("block", r)
    n = int(b["number"], 16) if isinstance(b["number"], str) else b["number"]
    ts = int(b["timestamp"], 16) if isinstance(b["timestamp"], str) else b["timestamp"]
    return n, ts


def last_line_ts(path: Path) -> tuple[int, int]:
    p = subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE)
    assert p.stdout is not None
    line = None
    for line in p.stdout:
        pass
    p.wait()
    r = json.loads(line)
    b = r.get("block", r)
    n = int(b["number"], 16) if isinstance(b["number"], str) else b["number"]
    ts = int(b["timestamp"], 16) if isinstance(b["timestamp"], str) else b["timestamp"]
    return n, ts


def find_start_chunk(idx: list[tuple[int, int, Path]], start_ts: int) -> int:
    """Index of the first chunk that may contain a block with ts >= start_ts."""
    lo, hi = 0, len(idx) - 1
    ans = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        _, ts = first_line_ts(idx[mid][2])
        if ts < start_ts:
            lo = mid + 1
            ans = lo
        else:
            hi = mid - 1
            ans = mid
    return max(0, min(ans, len(idx) - 1))


def decode_bid_calldata(data: str):
    d = data[2:] if data.startswith("0x") else data
    if not d.startswith(SEL_BID[2:]):
        return None

    def word(i):
        return d[8 + i * 64 : 8 + (i + 1) * 64]

    try:
        bid = int(word(0), 16)
        off_hashes = int(word(1), 16) // 32
        target = int(word(2), 16)
        exec_on_loss = int(word(3), 16) == 1
        pay_on_fail = int(word(4), 16) == 1
        searcher_to = "0x" + word(5)[-40:]
        n_hashes = int(word(off_hashes), 16)
    except (ValueError, IndexError):
        return None
    return {
        "bid_wei": bid,
        "target_block": target,
        "execute_on_loss": exec_on_loss,
        "pay_bid_on_fail": pay_on_fail,
        "searcher_to": searcher_to,
        "n_hashes": n_hashes,
        "kind": "top_of_block" if n_hashes == 1 else ("backrun_bundle" if n_hashes == 2 else f"n={n_hashes}"),
    }


def open_out(name: str):
    OUT.mkdir(parents=True, exist_ok=True)
    return (OUT / name).open("w")


def write_progress(meta: dict) -> None:
    (OUT / "progress.json").write_text(json.dumps(meta, indent=2) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="FastLane 7 day measurement from a local archive")
    ap.add_argument("--days", type=float, default=7.0, help="window length in days")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--mon-usd", type=float, default=0.0, help="if >0, write USD into summary")
    ap.add_argument("--price-source", default="not recorded")
    ap.add_argument("--end-block", type=int, default=0, help="0 = archive tip (last chunk)")
    ap.add_argument("--follow-progress", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    lock_path = OUT / "fastlane_7d.lock"
    if lock_path.exists():
        try:
            old = int(lock_path.read_text().strip().split()[0])
        except ValueError:
            old = -1
        if old > 0 and Path(f"/proc/{old}").exists():
            print(f"FATAL: already running pid={old} (delete {lock_path} if stale)", file=sys.stderr)
            return 3
    lock_path.write_text(f"{os.getpid()} {int(time.time())}\n")

    if not ARCHIVE.is_dir():
        print(f"FATAL: archive not found: {ARCHIVE}", file=sys.stderr)
        lock_path.unlink(missing_ok=True)
        return 2

    try:
        return _main_locked(a, lock_path)
    finally:
        if lock_path.exists() and lock_path.read_text().startswith(str(os.getpid())):
            lock_path.unlink(missing_ok=True)


def _main_locked(a: argparse.Namespace, lock_path: Path) -> int:
    t_wall0 = time.time()
    idx = chunk_index()
    if not idx:
        print("FATAL: archive is empty", file=sys.stderr)
        return 2

    end_block = a.end_block or idx[-1][1]
    tip_path = None
    for lo, hi, p in reversed(idx):
        if lo <= end_block <= hi:
            tip_path = p
            break
    if tip_path is None:
        print(f"FATAL: end_block {end_block} is not in the archive", file=sys.stderr)
        return 2
    tip_n, tip_ts = last_line_ts(tip_path)
    end_ts = tip_ts
    window_sec = int(a.days * 86_400)
    start_ts = end_ts - window_sec

    start_i = find_start_chunk(idx, start_ts)
    start_i = max(0, start_i - 1)
    files = [p for lo, hi, p in idx[start_i:] if lo <= end_block]

    window = {
        "chain_id": CHAIN_ID,
        "source": "local_archive",
        "archive": "<redacted>",
        "contract": "0xD32EdF6642D917DbBE7B8BF8e5d6F5df6a9FFF58",
        "measured_at_unix": int(time.time()),
        "measured_at_utc": utc(int(time.time())),
        "window_sec": window_sec,
        "days": a.days,
        "end_block_requested": end_block,
        "end_ts_anchor": end_ts,
        "end_ts_utc": utc(end_ts),
        "start_ts_target": start_ts,
        "start_ts_utc": utc(start_ts),
        "n_chunks_planned": len(files),
        "topics": EV,
        "selector_flashExecutionBid": SEL_BID,
        "note": "start/end block numbers are filtered by timestamp during the scan",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "window.json").write_text(json.dumps(window, indent=2) + "\n")
    print(json.dumps(window, indent=2), flush=True)
    print(f"scan {len(files):,} chunks from {files[0].name} ...", flush=True)

    logs_fh = open_out("logs.ndjson")
    census_fh = open_out("census_txs.ndjson")

    agg = {
        "n_blocks": 0,
        "n_tx": 0,
        "gas_used": 0,
        "fee_wei": 0,
        "burn_wei": 0,
        "tip_wei": 0,
        "n_reverted": 0,
        "n_fl_logs": 0,
        "n_fl_txs": 0,
        "n_relay_fee": 0,
        "relay_fee_wei": 0,
        "n_bid_failed": 0,
        "first_block": None,
        "last_block": None,
        "first_ts": None,
        "last_ts": None,
    }
    by_to_tip: dict[str, int] = defaultdict(int)
    by_day_tip: dict[str, int] = defaultdict(int)
    by_day_relay: dict[str, int] = defaultdict(int)
    by_day_fl_tx: dict[str, int] = defaultdict(int)

    done_chunks = 0
    t0 = time.time()

    def flush_progress(force: bool = False) -> None:
        if not a.follow_progress and not force:
            return
        el = time.time() - t0
        rate = done_chunks / el if el > 0 else 0
        eta = (len(files) - done_chunks) / rate if rate > 0 else None
        write_progress(
            {
                "done_chunks": done_chunks,
                "total_chunks": len(files),
                "pct": round(100.0 * done_chunks / len(files), 2) if files else 0,
                "elapsed_s": round(el, 1),
                "eta_s": round(eta, 1) if eta is not None else None,
                "agg": {k: agg[k] for k in agg},
                "updated_at_unix": int(time.time()),
            }
        )

    for bi in range(0, len(files), a.batch):
        batch = files[bi : bi + a.batch]
        cmd = ["zstd", "-dc", *[str(p) for p in batch]]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        assert proc.stdout is not None
        for raw in proc.stdout:
            rec = json.loads(raw)
            blk = rec.get("block", rec)
            receipts = rec.get("receipts") or []
            n = int(blk["number"], 16) if isinstance(blk["number"], str) else blk["number"]
            if n > end_block:
                continue
            ts = int(blk["timestamp"], 16) if isinstance(blk["timestamp"], str) else blk["timestamp"]
            if ts < start_ts or ts > end_ts:
                continue

            base = int(blk.get("baseFeePerGas", "0x0"), 16)
            txs = blk.get("transactions") or []
            day = utc(ts)[:10]

            to_of = {}
            for t in txs:
                if isinstance(t, str):
                    continue
                to_of[t["hash"]] = (t.get("to") or "0x0").lower()

            for r in receipts:
                gu = int(r["gasUsed"], 16)
                egp = int(r.get("effectiveGasPrice", "0x0"), 16)
                fee = gu * egp
                burn = gu * base
                tip = fee - burn
                agg["n_tx"] += 1
                agg["gas_used"] += gu
                agg["fee_wei"] += fee
                agg["burn_wei"] += burn
                agg["tip_wei"] += tip
                if int(r.get("status", "0x1"), 16) == 0:
                    agg["n_reverted"] += 1
                to_addr = to_of.get(r["transactionHash"], "0x0")
                by_to_tip[to_addr] += tip
                by_day_tip[day] += tip

                for lg in r.get("logs") or []:
                    topics = lg.get("topics") or []
                    if not topics:
                        continue
                    t0x = topics[0].lower()
                    if t0x not in TOPIC_SET:
                        continue
                    if (lg.get("address") or "").lower() != FASTLANE:
                        continue
                    logs_fh.write(json.dumps(lg, separators=(",", ":")) + "\n")
                    agg["n_fl_logs"] += 1
                    name = TOPIC_NAME[t0x]
                    if name == "RelayFeeCollected":
                        amt = int(lg["data"], 16)
                        agg["n_relay_fee"] += 1
                        agg["relay_fee_wei"] += amt
                        by_day_relay[day] += amt
                    elif name == "RelayBidFailed":
                        agg["n_bid_failed"] += 1

            for t in txs:
                if isinstance(t, str):
                    continue
                if (t.get("to") or "").lower() != FASTLANE:
                    continue
                dec = decode_bid_calldata(t.get("input", "0x"))
                row = {
                    "block": n,
                    "ts": ts,
                    "base_fee_wei": base,
                    "tx": t["hash"],
                    "from": t["from"],
                    "tx_index": int(t["transactionIndex"], 16),
                    "value_wei": int(t["value"], 16),
                    "gas_limit": int(t["gas"], 16),
                    "gas_price_wei": int(t.get("gasPrice", "0x0"), 16),
                    "max_fee_wei": int(t.get("maxFeePerGas", "0x0") or "0x0", 16),
                    "prio_fee_wei": int(t.get("maxPriorityFeePerGas", "0x0") or "0x0", 16),
                    "input_len": len(t.get("input", "0x")) // 2 - 1,
                }
                if dec:
                    row.update(dec)
                else:
                    row["kind"] = "not_flashExecutionBid"
                    row["selector"] = t.get("input", "0x")[:10]
                census_fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                agg["n_fl_txs"] += 1
                by_day_fl_tx[day] += 1

            agg["n_blocks"] += 1
            if agg["first_block"] is None:
                agg["first_block"] = n
                agg["first_ts"] = ts
            agg["last_block"] = n
            agg["last_ts"] = ts

        rc = proc.wait()
        done_chunks += len(batch)
        if done_chunks % (a.batch * 4) == 0 or done_chunks >= len(files):
            el = time.time() - t0
            print(
                f"  {done_chunks:>7,}/{len(files):,} chunk | {el:7.1f}s |"
                f" blocks={agg['n_blocks']:,} fl_logs={agg['n_fl_logs']:,}"
                f" fl_tx={agg['n_fl_txs']:,} | rc={rc}",
                flush=True,
            )
            flush_progress(force=True)

    logs_fh.close()
    census_fh.close()

    top_to = sorted(by_to_tip.items(), key=lambda kv: -kv[1])[:50]
    chain_fees = {
        "window": {
            "first_block": agg["first_block"],
            "last_block": agg["last_block"],
            "first_ts": agg["first_ts"],
            "last_ts": agg["last_ts"],
            "first_utc": utc(agg["first_ts"]) if agg["first_ts"] else None,
            "last_utc": utc(agg["last_ts"]) if agg["last_ts"] else None,
            "span_sec": (agg["last_ts"] - agg["first_ts"]) if agg["first_ts"] and agg["last_ts"] else None,
        },
        "n_blocks": agg["n_blocks"],
        "n_tx": agg["n_tx"],
        "n_reverted": agg["n_reverted"],
        "gas_used": agg["gas_used"],
        "fee_wei": agg["fee_wei"],
        "burn_wei": agg["burn_wei"],
        "tip_wei": agg["tip_wei"],
        "by_day_tip_wei": dict(sorted(by_day_tip.items())),
        "top50_to_tip_wei": [{"to": k, "tip_wei": v} for k, v in top_to],
    }
    (OUT / "chain_fees.json").write_text(json.dumps(chain_fees, indent=2) + "\n")

    fl = {
        "n_fl_logs": agg["n_fl_logs"],
        "n_relay_fee": agg["n_relay_fee"],
        "relay_fee_wei": agg["relay_fee_wei"],
        "n_bid_failed": agg["n_bid_failed"],
        "n_fl_txs": agg["n_fl_txs"],
        "by_day_relay_wei": dict(sorted(by_day_relay.items())),
        "by_day_fl_tx": dict(sorted(by_day_fl_tx.items())),
    }
    if a.mon_usd > 0:
        fl["mon_usd"] = a.mon_usd
        fl["price_source"] = a.price_source
        fl["relay_fee_usd"] = agg["relay_fee_wei"] / WEI * a.mon_usd
        fl["tip_usd"] = agg["tip_wei"] / WEI * a.mon_usd
        fl["fastlane_share_of_tips"] = (
            agg["relay_fee_wei"] / agg["tip_wei"] if agg["tip_wei"] else None
        )

    summary = {
        "window": chain_fees["window"],
        "fastlane": fl,
        "chain": {
            "fee_wei": agg["fee_wei"],
            "burn_wei": agg["burn_wei"],
            "tip_wei": agg["tip_wei"],
            "n_tx": agg["n_tx"],
            "n_blocks": agg["n_blocks"],
        },
        "elapsed_s": round(time.time() - t_wall0, 1),
        "out_dir": "<redacted>",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_progress(
        {
            "done_chunks": done_chunks,
            "total_chunks": len(files),
            "pct": 100.0,
            "elapsed_s": round(time.time() - t0, 1),
            "eta_s": 0,
            "agg": agg,
            "finished": True,
            "updated_at_unix": int(time.time()),
        }
    )

    print(json.dumps(summary, indent=2), flush=True)
    print(f"[ok] done -> {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
