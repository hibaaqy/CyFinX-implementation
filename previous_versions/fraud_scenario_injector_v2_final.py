#!/usr/bin/env python3
"""CyFinX Fraud Injector V2: nine improved fraud stories, five legitimate lookalikes.

Input: the clean 13-CSV normal population folder.
Output: EXACTLY 14 CSVs using the current MS Access table and column schema.
No new CSV evidence sources or private-message access assumptions.
This is synthetic research evidence, NOT real JazzCash/Easypaisa/Meezan data.

The synthetic ground truth is evaluation-only: do not expose it to CyFinX.
Some events and thresholds are fictional modelling assumptions. A complaint
records an allegation; a bank-held authentication or transaction record may
corroborate but cannot necessarily prove the alleged fraud mechanism.

Run: python fraud_scenario_injector_v2_final.py
Optional: --input cyfinx_normal_population --output cyfinx_fraud_test_v2_final
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


class InjectorV2(Injector):
    def __init__(self, input_dir, output_dir, seed=20261009):
        super().__init__(input_dir, output_dir, seed)
        self.scenario_notes = []
        self.original_transaction_count = len(self.transactions)
        self.original_complaint_count = len(self.complaints)
        self.start_balance = {}
        for cid in [r['Customer_ID'] for r in self.customers]:
            history = self.customer_transactions(cid)
            if history:
                last = max(history, key=lambda x: x['Timestamp'])
                self.start_balance[cid] = money(last['Sender_balance_after'])
            else:
                self.start_balance[cid] = 0.0
        self.post_balance = dict(self.start_balance)
        # Target customers cannot simultaneously act as related receivers.
        self.reserved_receivers = set()
        self.initial_agents = [dict(x) for x in self.agents]
        self.initial_transactions = [dict(x) for x in self.transactions]
        self.normalization_counts = defaultdict(int)
        self.city_coordinates = {
            'Karachi': (24.8607,67.0011), 'Lahore': (31.5204,74.3587),
            'Islamabad': (33.6844,73.0479), 'Rawalpindi': (33.5651,73.0169),
            'Multan': (30.1575,71.5249), 'Faisalabad': (31.4504,73.1350),
            'Peshawar': (34.0151,71.5249), 'Quetta': (30.1798,66.9750),
            'Hyderabad': (25.3960,68.3578), 'Gujranwala': (32.1877,74.1945),
        }
        # Correct only implausible out-of-city retailer associations in the
        # V2 working copy. Original ZIP and customers' six-month event times,
        # amounts, and financial balances are unchanged.
        self.fix_retailer_geography()
        self.fix_benign_shared_devices()
        self.fix_normal_biometric_timing()
        self.fraud_scenario_count = 0
        self.false_positive_count = 0

    def fix_retailer_geography(self):
        cities = {x['City'] for x in self.customers}
        bycity = defaultdict(list)
        for agent in self.agents:
            if agent['Agent_status'] == 'active':
                bycity[agent['City']].append(agent['Agent_ID'])
        for city in cities:
            if not bycity[city]:
                num = max(numeric_suffix(x['Agent_ID']) for x in self.agents) + 1
                aid = f'A{num:06d}'
                self.agents.append(dict(Agent_ID=aid, Agent_name=f'Synthetic {city} Service Point',
                    Agent_location=f'{city} central area', City=city,
                    Agent_reg_date='2025-07-01 09:00:00', Agent_status='active', Agent_type='retailer'))
                bycity[city].append(aid)
                self.normalization_counts['added_local_agents'] += 1
        session_by_id = {r['Session_ID']: r for r in self.sessions}
        agents_by_id = {r['Agent_ID']:r for r in self.agents}
        changes = {}
        for t in self.transactions:
            if t['Transaction_Type'] not in ('cash_out','cash_in') or not t['Agent_ID']:
                continue
            city = session_by_id[t['Session_ID']]['City']
            aid = t['Agent_ID']
            if aid in agents_by_id and agents_by_id[aid]['City'] != city:
                new = self.rng.choice(bycity[city])
                changes[t['Transaction_ID']] = (aid,new)
                t['Agent_ID'] = new
                self.normalization_counts['remapped_agent_transactions'] += 1
        for b in self.biometrics:
            if b['Transaction_ID'] in changes:
                b['Agent_ID'] = changes[b['Transaction_ID']][1]

    def fix_benign_shared_devices(self):
        # Most legitimate physically shared devices should connect customers
        # plausibly close to one another. Remap historical *cross-city shared*
        # links to an already-known same-city physical device where feasible.
        # Preserve original source. Update linked sessions and authentication.
        customer_city={r['Customer_ID']:r['City'] for r in self.customers}
        originals={r['Device_ID']:r for r in self.devices}
        by_device=defaultdict(list)
        for l in self.customer_devices:by_device[l['Device_ID']].append(l)
        for old_id, links in list(by_device.items()):
            if len(links)<2:continue
            for moving in sorted(links,key=lambda x:x['First_seen'],reverse=True):
                city=customer_city[moving['Customer_ID']]
                if all(customer_city[l['Customer_ID']]==city for l in links):break
                # Find a device of another customer from this city, present
                # before the link begins and not already linked to our user.
                possible=[]
                for candidate in self.customer_devices:
                    if candidate['Customer_ID']==moving['Customer_ID']:continue
                    if customer_city[candidate['Customer_ID']]!=city:continue
                    did=candidate['Device_ID']
                    if did==old_id:continue
                    if did in {x['Device_ID'] for x in self.customer_devices if x['Customer_ID']==moving['Customer_ID']}:continue
                    if parse_dt(originals[did]['Device_first_seen'])>parse_dt(moving['First_seen']):continue
                    possible.append(did)
                if not possible:continue
                new_id=self.rng.choice(possible)
                cust=moving['Customer_ID']
                moving['Device_ID']=new_id
                for sess in self.sessions:
                    if sess['Customer_ID']==cust and sess['Device_ID']==old_id:
                        sess['Device_ID']=new_id
                for auth in self.auth:
                    if auth['Customer_ID']==cust and auth['Device_ID']==old_id:
                        auth['Device_ID']=new_id
                # Preserve the global last-seen invariant on the new phone.
                if parse_dt(originals[new_id]['Device_last_seen'])<parse_dt(moving['Last_seen']):
                    originals[new_id]['Device_last_seen']=moving['Last_seen']
                self.normalization_counts['repaired_cross_city_shared_links']+=1
                break

    def fix_normal_biometric_timing(self):
        # V1 normal generator sometimes placed a biometric log *after* the
        # cashout transaction. Repair the V2 working copy for coherent
        # verification-before-disbursement chronology. Source stays intact.
        tx={r['Transaction_ID']:r for r in self.transactions}
        sessions={s['Session_ID']:s for s in self.sessions}
        for b in self.biometrics:
            t=tx.get(b['Transaction_ID'])
            if not t: continue
            if parse_dt(b['Event_Timestamp'])>parse_dt(t['Timestamp']):
                sess=sessions[t['Session_ID']]
                earliest=parse_dt(sess['Session_start'])+timedelta(seconds=5)
                new=max(earliest,parse_dt(t['Timestamp'])-timedelta(seconds=self.rng.randint(15,75)))
                b['Event_Timestamp']=fmt_dt(new)
                self.normalization_counts['corrected_biometric_timestamps']+=1

    def agent_baseline(self):
        counts = defaultdict(list)
        agents = {a['Agent_ID']:a for a in self.agents}
        for t in self.transactions:
            if t['Agent_ID']:
                counts[t['Agent_ID']].append(t)
        result = []
        for aid, agent in sorted(agents.items()):
            rows=counts[aid]
            cashouts=[r for r in rows if r['Transaction_Type']=='cash_out']
            days=183
            result.append(dict(Agent_ID=aid, City=agent['City'],
                Baseline_start='2026-04-01',Baseline_end='2026-09-30',
                Prior_transaction_count=len(rows),Prior_cashout_count=len(cashouts),
                Prior_unique_customers=len({r['Customer_ID'] for r in rows}),
                Prior_cashout_avg= f'{sum(float(r["Amount"]) for r in cashouts)/len(cashouts):.2f}' if cashouts else '0.00',
                Prior_cashouts_per_day=f'{len(cashouts)/days:.4f}'))
        return result

    def now(self, offset=0):
        return self.base_time + timedelta(hours=offset, minutes=self.rng.randint(0,9),seconds=self.rng.randint(0,59))

    def minutes(self, t, m=0):
        return t + timedelta(minutes=m, seconds=self.rng.randint(3,55))

    def choose_customer(self, predicate=lambda cid: True, prefer_status=None):
        # Exclude other cases' receiving accounts so account arithmetic is
        # straightforward and each incident has an independent main actor.
        return super().choose_customer(lambda c: c not in self.reserved_receivers and predicate(c),prefer_status)

    def suitable(self, cid, minimum=10000, status='active', tx_type=None, min_tx=5):
        return (self.customer_row(cid)['Acc_Status']==status
                and self.post_balance[cid] >= minimum
                and len(self.customer_transactions(cid,tx_type))>=min_tx)

    def add_device(self, cid, when, shared_existing_device=None):
        # As in V1, creates the physical device + the many-to-many mapping.
        return super().add_device(cid, when, shared_existing_device)

    def add_session(self, cid, did, start, minutes=30, city=None):
        sid, end=super().add_session(cid, did, start, minutes, city)
        # Vary seconds and timing naturally, no all :30 injection fingerprint.
        return sid, end

    def choose_receiver(self, sender, minimum_count=0):
        # Prefer an internal account not yet participating in any incident.
        candidates=[x['Customer_ID'] for x in self.customers
            if x['Customer_ID']!=sender and x['Customer_ID'] not in self.used_customers
            and x['Customer_ID'] not in self.reserved_receivers
            and x['Acc_Status']=='active']
        if not candidates: raise RuntimeError('No recipient candidates available.')
        receiver=self.rng.choice(candidates)
        self.reserved_receivers.add(receiver)
        return receiver

    def add_beneficiary(self, cid, when, internal=True):
        self.ben_counter+=1
        bid=f'B{self.ben_counter:07d}'
        receiver=self.choose_receiver(cid) if internal else ''
        self.beneficiaries.append(dict(Beneficiary_ID=bid,Customer_ID=cid,
            Beneficiary_customer_ID=receiver,
            Beneficiary_account=f'SYN{self.rng.randint(10**9,10**10-1)}',
            Beneficiary_type='internal' if internal else 'external',
            Beneficiary_added_time=fmt_dt(when),Beneficiary_status='active'))
        return bid,receiver

    def choose_amount(self, cid, tx_type='transfer', mode='large'):
        vals=[float(t['Amount']) for t in self.initial_transactions
            if t['Customer_ID']==cid and t['Transaction_Type']==tx_type]
        mean=sum(vals)/len(vals) if vals else 2800
        prior_max=max(vals) if vals else 0
        balance=self.post_balance[cid]
        if mode=='large': desired=max(mean*self.rng.uniform(2.3,3.2),prior_max*self.rng.uniform(1.25,1.65),3000)
        elif mode=='significant':desired=max(mean*self.rng.uniform(1.2,2.0),2000)
        elif mode=='small':desired=max(200,mean*self.rng.uniform(0.3,0.7))
        else:desired=max(1000,mean)
        # Never cap automatically at fixed 80%. A case without enough funds
        # should have been excluded during eligibility selection.
        if desired > balance*0.94:
            if mode=='large' and balance >= prior_max*1.30:
                desired=balance*self.rng.uniform(0.68,0.91)
            elif mode!='large':
                desired=balance*self.rng.uniform(0.32,0.77)
            else:
                raise ValueError(f'{cid}: cannot support a large {tx_type} scenario ({balance=:.2f}, max={prior_max:.2f}).')
        amt=round(desired,2)
        if tx_type=='cash_out':
            amt=round(amt/100)*100
            if amt<100 or amt>=balance: raise ValueError(f'{cid}: cannot generate physical cash out of {amt}')
        if amt<=0 or amt>balance:
            raise ValueError('Invalid derived scenario amount.')
        return amt

    def add_transaction(self, cid, sid, when, tx_type, amount,
                        beneficiary_id='',agent_id='',receiver_id=''):
        # Override old ensure_balance() that forced exact 80% drains.
        amt=money(amount); before=money(self.post_balance[cid]);
        if tx_type!='cash_in' and (amt <= 0 or amt>before):
            raise ValueError(f'{cid}: insufficient balance for PKR {amt}; available {before}')
        after=money(before + amt if tx_type=='cash_in' else before-amt)
        self.tx_counter+=1
        tid=f'T{self.tx_counter:08d}'
        self.transactions.append(dict(Transaction_ID=tid,Customer_ID=cid,Session_ID=sid,
            Beneficiary_ID=beneficiary_id,Agent_ID=agent_id,Receiver_ID=receiver_id,
            Timestamp=fmt_dt(when),Transaction_Type=tx_type,Amount=f'{amt:.2f}',
            Currency='PKR',Channel='agent' if tx_type in ('cash_out','cash_in') else 'mobile_app',
            Transaction_status='success',Sender_balance_before=f'{before:.2f}',
            Sender_balance_after=f'{after:.2f}'))
        self.post_balance[cid]=after
        kind='CREDIT' if tx_type=='cash_in' else 'DEBIT'
        self.add_ledger(cid,tid,when,kind,amt,receiver_id)
        if tx_type=='transfer' and receiver_id:
            # Receiver credit belongs to wallet settlement evidence, not an
            # invented recipient login / fabricated session.
            self.add_ledger(receiver_id,tid,when+timedelta(seconds=4),'CREDIT',amt,cid)
            self.post_balance[receiver_id]=money(self.post_balance[receiver_id]+amt)
        return tid,amt

    def add_retailer(self, city):
        candidates=[a for a in self.agents if a['City']==city and a['Agent_status']=='active']
        if not candidates: raise ValueError('No active retailer for '+city)
        return self.rng.choice(candidates)['Agent_ID']

    def add_case(self, cid, scenario, fraud_type, created, transaction_id='',
                 alert_type=None,criticality=None,complaint_id='',source='alert',notes='',
                 is_fraud=True):
        # Uses original 14-table layout but Case_source means ORIGINAL origin,
        # even when Complaint_ID is subsequently linked to an alert-opened case.
        alert_id=''
        if source in ('alert','alert_and_complaint'):
            self.alert_counter+=1; alert_id=f'ALT{self.alert_counter:07d}'
            score=criticality if criticality is not None else self.rng.randint(55,92)
            self.alerts.append(dict(Alert_ID=alert_id,Customer_ID=cid,
                Transaction_ID=transaction_id,Alert_timestamp=fmt_dt(created),
                Alert_type=alert_type or 'unusual_wallet_activity',
                Criticality_score=score,Criticality_level='high' if score>=80 else 'medium',
                Alert_source='synthetic_upstream_monitoring',Alert_status='open'))
        self.case_counter+=1
        case_id=f'CASE{self.case_counter:07d}'
        if source=='alert_and_complaint': source='alert' # later complaint linkage
        if source=='complaint' and not complaint_id: raise ValueError('Complaint case missing complaint.')
        self.cases.append(dict(Case_ID=case_id,Customer_ID=cid,Alert_ID=alert_id,
            Complaint_ID=complaint_id,Case_created_timestamp=fmt_dt(created),
            Case_source=source,Case_status='open',Case_priority='high' if (criticality or 0)>=80 else 'medium'))
        self.ground_truth.append(dict(Case_ID=case_id,
            is_fraud='Yes' if is_fraud else 'No',Fraud_type=fraud_type if is_fraud else 'NONE',
            Scenario_ID=scenario,Validation_notes=notes))
        if is_fraud:self.fraud_scenario_count+=1
        else:self.false_positive_count+=1
        return case_id

    def add_complaint(self,cid,tid,when,complaint_type,description):
        if complaint_type.upper() in ('ACCOUNT_TAKEOVER','SOCIAL_ENGINEERING','UNAUTHORIZED_TRANSFER','CREDENTIAL_COMPROMISE'):
            raise ValueError('Use a neutral customer complaint category.')
        return super().add_complaint(cid,tid,when,complaint_type,description)

    def existing_beneficiary(self,cid):
        options=[r for r in self.beneficiaries if r['Customer_ID']==cid and r['Beneficiary_status']=='active']
        return self.rng.choice(options) if options else None

    def note(self,scenario, text): self.scenario_notes.append((scenario,text))

    def inject_ato_new_device(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,6000,min_tx=15))
        t=self.now(offset); did=self.add_device(cid,t)
        self.add_security(cid,did,t,'DEVICE_REGISTRATION_REQUEST','received','otp')
        approval=self.minutes(t,7)
        self.add_security(cid,did,approval,'DEVICE_REGISTRATION_VERIFICATION','approved','otp',details='Synthetic registration approval; do not infer who controlled the OTP.')
        reset=self.minutes(t,143)
        sid,_=self.add_session(cid,did,self.minutes(t,135),40)
        self.add_auth(cid,did,sid,self.minutes(t,136),'LOGIN','mpin','failed','wrong_mpin',1)
        self.add_auth(cid,did,sid,self.minutes(t,138),'LOGIN','mpin','failed','wrong_mpin',2)
        self.add_security(cid,did,reset,'MPIN_RECOVERY_VERIFICATION','approved','otp',sid)
        self.add_auth(cid,did,sid,reset,'MPIN_RESET','otp','success','',1)
        # Separate session after credential reset + assumed 2-hour wait.
        t2=self.minutes(reset,132)
        sid2,_=self.add_session(cid,did,t2,35)
        login=self.minutes(t2,2)
        self.add_auth(cid,did,sid2,login,'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,self.minutes(t2,7))
        amount=self.choose_amount(cid,'transfer','significant')
        tx_time=self.minutes(t2,16)
        tid,_=self.add_transaction(cid,sid2,tx_time,'transfer',amount,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(t2,14))
        case_time=self.minutes(tx_time,2)
        cmp_time=self.minutes(tx_time,165)
        cmpid=self.add_complaint(cid,tid,cmp_time,'disputed_account_activity',
            'Customer reports not registering a new device, not requesting MPIN recovery and not approving a transfer to an unknown wallet. This is the customer statement, not independently verified.')
        case_id=self.add_case(cid,'ATO_NEW_DEVICE','ACCOUNT_TAKEOVER',case_time,tid,
            'unusual_account_access_activity',87,cmpid,'alert',
            'New verified device, recovery workflow, cooling intervals, unfamiliar beneficiary, disputed payment. Customer allegation requires investigation.')
        self.add_dispute(case_id,cmpid,tid,cmp_time,'CUSTOMER_COMPLAINT_RECEIVED')
        self.note('ATO_NEW_DEVICE','No claim that bank verified the claimant controlled the OTP; assumes a fictional provider cooldown of >=2 hours.')

    def inject_ut_new_beneficiary(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,12000,tx_type='transfer',min_tx=3))
        t=self.now(offset);did=self.primary_device(cid)
        sid,_=self.add_session(cid,did,t,30)
        self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,self.minutes(t,4))
        amount=self.choose_amount(cid,'transfer','significant')
        at=self.minutes(t,11);tid,_=self.add_transaction(cid,sid,at,'transfer',amount,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(t,9))
        ct=self.minutes(at,116)
        cmpid=self.add_complaint(cid,tid,ct,'disputed_transfer',
            'Customer denies creating the newly added beneficiary and denies approving the transfer. No lost phone is reported; transfer-specific authorization record must be assessed rather than assumed conclusive.')
        case_id=self.add_case(cid,'UT_NEW_BENEFICIARY','UNAUTHORIZED_TRANSFER',ct,tid,
            None,75,cmpid,'complaint','Complaint disputes authorization; linked device and transfer authorization recorded; recipient credit trace exists.')
        self.add_dispute(case_id,cmpid,tid,self.minutes(ct,1),'DISPUTE_REGISTERED')
        self.add_dispute(case_id,cmpid,tid,self.minutes(ct,6),'RECEIVING_ACCOUNT_REVIEW_REQUESTED','requested',note='Synthetic FTDH-style notification; actual interinstitution data not assumed available.')
        self.note('UT_NEW_BENEFICIARY','FTDH actions are simulated requests, not proofs that recovery or liens have occurred.')

    def inject_se_new_beneficiary(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,9500,tx_type='transfer',min_tx=2))
        t=self.now(offset);did=self.primary_device(cid)
        sid,_=self.add_session(cid,did,t,30)
        self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,self.minutes(t,5))
        amt=self.choose_amount(cid,'transfer','significant')
        at=self.minutes(t,12);tid,_=self.add_transaction(cid,sid,at,'transfer',amt,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(t,10))
        ct=self.minutes(at,289)
        cmpid=self.add_complaint(cid,tid,ct,'disputed_transfer',
            'Customer reports receiving a call from a person claiming to be wallet support and was told to transfer money to resolve an alleged account issue. Customer confirms personally opening the app, adding the recipient and sending the money. The call is customer-reported; institution has no private call recording.')
        case_id=self.add_case(cid,'SE_NEW_BENEFICIARY','SOCIAL_ENGINEERING',ct,tid,
            None,69,cmpid,'complaint','Customer-described deception with legitimate login and user-entered transfer. Financial logs cannot independently verify private call.')
        self.add_dispute(case_id,cmpid,tid,self.minutes(ct,1),'CUSTOMER_ALLEGATION_RECORDED')
        self.note('SE_NEW_BENEFICIARY','No synthetic private SMS/WhatsApp data invented; bank-held complaint is explicitly an allegation.')

    def inject_dc_shared_device(self,offset):
        t=self.now(offset)
        city='Karachi'
        pool=[x['Customer_ID'] for x in self.customers if x['City']==city
              and x['Customer_ID'] not in self.used_customers
              and x['Customer_ID'] not in self.reserved_receivers
              and self.suitable(x['Customer_ID'],3500,min_tx=5)]
        if len(pool)<3: raise ValueError('Insufficient same-city multi-account device candidates.')
        target=self.rng.choice(pool); self.used_customers.add(target)
        others=self.rng.sample([x for x in pool if x!=target],2)
        self.used_customers.update(others)  # protect related actors from reuse as later main cases
        did=self.add_device(target,t)
        self.add_security(target,did,t,'DEVICE_REGISTRATION_VERIFICATION','approved','otp')
        self.add_security(target,did,self.minutes(t,1),'DEVICE_INTEGRITY_ATTESTATION','emulator_observed','device_integrity_sdk',details='Synthetic optional app security telemetry; may not be available from a real institution.')
        # Registration for the related accounts happens near the initial
        # linkage. All 3 financial activities begin after the 2-hour wait
        # and occur in a short observation window (~30-40 minutes).
        main_tid=''
        for i,cid in enumerate([target]+others):
            if cid!=target:
                link_at=self.minutes(t,i*3)
                self.add_device(cid,link_at,shared_existing_device=did)
                self.add_security(cid,did,self.minutes(link_at,2),'DEVICE_REGISTRATION_VERIFICATION','approved','otp')
            start=self.minutes(t,145+i*13)
            sid,_=self.add_session(cid,did,start,30,city=city)
            self.add_auth(cid,did,sid,self.minutes(start,2),'LOGIN','mpin','success')
            bid,receiver=self.add_beneficiary(cid,self.minutes(start,6))
            amt=self.choose_amount(cid,'transfer','significant')
            tx_when=self.minutes(start,13)
            tid,_=self.add_transaction(cid,sid,tx_when,'transfer',amt,bid,receiver_id=receiver)
            self.add_authorization(cid,tid,did,self.minutes(start,12))
            if cid==target:main_tid=tid
        # Fraud alert occurs when cross-account linkage emerges, not before.
        last=max(parse_dt(x['Timestamp']) for x in self.transactions[self.original_transaction_count:] if x['Customer_ID'] in [target]+others)
        self.add_case(target,'DC_MULTI_ACCOUNT_EMULATOR','DEVICE_COMPROMISE',self.minutes(last,3),
            main_tid,'unusual_multi_account_device_activity',88,'','alert',
            'Three Karachi customers use same recently linked physical device; independent device-integrity attestation reports emulator. Distinct from ordinary two-account family sharing.')
        self.note('DC_MULTI_ACCOUNT_EMULATOR','Same-device multi-account alone not conclusive; device-integrity event is optional simulated provider telemetry.')

    def inject_cc_mpin_failures(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,10500,min_tx=10))
        t=self.now(offset);did=self.primary_device(cid)
        home=self.customer_row(cid)['City']
        away=self.rng.choice([x for x in ['Karachi','Lahore','Islamabad','Multan','Faisalabad'] if x!=home])
        sid,_=self.add_session(cid,did,t,32,city=away)
        login=self.minutes(t,1)
        self.add_auth(cid,did,sid,login,'LOGIN','mpin','success')
        self.add_security(cid,did,self.minutes(t,3),'UNUSUAL_SESSION_CONTEXT','observed','session_log',sid,
            'Session used the usual device but unusual network city; this is not independently proof of credential theft.')
        bid,receiver=self.add_beneficiary(cid,self.minutes(t,6))
        amount=self.choose_amount(cid,'transfer','significant')
        tx_at=self.minutes(t,13)
        tid,_=self.add_transaction(cid,sid,tx_at,'transfer',amount,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(t,11))
        self.add_case(cid,'CC_STOLEN_CREDENTIAL_NEW_CONTEXT','CREDENTIAL_COMPROMISE',
            self.minutes(tx_at,3),tid,'unusual_authenticated_transaction',79,'','alert',
            'Known physical device with novel access location and valid MPIN, then new beneficiary and transfer. Attack cause remains hypothesis from evidence.')
        self.note('CC_STOLEN_CREDENTIAL_NEW_CONTEXT','Renamed old CC_MPIN_FAILURES: 3 failures followed by success was not defensible without provider lockout policy.')

    def inject_sco_large(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,26000,tx_type='cash_out',min_tx=3)
            and self.post_balance[c] >= 2.20*max(float(x['Amount']) for x in self.customer_transactions(c,'cash_out'))
            and any(a['City']==self.customer_row(c)['City'] for a in self.agents))
        t=self.now(offset);did=self.primary_device(cid)
        city=self.customer_row(cid)['City'];aid=self.add_retailer(city)
        sid,_=self.add_session(cid,did,t,55,city=city)
        self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
        # A recent cash-in is a modelled funding event, not an assumed fraud flag.
        inflow=self.rng.randrange(3000,9001,100)
        self.add_transaction(cid,sid,self.minutes(t,7),'cash_in',inflow,agent_id=aid)
        vals=[float(r['Amount']) for r in self.initial_transactions if r['Customer_ID']==cid and r['Transaction_Type']=='cash_out']
        prior_max=max(vals)
        desired=round((prior_max*self.rng.uniform(1.55,1.95))/100)*100
        if desired>=self.post_balance[cid]*0.95:raise ValueError('Insufficient balance for a >1.5x historical max cash out.')
        at=self.minutes(t,21)
        tid,amt=self.add_transaction(cid,sid,at,'cash_out',desired,agent_id=aid)
        self.add_biometric(cid,tid,aid,self.minutes(t,19),attempts=1,failed=0)
        self.add_bio_audit(cid,aid,tid,self.minutes(t,19),count=1)
        self.add_receipt_audit(cid,aid,tid,self.minutes(t,22),amt,amt)
        self.add_case(cid,'SCO_LARGE','SUSPICIOUS_CASH_OUT',self.minutes(at,3),tid,
            'unusual_cashout_velocity',78,'','alert',
            'After an observed cash-in, a local verified agent completes a cash-out >1.5x customer historical max; receipt and biometric present. Unusual does not prove theft.')
        self.note('SCO_LARGE','Synthetic prior cash-out night/cross-city assumptions require separate review; do not invent institution rates.')

    def inject_kyc_dormant(self,offset):
        t=self.now(offset)
        cid=self.choose_customer(lambda c:self.customer_row(c)['Acc_Status']=='dormant'
            and (t-max(parse_dt(x['Timestamp']) for x in self.customer_transactions(c))).days>=45
            and self.post_balance[c]>2500,prefer_status='dormant')
        did=self.add_device(cid,t)
        self.add_id_event(cid,did,t,'REACTIVATION_REQUEST','submitted','Unknown',
            'Fictional provider dormancy threshold=45 days without financial activity; not an SBP rule.')
        self.add_id_event(cid,did,self.minutes(t,5),'REACTIVATION_APPROVED','approved','Yes',
            'Synthetic control record, pending later independent KYC reconciliation.')
        self.add_security(cid,did,self.minutes(t,7),'DEVICE_REGISTRATION_VERIFICATION','approved','otp')
        active_at=self.minutes(t,151)
        # Current status is a snapshot; preserve pre-case dormancy in earlier
        # normal history and explicitly record the reactivation event.
        self.customer_row(cid)['Acc_Status']='active'
        sid,_=self.add_session(cid,did,active_at,35)
        self.add_auth(cid,did,sid,self.minutes(active_at,1),'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,self.minutes(active_at,4))
        amt=self.choose_amount(cid,'transfer','significant')
        at=self.minutes(active_at,12)
        tid,_=self.add_transaction(cid,sid,at,'transfer',amt,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(active_at,10))
        audit_at=self.minutes(at,75)
        self.add_id_event(cid,did,audit_at,'POST_REACTIVATION_KYC_RECONCILIATION','requires_review','No',
            'Synthetic reviewer found reactivation submission inconsistent with pre-existing verified identity fields; underlying sensitive values are not exposed.')
        self.add_case(cid,'KYC_REACTIVATION_IDENTITY_MISMATCH','IDENTITY_KYC_RELATED_FRAUD',
            self.minutes(audit_at,2),tid,'identity_reverification_required',84,'','alert',
            'Previously dormant account reactivated, linked new device, moved funds; subsequent KYC reconciliation found inconsistency.')
        self.note('KYC_REACTIVATION_IDENTITY_MISMATCH','45-day inactivity definition is a fictional simulation parameter, not a JazzCash or SBP threshold.')

    def inject_benign_lookalikes(self):
        # Leave raw events ambiguous; only Ground_Truth identifies is_fraud=No.
        benign=[('BENIGN_NEW_BENEFICIARY',38),('BENIGN_MPIN_RETRIES',44),
                ('BENIGN_BIOMETRIC_RETRY',50),('BENIGN_NEW_DEVICE',56),
                ('BENIGN_LARGE_CASHOUT',62)]
        for label,offset in benign:
            t=self.now(offset)
            if label=='BENIGN_NEW_BENEFICIARY':
                cid=self.choose_customer(lambda c:self.suitable(c,4500,min_tx=10))
                did=self.primary_device(cid);sid,_=self.add_session(cid,did,t,28)
                self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
                bid,receiver=self.add_beneficiary(cid,self.minutes(t,4))
                amt=self.choose_amount(cid,'transfer','small')
                at=self.minutes(t,10);tid,_=self.add_transaction(cid,sid,at,'transfer',amt,bid,receiver_id=receiver)
                self.add_authorization(cid,tid,did,self.minutes(t,9))
                self.add_case(cid,label,'NONE',self.minutes(at,3),tid,'new_beneficiary_transfer',58,'','alert',
                    'Synthetic legitimate first payment to newly registered beneficiary.',False)
            elif label=='BENIGN_MPIN_RETRIES':
                cid=self.choose_customer(lambda c:self.suitable(c,3000,min_tx=4))
                did=self.primary_device(cid);sid,_=self.add_session(cid,did,t,20)
                for i in range(3):self.add_auth(cid,did,sid,self.minutes(t,1+i),'LOGIN','mpin','failed','wrong_mpin',i+1)
                self.add_security(cid,did,self.minutes(t,5),'MPIN_LOCKOUT','enforced','system',sid)
                self.add_security(cid,did,self.minutes(t,8),'MPIN_RECOVERY_VERIFICATION','approved','otp',sid)
                self.add_auth(cid,did,sid,self.minutes(t,9),'MPIN_RESET','otp','success')
                sid2,_=self.add_session(cid,did,self.minutes(t,149),28)
                self.add_auth(cid,did,sid2,self.minutes(t,150),'LOGIN','mpin','success')
                tid,_=self.add_transaction(cid,sid2,self.minutes(t,154),'payment',300)
                self.add_authorization(cid,tid,did,self.minutes(t,152))
                self.add_case(cid,label,'NONE',self.minutes(t,157),tid,'credential_recovery_activity',62,'','alert',
                    'Normal user genuinely forgot PIN, lockout and registered-device recovery succeeded.',False)
            elif label=='BENIGN_BIOMETRIC_RETRY':
                cid=self.choose_customer(lambda c:self.suitable(c,4000,tx_type='cash_out',min_tx=2)
                    and any(a['City']==self.customer_row(c)['City'] for a in self.agents))
                did=self.primary_device(cid);city=self.customer_row(cid)['City'];aid=self.add_retailer(city)
                sid,_=self.add_session(cid,did,t,28)
                self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
                tid,amt=self.add_transaction(cid,sid,self.minutes(t,14),'cash_out',500,agent_id=aid)
                self.add_biometric(cid,tid,aid,self.minutes(t,12),4,3)
                self.add_bio_audit(cid,aid,tid,self.minutes(t,11),count=4,inconsistent=False)
                self.add_receipt_audit(cid,aid,tid,self.minutes(t,17),amt,amt)
                self.add_case(cid,label,'NONE',self.minutes(t,19),tid,'repeated_biometric_attempts',55,'','alert',
                    'Poor scan quality followed by valid terminal verification and matching disbursement.',False)
            elif label=='BENIGN_NEW_DEVICE':
                cid=self.choose_customer(lambda c:self.suitable(c,4000,min_tx=10))
                did=self.add_device(cid,t)
                self.add_security(cid,did,t,'DEVICE_REGISTRATION_REQUEST','received','otp')
                self.add_security(cid,did,self.minutes(t,5),'DEVICE_REGISTRATION_VERIFICATION','approved','otp')
                start=self.minutes(t,146)
                sid,_=self.add_session(cid,did,start,30)
                self.add_auth(cid,did,sid,self.minutes(start,1),'LOGIN','mpin','success')
                tid,_=self.add_transaction(cid,sid,self.minutes(start,9),'payment',420)
                self.add_authorization(cid,tid,did,self.minutes(start,7))
                self.add_case(cid,label,'NONE',self.minutes(start,11),tid,'new_device_activity',60,'','alert',
                    'Legitimate handset replacement, verified and cooled before first payment.',False)
            elif label=='BENIGN_LARGE_CASHOUT':
                cid=self.choose_customer(lambda c:self.suitable(c,12000,tx_type='cash_out',min_tx=3)
                    and self.post_balance[c] >= 2.3*max(float(x['Amount']) for x in self.customer_transactions(c,'cash_out'))
                    and any(a['City']==self.customer_row(c)['City'] for a in self.agents))
                did=self.primary_device(cid); aid=self.add_retailer(self.customer_row(cid)['City'])
                sid,_=self.add_session(cid,did,t,30)
                self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
                amt=self.choose_amount(cid,'cash_out','large')
                at=self.minutes(t,11);tid,_=self.add_transaction(cid,sid,at,'cash_out',amt,agent_id=aid)
                self.add_biometric(cid,tid,aid,self.minutes(t,9),1,0)
                self.add_bio_audit(cid,aid,tid,self.minutes(t,9),1)
                self.add_receipt_audit(cid,aid,tid,self.minutes(t,12),amt,amt)
                self.add_case(cid,label,'NONE',self.minutes(at,3),tid,'unusual_cashout_amount',66,'','alert',
                    'Customer genuinely took larger cash-out; retailer audit/biometric match.',False)

    def run(self):
        self.inject_ato_new_device(0)
        self.inject_ut_new_beneficiary(7)
        self.inject_se_new_beneficiary(10)
        self.inject_dc_shared_device(13)
        self.inject_cc_mpin_failures(18)
        self.inject_sco_large(22)
        self.inject_rf_multi_customer(25)
        self.inject_bio_failure_success(30)
        self.inject_kyc_dormant(34)
        self.inject_benign_lookalikes()
        self.validate()
        self.export()


class InjectorV2Final(InjectorV2):
    """Frozen 14-table version with no extra files."""

    def __init__(self, input_dir, output_dir, seed=20261009):
        super().__init__(input_dir, output_dir, seed)
        self._maintenance_sessions = {}
        self._biometric_agent_mismatch_tx = set()
        self._source_original_counts = {
            'customers': len(self.customers), 'transactions': len(self.transactions),
            'sessions': len(self.sessions), 'auth': len(self.auth),
            'biometrics': len(self.biometrics), 'kyc': len(self.kyc),
        }

    def _maintenance_session(self, cid, did, when):
        """A real customer-device security event has a matching session record."""
        k = (cid, did)
        old = self._maintenance_sessions.get(k)
        if old and parse_dt(old[1]) >= when and parse_dt(old[2]) <= when:
            return old[0]
        sid, end = self.add_session(cid, did, when, 16, city=self.customer_row(cid)['City'])
        self._maintenance_sessions[k] = (sid, fmt_dt(end), fmt_dt(when))
        return sid

    def add_security(self, cid, did, when, kind, result, method='system', sid='', details=''):
        """Represent institution-side binding/recovery via Authentication_Logs.

        Does NOT claim bank access to private calls, WhatsApp, or external
        phone-forensics. Device-integrity attestation is unsupported by these
        14 tables and is not fabricated.
        """
        if kind in ('DEVICE_INTEGRITY_ATTESTATION', 'UNUSUAL_SESSION_CONTEXT'):
            # Queryable facts instead exist in Customer_Device / Network_Sessions.
            return
        if not sid:
            sid = self._maintenance_session(cid, did, when)
        event_type = {
            'DEVICE_REGISTRATION_REQUEST': 'DEVICE_BINDING_REQUEST',
            'DEVICE_REGISTRATION_VERIFICATION': 'DEVICE_BINDING_VERIFICATION',
            'MPIN_RECOVERY_VERIFICATION': 'MPIN_RECOVERY_VERIFICATION',
            'MPIN_LOCKOUT': 'MPIN_LOCKOUT',
        }.get(kind, kind)
        outcome = 'success' if result in ('approved', 'received', 'enforced', 'success') else 'failed'
        self.add_auth(cid, did, sid, when, event_type, method, outcome,
                      '' if outcome == 'success' else 'verification_not_approved', 1)

    def add_authorization(self, cid, tid, did, when, method='mpin', result='success'):
        """A synthetic transaction-confirmation log; not a claim about a bank's exact UI."""
        txn = next(t for t in self.transactions if t['Transaction_ID'] == tid)
        self.add_auth(cid, did, txn['Session_ID'], when, 'TRANSACTION_CONFIRMATION',
                      method, result, '', 1)

    def add_ledger(self, cid, tid, when, kind, amount, other=''):
        # No ledger CSV in the agreed schema.  Crucially, no invented recipient
        # settlement record or unsupported claim of confirmed fund recovery.
        return

    def add_transaction(self, cid, sid, when, tx_type, amount,
                        beneficiary_id='', agent_id='', receiver_id=''):
        """Maintain available balance from actual customer transactions only."""
        amt = money(amount)
        before = money(self.post_balance[cid])
        if amt <= 0 or (tx_type != 'cash_in' and amt > before):
            raise ValueError(f'Insufficient balance: {cid}, {amt}, available={before}')
        after = money(before + amt if tx_type == 'cash_in' else before - amt)
        self.tx_counter += 1
        tid = f'T{self.tx_counter:08d}'
        self.transactions.append(dict(
            Transaction_ID=tid, Customer_ID=cid, Session_ID=sid,
            Beneficiary_ID=beneficiary_id, Agent_ID=agent_id, Receiver_ID=receiver_id,
            Timestamp=fmt_dt(when), Transaction_Type=tx_type, Amount=f'{amt:.2f}',
            Currency='PKR', Channel='agent' if tx_type in ('cash_out','cash_in') else 'mobile_app',
            Transaction_status='success', Sender_balance_before=f'{before:.2f}',
            Sender_balance_after=f'{after:.2f}'))
        self.post_balance[cid] = after
        return tid, amt

    def add_receipt_audit(self, cid, aid, tid, when, wallet_debit, cash_handed,
                          fee=0, source='retailer_receipt_reconciliation', note=''):
        # No independent till/receipt field in the agreed schema. Wallet debit
        # is in Transactions; alleged cash shortfall belongs in Complaints.
        return

    def add_bio_audit(self, cid, aid, tid, when, count=3, inconsistent=False):
        # Only the explicitly inconsistent case gets cross-agent verification
        # evidence. Otherwise Biometric_Logs already holds attempt summary.
        if not inconsistent:
            return
        tx = next(t for t in self.transactions if t['Transaction_ID'] == tid)
        city = next(a['City'] for a in self.agents if a['Agent_ID'] == aid)
        other_agents = [a['Agent_ID'] for a in self.agents
                        if a['City'] == city and a['Agent_ID'] != aid and a['Agent_status'] == 'active']
        if not other_agents:
            num = max(numeric_suffix(a['Agent_ID']) for a in self.agents) + 1
            extra = f'A{num:06d}'
            self.agents.append(dict(Agent_ID=extra, Agent_name=f'Synthetic {city} Service Point 2',
                Agent_location=f'{city} central area', City=city,
                Agent_reg_date='2025-06-01 09:00:00', Agent_status='active', Agent_type='retailer'))
            other_agents = [extra]
        other = self.rng.choice(other_agents)
        # Two successful biometric assertions, attached to the same cash-out,
        # point to different retailer IDs. That discrepancy is INVESTIGATABLE,
        # not proof of fraud or a magical external biometric audit.
        mismatch_when = min(when + timedelta(seconds=35), parse_dt(tx['Timestamp']) - timedelta(seconds=7))
        self.add_biometric(cid, tid, other, mismatch_when, attempts=1, failed=0, result='success')
        self._biometric_agent_mismatch_tx.add(tid)

    def add_id_event(self, cid, did, when, kind, result, record_match='Yes', note=''):
        if kind in ('REACTIVATION_REQUEST', 'REACTIVATION_APPROVED'):
            sid = self._maintenance_session(cid, did, when)
            etype = 'ACCOUNT_REACTIVATION_REQUEST' if kind == 'REACTIVATION_REQUEST' else 'ACCOUNT_REACTIVATION_VERIFICATION'
            self.add_auth(cid, did, sid, when, etype, 'kyc_otp',
                          'success' if kind == 'REACTIVATION_APPROVED' else 'success')
        elif kind == 'POST_REACTIVATION_KYC_RECONCILIATION':
            original = next((k for k in self.kyc if k['Customer_ID'] == cid and k['KYC_status'] == 'verified'), None)
            if original is None:
                original = next(k for k in self.kyc if k['Customer_ID'] == cid)
            candidate = dict(original)
            number = max(numeric_suffix(k['KYC_ID']) for k in self.kyc) + 1
            candidate['KYC_ID'] = f'KYC{number:07d}'
            # A newly submitted reactivation record does NOT match previously
            # verified identity information and is rejected for investigation.
            candidate['Guardian_Name'] = self.rng.choice([
                name for name in ('Muhammad Raza', 'Abdul Rahman', 'Imran Yousaf', 'Javed Akhtar', 'Naveed Hussain')
                if name != str(original['Guardian_Name'])])
            old_cnic = str(original['CNIC'])
            if len(old_cnic) >= 3 and old_cnic[-1].isdigit():
                candidate['CNIC'] = old_cnic[:-1] + str((int(old_cnic[-1]) + 3) % 10)
            else:
                candidate['CNIC'] = old_cnic + '_ALT'
            candidate['KYC_status'] = 'rejected'
            candidate['KYC_Reg_Date'] = fmt_dt(when)
            candidate['KYC_last_updated_date'] = fmt_dt(when)
            self.kyc.append(candidate)

    def add_dispute(self, case_id, cmpid, tid, when, kind, status='recorded',
                    role='sending_institution', note=''):
        # FTDH workflow is not represented in the frozen schema. Do not create
        # imaginary bank-to-bank lien, recovery, notification or audit records.
        return

    def inject_cc_mpin_failures(self, offset):
        # Preserve the reviewed unusual-city + valid-credential trajectory,
        # but make the alleged lack of authorization explicit via bank-held
        # customer complaint, rather than assuming a changed IP proves theft.
        super().inject_cc_mpin_failures(offset)
        case = self.cases[-1]
        cid = case['Customer_ID']
        tx = max((t for t in self.transactions[self.original_transaction_count:]
                  if t['Customer_ID'] == cid), key=lambda t: t['Timestamp'])
        new_city = next(s['City'] for s in self.sessions if s['Session_ID'] == tx['Session_ID'])
        complained = parse_dt(case['Case_created_timestamp']) + timedelta(hours=2, minutes=17)
        cmpid = self.add_complaint(cid, tx['Transaction_ID'], complained,
            'account_access_dispute',
            f'Customer reports keeping possession of their registered device and denies logging in '
            f'from {new_city}, adding the new beneficiary, or making this transfer. '
            'Customer statement is unverified and needs comparison with institution session records.')
        case['Complaint_ID'] = cmpid  # later attachment to alert-origin case
        self.ground_truth[-1]['Validation_notes'] += (
            ' Later customer denial supports credential misuse hypothesis but is not independent proof.')

    def inject_dc_shared_device(self, offset):
        super().inject_dc_shared_device(offset)
        # This is a multi-account device *pattern*, not observed emulator proof.
        gt = self.ground_truth[-1]
        gt['Scenario_ID'] = 'DC_MULTI_ACCOUNT_SHARED_DEVICE'
        gt['Validation_notes'] = ('Three customers used a newly linked same-city device in a short '
                                  'window with beneficiary transfers. Multi-account linkage suggests '
                                  'coordinated account activity, but does not independently establish malware.')
        self.alerts[-1]['Alert_type'] = 'rapid_multi_account_device_use'

    def inject_rf_multi_customer(self, offset):
        """Multi-customer retailer cash-outs + two customer reports of shortage.

        The wallet debit is verified; cash actually handed over is NOT verified
        because the frozen schema lacks retailer till and receipt fields.
        """
        t = self.now(offset)
        city = 'Lahore'
        pool = [x['Customer_ID'] for x in self.customers
            if x['City'] == city and x['Customer_ID'] not in self.used_customers
            and x['Customer_ID'] not in self.reserved_receivers
            and self.suitable(x['Customer_ID'], 6000, min_tx=3)]
        if len(pool) < 3:
            raise ValueError('Need three local customers for retailer pattern.')
        primary = self.rng.choice(pool)
        self.used_customers.add(primary)
        related = self.rng.sample([x for x in pool if x != primary], 2)
        self.used_customers.update(related)
        agent = self.add_retailer(city)
        txns = []
        for i, cid in enumerate([primary] + related):
            start = self.minutes(t, i * 13)
            did = self.primary_device(cid)
            sid, _ = self.add_session(cid, did, start, 28, city)
            self.add_auth(cid, did, sid, self.minutes(start, 1), 'LOGIN','mpin','success')
            amt = max(600, round(min(self.post_balance[cid] * self.rng.uniform(.25,.42),
                                      4200+i*1200) / 100) * 100)
            tx_at = self.minutes(start, 9)
            tid, amt = self.add_transaction(cid, sid, tx_at, 'cash_out', amt, agent_id=agent)
            self.add_biometric(cid, tid, agent, self.minutes(start, 7), 1, 0)
            txns.append((cid,tid,amt,tx_at))
        reported = []
        for j in (0, 1):
            cid,tid,amt,tx_at = txns[j]
            short = self.rng.choice([300,500,600])
            when = self.minutes(tx_at, 65+j*24)
            complaint = self.add_complaint(cid,tid,when,'cash_disbursement_dispute',
                f'Customer reports wallet debit PKR {amt:.0f}, but states retailer handed over '
                f'PKR {amt-short:.0f} in cash. Difference PKR {short:.0f} is CUSTOMER-REPORTED '
                'and requires receipt and retailer till reconciliation; not verified in these tables.')
            reported.append((cid,tid,when,complaint))
        # A complaint-created case is appropriate because cash shortfall is a
        # customer allegation, not something detectable from volume alone.
        cid,tid,when,cmpid = reported[0]
        self.add_case(cid,'RF_MULTI_CUSTOMER_CASH_SHORTFALL', 'RETAILER_RELATED_FRAUD',
            when,tid,None,76,cmpid,'complaint',
            'Three short-window same-retailer cash-outs and two independent customers report cash shortfalls. '
            'Bank debit and customer allegations are visible; no verified till evidence is assumed.')

    def inject_bio_failure_success(self, offset):
        cid = self.choose_customer(lambda c:self.suitable(c,6500,tx_type='cash_out',min_tx=2)
            and any(a['City']==self.customer_row(c)['City'] for a in self.agents))
        t = self.now(offset)
        did = self.primary_device(cid)
        city = self.customer_row(cid)['City']
        agent = self.add_retailer(city)
        sid,_ = self.add_session(cid,did,t,32,city)
        self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
        amount = self.choose_amount(cid,'cash_out','significant')
        tx_at = self.minutes(t,15)
        tid,amt = self.add_transaction(cid,sid,tx_at,'cash_out',amount,agent_id=agent)
        self.add_biometric(cid,tid,agent,self.minutes(t,12),4,3)
        self.add_bio_audit(cid,agent,tid,self.minutes(t,12),4,inconsistent=True)
        ct = self.minutes(tx_at,125)
        cmpid = self.add_complaint(cid,tid,ct,'disputed_cash_withdrawal',
            'Customer denies being present for this cash-out or providing fingerprint verification. '
            'Customer requests the institution to review the retailer identity and biometric verification. '
            'The customer statement is an allegation, not independently confirmed.')
        self.add_case(cid,'BIO_CROSS_AGENT_VERIFICATION_MISMATCH', 'BIOMETRIC_RELATED_FRAUD',
            ct,tid,None,76,cmpid,'complaint',
            'Biometric retry record and a second success attributed to different agent for same '
            'cash-out, plus customer dispute. Evidence is a contradictory audit trail.')

    def validate(self):
        """Checks actual 14 exported tables, including intentionally disputed links."""
        errors = []
        def check(ok, msg):
            if not ok: errors.append(msg)
        tbls = {
            'customers': (self.customers, 'Customer_ID'),
            'KYC_records': (self.kyc, 'KYC_ID'),
            'Devices': (self.devices, 'Device_ID'),
            'Customer_Device': (self.customer_devices, 'Customer_Device_ID'),
            'Agent_Retailers': (self.agents, 'Agent_ID'),
            'Beneficiaries': (self.beneficiaries, 'Beneficiary_ID'),
            'Network_Sessions': (self.sessions, 'Session_ID'),
            'Authentication_Logs': (self.auth, 'Auth_event_ID'),
            'Transactions': (self.transactions, 'Transaction_ID'),
            'Biometric_Logs': (self.biometrics, 'Biometric_event_ID'),
            'Complaints': (self.complaints, 'Complaint_ID'),
            'Fraud_Alerts': (self.alerts, 'Alert_ID'),
            'Cases': (self.cases, 'Case_ID'),
            'Ground_Truth': (self.ground_truth, 'Case_ID'),
        }
        for tab, (rows, key) in tbls.items():
            check(len({x[key] for x in rows}) == len(rows), f'{tab} duplicate {key}')
        customers = {r['Customer_ID']:r for r in self.customers}
        devs = {r['Device_ID']:r for r in self.devices}
        links = {(r['Customer_ID'],r['Device_ID']):r for r in self.customer_devices}
        sessions = {r['Session_ID']:r for r in self.sessions}
        txs = {r['Transaction_ID']:r for r in self.transactions}
        agents = {a['Agent_ID']:a for a in self.agents}
        benes = {b['Beneficiary_ID']:b for b in self.beneficiaries}
        complaints = {c['Complaint_ID']:c for c in self.complaints}
        alerts = {a['Alert_ID']:a for a in self.alerts}
        cases = {c['Case_ID']:c for c in self.cases}
        kyc_ids = {r['KYC_ID'] for r in self.kyc}
        for row in self.kyc:
            check(row['Customer_ID'] in customers, 'KYC missing customer')
        for row in self.customer_devices:
            check(row['Customer_ID'] in customers and row['Device_ID'] in devs,
                  'Customer_Device FK invalid')
            check(parse_dt(row['First_seen'])<=parse_dt(row['Last_seen']),
                  'Customer_Device invalid dates')
        for s in self.sessions:
            link = links.get((s['Customer_ID'],s['Device_ID']))
            check(bool(link),'Session not linked to account and device')
            if link:
                check(parse_dt(s['Session_start']) >= parse_dt(link['First_seen']),
                      'Session precedes device association')
            check(parse_dt(s['Session_start'])<=parse_dt(s['Session_end']), 'Session end before start')
        for a in self.auth:
            sess = sessions.get(a['Session_ID'])
            check(bool(sess), 'Authentication missing session')
            if sess:
                check(sess['Customer_ID']==a['Customer_ID'] and sess['Device_ID']==a['Device_ID'],
                      'Authentication/session owner mismatch')
                check(parse_dt(sess['Session_start'])<=parse_dt(a['Event_timestamp'])<=parse_dt(sess['Session_end']),
                      'Authentication outside session')
        for tx in self.transactions:
            sess = sessions.get(tx['Session_ID'])
            check(bool(sess),'Transaction missing session')
            if sess:
                check(sess['Customer_ID']==tx['Customer_ID'], 'Transaction/customer mismatch')
                check(parse_dt(sess['Session_start'])<=parse_dt(tx['Timestamp'])<=parse_dt(sess['Session_end']),
                      'Transaction time outside session')
            if tx['Beneficiary_ID']:
                ben = benes.get(tx['Beneficiary_ID'])
                check(bool(ben),'Unknown beneficiary')
                if ben:
                    check(ben['Customer_ID']==tx['Customer_ID'], 'Beneficiary belongs to different customer')
                    check(parse_dt(ben['Beneficiary_added_time'])<=parse_dt(tx['Timestamp']),
                          'Beneficiary added after transfer')
            if tx['Agent_ID']:
                check(tx['Agent_ID'] in agents, 'Unknown retailer')
            if tx['Transaction_ID'].startswith('T') and not tx['Transaction_ID'].startswith('TX'):
                amount=money(tx['Amount']); before=money(tx['Sender_balance_before']); after=money(tx['Sender_balance_after'])
                check(amount>0 and after>=0 and abs(after-(before+amount if tx['Transaction_Type']=='cash_in' else before-amount))<0.011,
                      'Injected transaction balance arithmetic invalid')
                if tx['Transaction_Type'] in ('cash_out','cash_in'):
                    check(abs(amount % 100)<0.011,'Injected physical cash movement fractional')
                    check(sess is not None and agents[tx['Agent_ID']]['City']==sess['City'],
                          'Injected physical cash movement wrong-city retailer')
        for b in self.biometrics:
            txn = txs.get(b['Transaction_ID'])
            check(bool(txn),'Biometric references absent transaction')
            if txn:
                check(b['Customer_ID']==txn['Customer_ID'], 'Biometric customer mismatch')
                if b['Agent_ID'] != txn['Agent_ID']:
                    check(b['Transaction_ID'] in self._biometric_agent_mismatch_tx,
                          'Unexpected biometric agent inconsistency')
                check(parse_dt(b['Event_Timestamp'])<=parse_dt(txn['Timestamp']),
                      'Biometric recorded after cashout')
        for c in self.complaints:
            check(c['Customer_ID'] in customers and (not c['Transaction_ID'] or c['Transaction_ID'] in txs),
                  'Complaint invalid references')
        for al in self.alerts:
            check(al['Customer_ID'] in customers and (not al['Transaction_ID'] or al['Transaction_ID'] in txs),
                  'Alert invalid references')
        for case in self.cases:
            alert=alerts.get(case['Alert_ID']); complaint=complaints.get(case['Complaint_ID'])
            created=parse_dt(case['Case_created_timestamp'])
            check(bool(alert or complaint), 'Case missing origin')
            if alert:
                check(alert['Customer_ID']==case['Customer_ID'] and parse_dt(alert['Alert_timestamp'])<=created,
                      'Invalid alert chronology')
            if case['Case_source']=='complaint':
                check(bool(complaint) and parse_dt(complaint['Complaint_timestamp'])<=created,
                      'Complaint case started before complaint')
            if case['Case_source']=='alert':
                check(bool(alert), 'Alert-origin case missing alert')
        for gt in self.ground_truth:
            check(gt['Case_ID'] in cases, 'Ground truth missing case')
        check(len(self.cases)==14*getattr(self,'batches',1) and self.fraud_scenario_count==9*getattr(self,'batches',1) and self.false_positive_count==5*getattr(self,'batches',1),
              'Scaled case counts do not match batches')
        for r in self.kyc:
            check(r['Customer_ID'] in customers, 'KYC without existing customer')
        # Core scenario-specific checks: require evidence in the exported data.
        by_sc={g['Scenario_ID']:cases[g['Case_ID']] for g in self.ground_truth}
        multi=by_sc.get('DC_MULTI_ACCOUNT_SHARED_DEVICE')
        if multi:
            cid=multi['Customer_ID']
            activity=[t for t in self.transactions[self.original_transaction_count:] if t['Customer_ID']==cid]
            if activity:
                device=sessions[activity[-1]['Session_ID']]['Device_ID']
                users={r['Customer_ID'] for r in self.customer_devices if r['Device_ID']==device}
                check(len(users)>=3,'Device scenario needs >=3 linked accounts')
        bio_case=by_sc.get('BIO_CROSS_AGENT_VERIFICATION_MISMATCH')
        if bio_case:
            complaint=complaints.get(bio_case['Complaint_ID'])
            txid=complaint['Transaction_ID'] if complaint else ''
            agents_used={b['Agent_ID'] for b in self.biometrics if b['Transaction_ID']==txid and b['Result']=='success'}
            check(len(agents_used)>=2,'Biometric case missing conflicting agent IDs')
        kyc_case=by_sc.get('KYC_REACTIVATION_IDENTITY_MISMATCH')
        if kyc_case:
            rows=[k for k in self.kyc if k['Customer_ID']==kyc_case['Customer_ID']]
            check(len(rows)>=2 and any(k['KYC_status']=='rejected' for k in rows),
                  'KYC mismatch case lacks rejected candidate document')
        for newc in self.complaints[self.original_complaint_count:]:
            check(newc['Complaint_Type'].lower() not in {g['Fraud_type'].lower() for g in self.ground_truth},
                  'Fraud category leaked into Complaint_Type')
        if errors:
            raise ValueError(f'Core-schema validation FAILED ({len(errors)}):\n'+'\n'.join(' - '+x for x in errors[:45]))
        print('VALIDATION PASSED: original 14 tables and expected fraud/nonfraud cases; no supplementary CSVs.')

    def export(self):
        # Reuse the original core-table schema writer. No extra files at all.
        self.output_dir.mkdir(parents=True,exist_ok=True)
        Injector.export(self)
        actual={p.name for p in self.output_dir.iterdir() if p.is_file()}
        expected={'customers.csv','KYC_records.csv','Devices.csv','Customer_Device.csv',
            'Agent_Retailers.csv','Beneficiaries.csv','Network_Sessions.csv','Authentication_Logs.csv',
            'Transactions.csv','Biometric_Logs.csv','Complaints.csv','Fraud_Alerts.csv',
            'Cases.csv','Ground_Truth.csv'}
        if actual != expected:
            raise ValueError(f'Expected exactly 14 CSVs: extras={actual-expected}, missing={expected-actual}')
        print(f'Final V2 export contains exactly {len(actual)} CSVs; current Access schema unchanged.')


def main_v2_final():
    parser=argparse.ArgumentParser(description='CyFinX Fraud Injector V2 FINAL: 14 existing Access tables only.')
    parser.add_argument('--input',default='cyfinx_normal_population',
                        help='Directory containing the clean normal-population CSVs')
    parser.add_argument('--output',default='cyfinx_fraud_test_v2_final',
                        help='Directory for exactly 14 resulting CSVs')
    parser.add_argument('--seed',type=int,default=20261009)
    args=parser.parse_args()
    generator=InjectorV2Final(args.input,args.output,args.seed)
    generator.run()

if __name__=='__main__':
    main_v2_final()
