# Data quality report

Rows touched by each cleaning rule. Quarantined rows are saved under `data/processed/quarantine/`.

## suppliers
Rows in: **28** | rows out: **25**

| Rule | Rows affected |
|---|---:|
| duplicate supplier records removed (kept most complete) | 3 |
| lead time text ('3 weeks', '21') -> days | 11 |
| payment terms text ('Net 45') -> days | 16 |
| city spelling standardised | 2 |
| GSTIN failed format check (flagged, not deleted) | 0 |
| contact e-mail missing (left blank) | 1 |

## items
Rows in: **302** | rows out: **300**

| Rule | Rows affected |
|---|---:|
| duplicate item rows removed | 2 |
| unit cost text ('Rs. 1,250.00') -> number | 207 |
| UoM spelling standardised | 31 |
| missing category filled from supplier category | 13 |
| items with unknown supplier (should be 0) | 0 |

## sales
Rows in: **232,514** | rows out: **229,084**

| Rule | Rows affected |
|---|---:|
| item_id re-formatted (case/space/hyphen) | 15,884 |
| quarantined: unknown item_id | 0 |
| quarantined: unparseable date | 0 |
| customer name standardised | 46,240 |
| missing UoM filled from item master | 2,340 |
| quantities converted to item base UoM (g/MT -> kg, ml -> litre) | 438 |
| UoM still different from base after conversion (should be 0) | 0 |
| duplicate rows removed | 3,430 |
| negative dispatched qty -> absolute value (sign error) | 439 |
| outlier schedule qty replaced by 7-row rolling median | 203 |
| missing dispatched qty := schedule qty (assume full shipment) | 2,309 |
| missing customer := item's most frequent customer not already on that date | 1,126 |

## purchase_orders
Rows in: **10,813** | rows out: **10,676**

| Rule | Rows affected |
|---|---:|
| quarantined: unknown item_id | 0 |
| supplier name mapped to supplier_id | 1,052 |
| quarantined: unknown supplier | 0 |
| price/quantity text ('Rs. 1,250.00', '1,200') -> number | 7,874 |
| duplicate PO lines removed | 104 |
| quarantined: receipt date before PO date | 33 |
| missing received qty on closed PO := order qty | 76 |

## inventory_snapshot
Rows in: **36,332** | rows out: **36,000**

| Rule | Rows affected |
|---|---:|
| duplicate snapshot rows removed | 332 |
| location format standardised | 5,368 |
| negative on-hand treated as missing | 63 |
| missing on-hand filled with neighbouring day (max 3 days) | 250 |
| still missing after fill (kept as blank) | 0 |

## reorder_policy
Rows in: **300** | rows out: **300**

| Rule | Rows affected |
|---|---:|
| safety stock missing (will be recomputed in Phase 4) | 8 |
| policy last reviewed more than 180 days before 2026-10-31 | 126 |
