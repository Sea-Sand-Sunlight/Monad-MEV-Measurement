# Monad MEV Measurement. Method

*Companion to [`mev_transparency_monad_en_2026-09-06.md`](mev_transparency_monad_en_2026-09-06.md).
Version 1, 2026-09-06. Measurement window 2026-08-23 → 2026-08-30.*

This page exists because we are asking you to believe some numbers about a system whose only other
public numbers come from the party operating it. You should be able to check ours without asking
us anything.

---

## 1. Scope

We measure two quantities over one exact window on Monad mainnet (chain ID 143):

1. **Auction bids**, value collected by the FastLane auction contract.
2. **Chain wide priority fees**, the tip component of every transaction fee on the chain.

We do **not** measure: searcher profit, MEV "extracted" in any economic sense, sandwich or
liquidation attribution, or where a bid goes after it enters the contract.

---

## 2. Data source

| | |
|---|---|
| Node | One self operated Monad mainnet full node, chain ID 143 |
| Archive | Local continuous block + receipt archive, running since 2026-08-21 |
| Third party data | None. No indexer, no vendor API, no public RPC backfill |
| Access level | None privileged, a standard node with receipts is sufficient |

The node retains transactions and receipts for roughly 1.6–2 days, which is why the seven day
window is taken from the local archive rather than from the node directly. The archive is written
continuously by a separate recorder process; the measurement scripts only read files.

**Gap check.** The window is required to be one unbroken block range. The run reports 0 gaps for
this window. A run with any gap is discarded rather than interpolated.

---

## 3. Window definition

The window is anchored to the archive tip at scan time and extends back exactly 604,800 seconds.
It is defined in seconds, not in calendar days.

| | |
|---|---|
| Start | block 98,445,350 · timestamp 1787477976 · 2026-08-23T09:39:36Z |
| End | block 100,436,203 · timestamp 1788082776 · 2026-08-30T09:39:36Z |
| Span | 604,800 s · 1,990,854 blocks · 37,526,205 transactions |

Because the anchor is 09:39:36Z and not midnight, the first and last calendar days in any per day
table are **partial**. We label them and we do not compute a "per day" figure by dividing by
calendar days, the daily mean is always `total ÷ 7`, using the full 604,800 s.

---

## 4. Auction measurement

**Contract.** `0xD32EdF6642D917DbBE7B8BF8e5d6F5df6a9FFF58` (`FastLaneAuctionHandler`), verified on
MonadScan; source read from [FastLane-Labs/monad-auction](https://github.com/FastLane-Labs/monad-auction).

**Events.** Topic hashes are computed in process by hashing the signature string, never copied
from a block explorer:

| Event | Signature | topic0 |
|---|---|---|
| Fee collected | `RelayFeeCollected(address,uint64,uint256)` | `0x17f45ae963f99b4d1929ba44f0acd3d95021fd4ccf3ec9af9d3dcdb7417274bd` |
| Bid failed | `RelayBidFailed(address,bytes)` | `0xbe877e9fd96672907d8df80a513570f0220a522480acbe4c0e8b2c63af9fbec2` |
| Withdraw (native) | `RelayWithdrawStuckNativeToken(address,uint256)` | `0x81a2140e856260bc8f016ea5945b13611668fb5f3fcf1ab0beb261e09149cfaa` |
| Withdraw (ERC20) | `RelayWithdrawStuckERC20(address,address,uint256)` | `0x926728cf17c245d940beb38b77b4f8bc09b8d54bb7564f5d53598c12607fe934` |

Collected value is the `uint256` in the log `data` field. Neither withdraw event occurred in this
window.

**Census.** Separately from the logs, every transaction with `to == FastLaneAuctionHandler` is
recorded with its calldata decoded against

```
flashExecutionBid(uint256,bytes32[],uint256,bool,bool,address,bytes)  →  selector 0x0c7abd22
```

giving, per submission: declared bid amount, target block, the array of target transaction hashes,
the `executeOnLoss` and `payBidOnFail` flags, and the searcher's destination contract.

**Classification.** A submission with exactly one target hash is *top of block*; two or more is a
*backrun bundle*. This is a property of the calldata, not an inference.

**Three tier join.** Census transactions are matched to logs by transaction hash:

| Tier | Definition |
|---|---|
| Paid | at least one `RelayFeeCollected` |
| Failed | a `RelayBidFailed`, no fee collected |
| Silent | present in census, emitted no contract event at all |

---

## 5. Chain wide fee measurement

For every transaction in every block in the window, from its receipt:

```
fee_paid  = gasUsed × effectiveGasPrice
base_burn = gasUsed × baseFeePerGas
priority  = gasUsed × (effectiveGasPrice − baseFeePerGas)
```

Priority fees are attributed to the transaction's `to` address to produce the ranking of tip
recipients. "Tips to the FastLane contract" means priority fees carried by transactions sent to the
handler, it is **not** the same quantity as bids collected, and conflating the two is the single
easiest way to get this wrong. In this window they differ by roughly 5× (84,455 MON of tips against
406,800 MON of bids).

---

## 6. Pricing

MON is priced from a single on chain source: the Uniswap V3 WMON/USDC pool
`0x659b…a9da`, spot at window close, **$0.02657**.

An earlier 24 hour sample used $0.02929, and figures anchored to that price are labelled as such
wherever both appear. Every table reports MON alongside USD so any reader can substitute a
different price or a TWAP. No USD figure in the article depends on a price feed we control.

---

## 7. Verification

Eight checks, of which four carry over from the earlier 24 hour work and four are specific to this
window.

| # | Check | Result |
|---|---|---|
| 1 | Event topics and function selector derived by hashing signature strings in process | Match on chain logs |
| 2 | Calldata census ↔ emitted logs, both directions | 100%, no orphans |
| 3 | Manual decode of sampled calldata against the ABI | Match |
| 4 | Local node vs public RPC, same blocks | Absolute match, wei for wei |
| 5 | Duplicate scan: `(txHash, logIndex)` pairs and census tx hashes | 0 duplicates in 3,450,615 logs and 3,667,074 txs |
| 6 | Log conservation: `paid + failed == total contract logs` | 3,016,355 + 434,260 = 3,450,615 exactly |
| 7 | Declared bid vs collected fee, per winning transaction | Identical for all 3,016,355, sums to 406,799.52 MON on both sides |
| 8 | Window robustness: full pipeline rerun on a window shifted 29.5 minutes | All aggregates within 0.4%, see below |

Check 7 deserves a note: the declared amount comes from calldata and the collected amount comes
from an event log. They are read by different code paths from different parts of the archive, and
they agree exactly across three million transactions. That is the strongest internal evidence we
have that the decoder is correct.

### 7.1 Two pass window robustness

The pipeline was run twice, over two overlapping 604,800 second windows anchored 29.5 minutes
apart. This is not a repeat of the same computation; it is a different sample of the chain.

| Aggregate | Pass 1 (09:10:06Z anchor) | Pass 2 (09:39:36Z anchor) | Delta |
|---|---:|---:|---:|
| Auction bids collected (MON) | 408,280.98 | 406,799.52 | −0.363% |
| Chain priority tips (MON) | 877,199.91 | 874,670.66 | −0.288% |
| Total gas fees (MON) | 4,068,864.57 | 4,066,006.37 | −0.070% |
| Transactions | 37,543,444 | 37,526,205 | −0.046% |
| Handler transactions | 3,666,210 | 3,667,074 | +0.024% |

The published article uses **pass 2 throughout**, because pass 2 is the run that also produced the
transaction level artifacts. Pass 1 is retained as the comparison. The differences are entirely
explained by the boundary blocks entering and leaving the window; they are not corrections.

---

## 8. Known gaps

Ranked by how much they would change a conclusion if someone fixed them.

1. **No execution traces.** Without them there is no searcher revenue side and therefore no
   profitability claim of any kind. This is the largest single gap.
2. **Gas cost is a ceiling, not a measurement.** The `gasLimit × gasPrice` figure in the article's
   section 3.8 is an upper bound. Actual consumption requires a receipt level pass over the same
   window, which we have done for 24 hours but not for 7 days.
3. **Priority fee ≠ MEV.** We measure payment for ordering. No intent is inferred, and ordinary
   user tips are included in the chain wide total.
4. **No entity resolution.** 172 sender addresses may be fewer than 172 operators. We do not
   cluster and do not speculate.
5. **Single price source, single timestamp.** No TWAP, no cross venue check.
6. **Archive depth.** Nothing before 2026-08-21 exists locally, so no seasonal or longer horizon
   comparison is possible from this data.
7. **Bid destination unverified.** We measure value entering the contract. FastLane's published
   design routes most of it to validators and shMON; we did not confirm that on chain.
8. **Window is one week in a declining period.** Peak to trough inside the window is 6.6×.
   Extrapolating a month from it would be unsound.

---

## 9. Rerunning this

```
export FL_ARCHIVE=/path/to/archive/chunks
export FL_OUT=./out

# 1. archive scan: auction logs + tx census + chain wide fees
nice -n 19 ionice -c3 python3 fastlane_auction_7d.py --follow-progress --days 7

# 2. tier join: paid/failed/silent, bid distribution, sender ranking
nice -n 19 ionice -c3 python3 fastlane_census_7d.py --mon-usd 0.02657
```

Step 1 is I/O bound: 1,990,854 blocks in 1,736 s on one machine at lowest scheduling priority.
Step 2 is a single streaming pass over 4.2 GB of NDJSON, about 35 s.

Neither step calls an RPC endpoint. Point `FL_ARCHIVE` at any Monad archive that stores blocks with
receipts and the same numbers should fall out; if they do not, we would like to know.

---

## 10. Corrections log

Corrections to published figures are recorded here rather than edited silently.

| Date | Change |
|---|---|
| 2026-09-06 | v1. No corrections yet. |

Earlier internal drafts of this measurement quoted the 24 hour sample (≈ $2,862/day in auction
bids) without a variance caveat. That figure is superseded by the seven day mean of $1,544/day and
should not be cited as typical; it is retained in the article only as a comparison point.
