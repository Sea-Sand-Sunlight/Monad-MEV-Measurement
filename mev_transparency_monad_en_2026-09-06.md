# What MEV Pulse does not show: a full chain, 7 day measurement of Monad priority payments

*Published 2026-09-06. Window measured 2026-08-23 → 2026-08-30.*

Method and limitations: [`methodology_fastlane_en_2026-09-06.md`](methodology_fastlane_en_2026-09-06.md).

---

## Abstract

Monad's only public MEV dashboard, [MEV Pulse](https://mev-pulse.fastlane.xyz/), is operated by
FastLane, the team that runs the auction it reports on. It is real, it is useful, and our numbers
agree with it in order of magnitude. It is also denominated in MON, scoped to the auction, and has
no methodology page.

We remeasured the same auction from an independent Monad mainnet node plus a continuous local
archive, over an exact 604,800 second window (2026-08-23 09:39:36Z → 2026-08-30 09:39:36Z), and we
also measured the thing the dashboard does not cover: chain wide priority fees.

Over those seven days the FastLane auction collected **406,800 MON** in paid bids, an average of
**58,114 MON/day (≈ $1,544/day** at MON = $0.02657). Chain wide priority tips over the same window
ran **124,953 MON/day (≈ $3,320/day)**. The official auction is therefore roughly **one third of
total on chain priority payments**, the dashboard shows the smaller flow.

Three further results come out of the transaction level census. Of 3,667,074 bid transactions,
**zero were backrun bundles**; every one was top of block. Only **172 distinct addresses** ever
placed a winning bid, with the top five taking 46% of all fees paid. And searchers declared
**2,972,711 MON** of bids while paying **406,800 MON**, because `payBidOnFail` was `false` on
100% of submissions, a losing bid costs only gas.

---

## 1. Why this exists

This is not a "nobody has measured Monad MEV" article. Somebody has: FastLane ships MEV Pulse, it
updates in real time, and when we pulled a day sample from its GraphQL endpoint on 2026-08-26 it
reported 387,844 auction events for 2026-08-20, the same shape and the same order of magnitude as
our own independent count of 430,908 paid bid events per day. An operator run dashboard that
independently reproduces is worth saying out loud.

The gap is not existence. It is scope, unit, and reproducibility:

| MEV Pulse reports | Not covered |
|---|---|
| MON only | No USD denomination, no price source, no timestamp |
| The FastLane auction channel | No chain wide priority fees, the larger flow |
| Bids collected | No paid / failed / silently skipped split |
| Auction totals | No backrun vs top of block classification |
| Revenue side | No cost side |
| Cumulative counters | No per day series; no window definition |
| | `/methodology` returns **404** (checked again 2026-09-06) |

None of these are errors. They are the natural boundary of a dashboard built to show an auction.
They are also exactly the boundary that matters if you want to know how much value actually moves
through priority ordering on Monad, rather than how much moves through one venue for it.

---

## 2. What we measured

One Monad mainnet node (chain 143) and a continuous block+receipt archive running since
2026-08-21. No vendor data, no third party indexer, no public RPC backfill.

Two independent quantities, from two different sources in the same window:

1. **Auction bids.** Every `RelayFeeCollected` and `RelayBidFailed` log emitted by the
   `FastLaneAuctionHandler` contract at `0xD32EdF6642D917DbBE7B8BF8e5d6F5df6a9FFF58`, plus a
   census of every transaction sent to that address with its `flashExecutionBid` calldata decoded.
2. **Chain wide priority fees.** For every transaction in every block,
   `gasUsed × (effectiveGasPrice − baseFeePerGas)`.

These are separate money flows and we do not net them against each other. An auction bid is paid
inside the contract call; the priority fee is paid on the transaction that carries it. A bid
transaction pays both.

Full method, event topic hashes, verification layers and known weaknesses are in the
[methodology page](methodology_fastlane_en_2026-09-06.md). Every figure below is reproducible from
the published JSON artifacts and scripts.

---

## 3. Results

### 3.1 The window

| | |
|---|---:|
| Start | block 98,445,350 · 2026-08-23 09:39:36 UTC |
| End | block 100,436,203 · 2026-08-30 09:39:36 UTC |
| Span | 604,800 s exactly · 1,990,854 blocks · 37,526,205 transactions |
| Gaps in archive | 0 |
| Average block time | 303.8 ms · 62.0 tx/s |
| Reverted transactions | 1,329,726 (3.54%) |

### 3.2 The auction is about a third of priority payments

| Flow | MON / 7d | MON / day | USD / day |
|---|---:|---:|---:|
| Total gas fees paid | 4,066,006 | 580,858 | $15,433 |
| base fee, burned (78.5%) | 3,191,336 | 455,905 | $12,113 |
| **priority fees to validators (21.5%)** | **874,671** | **124,953** | **$3,320** |
| **FastLane auction bids collected** | **406,800** | **58,114** | **$1,544** |
| Priority tips attached to auction txs | 84,455 | 12,065 | $321 |

Priority fees and auction bids together are about **$4,864/day**. The public dashboard covers the
**$1,544**, i.e. **31.7%**. Put the other way, roughly **two thirds of what users and searchers pay
for ordering on Monad never touches the official auction.**

Two caveats we want stated before anyone quotes that number. First, chain wide priority fees are
not all MEV, ordinary users tip too, and we make no attempt to separate intent. Second, FastLane's
published design routes most of each bid onward to validators and shMON; we did not verify that
split on chain and nothing above depends on it.

The auction's own footprint is larger than its share of value. Transactions to the handler were
**3,667,074, 9.77% of every transaction on Monad** in the window, and **62.6% of all blocks**
contained at least one bid. Those transactions carried **9.66%** of all chain priority tips, almost
exactly their share of transaction count: auction traffic tips at the chain average rate and buys
no ordering premium with the tip itself.

### 3.3 One day is not a sample

The 24 hour sample we ran on 2026-08-23 put auction bids at ≈ $2,862/day. The seven day mean is
$1,544/day. The single day was not wrong; it was near a local peak.

| Day (UTC) | Auction bids (MON) | Chain tips (MON) | Bids ÷ tips |
|---|---:|---:|---:|
| 2026-08-23 * | 51,291 | 113,037 | 45.4% |
| 2026-08-24 | 106,032 | 193,632 | 54.8% |
| 2026-08-25 | 95,517 | 147,682 | 64.7% |
| 2026-08-26 | 50,322 | 117,185 | 42.9% |
| 2026-08-27 | 36,858 | 100,636 | 36.6% |
| 2026-08-28 | 46,589 | 140,967 | 33.0% |
| 2026-08-29 | 16,022 | 44,590 | 35.9% |
| 2026-08-30 * | 4,168 | 16,941 | 24.6% |

\* partial days: the window is anchored at 09:39:36Z, so the first and last calendar days are cut.
The ratio column is still comparable because both sides are cut identically.

Peak day to trough day is **6.6×** on the auction and the bids to tips ratio moves between 24.6%
and 64.7%. Any single day figure for Monad MEV, ours or anyone's, should carry that range next to
it. This is also why we declined to publish our own 24 hour number as a headline.

### 3.4 Inside the auction: paid, failed, silently skipped

Joining the 3,667,074 census transactions against the 3,450,615 contract logs gives a clean
three way split, with no orphans in either direction:

| Outcome | Transactions | Share |
|---|---:|---:|
| Paid, `RelayFeeCollected` | 3,016,355 | 82.26% |
| Failed, `RelayBidFailed` | 434,260 | 11.84% |
| No event emitted at all | 216,459 | 5.90% |

Our 24 hour sample in August found 79.93% / 14.93% / 5.13% on 424,180 transactions. The seven day
window reproduces that shape on nearly nine times the data.

### 3.5 Declared bids are 7× the bids actually paid

Every submission carries a bid amount in its calldata. Summed across all 3,667,074 submissions
that comes to **2,972,711 MON**. Actually collected: **406,800 MON, 13.68%**.

| Outcome | Declared (MON) | Mean declared per tx (MON) |
|---|---:|---:|
| Paid | 406,800 | 0.1349 |
| Failed | 2,364,326 | 5.4445 |
| No event | 201,585 | 0.9313 |

**The average losing bid is 40× the average winning bid.** The mechanism is visible in the
calldata: `payBidOnFail` was `false` on **100.00%** of all 3,667,074 submissions, and
`executeOnLoss` was `true` on 99.46%. A bid that does not execute costs its sender nothing but gas,
so there is no economic pressure against declaring a very large number and hoping.

This matters for anyone reading auction totals as a demand signal. The declared bid stack is not a
measure of willingness to pay; it is a measure of what is free to say.

Meanwhile the bids that do get paid are tiny. The median declared bid across the window is
**27 nano MON**, about 7 ten billionths of a cent. 1,307,066 submissions bid exactly 25 nano MON.
The mean *paid* bid is 0.1349 MON, roughly **$0.0036**. The distribution is extreme in both
directions, and there are 595,393 distinct bid values, so this is not a handful of bots repeating
one constant.

### 3.6 The official backrun channel is empty, all seven days of it

Every one of the **3,667,074** bid transactions in the window declared exactly one target
transaction hash. **Zero backrun bundles.** Not a low number: zero, across 1,990,854 blocks.

Our earlier 24 hour census found 0 of 424,180. Seven days at nearly nine times the volume returns
the same answer, which moves this from "an odd day" to a property of how the auction is currently
used.

The honest reading is narrow. The *permissionless backrun channel* is unused; backrunning itself is
not impossible on Monad, and ordinary transactions still compete through priority fees, which is
consistent with two thirds of priority payments sitting outside the auction. Monad has no public
mempool, so a searcher wanting to backrun has to see the target transaction some other way, and the
data says they are not doing it through this contract.

### 3.7 Who is actually bidding

Across seven days, winning bids came from **172 distinct sender addresses** routing through
**55 distinct searcher contracts**.

| | Share of all fees paid |
|---|---:|
| Top 1 sender | 22.9% |
| Top 5 senders | 46.2% |
| Top 10 senders | 65.1% |
| Top 1 destination contract | 24.7% |
| Top 5 destination contracts | 67.9% |

The full ranked list of addresses is in the published artifact. We have not attached names to any
of them: we have done no entity clustering and we are not going to guess which addresses belong to
the same operator, so 172 senders is an upper bound on the number of distinct participants.

### 3.8 The cost side

We can bound what searchers spend. Summing `gasLimit × gasPrice` over every bid transaction gives
**835,751 MON ≈ $3,172/day**, a ceiling, not actual spend, because we do not have `gasUsed` per
transaction in this pass. That ceiling is **2.05× the $1,544/day** the auction returns.

Our 24 hour receipt level measurement, which did have `gasUsed`, found searchers spending $5,563 to
pay $2,862, a ratio of 1.94. Two different windows and two different methods land in the same
place: **searchers commit on the order of twice the auction's payout in gas.**

We are deliberately not turning this into a claim about searcher profitability. Gas spend is not
loss; the winners are presumably capturing value elsewhere in the same transaction, and measuring
that needs execution traces we do not currently collect. What we can say is that the auction's
gross payout is small relative to the gas the competition for it consumes.

---

## 4. What we think this means

**The auction is not the MEV market; it is one venue in it.** A dashboard reporting $1,544/day is
accurate about itself and incomplete about Monad. Anyone sizing the opportunity, or arguing about
how much value validators capture, needs the $4,864/day figure and the split.

**Searchers are already routing around it.** Two thirds of priority payments and a completely
unused backrun channel point the same way.

**Free failure distorts the visible signal.** With `payBidOnFail` false everywhere, declared bid
volume is close to meaningless as a demand measure while collected fees are not. Any auction metric
should say which one it is reporting.

**Concentration is high and measurable.** 172 addresses, five of them taking nearly half. That is a
fact about competition on this chain that is currently not published anywhere.

---

## 5. Where this measurement is weakest

Stated plainly, because a number you cannot criticise is a number you cannot check:

- **No execution traces.** No searcher gross P&L, no revenue side, no true profitability. The gas
  figure above is a ceiling from `gasLimit`, not measured consumption.
- **Priority fees are not MEV.** We measure payments for ordering. Intent is not observable.
- **Seven days is seven days.** It covers a declining period; the peak to trough range within the
  window is 6.6×. It is not a claim about any other week.
- **One price source.** MON/USD is a single on chain spot reading (Uniswap V3 WMON/USDC) at window
  close. All MON figures are given so you can reprice.
- **Recent history only.** Our archive starts 2026-08-21. We cannot speak to anything earlier.
- **No entity resolution.** Addresses are addresses.
- **The bid/validator split is unverified.** We measured what enters the contract, not where it goes.

One robustness check we can offer: we ran the full pipeline twice over two overlapping seven day
windows anchored 29.5 minutes apart. Every aggregate agreed within **0.4%** (auction bids −0.363%,
chain tips −0.288%, total fees −0.070%). The measurement is not sensitive to where the window is
placed. The figures in this article are all from the later pass, which is the one with complete
transaction level artifacts.

---

## 6. Reproducing this

Everything here comes from files on disk plus two scripts, with no privileged access:

| Artifact | What it is |
|---|---|
| `fastlane_auction_7d.py` | Archive scan → auction logs, tx census, chain wide fee aggregation |
| `fastlane_census_7d.py` | Joins census against logs → paid/failed/silent, bid distribution, sender ranking |
| `*_summary.json` | Window, auction totals, per day series, chain fee/burn/tip |
| `*_chain_fees.json` | Per day tips, top recipients of priority fees |
| `*_census_tiers.json` | Every tier figure in section 3.4 to 3.8 |

The scan is I/O bound and took 29 minutes over 1.99M blocks on one machine at `nice 19`. It runs
against any Monad archive or RPC that can serve blocks with receipts; it does not need a modified
node.

---

## 7. Availability

We intend to keep this series running and public rather than publish once and stop. If you work on
Monad MEV, at FastLane, at Category Labs, at the Foundation, or independently, we are interested
in two things: comparing method with anyone maintaining competing numbers, and hearing which cuts
of this are worth maintaining.

Where we think we are wrong, we would rather be told than be quoted.

*Quang Nhan, independent researcher operating a Monad mainnet node.
Contact: quangnhan239@gmail.com*
