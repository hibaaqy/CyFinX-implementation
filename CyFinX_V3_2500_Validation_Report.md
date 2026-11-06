# CyFinX V3 — Independent Validation Report

**Result: PASS — 0 detected validation errors**
**Population:** 2,500 customers
**Cases:** 135 fraud + 75 legitimate = 210
**Period:** April–September 2026 normal history; October 2026 investigation events
**Schema:** 14 unchanged CSV tables, with no additional evidence tables
**Generation:** normal seed 42; investigation seed 20261009; 15 batches

## Final row counts

| Table | Rows |
|---|---:|
| customers | 2,500 |
| KYC_records | 2,515 |
| Devices | 3,367 |
| Customer_Device | 3,522 |
| Agent_Retailers | 125 |
| Beneficiaries | 7,469 |
| Network_Sessions | 142,863 |
| Authentication_Logs | 156,654 |
| Transactions | 114,283 |
| Biometric_Logs | 14,616 |
| Complaints | 285 |
| Fraud_Alerts | 120 |
| Cases | 210 |
| Ground_Truth | 210 |

## Case coverage

| Scenario family | Cases |
|---|---:|
| ATO_NEW_DEVICE | 15 |
| UT_NEW_BENEFICIARY | 15 |
| SE_NEW_BENEFICIARY | 15 |
| DC_MULTI_ACCOUNT_SHARED_DEVICE | 15 |
| CC_STOLEN_CREDENTIAL_NEW_CONTEXT | 15 |
| SCO_LARGE | 15 |
| RF_MULTI_CUSTOMER_CASH_SHORTFALL | 15 |
| BIO_CROSS_AGENT_VERIFICATION_MISMATCH | 15 |
| KYC_REACTIVATION_IDENTITY_MISMATCH | 15 |
| BENIGN_NEW_BENEFICIARY | 15 |
| BENIGN_MPIN_RETRIES | 15 |
| BENIGN_BIOMETRIC_RETRY | 15 |
| BENIGN_NEW_DEVICE | 15 |
| BENIGN_LARGE_CASHOUT | 15 |

## Independent automated checks — PASS

- All 14 CSVs present; unique primary keys and valid foreign keys.
- Authentication events and transactions inside their own sessions; valid customer/device ownership.
- **0 overlapping physical-device sessions**; customer sessions also checked for overlap.
- Chronological account balance continuity and correct arithmetic for every transaction, including failed transactions.
- Physical cash-in/out denominations in multiples of PKR 100; no fractional cash amounts.
- Correct device OS/model pairings; device and customer-device last-seen chronology.
- Correct beneficiary ownership, internal account formats, and beneficiary creation before transfers.
- Consistent session ISP and network type, and cash retailer geography.
- Biometric verification timestamps before withdrawals; conflicting retailer IDs checked against the relevant cases.
- Complaint/alert/case chronology; no direct future-complaint pointers in Cases.
- All 9 fraud scenarios and all 5 benign lookalikes represented 15 times each.
- Reviewed scenario evidence: ATO and credential cooling gaps, unauthorized transfer MPIN and prior max, social-engineering device history, shared-device convergence, cash-in/out velocity, retailer complaints, KYC inactivity and biometric discrepancy.
- Fraud and legitimate investigations both include complaint-origin cases; alert scores overlap across classes.
- **Three additional random-seed tests at 500 customers / 2 batches passed**, and identical-seed regeneration is verified by SHA-256 checksums.

## Findings requiring honest qualification

**This is a validated synthetic research dataset, not a guarantee of production accuracy.** The checks demonstrate internal structure and reviewed scenario consistency; they do not establish actual Pakistan fraud prevalence or prove that every labelled case would be legally confirmed as fraud.

1. The schema captures sender-side transaction balances but lacks a complete mirrored recipient-settlement ledger. Internal transfers are not independently reconciled at the receiving wallet.
2. Retailer cash shortfall and social-engineering communications are customer allegations. They are not verified retailer till records or bank-accessible WhatsApp/call transcripts.
3. Shared-device coordination is evidence of suspicious misuse, not independent proof of malware. The existing `DEVICE_COMPROMISE` family label is retained for continuity.
4. The 2-hour cooling and 120-day inactivity values are **synthetic scenario assumptions**; they are not claims about JazzCash or SBP provider-specific controls.
5. The 210 cases are deliberately sampled for investigation evaluation; the 135/210 class mix is not a population fraud rate.
6. CyFinX must enforce observation-time filtering when querying later complaints, KYC updates and other evidence. Ground truth must be isolated from all investigation tools.
7. ML planner training still requires separate labelled next-action decisions / investigation trajectories. The 14 tables do not contain that supervision.

## Reproduction and checksums

Use `build_cyfinx_v3.py` with the documented seeds. `VALIDATION_REPORT.json` contains SHA-256 checksums for all final CSVs. No external packages are required to regenerate or validate the data.
