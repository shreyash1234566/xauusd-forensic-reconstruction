# Phase 6B native-artifact ingestion schema

## Intake location

Place copies of original artifacts in `data/native/incoming/`. The pipeline reads them in place, computes SHA-256, and never overwrites, renames, de-duplicates, or normalizes the raw sources.

## Supported sources

| Source | Accepted formats | Minimum evidence | Important non-assumption |
| --- | --- | --- | --- |
| Tick/quote export | CSV, TSV, Parquet | timestamp plus Bid and Ask for quote-side reachability | `Price` alone is not assumed to be Bid, Ask, Last or fill price. |
| Orders | CSV, TSV, HTML report | order ticket, state/type, time, symbol, volume | order ID is not assumed to equal deal ID. |
| Deals | CSV, TSV, HTML report | deal ticket, order/position relation where present, time, price, side | one order is not assumed to create one deal. |
| Positions | CSV, TSV, HTML report | position ID, direction, volume, open/close timing where present | positions are not collapsed into ledger rows before linkage. |
| Journal/Experts logs | TXT, LOG, CSV, HTML | documented timestamps/event messages | logs are not assumed to expose EA source or full internal state. |

## Validation protocol

For every artifact: record source path, SHA-256, size, encoding, delimiter, header, missing-value profile, duplicate policy, timestamp convention/timezone evidence, symbol evidence, and conservative role classification. Field meaning is accepted only when supplied documentation or native export headers establish it. Ambiguities remain `UNKNOWN_SCHEMA`.

## Acceptance gates before Phase 6C

A provenance; B XAUUSD.f/equivalence; C timestamp coverage; D substantial entry alignment; E Bid/Ask execution reachability; F order/deal/position linkage. Failure at any gate is recorded and stops trigger reconstruction.
