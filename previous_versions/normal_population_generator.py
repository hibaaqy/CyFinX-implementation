#!/usr/bin/env python3
"""
CyFinX Normal Population Generator V1
-------------------------------------
Generates a NORMAL synthetic six-month financial-services population that matches
the CyFinX Access schema. It does NOT inject fraud.

Outputs:
    customers.csv
    KYC_records.csv
    Devices.csv
    Agent_Retailers.csv
    Beneficiaries.csv
    Network_Sessions.csv
    Authentication_Logs.csv
    Transactions.csv
    Biometric_Logs.csv
    Fraud_Alerts.csv          (headers only)
    Ground_Truth.csv          (headers only)

Design principles:
- Relational consistency: every foreign key points to an existing parent record.
- Chronological consistency: devices, sessions, beneficiaries and transactions
  appear in a sensible order.
- Behavioural consistency: each customer has a hidden normal profile used only
  to generate their history.
- Legitimate variation: normal customers can have new devices, MPIN failures,
  resets, new beneficiaries, travel, late-night activity and biometric retries.
- No fraud labels or alerts are generated in this phase.

All data is synthetic and is NOT intended to reproduce JazzCash statistics.
"""

import argparse
import csv
import ipaddress
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# ----------------------------- CONFIGURATION -----------------------------

DEFAULT_CUSTOMERS = 100
DEFAULT_SEED = 42
DEFAULT_START = datetime(2026, 4, 1, 0, 0, 0)
DEFAULT_END = datetime(2026, 9, 30, 23, 59, 59)

CITIES = {
    "Karachi": (24.8607, 67.0011),
    "Lahore": (31.5204, 74.3587),
    "Islamabad": (33.6844, 73.0479),
    "Rawalpindi": (33.5651, 73.0169),
    "Multan": (30.1575, 71.5249),
    "Faisalabad": (31.4504, 73.1350),
    "Peshawar": (34.0151, 71.5249),
    "Quetta": (30.1798, 66.9750),
    "Gujranwala": (32.1877, 74.1945),
    "Hyderabad": (25.3960, 68.3578),
}

CITY_WEIGHTS = [0.23, 0.17, 0.10, 0.09, 0.09, 0.09, 0.07, 0.05, 0.06, 0.05]

FIRST_NAMES = [
    "Ayesha", "Ali", "Hiba", "Hamza", "Fatima", "Ahmed", "Sara", "Usman",
    "Zainab", "Bilal", "Mariam", "Hassan", "Sana", "Omar", "Iqra", "Saad",
    "Mahnoor", "Daniyal", "Laiba", "Talha", "Noor", "Abdullah", "Anaya", "Adeel",
]
LAST_NAMES = [
    "Khan", "Ali", "Ahmed", "Malik", "Qureshi", "Sheikh", "Raza", "Hussain",
    "Siddiqui", "Butt", "Chaudhry", "Iqbal", "Rashid", "Farooq", "Akram", "Shah",
]

ANDROID_MODELS = [
    ("mobile", "Android", "Samsung Galaxy A54"),
    ("mobile", "Android", "Samsung Galaxy A24"),
    ("mobile", "Android", "Infinix Note 30"),
    ("mobile", "Android", "Tecno Camon 20"),
    ("mobile", "Android", "Xiaomi Redmi Note 12"),
    ("mobile", "Android", "Oppo A78"),
    ("mobile", "Android", "Vivo Y27"),
]
IOS_MODELS = [
    ("mobile", "iOS", "iPhone 11"),
    ("mobile", "iOS", "iPhone 12"),
    ("mobile", "iOS", "iPhone 13"),
    ("mobile", "iOS", "iPhone 14"),
]
ISPS = ["Jazz", "Zong", "Telenor", "Ufone", "PTCL", "Nayatel", "StormFiber"]
NETWORK_TYPES = ["mobile_data", "wifi"]

# These are explicit SYNTHETIC assumptions for simulation, not real institution statistics.
SEGMENT_CONFIG = {
    "LOW_ACTIVITY": {
        "weight": 0.25,
        "monthly_transactions": (2, 5),
        "typical_amount": (500, 5000),
        "starting_balance": (15000, 60000),
    },
    "REGULAR": {
        "weight": 0.60,
        "monthly_transactions": (5, 12),
        "typical_amount": (1000, 15000),
        "starting_balance": (30000, 150000),
    },
    "HIGH_ACTIVITY": {
        "weight": 0.15,
        "monthly_transactions": (12, 28),
        "typical_amount": (2000, 40000),
        "starting_balance": (75000, 350000),
    },
}

TRANSACTION_TYPES = ["transfer", "payment", "cash_in", "cash_out"]
TRANSACTION_WEIGHTS = [0.38, 0.25, 0.17, 0.20]

# ----------------------------- HELPERS -----------------------------

def fmt_dt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def clamp(value, low, high):
    return max(low, min(high, value))

def random_datetime(start, end):
    seconds = int((end - start).total_seconds())
    if seconds <= 0:
        return start
    return start + timedelta(seconds=random.randint(0, seconds))

def weighted_choice(items, weights):
    return random.choices(items, weights=weights, k=1)[0]

def synthetic_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def synthetic_cnic(index):
    # Synthetic structure only. Deliberately generated, not sourced from real people.
    area = 90000 + (index % 9999)
    family = 1000000 + ((index * 7919) % 8999999)
    check = (index * 7) % 10
    return f"{area:05d}-{family:07d}-{check}"

def synthetic_mobile(index):
    # Synthetic mobile-like identifier.
    prefix = random.choice(["0300", "0301", "0302", "0303", "0310", "0320", "0330", "0340"])
    suffix = 1000000 + ((index * 3571) % 8999999)
    return f"{prefix}{suffix:07d}"

def synthetic_account(prefix, index):
    return f"{prefix}{index:010d}"

def synthetic_ip():
    # CGNAT range used as synthetic session IPs; changes naturally between sessions.
    a = random.randint(64, 127)
    b = random.randint(0, 255)
    c = random.randint(1, 254)
    return f"100.{a}.{b}.{c}"

def jitter_coordinates(city, wider=False):
    lat, lon = CITIES[city]
    spread = 0.15 if wider else 0.035
    return round(lat + random.uniform(-spread, spread), 6), round(lon + random.uniform(-spread, spread), 6)

def choose_segment():
    names = list(SEGMENT_CONFIG.keys())
    weights = [SEGMENT_CONFIG[n]["weight"] for n in names]
    return weighted_choice(names, weights)

def choose_device_model():
    # Mostly Android in this synthetic environment, with some iOS.
    return random.choice(ANDROID_MODELS if random.random() < 0.82 else IOS_MODELS)

def choose_active_hour(profile):
    # Usually use preferred hours, with occasional legitimate late-night activity.
    if random.random() < 0.06:
        return random.choice([0, 1, 2, 3, 4, 5])
    start_h, end_h = profile["preferred_hours"]
    return random.randint(start_h, end_h)

def amount_for(profile, tx_type):
    low, high = profile["amount_range"]
    if tx_type == "cash_in":
        factor = random.uniform(0.8, 1.8)
    elif tx_type == "cash_out":
        factor = random.uniform(0.7, 1.5)
    elif tx_type == "payment":
        factor = random.uniform(0.25, 0.8)
    else:
        factor = random.uniform(0.6, 1.4)

    amount = random.uniform(low, high) * factor

    # Legitimate lookalike: occasional amount outside the usual range.
    if random.random() < 0.035:
        amount *= random.uniform(1.8, 3.2)

    return round(max(100.0, amount), 2)

def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

# ----------------------------- GENERATOR -----------------------------

class CyFinXGenerator:
    def __init__(self, customer_count, start, end, seed, output_dir):
        random.seed(seed)
        self.customer_count = customer_count
        self.start = start
        self.end = end
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.customers = []
        self.kyc = []
        self.devices = []
        self.agents = []
        self.beneficiaries = []
        self.sessions = []
        self.auth_logs = []
        self.transactions = []
        self.biometric_logs = []
        self.fraud_alerts = []
        self.ground_truth = []

        self.profiles = {}
        self.customer_devices = defaultdict(list)
        self.customer_beneficiaries = defaultdict(list)
        self.customer_balances = {}

        self.device_counter = 0
        self.beneficiary_counter = 0
        self.session_counter = 0
        self.auth_counter = 0
        self.transaction_counter = 0
        self.biometric_counter = 0

    def generate_agents(self):
        # Scales to ~250 agents at 5,000 customers, but keeps a useful pool for 100-customer test.
        agent_count = max(25, round(self.customer_count * 0.05))
        for i in range(1, agent_count + 1):
            city = weighted_choice(list(CITIES.keys()), CITY_WEIGHTS)
            reg_date = random_datetime(self.start - timedelta(days=1500), self.start - timedelta(days=30))
            status = weighted_choice(["active", "inactive"], [0.95, 0.05])
            agent_type = weighted_choice(["agent", "retailer"], [0.65, 0.35])
            self.agents.append({
                "Agent_ID": f"A{i:06d}",
                "Agent_name": f"{city} {agent_type.title()} {i:04d}",
                "Agent_location": f"Synthetic service point {i}, {city}",
                "City": city,
                "Agent_reg_date": fmt_dt(reg_date),
                "Agent_status": status,
                "Agent_type": agent_type,
            })

    def generate_customers_and_kyc(self):
        sim_days = (self.end - self.start).days

        for i in range(1, self.customer_count + 1):
            cid = f"C{i:06d}"
            city = weighted_choice(list(CITIES.keys()), CITY_WEIGHTS)
            segment = choose_segment()

            # Most accounts predate the simulation; a minority join during it.
            if random.random() < 0.85:
                reg_date = random_datetime(self.start - timedelta(days=1500), self.start - timedelta(days=1))
            else:
                reg_date = random_datetime(self.start, self.end - timedelta(days=14))

            acc_status = weighted_choice(["active", "dormant", "closed"], [0.90, 0.08, 0.02])
            if acc_status == "closed":
                # Closed customers will simply have little/no later activity.
                segment = "LOW_ACTIVITY"

            self.customers.append({
                "Customer_ID": cid,
                "Reg_Date": fmt_dt(reg_date),
                "Acc_Status": acc_status,
                "City": city,
                "Customer_segment": segment,
            })

            dob = random_datetime(datetime(1965, 1, 1), datetime(2007, 12, 31))
            kyc_date = reg_date - timedelta(days=random.randint(0, 7))
            kyc_last_update = kyc_date + timedelta(days=random.randint(0, max(1, (self.end - kyc_date).days)))
            kyc_last_update = min(kyc_last_update, self.end)

            self.kyc.append({
                "KYC_ID": f"KYC{i:06d}",
                "Customer_ID": cid,
                "Full_name": synthetic_name(),
                "CNIC": synthetic_cnic(i),
                "DOB": fmt_dt(dob),
                "Guardian_Name": synthetic_name(),
                "Reg_Mobile": synthetic_mobile(i),
                "Reg_Address": f"House {100 + (i % 900)}, Synthetic Block {chr(65 + (i % 6))}, {city}",
                "City": city,
                "KYC_Reg_Date": fmt_dt(kyc_date),
                "KYC_status": weighted_choice(["verified", "pending"], [0.98, 0.02]),
                "KYC_last_updated_date": fmt_dt(kyc_last_update),
            })

            cfg = SEGMENT_CONFIG[segment]
            preferred_start = random.choice([7, 8, 9, 10, 11])
            preferred_end = random.choice([20, 21, 22, 23])
            self.profiles[cid] = {
                "home_city": city,
                "segment": segment,
                "amount_range": cfg["typical_amount"],
                "monthly_transactions": random.randint(*cfg["monthly_transactions"]),
                "preferred_hours": (preferred_start, preferred_end),
                "travel_probability": random.uniform(0.01, 0.05),
                "auth_failure_probability": random.uniform(0.02, 0.08),
                "mpin_reset_probability": random.uniform(0.002, 0.012),
                "biometric_retry_probability": random.uniform(0.02, 0.07),
                "acc_status": acc_status,
                "reg_date": reg_date,
            }
            self.customer_balances[cid] = round(random.uniform(*cfg["starting_balance"]), 2)

    def generate_devices(self):
        for customer in self.customers:
            cid = customer["Customer_ID"]
            profile = self.profiles[cid]
            available_start = max(self.start, profile["reg_date"])

            # Explicit synthetic assumption: 75% one device, 20% two, 5% three.
            device_count = weighted_choice([1, 2, 3], [0.75, 0.20, 0.05])

            first_seen_dates = [available_start]
            for _ in range(1, device_count):
                if available_start < self.end - timedelta(days=20):
                    first_seen_dates.append(random_datetime(available_start + timedelta(days=15), self.end - timedelta(days=5)))
                else:
                    first_seen_dates.append(available_start)
            first_seen_dates.sort()

            for j, first_seen in enumerate(first_seen_dates):
                self.device_counter += 1
                did = f"D{self.device_counter:07d}"
                dtype, os_name, model = choose_device_model()

                # Older device may become inactive after a later device appears.
                if j < len(first_seen_dates) - 1 and random.random() < 0.70:
                    last_seen = first_seen_dates[j + 1] + timedelta(days=random.randint(0, 20))
                    last_seen = min(last_seen, self.end)
                    status = "inactive"
                else:
                    last_seen = self.end
                    status = "active"

                row = {
                    "Device_ID": did,
                    "Customer_ID": cid,
                    "Device_type": dtype,
                    "Device_OS": os_name,
                    "Device_model": model,
                    "Device_first_seen": fmt_dt(first_seen),
                    "Device_last_seen": fmt_dt(last_seen),
                    "Device_status": status,
                }
                self.devices.append(row)
                self.customer_devices[cid].append({
                    **row,
                    "_first": first_seen,
                    "_last": last_seen,
                })

    def generate_beneficiaries(self):
        for customer in self.customers:
            cid = customer["Customer_ID"]
            profile = self.profiles[cid]
            available_start = max(self.start, profile["reg_date"])

            if profile["acc_status"] == "closed":
                max_b = 1
            elif profile["segment"] == "LOW_ACTIVITY":
                max_b = 3
            elif profile["segment"] == "REGULAR":
                max_b = 6
            else:
                max_b = 10

            beneficiary_count = random.randint(0, max_b)
            for _ in range(beneficiary_count):
                self.beneficiary_counter += 1
                bid = f"B{self.beneficiary_counter:07d}"
                added = random_datetime(available_start, self.end - timedelta(hours=1))

                internal = random.random() < 0.60 and self.customer_count > 1
                if internal:
                    possible = [c["Customer_ID"] for c in self.customers if c["Customer_ID"] != cid]
                    receiver_customer = random.choice(possible)
                    beneficiary_type = "internal"
                    account = synthetic_account("INT", int(receiver_customer[1:]))
                else:
                    receiver_customer = ""
                    beneficiary_type = "external"
                    account = synthetic_account("EXT", self.beneficiary_counter)

                row = {
                    "Beneficiary_ID": bid,
                    "Customer_ID": cid,
                    "Beneficiary_customer_ID": receiver_customer,
                    "Beneficiary_account": account,
                    "Beneficiary_type": beneficiary_type,
                    "Beneficiary_added_time": fmt_dt(added),
                    "Beneficiary_status": weighted_choice(["active", "inactive"], [0.95, 0.05]),
                }
                self.beneficiaries.append(row)
                self.customer_beneficiaries[cid].append({**row, "_added": added})

    def active_device_at(self, cid, when):
        candidates = [
            d for d in self.customer_devices[cid]
            if d["_first"] <= when <= d["_last"] and d["Device_status"] != "blocked"
        ]
        if not candidates:
            # Fall back to a device already introduced by this time.
            candidates = [d for d in self.customer_devices[cid] if d["_first"] <= when]
        if not candidates:
            return None
        # Usually use the most recently introduced active device.
        candidates.sort(key=lambda x: x["_first"], reverse=True)
        return candidates[0] if random.random() < 0.82 else random.choice(candidates)

    def available_beneficiary_at(self, cid, when):
        candidates = [
            b for b in self.customer_beneficiaries[cid]
            if b["_added"] <= when and b["Beneficiary_status"] == "active"
        ]
        return random.choice(candidates) if candidates else None

    def create_session(self, cid, when, device):
        self.session_counter += 1
        sid = f"S{self.session_counter:08d}"
        profile = self.profiles[cid]

        # Usually home city, sometimes legitimate travel.
        if random.random() < profile["travel_probability"]:
            other = [c for c in CITIES if c != profile["home_city"]]
            city = random.choice(other)
            wider = True
        else:
            city = profile["home_city"]
            wider = False

        lat, lon = jitter_coordinates(city, wider=wider)
        duration = random.randint(2, 35)
        end = min(when + timedelta(minutes=duration), self.end)

        row = {
            "Session_ID": sid,
            "Customer_ID": cid,
            "Device_ID": device["Device_ID"],
            "Session_start": fmt_dt(when),
            "Session_end": fmt_dt(end),
            "IP_address": synthetic_ip(),
            "Latitude": lat,
            "Longitude": lon,
            "City": city,
            "Network_type": weighted_choice(NETWORK_TYPES, [0.65, 0.35]),
            "ISP": random.choice(ISPS),
        }
        self.sessions.append(row)
        return row

    def create_authentication(self, cid, session, when):
        profile = self.profiles[cid]
        device_id = session["Device_ID"]
        sid = session["Session_ID"]

        # Occasional legitimate MPIN reset flow.
        if random.random() < profile["mpin_reset_probability"]:
            self.auth_counter += 1
            self.auth_logs.append({
                "Auth_event_ID": f"AUTH{self.auth_counter:08d}",
                "Customer_ID": cid,
                "Device_ID": device_id,
                "Session_ID": sid,
                "Event_timestamp": fmt_dt(when),
                "Event_type": "OTP_RESET",
                "Auth_method": "otp",
                "Result": "success",
                "Failure_reason": "",
                "Attempt_count": 1,
            })
            when += timedelta(seconds=random.randint(20, 90))

            self.auth_counter += 1
            self.auth_logs.append({
                "Auth_event_ID": f"AUTH{self.auth_counter:08d}",
                "Customer_ID": cid,
                "Device_ID": device_id,
                "Session_ID": sid,
                "Event_timestamp": fmt_dt(when),
                "Event_type": "MPIN_RESET",
                "Auth_method": "mpin",
                "Result": "success",
                "Failure_reason": "",
                "Attempt_count": 1,
            })
            when += timedelta(seconds=random.randint(15, 60))

        # Normal login, sometimes with one or two legitimate failures first.
        failed = 0
        if random.random() < profile["auth_failure_probability"]:
            failed = weighted_choice([1, 2], [0.85, 0.15])

        for attempt in range(1, failed + 1):
            self.auth_counter += 1
            self.auth_logs.append({
                "Auth_event_ID": f"AUTH{self.auth_counter:08d}",
                "Customer_ID": cid,
                "Device_ID": device_id,
                "Session_ID": sid,
                "Event_timestamp": fmt_dt(when),
                "Event_type": "LOGIN",
                "Auth_method": "mpin",
                "Result": "failed",
                "Failure_reason": "wrong_mpin",
                "Attempt_count": attempt,
            })
            when += timedelta(seconds=random.randint(10, 45))

        self.auth_counter += 1
        self.auth_logs.append({
            "Auth_event_ID": f"AUTH{self.auth_counter:08d}",
            "Customer_ID": cid,
            "Device_ID": device_id,
            "Session_ID": sid,
            "Event_timestamp": fmt_dt(when),
            "Event_type": "LOGIN",
            "Auth_method": "mpin",
            "Result": "success",
            "Failure_reason": "",
            "Attempt_count": failed + 1,
        })

    def choose_agent(self, customer_city):
        active = [a for a in self.agents if a["Agent_status"] == "active"]
        same_city = [a for a in active if a["City"] == customer_city]
        if same_city and random.random() < 0.85:
            return random.choice(same_city)
        return random.choice(active)

    def create_biometric(self, cid, tx, agent, when):
        self.biometric_counter += 1
        profile = self.profiles[cid]

        # Normal biometric retries are intentionally present.
        retry = random.random() < profile["biometric_retry_probability"]
        failed_attempts = 1 if retry else 0
        attempts = 2 if retry else 1

        self.biometric_logs.append({
            "Biometric_event_ID": f"BIO{self.biometric_counter:08d}",
            "Customer_ID": cid,
            "Transaction_ID": tx["Transaction_ID"],
            "Agent_ID": agent["Agent_ID"] if agent else "",
            "Event_Timestamp": fmt_dt(when),
            "Biometric_type": weighted_choice(["fingerprint", "face"], [0.85, 0.15]),
            "Biometric_required": True,
            "Attempt_count": attempts,
            "Failed_attempts": failed_attempts,
            "Result": "success",
        })

    def create_transaction(self, cid, session, when):
        profile = self.profiles[cid]
        tx_type = weighted_choice(TRANSACTION_TYPES, TRANSACTION_WEIGHTS)
        beneficiary = None
        agent = None

        if tx_type == "transfer":
            beneficiary = self.available_beneficiary_at(cid, when)
            if beneficiary is None:
                # No beneficiary available yet: use a payment instead.
                tx_type = "payment"

        if tx_type in ("cash_in", "cash_out"):
            agent = self.choose_agent(session["City"])

        amount = amount_for(profile, tx_type)
        before = self.customer_balances[cid]

        # Keep normal outgoing activity within available balance.
        if tx_type in ("transfer", "payment", "cash_out"):
            if before < 200:
                tx_type = "cash_in"
                beneficiary = None
                agent = self.choose_agent(session["City"])
                amount = round(random.uniform(1000, 10000), 2)
            else:
                amount = min(amount, max(100.0, before * 0.75))

        status = weighted_choice(["success", "failed"], [0.97, 0.03])

        if status == "failed":
            after = before
        elif tx_type == "cash_in":
            after = before + amount
        else:
            after = max(0.0, before - amount)

        self.transaction_counter += 1
        txid = f"TX{self.transaction_counter:09d}"

        receiver_id = ""
        if beneficiary:
            receiver_id = beneficiary["Beneficiary_customer_ID"] or beneficiary["Beneficiary_account"]

        channel = "agent" if tx_type in ("cash_in", "cash_out") else "mobile_app"

        tx = {
            "Transaction_ID": txid,
            "Customer_ID": cid,
            "Session_ID": session["Session_ID"],
            "Beneficiary_ID": beneficiary["Beneficiary_ID"] if beneficiary else "",
            "Agent_ID": agent["Agent_ID"] if agent else "",
            "Receiver_ID": receiver_id,
            "Timestamp": fmt_dt(when),
            "Transaction_Type": tx_type,
            "Amount": round(amount, 2),
            "Currency": "PKR",
            "Channel": channel,
            "Transaction_status": status,
            "Sender_balance_before": round(before, 2),
            "Sender_balance_after": round(after, 2),
        }
        self.transactions.append(tx)

        if status == "success":
            self.customer_balances[cid] = round(after, 2)

        # In this synthetic model, successful agent cash-out sometimes requires biometrics.
        if tx_type == "cash_out" and status == "success" and random.random() < 0.70:
            self.create_biometric(cid, tx, agent, when + timedelta(seconds=random.randint(5, 60)))

    def simulate_activity(self):
        total_days = max(1, (self.end - self.start).days + 1)
        months = total_days / 30.4375

        for customer in self.customers:
            cid = customer["Customer_ID"]
            profile = self.profiles[cid]

            if profile["acc_status"] == "closed":
                activity_multiplier = 0.12
            elif profile["acc_status"] == "dormant":
                activity_multiplier = 0.18
            else:
                activity_multiplier = 1.0

            expected = profile["monthly_transactions"] * months * activity_multiplier
            # Add natural variation around expected activity.
            count = max(0, int(random.gauss(expected, max(1.0, expected * 0.20))))

            active_start = max(self.start, profile["reg_date"])
            if active_start >= self.end:
                continue

            event_dates = []
            for _ in range(count):
                base = random_datetime(active_start, self.end)
                hour = choose_active_hour(profile)
                event_dt = base.replace(
                    hour=hour,
                    minute=random.randint(0, 59),
                    second=random.randint(0, 59),
                )
                event_dt = clamp_datetime(event_dt, active_start, self.end)
                event_dates.append(event_dt)

            event_dates.sort()

            for when in event_dates:
                device = self.active_device_at(cid, when)
                if not device:
                    continue

                session = self.create_session(cid, when, device)
                self.create_authentication(cid, session, when)
                self.create_transaction(cid, session, when + timedelta(minutes=random.randint(1, 8)))

    def adjust_device_last_seen(self):
        # Make Device_last_seen reflect actual observed session history where possible.
        seen = defaultdict(list)
        for s in self.sessions:
            seen[s["Device_ID"]].append(datetime.strptime(s["Session_start"], "%Y-%m-%d %H:%M:%S"))

        for row in self.devices:
            did = row["Device_ID"]
            if seen[did]:
                row["Device_last_seen"] = fmt_dt(max(seen[did]))

    def validate(self):
        errors = []

        customers = {r["Customer_ID"] for r in self.customers}
        devices = {r["Device_ID"] for r in self.devices}
        sessions = {r["Session_ID"] for r in self.sessions}
        beneficiaries = {r["Beneficiary_ID"] for r in self.beneficiaries}
        agents = {r["Agent_ID"] for r in self.agents}
        transactions = {r["Transaction_ID"] for r in self.transactions}

        def check(condition, message):
            if not condition:
                errors.append(message)

        for r in self.kyc:
            check(r["Customer_ID"] in customers, f"KYC bad Customer_ID: {r}")
        for r in self.devices:
            check(r["Customer_ID"] in customers, f"Device bad Customer_ID: {r}")
        for r in self.sessions:
            check(r["Customer_ID"] in customers, f"Session bad Customer_ID: {r}")
            check(r["Device_ID"] in devices, f"Session bad Device_ID: {r}")
            check(datetime.strptime(r["Session_end"], "%Y-%m-%d %H:%M:%S") >=
                  datetime.strptime(r["Session_start"], "%Y-%m-%d %H:%M:%S"),
                  f"Session end before start: {r}")
        for r in self.auth_logs:
            check(r["Customer_ID"] in customers, f"Auth bad Customer_ID: {r}")
            check(r["Device_ID"] in devices, f"Auth bad Device_ID: {r}")
            check(r["Session_ID"] in sessions, f"Auth bad Session_ID: {r}")
        for r in self.beneficiaries:
            check(r["Customer_ID"] in customers, f"Beneficiary bad Customer_ID: {r}")
        for r in self.transactions:
            check(r["Customer_ID"] in customers, f"Transaction bad Customer_ID: {r}")
            check(r["Session_ID"] in sessions, f"Transaction bad Session_ID: {r}")
            if r["Beneficiary_ID"]:
                check(r["Beneficiary_ID"] in beneficiaries, f"Transaction bad Beneficiary_ID: {r}")
            if r["Agent_ID"]:
                check(r["Agent_ID"] in agents, f"Transaction bad Agent_ID: {r}")
            check(r["Sender_balance_after"] >= 0, f"Negative balance: {r}")
        for r in self.biometric_logs:
            check(r["Customer_ID"] in customers, f"Biometric bad Customer_ID: {r}")
            check(r["Transaction_ID"] in transactions, f"Biometric bad Transaction_ID: {r}")
            if r["Agent_ID"]:
                check(r["Agent_ID"] in agents, f"Biometric bad Agent_ID: {r}")

        # Chronology: beneficiary must exist before any transaction using it.
        beneficiary_added = {
            r["Beneficiary_ID"]: datetime.strptime(r["Beneficiary_added_time"], "%Y-%m-%d %H:%M:%S")
            for r in self.beneficiaries
        }
        for r in self.transactions:
            if r["Beneficiary_ID"]:
                tx_time = datetime.strptime(r["Timestamp"], "%Y-%m-%d %H:%M:%S")
                check(beneficiary_added[r["Beneficiary_ID"]] <= tx_time,
                      f"Beneficiary used before added: {r}")

        if errors:
            print("\nVALIDATION FAILED")
            for e in errors[:25]:
                print(" -", e)
            if len(errors) > 25:
                print(f" ... plus {len(errors)-25} more errors")
            raise ValueError(f"Dataset validation failed with {len(errors)} error(s).")

        print("Validation passed: all tested foreign keys and chronology rules are consistent.")

    def export(self):
        schemas = {
            "customers.csv": (
                ["Customer_ID", "Reg_Date", "Acc_Status", "City", "Customer_segment"],
                self.customers,
            ),
            "KYC_records.csv": (
                ["KYC_ID", "Customer_ID", "Full_name", "CNIC", "DOB", "Guardian_Name",
                 "Reg_Mobile", "Reg_Address", "City", "KYC_Reg_Date", "KYC_status",
                 "KYC_last_updated_date"],
                self.kyc,
            ),
            "Devices.csv": (
                ["Device_ID", "Customer_ID", "Device_type", "Device_OS", "Device_model",
                 "Device_first_seen", "Device_last_seen", "Device_status"],
                self.devices,
            ),
            "Agent_Retailers.csv": (
                ["Agent_ID", "Agent_name", "Agent_location", "City", "Agent_reg_date",
                 "Agent_status", "Agent_type"],
                self.agents,
            ),
            "Beneficiaries.csv": (
                ["Beneficiary_ID", "Customer_ID", "Beneficiary_customer_ID",
                 "Beneficiary_account", "Beneficiary_type", "Beneficiary_added_time",
                 "Beneficiary_status"],
                self.beneficiaries,
            ),
            "Network_Sessions.csv": (
                ["Session_ID", "Customer_ID", "Device_ID", "Session_start", "Session_end",
                 "IP_address", "Latitude", "Longitude", "City", "Network_type", "ISP"],
                self.sessions,
            ),
            "Authentication_Logs.csv": (
                ["Auth_event_ID", "Customer_ID", "Device_ID", "Session_ID", "Event_timestamp",
                 "Event_type", "Auth_method", "Result", "Failure_reason", "Attempt_count"],
                self.auth_logs,
            ),
            "Transactions.csv": (
                ["Transaction_ID", "Customer_ID", "Session_ID", "Beneficiary_ID", "Agent_ID",
                 "Receiver_ID", "Timestamp", "Transaction_Type", "Amount", "Currency", "Channel",
                 "Transaction_status", "Sender_balance_before", "Sender_balance_after"],
                self.transactions,
            ),
            "Biometric_Logs.csv": (
                ["Biometric_event_ID", "Customer_ID", "Transaction_ID", "Agent_ID",
                 "Event_Timestamp", "Biometric_type", "Biometric_required", "Attempt_count",
                 "Failed_attempts", "Result"],
                self.biometric_logs,
            ),
            "Fraud_Alerts.csv": (
                ["Alert_ID", "Customer_ID", "Transaction_ID", "Alert_timestamp", "Alert_type",
                 "Criticality_score", "Criticality_level", "Alert_source", "Alert_status"],
                self.fraud_alerts,
            ),
            "Ground_Truth.csv": (
                ["Case_ID", "Alert_ID", "is_fraud", "Fraud_type", "Scenario_ID",
                 "Validation_notes"],
                self.ground_truth,
            ),
        }

        for filename, (fields, rows) in schemas.items():
            write_csv(self.output_dir / filename, fields, rows)

        print(f"\nCreated {len(schemas)} CSV files in: {self.output_dir.resolve()}")
        print("\nRecord counts:")
        for filename, (_, rows) in schemas.items():
            print(f"  {filename:<25} {len(rows):>8}")

    def run(self):
        print("Generating CyFinX normal synthetic population...")
        self.generate_agents()
        self.generate_customers_and_kyc()
        self.generate_devices()
        self.generate_beneficiaries()
        self.simulate_activity()
        self.adjust_device_last_seen()
        self.validate()
        self.export()


def clamp_datetime(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def parse_args():
    parser = argparse.ArgumentParser(description="Generate CyFinX normal synthetic population.")
    parser.add_argument("--customers", type=int, default=DEFAULT_CUSTOMERS,
                        help=f"Number of customers (default: {DEFAULT_CUSTOMERS})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"Random seed for reproducibility (default: {DEFAULT_SEED})")
    parser.add_argument("--start", type=str, default=DEFAULT_START.strftime("%Y-%m-%d"),
                        help="Simulation start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=DEFAULT_END.strftime("%Y-%m-%d"),
                        help="Simulation end date YYYY-MM-DD")
    parser.add_argument("--output", type=str, default="cyfinx_normal_population",
                        help="Output folder")
    return parser.parse_args()


def main():
    args = parse_args()
    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d") + timedelta(hours=23, minutes=59, seconds=59)

    if args.customers < 1:
        raise ValueError("--customers must be at least 1")
    if end <= start:
        raise ValueError("--end must be after --start")

    gen = CyFinXGenerator(
        customer_count=args.customers,
        start=start,
        end=end,
        seed=args.seed,
        output_dir=args.output,
    )
    gen.run()


if __name__ == "__main__":
    main()
