# Ledgerlens audit report

**13 findings, $2,356.00 recoverable.**

| Class | Count |
|---|---|
| `billed_after_cancel` | 1 |
| `cannot_determine` | 3 |
| `conflict` | 2 |
| `credit_not_applied` | 1 |
| `duplicate_charge` | 1 |
| `price_over_contract` | 1 |
| `renewal_notice_due` | 2 |
| `seats_over_licensed` | 1 |
| `uplift_over_cap` | 1 |

## batch_01 (as of 2026-02-10)

### `price_over_contract`: Cloudkeep Ltd. / INV-CK-301 / CK-STORE-TB, $60.00

CK-STORE-TB billed at $23.00, agreed $21.50

Action: **dispute** (done). Rule: `unit_price_above_agreed`. Finding `a55e14b1`.

> line,CK-STORE-TB,Backup storage,2026-01-01,2026-01-31,40,23.00,920.00  
> source: `batch_01/005_cloudkeep_jan/INV-CK-301.csv`

> | CK-STORE-TB | Backup storage, per TB | 21.50 | 40 |  
> source: `batch_01/002_cloudkeep_order_form/OF-2026-019.txt`

### `seats_over_licensed`: Brightdesk Inc. / INV-BD-1078 / BD-PRO, $456.00

132 BD-PRO billed, 120 licensed and true-up not permitted

Action: **dispute** (done). Rule: `qty_above_licensed_no_true_up`. Finding `55935645`.

> line,BD-PRO,Pro seat,2026-02-01,2026-02-28,132,38.00,5016.00  
> source: `batch_01/008_brightdesk_feb/INV-BD-1078.csv`

> | BD-PRO | Brightdesk Pro seat | 38.00 | 120 |  
> source: `batch_01/001_brightdesk_order_form/OF-2025-311.txt`

### `billed_after_cancel`: Brightdesk Inc. / INV-BD-1078 / BD-ANALYTICS, $600.00

BD-ANALYTICS billed for 2026-02-01..2026-02-28 after cancellation effective 2026-02-01

Action: **dispute** (done). Rule: `cancelled_sku_billed`. Finding `c93f06fb`.

> line,BD-ANALYTICS,Analytics add-on,2026-02-01,2026-02-28,1,600.00,600.00  
> source: `batch_01/008_brightdesk_feb/INV-BD-1078.csv`

> Please cancel BD-ANALYTICS effective 2026-02-01  
> source: `batch_01/006_cancel_analytics`

### `renewal_notice_due`: Pagewise, $7,200.00

OF-2025-090 auto-renews 2026-04-01; notice is due by 2026-03-01 (19 days)

Action: **human_review** (recommended). Rule: `auto_renew_notice_window`. Finding `6c955b4a`.

> ORDER FORM OF-2025-090  
> source: `batch_01/003_pagewise_order_form/OF-2025-090.txt`


## batch_02 (as of 2026-09-15)

### `duplicate_charge`: Cloudkeep Ltd. / INV-CK-301A / CK-STORE-TB, $860.00

CK-STORE-TB for 2026-01-01..2026-01-31 already billed on INV-CK-301

Action: **dispute** (done). Rule: `same_sku_same_period`. Finding `92645054`.

> line,CK-STORE-TB,Backup storage,2026-01-01,2026-01-31,40,21.50,860.00  
> source: `batch_02/103_cloudkeep_rebill/INV-CK-301A.csv`

> invoice_id,INV-CK-301  
> source: `batch_01/005_cloudkeep_jan/INV-CK-301.csv`

### `uplift_over_cap`: Pagewise / INV-PW-077 / PW-TEAM, $30.00

PW-TEAM renewed at $13.20; cap allows $12.60 (from $12.00)

Action: **dispute** (done). Rule: `renewal_uplift_cap`. Finding `70225b40`.

> line,PW-TEAM,Team seat,2026-04-01,2026-04-30,50,13.20,660.00  
> source: `batch_02/104_pagewise_renewal/INV-PW-077.csv`

> | PW-TEAM | Pagewise Team seat | 12.00 | 50 |  
> source: `batch_01/003_pagewise_order_form/OF-2025-090.txt`

> Renewal uplift cap: 5%  
> source: `batch_01/003_pagewise_order_form/OF-2025-090.txt`

### `conflict`: Brightdesk Inc. / INV-BD-1190 / BD-PRO, $360.00

Agreements effective the same day disagree on BD-PRO: $36.00 vs $35.00

Action: **human_review** (recommended). Rule: `same_day_amendments_disagree`. Finding `8d6ff40e`.

> line,BD-PRO,Pro seat,2026-06-01,2026-06-30,120,38.00,4560.00  
> source: `batch_02/107_brightdesk_jun/INV-BD-1190.csv`

> | BD-PRO | Brightdesk Pro seat | 36.00 | 120 |  
> source: `batch_02/105_brightdesk_amendment/AM-2026-03.txt`

> | BD-PRO | Brightdesk Pro seat | 35.00 | 120 |  
> source: `batch_02/106_brightdesk_amendment_v2/AM-2026-04.txt`

### `cannot_determine`: Fluxmetrics / INV-FX-0009, $2,400.00

No agreement on file for Fluxmetrics; order form OF-2026-052 is cited but was never received

Action: **request_document** (done). Rule: `no_agreement`. Finding `bbc87974`.

> invoice_id,INV-FX-0009  
> source: `batch_02/109_fluxmetrics_jul/INV-FX-0009.csv`

> Hi Priya, hosting starts this month per order form OF-2026-052  
> source: `batch_02/108_fluxmetrics_intro`

### `credit_not_applied`: Cloudkeep Ltd., $350.00

Credit SLA-2026-02 of $350.00 promised 2026-02-10 is missing from 2 later invoice(s)

Action: **request_credit** (done). Rule: `promised_credit_missing`. Finding `57e863e1`.

> We will apply a service credit of $350.00 to your next invoice (ref SLA-2026-02)  
> source: `batch_01/007_cloudkeep_outage`

> invoice_id,INV-CK-318  
> source: `batch_02/102_cloudkeep_mar/INV-CK-318.csv`

> invoice_id,INV-CK-301A  
> source: `batch_02/103_cloudkeep_rebill/INV-CK-301A.csv`

### `renewal_notice_due`: Brightdesk Inc., $54,720.00

OF-2025-311 auto-renews 2026-12-01; notice is due by 2026-10-01 (16 days)

Action: **human_review** (recommended). Rule: `auto_renew_notice_window`. Finding `c4325bc0`.

> ORDER FORM OF-2025-311  
> source: `batch_01/001_brightdesk_order_form/OF-2025-311.txt`


## batch_03 (as of 2026-11-10)

### `cannot_determine`: Pagewise / INV-PW-120 / PW-TEAM, $150.00

PW-TEAM billed at $13.00 x 60 as in amendment AM-2026-06, which Dev Malhotra, Engineering Manager signed without authority to agree terms

Action: **request_document** (done). Rule: `term_agreed_without_authority`. Finding `feaace9f`.

> line,PW-TEAM,Team seat,2026-10-01,2026-10-31,60,13.00,780.00  
> source: `batch_03/206_pagewise_oct/INV-PW-120.csv`

> | PW-TEAM | Pagewise Team seat | 13.00 | 60 |  
> source: `batch_03/205_pagewise_amendment/AM-2026-06.txt`

> | PW-TEAM | Pagewise Team seat | 12.00 | 50 |  
> source: `batch_01/003_pagewise_order_form/OF-2025-090.txt`

> Renewal uplift cap: 5%  
> source: `batch_01/003_pagewise_order_form/OF-2025-090.txt`

### `conflict`: Cloudkeep Ltd. / INV-CK-402 / CK-STORE-TB, $80.00

Sources disagree on the price of CK-STORE-TB: order form OF-2026-019 says $21.50 vs email of 2026-10-01 agreed by priya.raman@acme-robotics.com says $19.50

Action: **human_review** (recommended). Rule: `later_email_disagrees_with_signed_terms`. Finding `7a31e82a`.

> line,CK-STORE-TB,Backup storage,2026-10-01,2026-10-31,40,21.50,860.00  
> source: `batch_03/207_cloudkeep_oct/INV-CK-402.csv`

> | CK-STORE-TB | Backup storage, per TB | 21.50 | 40 |  
> source: `batch_01/002_cloudkeep_order_form/OF-2026-019.txt`

> Following our call, the price for CK-STORE-TB will be $19.50 per TB effective 2026-10-01  
> source: `batch_03/204_cloudkeep_price_email`

### `cannot_determine`: Tallyhub / INV-TH-233 / TH-SEAT, $90.00

TH-SEAT billed at $22.00 x 30, more than the terms on file allow; amendment AM-2026-11 is cited but was never received and may change them

Action: **request_document** (done). Rule: `cited_document_missing`. Finding `36a8e4cf`.

> line,TH-SEAT,Seat,2026-11-01,2026-11-30,30,22.00,660.00  
> source: `batch_03/210_tallyhub_nov/INV-TH-233.csv`

> | TH-SEAT | Tallyhub seat | 19.00 | 30 |  
> source: `batch_03/203_tallyhub_amendment/AM-2026-08.txt`

> Hi Priya, your November invoice reflects amendment AM-2026-11, which adds reporting to every seat  
> source: `batch_03/209_tallyhub_notice`

