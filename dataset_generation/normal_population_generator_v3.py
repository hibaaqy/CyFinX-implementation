#!/usr/bin/env python3
"""CyFinX normal V3: corrected chronological balances, physical cash, binding, device times.
Synthetic six-month activity; retains the user's existing 13 normal CSV headers.
"""
import argparse
import random
import heapq
from collections import defaultdict
from datetime import datetime, timedelta
from normal_population_generator_v2_full_modified import (CyFinXGenerator, DEFAULT_START, DEFAULT_END,
    fmt_dt, clamp_datetime, random_datetime, choose_active_hour, weighted_choice, TRANSACTION_TYPES,
    TRANSACTION_WEIGHTS, amount_for)

class NormalV3(CyFinXGenerator):
    def generate_devices(self):
        super().generate_devices()
        # Replace implausible cross-city legitimate device sharing with
        # same-city sharing before any sessions are generated.
        city={c['Customer_ID']:c['City'] for c in self.customers}
        owner_by_device={d['Device_ID']:cid for cid,ds in self.customer_devices.items() for d in ds}
        primary_by_city=defaultdict(list)
        for cid,ds in self.customer_devices.items():
            for d in ds:
                if owner_by_device.get(d['Device_ID'])==cid:
                    primary_by_city[city[cid]].append((cid,d))
        for link in self.customer_device_links:
            cid=link['Customer_ID'];did=link['Device_ID']
            original_owner=owner_by_device.get(did)
            if original_owner is None or city[cid]==city[original_owner]:continue
            first=datetime.strptime(link['First_seen'],'%Y-%m-%d %H:%M:%S')
            existing={x['Device_ID'] for x in self.customer_devices[cid]}
            options=[d for other,d in primary_by_city[city[cid]] if other!=cid and d['Device_ID'] not in existing
                     and d['_first']<=first]
            if not options:continue
            new=random.choice(options)
            for runtime in self.customer_devices[cid]:
                if runtime['Device_ID']==did:
                    runtime.update({k:new[k] for k in ('Device_ID','Device_type','Device_OS','Device_model')})
                    break
            link['Device_ID']=new['Device_ID']

    def generate_normal_complaints(self):
        super().generate_normal_complaints()
        descriptions={
            'transaction_issue':'Customer asks why a recent wallet transaction shows a different status than expected.',
            'cashout_issue':'Customer reports difficulty completing a retailer cash withdrawal and requests a status check.',
            'payment_issue':'Customer says the merchant has not confirmed receiving a payment shown in the app.',
            'transfer_issue':'Customer asks for a beneficiary transfer reference and confirmation of processing.',
            'account_access_issue':'Customer reports difficulty accessing the wallet after changing handsets.',
            'authentication_issue':'Customer requests help after repeated MPIN authentication failures.',
            'profile_issue':'Customer requests a review of the registered contact information.'}
        for c in self.complaints:
            c['Complaint_description']=descriptions.get(c['Complaint_Type'],'Customer requests a wallet service review.')

    def create_session(self,cid,when,device):
        row=super().create_session(cid,when,device)
        if row['Network_type']=='mobile_data':
            row['ISP']=random.choice(['Jazz','Zong','Telenor','Ufone'])
        else:
            row['ISP']=random.choice(['PTCL','Nayatel','StormFiber'])
        # Institution-side binding event on first observed use, not private OTP contents.
        key=(cid,row['Device_ID'])
        if key not in self._seen_bindings:
            self._seen_bindings.add(key)
            self.auth_counter+=1
            self.auth_logs.append(dict(Auth_event_ID=f'AUTH{self.auth_counter:08d}',Customer_ID=cid,
                Device_ID=row['Device_ID'],Session_ID=row['Session_ID'],Event_timestamp=row['Session_start'],
                Event_type='DEVICE_BINDING_VERIFICATION',Auth_method='otp',Result='success',
                Failure_reason='',Attempt_count=1))
        return row

    def create_transaction(self,cid,session,when):
        """A single transaction, in actual timestamp order, with cash denominations and exact running balances."""
        profile=self.profiles[cid]
        tx_type=weighted_choice(TRANSACTION_TYPES,TRANSACTION_WEIGHTS)
        ben=None; agent=None
        if tx_type=='transfer':
            ben=self.available_beneficiary_at(cid,when)
            if ben is None:tx_type='payment'
        if tx_type in ('cash_in','cash_out'):agent=self.choose_agent(session['City'])
        amt=amount_for(profile,tx_type)
        before=round(self.customer_balances[cid],2)
        if tx_type in ('transfer','payment','cash_out'):
            if before<200:
                tx_type='cash_in';ben=None;agent=self.choose_agent(session['City']);amt=random.randrange(1000,10001,100)
            else:amt=min(amt,round(before*.75,2))
        if tx_type in ('cash_in','cash_out'):
            amt=max(100,round(amt/100)*100)
            if tx_type=='cash_out' and amt>before:
                # No fractional physical cash-out; retain an affordable denomination.
                amt=int(min(before,round(before*.75,2))//100)*100
                if amt<100:
                    tx_type='cash_in';ben=None;amt=1000
        amt=round(amt,2)
        status=weighted_choice(['success','failed'],[.97,.03])
        after=before if status=='failed' else round(before+amt if tx_type=='cash_in' else before-amt,2)
        if after<0:raise ValueError('negative balance')
        self.transaction_counter+=1
        tid=f'TX{self.transaction_counter:09d}'
        self.transactions.append(dict(Transaction_ID=tid,Customer_ID=cid,Session_ID=session['Session_ID'],
            Beneficiary_ID=ben['Beneficiary_ID'] if ben else '',Agent_ID=agent['Agent_ID'] if agent else '',
            Receiver_ID=(ben['Beneficiary_customer_ID'] or ben['Beneficiary_account']) if ben else '',
            Timestamp=fmt_dt(when),Transaction_Type=tx_type,Amount=amt,Currency='PKR',
            Channel='agent' if tx_type in ('cash_in','cash_out') else 'mobile_app',
            Transaction_status=status,Sender_balance_before=before,Sender_balance_after=after))
        if status=='success':self.customer_balances[cid]=after
        if tx_type=='cash_out' and status=='success' and random.random()<.70:
            # Biometric evidence precedes the physical withdrawal, within its session.
            self.create_biometric(cid,self.transactions[-1],agent,when-timedelta(seconds=random.randint(5,25)))

    def simulate_activity(self):
        self._seen_bindings=set()
        self._device_busy_until={}
        self._customer_busy_until={}
        total_days=max(1,(self.end-self.start).days+1)
        months=total_days/30.4375
        events=[]
        for customer in self.customers:
            cid=customer['Customer_ID'];profile=self.profiles[cid]
            status=profile['acc_status']
            mult=.12 if status=='closed' else (.18 if status=='dormant' else 1.)
            expected=profile['monthly_transactions']*months*mult
            count=max(0,int(random.gauss(expected,max(1.,expected*.20))))
            start=max(self.start,profile['reg_date'])
            if start>=self.end:continue
            # Dormant cohort: observed normal activity ends in May, leaving >=4 months
            # for post-history reactivation scenarios. This is an explicit synthetic cohort.
            end=min(self.end,datetime(2026,5,24,23,59,59)) if status=='dormant' else self.end
            if start>=end:continue
            for _ in range(count):
                dt=random_datetime(start,end).replace(hour=choose_active_hour(profile),
                    minute=random.randint(0,59),second=random.randint(0,59))
                dt=clamp_datetime(dt,start,end)
                events.append((dt,cid))
            # Extra browse-only sessions to avoid transaction-only activity.
            for _ in range(max(1,round(count*.16))):
                dt=random_datetime(start,end)
                events.append((dt,cid))
        # A priority queue reorders delayed events globally; simply shifting a
        # session in-place would allow later events on the same shared device
        # to start before it and cause overlapping sessions.
        queue=[(when,i,cid) for i,(when,cid) in enumerate(events)]
        heapq.heapify(queue)
        while queue:
            when,i,cid=heapq.heappop(queue)
            dev=self.active_device_at(cid,when)
            if dev is None:continue
            did=dev['Device_ID']
            # Global physical-device mutex prevents overlapping sessions even for
            # legitimately shared phones across different customer accounts.
            busy=max((x for x in (self._device_busy_until.get(did),self._customer_busy_until.get(cid)) if x is not None),default=None)
            if busy is not None and when<=busy:
                delayed=busy+timedelta(seconds=random.randint(30,90))
                if delayed<self.end-timedelta(minutes=50):heapq.heappush(queue,(delayed,i,cid))
                continue
            if when>=self.end-timedelta(minutes=50):continue
            sess=self.create_session(cid,when,dev)
            end=datetime.strptime(sess['Session_end'],'%Y-%m-%d %H:%M:%S')
            self._device_busy_until[did]=end
            self._customer_busy_until[cid]=end
            auth_end=self.create_authentication(cid,sess,when+timedelta(seconds=5))
            if random.random()<.80:
                earliest=auth_end+timedelta(seconds=random.randint(20,90))
                latest=end-timedelta(seconds=100)
                if earliest<=latest:
                    tx_when=random_datetime(earliest,latest)
                    self.create_transaction(cid,sess,tx_when)

    def adjust_device_last_seen(self):
        # Use last actual observed session END, or registration for never-used links.
        seen_device={};seen_link={}
        for s in self.sessions:
            when=datetime.strptime(s['Session_end'],'%Y-%m-%d %H:%M:%S')
            did=s['Device_ID'];key=(s['Customer_ID'],did)
            seen_device[did]=max(seen_device.get(did,when),when)
            seen_link[key]=max(seen_link.get(key,when),when)
        for l in self.customer_device_links:
            first=datetime.strptime(l['First_seen'],'%Y-%m-%d %H:%M:%S')
            l['Last_seen']=fmt_dt(max(first,seen_link.get((l['Customer_ID'],l['Device_ID']),first)))
        for d in self.devices:
            first=datetime.strptime(d['Device_first_seen'],'%Y-%m-%d %H:%M:%S')
            link_latest=max((datetime.strptime(l['Last_seen'],'%Y-%m-%d %H:%M:%S') for l in self.customer_device_links if l['Device_ID']==d['Device_ID']),default=first)
            d['Device_last_seen']=fmt_dt(max(first,link_latest,seen_device.get(d['Device_ID'],first)))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--customers',type=int,default=2500)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--output',default='cyfinx_normal_v3')
    a=p.parse_args()
    NormalV3(a.customers,DEFAULT_START,DEFAULT_END,a.seed,a.output).run()
