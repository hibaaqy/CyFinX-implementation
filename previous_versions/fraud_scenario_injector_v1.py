#!/usr/bin/env python3
"""
CyFinX Fraud Scenario Injector V1
=================================

Purpose
-------
Loads the validated 13-CSV normal population and creates a 14-table
investigation dataset by injecting ONE development case for each of the
nine frozen fraud families.

This V1 is deliberately small and inspectable. It is NOT the final fraud
distribution and does not claim real-world fraud prevalence.

Injected scenarios
------------------
1. ATO_NEW_DEVICE
2. UT_NEW_BENEFICIARY
3. SE_NEW_BENEFICIARY
4. DC_SHARED_DEVICE
5. CC_MPIN_FAILURES
6. SCO_LARGE
7. RF_MULTI_CUSTOMER
8. BIO_FAILURE_SUCCESS
9. KYC_DORMANT

Important design rules
----------------------
- Existing normal histories are preserved.
- Fraud is injected as linked raw events, not as a single fraud flag.
- Amounts are customer-relative where possible.
- Not every fraud uses a new device, failed MPIN, new beneficiary, or night time.
- Cases may originate from alerts, complaints, or both.
- Ground_Truth is evaluation-only and must never be exposed to CyFinX.
- Existing normal/non-fraud complaints are preserved.
- Fraud_Alerts and Ground_Truth from the normal population are expected to be empty.
"""

import argparse
import csv
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

DT = "%Y-%m-%d %H:%M:%S"


def parse_dt(v):
    return datetime.strptime(str(v), DT)


def fmt_dt(v):
    return v.strftime(DT)


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def money(v):
    return round(float(v), 2)


def numeric_suffix(value):
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits or 0)


class Injector:
    def __init__(self, input_dir, output_dir, seed=20261007):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.rng = random.Random(seed)

        required = [
            "customers.csv", "KYC_records.csv", "Devices.csv",
            "Customer_Device.csv", "Agent_Retailers.csv",
            "Beneficiaries.csv", "Network_Sessions.csv",
            "Authentication_Logs.csv", "Transactions.csv",
            "Biometric_Logs.csv", "Complaints.csv",
            "Fraud_Alerts.csv", "Ground_Truth.csv",
        ]
        missing = [f for f in required if not (self.input_dir / f).exists()]
        if missing:
            raise FileNotFoundError("Missing required CSVs: " + ", ".join(missing))

        self.customers = read_csv(self.input_dir / "customers.csv")
        self.kyc = read_csv(self.input_dir / "KYC_records.csv")
        self.devices = read_csv(self.input_dir / "Devices.csv")
        self.customer_devices = read_csv(self.input_dir / "Customer_Device.csv")
        self.agents = read_csv(self.input_dir / "Agent_Retailers.csv")
        self.beneficiaries = read_csv(self.input_dir / "Beneficiaries.csv")
        self.sessions = read_csv(self.input_dir / "Network_Sessions.csv")
        self.auth = read_csv(self.input_dir / "Authentication_Logs.csv")
        self.transactions = read_csv(self.input_dir / "Transactions.csv")
        self.biometrics = read_csv(self.input_dir / "Biometric_Logs.csv")
        self.complaints = read_csv(self.input_dir / "Complaints.csv")

        # Normal files should be empty, but do not silently mix prior injected cases.
        old_alerts = read_csv(self.input_dir / "Fraud_Alerts.csv")
        old_gt = read_csv(self.input_dir / "Ground_Truth.csv")
        if old_alerts or old_gt:
            raise ValueError(
                "V1 expects the clean normal population: Fraud_Alerts.csv and "
                "Ground_Truth.csv must be empty."
            )

        self.alerts = []
        self.cases = []
        self.ground_truth = []

        self.used_customers = set()

        self.device_counter = max(map(lambda r: numeric_suffix(r["Device_ID"]), self.devices), default=0)
        self.cd_counter = max(map(lambda r: numeric_suffix(r["Customer_Device_ID"]), self.customer_devices), default=0)
        self.ben_counter = max(map(lambda r: numeric_suffix(r["Beneficiary_ID"]), self.beneficiaries), default=0)
        self.session_counter = max(map(lambda r: numeric_suffix(r["Session_ID"]), self.sessions), default=0)
        self.auth_counter = max(map(lambda r: numeric_suffix(r["Auth_event_ID"]), self.auth), default=0)
        self.tx_counter = max(map(lambda r: numeric_suffix(r["Transaction_ID"]), self.transactions), default=0)
        self.bio_counter = max(map(lambda r: numeric_suffix(r["Biometric_event_ID"]), self.biometrics), default=0)
        self.complaint_counter = max(map(lambda r: numeric_suffix(r["Complaint_ID"]), self.complaints), default=0)

        self.alert_counter = 0
        self.case_counter = 0

        # Fraud injection begins after the six-month normal history.
        latest = max(parse_dt(r["Session_end"]) for r in self.sessions)
        self.base_time = latest + timedelta(hours=10)

    # ---------- lookup helpers ----------

    def customer_row(self, cid):
        return next(r for r in self.customers if r["Customer_ID"] == cid)

    def customer_transactions(self, cid, tx_type=None):
        rows = [r for r in self.transactions if r["Customer_ID"] == cid]
        if tx_type:
            rows = [r for r in rows if r["Transaction_Type"].lower() == tx_type.lower()]
        return rows

    def customer_device_ids(self, cid):
        return [r["Device_ID"] for r in self.customer_devices if r["Customer_ID"] == cid]

    def primary_device(self, cid):
        links = [r for r in self.customer_devices if r["Customer_ID"] == cid]
        links.sort(key=lambda r: parse_dt(r["Last_seen"]), reverse=True)
        if not links:
            raise ValueError(f"No device link for {cid}")
        return links[0]["Device_ID"]

    def choose_customer(self, predicate=lambda cid: True, prefer_status=None):
        ids = [r["Customer_ID"] for r in self.customers if r["Customer_ID"] not in self.used_customers]
        if prefer_status:
            preferred = [
                cid for cid in ids
                if self.customer_row(cid)["Acc_Status"].lower() == prefer_status.lower()
                and predicate(cid)
            ]
            if preferred:
                cid = self.rng.choice(preferred)
                self.used_customers.add(cid)
                return cid
        eligible = [cid for cid in ids if predicate(cid)]
        if not eligible:
            raise ValueError("No unused customer satisfies scenario eligibility.")
        cid = self.rng.choice(eligible)
        self.used_customers.add(cid)
        return cid

    def relative_amount(self, cid, tx_type=None, multiplier=4.0, minimum=15000, maximum=150000):
        rows = self.customer_transactions(cid, tx_type)
        vals = [float(r["Amount"]) for r in rows if float(r["Amount"]) > 0]
        baseline = (sum(vals) / len(vals)) if vals else 5000.0
        amt = max(minimum, baseline * multiplier)
        return round(min(amt, maximum), 2)

    def current_balance(self, cid):
        rows = self.customer_transactions(cid)
        if not rows:
            return 100000.0
        rows.sort(key=lambda r: parse_dt(r["Timestamp"]))
        return float(rows[-1]["Sender_balance_after"])

    def ensure_balance(self, cid, amount):
        # Synthetic fraud test only: keep transaction accounting internally valid.
        # If the existing synthetic balance is insufficient, use a smaller amount.
        bal = self.current_balance(cid)
        if bal <= 1000:
            return bal, max(100.0, bal * 0.50)
        return bal, min(amount, max(100.0, bal * 0.80))

    # ---------- row creators ----------

    def add_device(self, cid, when, shared_existing_device=None):
        if shared_existing_device:
            did = shared_existing_device
        else:
            self.device_counter += 1
            did = f"D{self.device_counter:07d}"
            self.devices.append({
                "Device_ID": did,
                "Device_type": "mobile",
                "Device_OS": self.rng.choice(["android", "ios"]),
                "Device_model": self.rng.choice([
                    "Samsung Galaxy A54", "Samsung Galaxy S23",
                    "iPhone 13", "iPhone 14", "Xiaomi Redmi Note 12"
                ]),
                "Device_first_seen": fmt_dt(when),
                "Device_last_seen": fmt_dt(when + timedelta(hours=2)),
                "Device_status": "active",
            })

        if not any(r["Customer_ID"] == cid and r["Device_ID"] == did for r in self.customer_devices):
            self.cd_counter += 1
            self.customer_devices.append({
                "Customer_Device_ID": f"CD{self.cd_counter:08d}",
                "Customer_ID": cid,
                "Device_ID": did,
                "First_seen": fmt_dt(when),
                "Last_seen": fmt_dt(when + timedelta(hours=2)),
                "Link_status": "active",
            })
        return did

    def extend_device_seen(self, cid, did, when):
        for r in self.devices:
            if r["Device_ID"] == did and parse_dt(r["Device_last_seen"]) < when:
                r["Device_last_seen"] = fmt_dt(when)
        for r in self.customer_devices:
            if r["Customer_ID"] == cid and r["Device_ID"] == did:
                if parse_dt(r["Last_seen"]) < when:
                    r["Last_seen"] = fmt_dt(when)
                r["Link_status"] = "active"

    def add_session(self, cid, did, start, minutes=30, city=None):
        self.session_counter += 1
        sid = f"S{self.session_counter:08d}"
        home = self.customer_row(cid)["City"]
        city = city or home

        # Synthetic session-level IP. IP changes are not a fraud label.
        ip = f"100.{self.rng.randint(64,127)}.{self.rng.randint(0,255)}.{self.rng.randint(1,254)}"
        city_coords = {
            "Karachi": (24.8607, 67.0011), "Lahore": (31.5204, 74.3587),
            "Islamabad": (33.6844, 73.0479), "Rawalpindi": (33.5651, 73.0169),
            "Multan": (30.1575, 71.5249), "Faisalabad": (31.4504, 73.1350),
            "Peshawar": (34.0151, 71.5249), "Quetta": (30.1798, 66.9750),
        }
        lat, lon = city_coords.get(city, (30.3753, 69.3451))
        end = start + timedelta(minutes=minutes)
        self.sessions.append({
            "Session_ID": sid, "Customer_ID": cid, "Device_ID": did,
            "Session_start": fmt_dt(start), "Session_end": fmt_dt(end),
            "IP_address": ip,
            "Latitude": f"{lat + self.rng.uniform(-0.03,0.03):.6f}",
            "Longitude": f"{lon + self.rng.uniform(-0.03,0.03):.6f}",
            "City": city,
            "Network_type": self.rng.choice(["wifi", "mobile_data"]),
            "ISP": self.rng.choice(["Jazz", "Zong", "Telenor", "Ufone", "PTCL"]),
        })
        self.extend_device_seen(cid, did, end)
        return sid, end

    def add_auth(self, cid, did, sid, when, event_type="LOGIN",
                 method="mpin", result="success", failure_reason="", attempt_count=1):
        self.auth_counter += 1
        self.auth.append({
            "Auth_event_ID": f"AUTH{self.auth_counter:08d}",
            "Customer_ID": cid, "Device_ID": did, "Session_ID": sid,
            "Event_timestamp": fmt_dt(when), "Event_type": event_type,
            "Auth_method": method, "Result": result,
            "Failure_reason": failure_reason, "Attempt_count": str(attempt_count),
        })

    def add_beneficiary(self, cid, when, internal=True):
        self.ben_counter += 1
        bid = f"B{self.ben_counter:07d}"
        other_customers = [r["Customer_ID"] for r in self.customers if r["Customer_ID"] != cid]
        receiver = self.rng.choice(other_customers) if internal else ""
        self.beneficiaries.append({
            "Beneficiary_ID": bid,
            "Customer_ID": cid,
            "Beneficiary_customer_ID": receiver,
            "Beneficiary_account": f"SYN{self.rng.randint(1000000000,9999999999)}",
            "Beneficiary_type": "internal" if internal else "external",
            "Beneficiary_added_time": fmt_dt(when),
            "Beneficiary_status": "active",
        })
        return bid, receiver

    def existing_beneficiary(self, cid):
        rows = [r for r in self.beneficiaries if r["Customer_ID"] == cid and r["Beneficiary_status"] == "active"]
        return self.rng.choice(rows) if rows else None

    def add_transaction(self, cid, sid, when, tx_type, amount,
                        beneficiary_id="", agent_id="", receiver_id=""):
        self.tx_counter += 1
        tid = f"T{self.tx_counter:08d}"
        before, amount = self.ensure_balance(cid, amount)

        # Payments/transfers/cash-outs reduce sender balance. Cash-in increases it.
        if tx_type == "cash_in":
            after = before + amount
        else:
            after = before - amount

        self.transactions.append({
            "Transaction_ID": tid, "Customer_ID": cid, "Session_ID": sid,
            "Beneficiary_ID": beneficiary_id, "Agent_ID": agent_id,
            "Receiver_ID": receiver_id, "Timestamp": fmt_dt(when),
            "Transaction_Type": tx_type, "Amount": f"{amount:.2f}",
            "Currency": "PKR",
            "Channel": "agent" if tx_type in ("cash_in", "cash_out") else "mobile_app",
            "Transaction_status": "success",
            "Sender_balance_before": f"{before:.2f}",
            "Sender_balance_after": f"{after:.2f}",
        })
        return tid, amount

    def add_biometric(self, cid, tid, agent_id, when, attempts=1, failed=0, result="success"):
        self.bio_counter += 1
        self.biometrics.append({
            "Biometric_event_ID": f"BIO{self.bio_counter:08d}",
            "Customer_ID": cid, "Transaction_ID": tid, "Agent_ID": agent_id,
            "Event_Timestamp": fmt_dt(when),
            "Biometric_type": "fingerprint",
            "Biometric_required": "Yes",
            "Attempt_count": str(attempts),
            "Failed_attempts": str(failed),
            "Result": result,
        })

    def add_complaint(self, cid, tid, when, complaint_type, description):
        self.complaint_counter += 1
        cmpid = f"CMP{self.complaint_counter:07d}"
        self.complaints.append({
            "Complaint_ID": cmpid, "Customer_ID": cid,
            "Transaction_ID": tid or "",
            "Complaint_timestamp": fmt_dt(when),
            "Complaint_Type": complaint_type,
            "Complaint_channel": self.rng.choice(["call_center", "app", "branch"]),
            "Complaint_description": description,
            "Complaint_status": "open",
        })
        return cmpid

    def add_case(self, cid, scenario, fraud_type, created, transaction_id="",
                 alert_type=None, criticality=None, complaint_id="",
                 source="alert", notes=""):
        alert_id = ""
        if source in ("alert", "alert_and_complaint"):
            self.alert_counter += 1
            alert_id = f"ALT{self.alert_counter:07d}"
            score = criticality if criticality is not None else self.rng.randint(70, 95)
            level = "high" if score >= 80 else ("medium" if score >= 50 else "low")
            self.alerts.append({
                "Alert_ID": alert_id, "Customer_ID": cid,
                "Transaction_ID": transaction_id,
                "Alert_timestamp": fmt_dt(created),
                "Alert_type": alert_type or "suspicious_activity",
                "Criticality_score": str(score),
                "Criticality_level": level,
                "Alert_source": "synthetic_upstream_monitoring",
                "Alert_status": "open",
            })

        self.case_counter += 1
        case_id = f"CASE{self.case_counter:07d}"
        priority = "high" if (criticality or 0) >= 80 else "medium"
        self.cases.append({
            "Case_ID": case_id, "Customer_ID": cid,
            "Alert_ID": alert_id, "Complaint_ID": complaint_id,
            "Case_created_timestamp": fmt_dt(created),
            "Case_source": source, "Case_status": "open",
            "Case_priority": priority,
        })
        self.ground_truth.append({
            "Case_ID": case_id, "is_fraud": "Yes",
            "Fraud_type": fraud_type, "Scenario_ID": scenario,
            "Validation_notes": notes,
        })
        return case_id

    # ---------- nine development scenarios ----------

    def inject_ato_new_device(self, offset):
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c)) >= 15)
        t = self.base_time + timedelta(hours=offset)
        did = self.add_device(cid, t)
        sid, _ = self.add_session(cid, did, t, 35)
        self.add_auth(cid, did, sid, t + timedelta(minutes=1), result="failed",
                      failure_reason="wrong_mpin", attempt_count=1)
        self.add_auth(cid, did, sid, t + timedelta(minutes=3), result="failed",
                      failure_reason="wrong_mpin", attempt_count=2)
        self.add_auth(cid, did, sid, t + timedelta(minutes=5), event_type="MPIN_RESET",
                      method="otp", result="success", attempt_count=1)
        self.add_auth(cid, did, sid, t + timedelta(minutes=7), result="success",
                      attempt_count=1)
        bid, receiver = self.add_beneficiary(cid, t + timedelta(minutes=9))
        amt = self.relative_amount(cid, "transfer", 4.5, 18000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=14),
                                      "transfer", amt, bid, receiver_id=receiver)
        cmpid = self.add_complaint(
            cid, tid, t + timedelta(hours=4), "unauthorized_transfer",
            "Synthetic customer reports an unrecognized transfer after account access."
        )
        self.add_case(cid, "ATO_NEW_DEVICE", "ACCOUNT_TAKEOVER",
                      t + timedelta(minutes=16), tid, "account_takeover_pattern",
                      91, cmpid, "alert_and_complaint",
                      "Injected new-device takeover with failed MPIN attempts, reset, new beneficiary and transfer.")

    def inject_ut_new_beneficiary(self, offset):
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c, "transfer")) >= 3)
        t = self.base_time + timedelta(hours=offset)
        did = self.primary_device(cid)
        sid, _ = self.add_session(cid, did, t, 25)
        self.add_auth(cid, did, sid, t + timedelta(minutes=1), result="success")
        bid, receiver = self.add_beneficiary(cid, t + timedelta(minutes=4))
        amt = self.relative_amount(cid, "transfer", 3.2, 12000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=8),
                                      "transfer", amt, bid, receiver_id=receiver)
        cmpid = self.add_complaint(
            cid, tid, t + timedelta(hours=2), "unauthorized_transfer",
            "Synthetic customer disputes a transfer to a recently added beneficiary."
        )
        self.add_case(cid, "UT_NEW_BENEFICIARY", "UNAUTHORIZED_TRANSFER",
                      t + timedelta(hours=2), tid, None, 78, cmpid, "complaint",
                      "Injected disputed transfer from a normal device to a newly added beneficiary.")

    def inject_se_new_beneficiary(self, offset):
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c)) >= 10)
        t = self.base_time + timedelta(hours=offset)
        did = self.primary_device(cid)
        sid, _ = self.add_session(cid, did, t, 30)
        # Authentication deliberately looks normal.
        self.add_auth(cid, did, sid, t + timedelta(minutes=1), result="success")
        bid, receiver = self.add_beneficiary(cid, t + timedelta(minutes=6))
        amt = self.relative_amount(cid, "transfer", 2.8, 10000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=12),
                                      "transfer", amt, bid, receiver_id=receiver)
        cmpid = self.add_complaint(
            cid, tid, t + timedelta(hours=6), "social_engineering",
            "Synthetic complaint: customer reports being persuaded to make the transfer."
        )
        self.add_case(cid, "SE_NEW_BENEFICIARY", "SOCIAL_ENGINEERING",
                      t + timedelta(hours=6), tid, None, 72, cmpid, "complaint",
                      "Injected social-engineering case with normal device/authentication and a customer-authorized transfer.")

    def inject_dc_shared_device(self, offset):
        # Select an existing physical device already linked to another customer,
        # then link a new target customer to it.
        by_device = defaultdict(set)
        for r in self.customer_devices:
            by_device[r["Device_ID"]].add(r["Customer_ID"])
        shared_or_used = [d for d, users in by_device.items() if users]
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c)) >= 10)
        candidates = [d for d in shared_or_used if cid not in by_device[d]]
        did = self.rng.choice(candidates)
        t = self.base_time + timedelta(hours=offset)
        self.add_device(cid, t, shared_existing_device=did)
        sid, _ = self.add_session(cid, did, t, 25)
        self.add_auth(cid, did, sid, t + timedelta(minutes=2), result="success")
        ben = self.existing_beneficiary(cid)
        if ben:
            bid = ben["Beneficiary_ID"]
            receiver = ben["Beneficiary_customer_ID"]
        else:
            bid, receiver = self.add_beneficiary(cid, t + timedelta(minutes=4))
        amt = self.relative_amount(cid, "transfer", 3.0, 12000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=9),
                                      "transfer", amt, bid, receiver_id=receiver)
        self.add_case(cid, "DC_SHARED_DEVICE", "DEVICE_COMPROMISE",
                      t + timedelta(minutes=11), tid, "multi_account_device_activity",
                      86, "", "alert",
                      "Injected activity from a physical device previously associated with another account.")

    def inject_cc_mpin_failures(self, offset):
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c)) >= 10)
        t = self.base_time + timedelta(hours=offset)
        did = self.primary_device(cid)
        sid, _ = self.add_session(cid, did, t, 30)
        for i in range(3):
            self.add_auth(cid, did, sid, t + timedelta(minutes=1+i*2),
                          result="failed", failure_reason="wrong_mpin",
                          attempt_count=i+1)
        self.add_auth(cid, did, sid, t + timedelta(minutes=8), result="success",
                      attempt_count=4)
        ben = self.existing_beneficiary(cid)
        if ben:
            bid, receiver = ben["Beneficiary_ID"], ben["Beneficiary_customer_ID"]
        else:
            bid, receiver = self.add_beneficiary(cid, t + timedelta(minutes=9))
        amt = self.relative_amount(cid, "transfer", 2.5, 10000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=13),
                                      "transfer", amt, bid, receiver_id=receiver)
        self.add_case(cid, "CC_MPIN_FAILURES", "CREDENTIAL_COMPROMISE",
                      t + timedelta(minutes=15), tid, "authentication_anomaly",
                      84, "", "alert",
                      "Injected repeated MPIN failures followed by success and financial activity.")

    def inject_sco_large(self, offset):
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c, "cash_out")) >= 3)
        t = self.base_time + timedelta(hours=offset)
        did = self.primary_device(cid)
        sid, _ = self.add_session(cid, did, t, 25)
        self.add_auth(cid, did, sid, t + timedelta(minutes=1), result="success")
        agent = self.rng.choice(self.agents)["Agent_ID"]
        amt = self.relative_amount(cid, "cash_out", 4.5, 15000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=8),
                                      "cash_out", amt, agent_id=agent)
        self.add_biometric(cid, tid, agent, t + timedelta(minutes=7),
                           attempts=1, failed=0, result="success")
        self.add_case(cid, "SCO_LARGE", "SUSPICIOUS_CASH_OUT",
                      t + timedelta(minutes=10), tid, "cashout_amount_anomaly",
                      81, "", "alert",
                      "Injected cash-out substantially above this customer's historical cash-out baseline.")

    def inject_rf_multi_customer(self, offset):
        primary = self.choose_customer(lambda c: len(self.customer_transactions(c, "cash_out")) >= 2)
        # Choose two related customers but do not consume them as primary cases.
        others = [
            r["Customer_ID"] for r in self.customers
            if r["Customer_ID"] not in self.used_customers and r["Customer_ID"] != primary
            and len(self.customer_transactions(r["Customer_ID"], "cash_out")) >= 1
        ]
        related = self.rng.sample(others, 2)
        agent = self.rng.choice(self.agents)["Agent_ID"]
        t = self.base_time + timedelta(hours=offset)

        primary_tid = ""
        for idx, cid in enumerate([primary] + related):
            event_t = t + timedelta(minutes=idx * 18)
            did = self.primary_device(cid)
            sid, _ = self.add_session(cid, did, event_t, 25)
            self.add_auth(cid, did, sid, event_t + timedelta(minutes=1), result="success")
            amt = self.relative_amount(cid, "cash_out", 2.8, 10000)
            tid, _ = self.add_transaction(cid, sid, event_t + timedelta(minutes=7),
                                          "cash_out", amt, agent_id=agent)
            self.add_biometric(cid, tid, agent, event_t + timedelta(minutes=6),
                               attempts=1, failed=0, result="success")
            if cid == primary:
                primary_tid = tid

        self.add_case(primary, "RF_MULTI_CUSTOMER", "RETAILER_RELATED_FRAUD",
                      t + timedelta(hours=1), primary_tid,
                      "retailer_multi_customer_pattern", 89, "", "alert",
                      "Injected multiple customers performing unusual cash-outs through the same retailer in a short window.")

    def inject_bio_failure_success(self, offset):
        cid = self.choose_customer(lambda c: len(self.customer_transactions(c, "cash_out")) >= 2)
        t = self.base_time + timedelta(hours=offset)
        did = self.primary_device(cid)
        sid, _ = self.add_session(cid, did, t, 30)
        self.add_auth(cid, did, sid, t + timedelta(minutes=1), result="success")
        agent = self.rng.choice(self.agents)["Agent_ID"]
        amt = self.relative_amount(cid, "cash_out", 2.5, 10000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=12),
                                      "cash_out", amt, agent_id=agent)
        self.add_biometric(cid, tid, agent, t + timedelta(minutes=10),
                           attempts=4, failed=3, result="success")
        self.add_case(cid, "BIO_FAILURE_SUCCESS", "BIOMETRIC_RELATED_FRAUD",
                      t + timedelta(minutes=14), tid, "biometric_attempt_anomaly",
                      83, "", "alert",
                      "Injected repeated biometric failures followed by success and cash-out.")

    def inject_kyc_dormant(self, offset):
        # Prefer an actually dormant account from the normal population.
        cid = self.choose_customer(lambda c: True, prefer_status="dormant")
        t = self.base_time + timedelta(hours=offset)

        # Keep the original account status as evidence that it had been dormant;
        # injected activity represents unexpected use rather than silently
        # rewriting the historical customer record.
        did = self.add_device(cid, t)
        sid, _ = self.add_session(cid, did, t, 35)
        self.add_auth(cid, did, sid, t + timedelta(minutes=2), result="success")
        bid, receiver = self.add_beneficiary(cid, t + timedelta(minutes=7))
        amt = self.relative_amount(cid, "transfer", 3.5, 12000)
        tid, _ = self.add_transaction(cid, sid, t + timedelta(minutes=13),
                                      "transfer", amt, bid, receiver_id=receiver)
        self.add_case(cid, "KYC_DORMANT", "IDENTITY_KYC_RELATED_FRAUD",
                      t + timedelta(minutes=15), tid, "dormant_account_activity",
                      90, "", "alert",
                      "Injected activity on a previously dormant account using a newly linked device and beneficiary.")

    # ---------- validation ----------

    def validate(self):
        errors = []

        def check(condition, message):
            if not condition:
                errors.append(message)

        customers = {r["Customer_ID"] for r in self.customers}
        devices = {r["Device_ID"] for r in self.devices}
        sessions = {r["Session_ID"]: r for r in self.sessions}
        transactions = {r["Transaction_ID"]: r for r in self.transactions}
        beneficiaries = {r["Beneficiary_ID"]: r for r in self.beneficiaries}
        agents = {r["Agent_ID"] for r in self.agents}
        alerts = {r["Alert_ID"] for r in self.alerts}
        complaints = {r["Complaint_ID"] for r in self.complaints}
        cases = {r["Case_ID"] for r in self.cases}
        links = {(r["Customer_ID"], r["Device_ID"]) for r in self.customer_devices}

        check(len(cases) == 9, f"Expected 9 cases, found {len(cases)}")
        check(len(self.ground_truth) == 9, f"Expected 9 ground truth rows, found {len(self.ground_truth)}")
        check(len({r["Scenario_ID"] for r in self.ground_truth}) == 9,
              "Scenario_ID values are not unique in V1.")

        for r in self.customer_devices:
            check(r["Customer_ID"] in customers, f"Bad Customer_Device customer: {r}")
            check(r["Device_ID"] in devices, f"Bad Customer_Device device: {r}")
            check(parse_dt(r["First_seen"]) <= parse_dt(r["Last_seen"]),
                  f"Customer_Device chronology error: {r}")

        for r in self.sessions:
            check(r["Customer_ID"] in customers, f"Bad session customer: {r}")
            check(r["Device_ID"] in devices, f"Bad session device: {r}")
            check((r["Customer_ID"], r["Device_ID"]) in links,
                  f"Session device not linked to customer: {r}")
            check(parse_dt(r["Session_start"]) <= parse_dt(r["Session_end"]),
                  f"Bad session chronology: {r}")

        for r in self.auth:
            s = sessions.get(r["Session_ID"])
            check(s is not None, f"Auth missing session: {r}")
            if s:
                check(r["Customer_ID"] == s["Customer_ID"], f"Auth customer mismatch: {r}")
                check(r["Device_ID"] == s["Device_ID"], f"Auth device mismatch: {r}")
                at = parse_dt(r["Event_timestamp"])
                check(parse_dt(s["Session_start"]) <= at <= parse_dt(s["Session_end"]),
                      f"Auth outside session: {r}")

        for r in self.transactions:
            s = sessions.get(r["Session_ID"])
            check(s is not None, f"Transaction missing session: {r}")
            if s:
                check(r["Customer_ID"] == s["Customer_ID"], f"Transaction customer mismatch: {r}")
                tt = parse_dt(r["Timestamp"])
                check(parse_dt(s["Session_start"]) <= tt <= parse_dt(s["Session_end"]),
                      f"Transaction outside session: {r}")
            if r["Beneficiary_ID"]:
                check(r["Beneficiary_ID"] in beneficiaries, f"Bad beneficiary FK: {r}")
                if r["Beneficiary_ID"] in beneficiaries:
                    b = beneficiaries[r["Beneficiary_ID"]]
                    check(parse_dt(b["Beneficiary_added_time"]) <= parse_dt(r["Timestamp"]),
                          f"Beneficiary used before addition: {r}")
            if r["Agent_ID"]:
                check(r["Agent_ID"] in agents, f"Bad agent FK: {r}")

        for r in self.biometrics:
            check(r["Transaction_ID"] in transactions, f"Biometric missing transaction: {r}")
            check(r["Agent_ID"] in agents, f"Biometric missing agent: {r}")

        for r in self.complaints:
            check(r["Customer_ID"] in customers, f"Complaint missing customer: {r}")
            if r["Transaction_ID"]:
                check(r["Transaction_ID"] in transactions, f"Complaint missing transaction: {r}")

        for r in self.alerts:
            check(r["Customer_ID"] in customers, f"Alert missing customer: {r}")
            if r["Transaction_ID"]:
                check(r["Transaction_ID"] in transactions, f"Alert missing transaction: {r}")

        for r in self.cases:
            check(r["Customer_ID"] in customers, f"Case missing customer: {r}")
            if r["Alert_ID"]:
                check(r["Alert_ID"] in alerts, f"Case missing alert: {r}")
            if r["Complaint_ID"]:
                check(r["Complaint_ID"] in complaints, f"Case missing complaint: {r}")
            check(bool(r["Alert_ID"] or r["Complaint_ID"]),
                  f"Case has neither alert nor complaint: {r}")

        for r in self.ground_truth:
            check(r["Case_ID"] in cases, f"Ground truth missing case: {r}")

        if errors:
            preview = "\n".join(" - " + e for e in errors[:30])
            raise ValueError(f"Validation failed with {len(errors)} issue(s):\n{preview}")

        print("Validation passed: 9 injected fraud cases are relationally and chronologically consistent.")

    # ---------- export ----------

    def export(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)

        schemas = {
            "customers.csv": (
                ["Customer_ID", "Reg_Date", "Acc_Status", "City", "Customer_segment"], self.customers),
            "KYC_records.csv": (
                ["KYC_ID", "Customer_ID", "Full_name", "CNIC", "DOB", "Guardian_Name",
                 "Reg_Mobile", "Reg_Address", "City", "KYC_Reg_Date", "KYC_status",
                 "KYC_last_updated_date"], self.kyc),
            "Devices.csv": (
                ["Device_ID", "Device_type", "Device_OS", "Device_model",
                 "Device_first_seen", "Device_last_seen", "Device_status"], self.devices),
            "Customer_Device.csv": (
                ["Customer_Device_ID", "Customer_ID", "Device_ID", "First_seen",
                 "Last_seen", "Link_status"], self.customer_devices),
            "Agent_Retailers.csv": (
                ["Agent_ID", "Agent_name", "Agent_location", "City", "Agent_reg_date",
                 "Agent_status", "Agent_type"], self.agents),
            "Beneficiaries.csv": (
                ["Beneficiary_ID", "Customer_ID", "Beneficiary_customer_ID",
                 "Beneficiary_account", "Beneficiary_type", "Beneficiary_added_time",
                 "Beneficiary_status"], self.beneficiaries),
            "Network_Sessions.csv": (
                ["Session_ID", "Customer_ID", "Device_ID", "Session_start", "Session_end",
                 "IP_address", "Latitude", "Longitude", "City", "Network_type", "ISP"], self.sessions),
            "Authentication_Logs.csv": (
                ["Auth_event_ID", "Customer_ID", "Device_ID", "Session_ID",
                 "Event_timestamp", "Event_type", "Auth_method", "Result",
                 "Failure_reason", "Attempt_count"], self.auth),
            "Transactions.csv": (
                ["Transaction_ID", "Customer_ID", "Session_ID", "Beneficiary_ID",
                 "Agent_ID", "Receiver_ID", "Timestamp", "Transaction_Type", "Amount",
                 "Currency", "Channel", "Transaction_status", "Sender_balance_before",
                 "Sender_balance_after"], self.transactions),
            "Biometric_Logs.csv": (
                ["Biometric_event_ID", "Customer_ID", "Transaction_ID", "Agent_ID",
                 "Event_Timestamp", "Biometric_type", "Biometric_required",
                 "Attempt_count", "Failed_attempts", "Result"], self.biometrics),
            "Complaints.csv": (
                ["Complaint_ID", "Customer_ID", "Transaction_ID", "Complaint_timestamp",
                 "Complaint_Type", "Complaint_channel", "Complaint_description",
                 "Complaint_status"], self.complaints),
            "Fraud_Alerts.csv": (
                ["Alert_ID", "Customer_ID", "Transaction_ID", "Alert_timestamp",
                 "Alert_type", "Criticality_score", "Criticality_level",
                 "Alert_source", "Alert_status"], self.alerts),
            "Cases.csv": (
                ["Case_ID", "Customer_ID", "Alert_ID", "Complaint_ID",
                 "Case_created_timestamp", "Case_source", "Case_status",
                 "Case_priority"], self.cases),
            "Ground_Truth.csv": (
                ["Case_ID", "is_fraud", "Fraud_type", "Scenario_ID",
                 "Validation_notes"], self.ground_truth),
        }

        for filename, (fields, rows) in schemas.items():
            write_csv(self.output_dir / filename, fields, rows)

        print(f"\nCreated {len(schemas)} CSV files in: {self.output_dir}")
        print("\nInjected development cases:")
        for gt in self.ground_truth:
            case = next(r for r in self.cases if r["Case_ID"] == gt["Case_ID"])
            print(f"  {gt['Case_ID']}  {gt['Scenario_ID']:<24} customer={case['Customer_ID']}  source={case['Case_source']}")

        print("\nInvestigation-layer counts:")
        print(f"  Fraud alerts: {len(self.alerts)}")
        print(f"  Cases:        {len(self.cases)}")
        print(f"  Ground truth: {len(self.ground_truth)}")
        fraud_complaints = sum(1 for c in self.cases if c["Complaint_ID"])
        print(f"  Cases with complaint: {fraud_complaints}")

    def run(self):
        # Offsets separate scenarios in time while keeping all injected activity
        # after the validated normal-history period.
        self.inject_ato_new_device(0)
        self.inject_ut_new_beneficiary(4)
        self.inject_se_new_beneficiary(8)
        self.inject_dc_shared_device(12)
        self.inject_cc_mpin_failures(16)
        self.inject_sco_large(20)
        self.inject_rf_multi_customer(24)
        self.inject_bio_failure_success(30)
        self.inject_kyc_dormant(34)

        self.validate()
        self.export()


def parse_args():
    p = argparse.ArgumentParser(description="Inject nine CyFinX fraud development scenarios.")
    p.add_argument(
        "--input",
        default="cyfinx_normal_population",
        help="Folder containing the validated 13 normal-population CSVs.",
    )
    p.add_argument(
        "--output",
        default="cyfinx_fraud_test_v1",
        help="Output folder for the 14-table fraud-development dataset.",
    )
    p.add_argument("--seed", type=int, default=20261007)
    return p.parse_args()


def main():
    args = parse_args()
    print("CyFinX Fraud Scenario Injector V1")
    print("Loading validated normal population...")
    injector = Injector(args.input, args.output, args.seed)
    print("Injecting 9 development fraud scenarios...")
    injector.run()


if __name__ == "__main__":
    main()
