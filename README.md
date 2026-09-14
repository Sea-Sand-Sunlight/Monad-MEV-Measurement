# Monad MEV Measurement

Independent 7 day measurement of Monad's FastLane MEV auction and
chain wide priority fees (2026-08-23 → 2026-08-30).

The only public Monad MEV dashboard is [MEV Pulse](https://mev-pulse.fastlane.xyz/).
It is real and useful. This repo publishes what it does not cover: a
USD denominated, full chain, reproducible window, with method and artifacts.

**Article:** [mev_transparency_monad_en_2026-09-06.md](mev_transparency_monad_en_2026-09-06.md)

**Method:** [methodology_fastlane_en_2026-09-06.md](methodology_fastlane_en_2026-09-06.md)

Headline from the measured window (MON = $0.02657 at close):

| Flow | USD / day |
|---|---:|
| FastLane auction bids collected | ≈ $1,544 |
| Chain wide priority fees | ≈ $3,320 |
| Auction share of those two flows | 31.7% |

Across 3,667,074 bid transactions: **zero** backrun bundles;
`payBidOnFail` was `false` on 100% of submissions.

Author: Quang Nhan
Email: quangnhan239@gmail.com
Available for measurement work.

---

## Reproduce

Requires Python 3.11+ and `zstd`. The scripts read a local block+receipt
archive. They do not call a live RPC.

```
export FL_ARCHIVE=/path/to/archive/chunks
export FL_OUT=./out

nice -n 19 ionice -c3 python3 fastlane_auction_7d.py --follow-progress --days 7
nice -n 19 ionice -c3 python3 fastlane_census_7d.py --mon-usd 0.02657
```

`FL_ARCHIVE` is required. There is no default path.

`keccak256.py` is original Keccak-256 (Ethereum padding `0x01`, not NIST
SHA-3). Event topics and the `flashExecutionBid` selector are hashed
in process:

```
python3 keccak256.py
```

must print three `ok` lines before you trust a new scan.

## Artifacts

`artifacts/` holds the JSON from the window used in the article (pass 2,
09:39:36Z anchor). Host paths have been removed. The large NDJSON files
(`logs.ndjson`, `census_txs.ndjson`) are not bundled; rerun the scan
against your own archive to regenerate them.
