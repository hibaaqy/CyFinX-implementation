#!/usr/bin/env python3
"""CyFinX V3 scaling helper base class (internal dependency, not a runnable pipeline).

Dependencies: fraud_scenario_injector_v2_final.py and
normal_population_generator_v2_full_modified.py beside this script.

Usage:
  python cyfinx_scale_pipeline.py --customers 5000 --batches 30

Generates six-month normal population and sampled post-alert investigations.
30 batches = 270 fraud and 150 legitimate case investigations.
These are deliberately case-enriched academic synthetic samples, NOT a fraud rate.
"""
import argparse
import csv
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from normal_population_generator_v2_full_modified import CyFinXGenerator, DEFAULT_START, DEFAULT_END
from fraud_scenario_injector_v2_final import InjectorV2Final, parse_dt, fmt_dt


class ScaledInjector(InjectorV2Final):
    """Repeat and independently randomize previously reviewed V2 trajectories."""

    def __init__(self, input_dir, output_dir, seed, batches):
        super().__init__(input_dir, output_dir, seed)
        self.batches = batches
        self._reference_time = self.base_time
        self._build_indexes()

    def fix_benign_shared_devices(self):
        """Scale-safe version of V2's same-city legitimate device repair."""
        by_dev = defaultdict(list)
        cust_city = {c['Customer_ID']: c['City'] for c in self.customers}
        devrow = {d['Device_ID']: d for d in self.devices}
        by_city = defaultdict(list)
        existing = defaultdict(set)
        for link in self.customer_devices:
            by_dev[link['Device_ID']].append(link)
            existing[link['Customer_ID']].add(link['Device_ID'])
            by_city[cust_city[link['Customer_ID']]].append(link)
        replacements=[]
        for did, links in by_dev.items():
            if len(links)<2 or len({cust_city[l['Customer_ID']] for l in links}) == 1:
                continue
            moving=max(links,key=lambda x:x['First_seen'])
            city=cust_city[moving['Customer_ID']]
            candidates=[other['Device_ID'] for other in by_city[city]
                if other['Customer_ID']!=moving['Customer_ID']
                and other['Device_ID']!=did
                and other['Device_ID'] not in existing[moving['Customer_ID']]
                and devrow[other['Device_ID']]['Device_first_seen'] <= moving['First_seen']]
            if not candidates: continue
            new=self.rng.choice(candidates)
            old=did; cid=moving['Customer_ID']
            moving['Device_ID']=new
            existing[cid].discard(old); existing[cid].add(new)
            replacements.append((cid,old,new,moving['Last_seen']))
            if devrow[new]['Device_last_seen']<moving['Last_seen']:
                devrow[new]['Device_last_seen']=moving['Last_seen']
        if replacements:
            change={(cid,old):new for cid,old,new,last in replacements}
            for sess in self.sessions:
                new=change.get((sess['Customer_ID'],sess['Device_ID']))
                if new: sess['Device_ID']=new
            for auth in self.auth:
                new=change.get((auth['Customer_ID'],auth['Device_ID']))
                if new: auth['Device_ID']=new
        self.normalization_counts['repaired_cross_city_shared_links']+=len(replacements)

    def customer_row(self, cid):
        if not hasattr(self, '_customers_by_id'):
            self._customers_by_id={r['Customer_ID']:r for r in self.customers}
        return self._customers_by_id[cid]

    def choose_customer(self, predicate=lambda cid: True, prefer_status=None):
        # Large normal populations include dormant accounts with zero history.
        # V2's dormancy predicate computes max(history), so require a history.
        return super().choose_customer(
            lambda cid: bool(self.customer_transactions(cid)) and predicate(cid),
            prefer_status=prefer_status)

    def _build_indexes(self):
        self._tx_by_customer = defaultdict(list)
        self._initial_by_cust_type = defaultdict(list)
        self._tx_by_id = {}
        for t in self.transactions:
            self._tx_by_customer[t['Customer_ID']].append(t)
            self._initial_by_cust_type[(t['Customer_ID'],t['Transaction_Type'])].append(float(t['Amount']))
            self._tx_by_id[t['Transaction_ID']] = t

    def customer_transactions(self, cid, tx_type=None):
        if not hasattr(self, '_tx_by_customer'):
            self._tx_by_customer = defaultdict(list)
            for tx in self.transactions:
                self._tx_by_customer[tx['Customer_ID']].append(tx)
        rows = self._tx_by_customer.get(cid, ())
        if not tx_type:
            return rows
        return [t for t in rows if t['Transaction_Type'].lower()==tx_type.lower()]

    def choose_amount(self, cid, tx_type='transfer', mode='large'):
        vals=self._initial_by_cust_type.get((cid, tx_type), ())
        mean=sum(vals)/len(vals) if vals else 2800
        prior_max=max(vals) if vals else 0
        balance=self.post_balance[cid]
        if mode=='large':
            desired=max(mean*self.rng.uniform(2.3,3.2), prior_max*self.rng.uniform(1.25,1.65),3000)
        elif mode=='significant':
            desired=max(mean*self.rng.uniform(1.2,2.0),2000)
        elif mode=='small':
            desired=max(200,mean*self.rng.uniform(0.3,0.7))
        else:desired=max(1000,mean)
        if desired>balance*.94:
            if mode=='large' and balance>=prior_max*1.30:
                desired=balance*self.rng.uniform(.68,.91)
            elif mode!='large':
                desired=balance*self.rng.uniform(.32,.77)
            else:
                raise ValueError(f'{cid}: not enough available for large {tx_type}')
        amt=round(desired,2)
        if tx_type=='cash_out':
            amt=round(amt/100)*100
            if amt<100 or amt>=balance:raise ValueError('Invalid physical cash out')
        if amt<=0 or amt>balance:raise ValueError('Invalid amount')
        return amt

    def add_transaction(self, cid, sid, when, tx_type, amount,
                        beneficiary_id='', agent_id='', receiver_id=''):
        tid, amt=super().add_transaction(cid,sid,when,tx_type,amount,
                          beneficiary_id,agent_id,receiver_id)
        row=self.transactions[-1]
        self._tx_by_customer[cid].append(row)
        self._tx_by_id[tid]=row
        return tid, amt

    def add_authorization(self, cid, tid, did, when, method='mpin', result='success'):
        txn=self._tx_by_id[tid]
        self.add_auth(cid,did,txn['Session_ID'],when,'TRANSACTION_CONFIRMATION',method,result,'',1)

    def inject_benign_lookalikes(self):
        # Preserve the approved five benign patterns with fresh customers.
        return super().inject_benign_lookalikes()

    def validate(self):
        # Frozen-V2 core validation now accepts batch-scaled case counts.
        super().validate()
        expected_count=14*self.batches
        assert len(self.cases)==expected_count
        assert self.fraud_scenario_count==9*self.batches
        assert self.false_positive_count==5*self.batches
        print(f'SCALE COUNTS PASS: {9*self.batches} fraud + {5*self.batches} legitimate = {expected_count} investigations')

    def run(self):
        # Each group generates 9 existing reviewed fraud family trajectories,
        # plus 5 reviewed legitimate lookalikes with unique primary subjects.
        # Batch start times vary across a 16-day observation period; avoid
        # artificially putting all sampled fraud in one same timestamp.
        for batch in range(self.batches):
            self.base_time=(self._reference_time+
                            timedelta(days=self.rng.randint(0,14),
                                      hours=self.rng.randint(0,8),
                                      minutes=self.rng.randint(0,58),
                                      seconds=self.rng.randint(0,59)))
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
            if (batch+1)%5==0 or batch==0:
                print(f'Generated batch {batch+1}/{self.batches}: {len(self.cases)} investigation cases',flush=True)
        self.validate()
        self.export()


