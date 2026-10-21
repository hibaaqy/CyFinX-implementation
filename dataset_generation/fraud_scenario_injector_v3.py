#!/usr/bin/env python3
"""CyFinX reproducible V3 corrections on existing 14-table schema.
Derived from uploaded V3 changelog and records, not a replay of the hand-edited rows.
Nine fraud families and five legitimate lookalikes per batch. Synthetic research only.
"""
import argparse
import random
from collections import defaultdict
from datetime import datetime, timedelta
from fraud_scenario_injector_v2_final import parse_dt,fmt_dt,money
from v3_scale_base import ScaledInjector

class V3Injector(ScaledInjector):
    def fix_benign_shared_devices(self):
        # Do not remap device IDs AFTER globally scheduling nonoverlapping sessions.
        # Such remapping reintroduced session overlaps in the previous scaled injector.
        self.normalization_counts['cross_city_links_preserved']=0

    def __init__(self,input_dir,output_dir,seed=20261009,batches=15):
        self.batches=batches
        super().__init__(input_dir,output_dir,seed,batches)
        self.reference_time=self.base_time
        self._cust={r['Customer_ID']:r for r in self.customers}
        self._history=defaultdict(list)
        self._by_type=defaultdict(list)
        self._auth_history=defaultdict(list)
        self._devices_by_cust=defaultdict(list)
        self._device_rows={r['Device_ID']:r for r in self.devices}
        self._session_rows={r['Session_ID']:r for r in self.sessions}
        self._tx_rows={r['Transaction_ID']:r for r in self.transactions}
        for t in self.transactions:
            self._history[t['Customer_ID']].append(t)
            self._by_type[(t['Customer_ID'],t['Transaction_Type'])].append(t)
        for a in self.auth:self._auth_history[(a['Customer_ID'],a['Device_ID'])].append(a)
        for l in self.customer_devices:self._devices_by_cust[l['Customer_ID']].append(l)
        self._cashout_prior_max={cid:max((float(x['Amount']) for x in rows),default=0)
            for (cid,typ),rows in self._by_type.items() if typ=='cash_out'}
        self._transfer_prior_max={cid:max((float(x['Amount']) for x in rows),default=0)
            for (cid,typ),rows in self._by_type.items() if typ=='transfer'}
        self._historical_last={cid:max((parse_dt(t['Timestamp']) for t in rows),default=datetime(2026,4,1))
            for cid,rows in self._history.items()}

    def customer_row(self,cid):
        if not hasattr(self,'_cust'):return super().customer_row(cid)
        return self._cust[cid]
    def customer_transactions(self,cid,tx_type=None):
        if not hasattr(self,'_history'):return super().customer_transactions(cid,tx_type)
        if tx_type:return self._by_type.get((cid,tx_type),[])
        return self._history.get(cid,[])
    def primary_device(self,cid):
        links=self._devices_by_cust[cid]
        return max(links,key=lambda r:r['Last_seen'])['Device_ID']
    def choose_customer(self,predicate=lambda c:True,prefer_status=None):
        # Indexes avoid repeated 100k-row scans during scaled scenario selection.
        candidates=[cid for cid in self._cust if cid not in self.used_customers and cid not in self.reserved_receivers
                    and self._history.get(cid) and predicate(cid)]
        if prefer_status:
            preferred=[cid for cid in candidates if self._cust[cid]['Acc_Status']==prefer_status]
            if preferred:candidates=preferred
        if not candidates:raise ValueError('No suitable unused customer for scenario')
        cid=self.rng.choice(candidates);self.used_customers.add(cid);return cid
    def add_device(self,cid,when,shared_existing_device=None):
        did=super().add_device(cid,when,shared_existing_device)
        if did not in self._device_rows:
            d=self.devices[-1]
            models=[('Android','Samsung Galaxy A54'),('Android','Infinix Note 30'),
                ('Android','Xiaomi Redmi Note 12'),('Android','Tecno Camon 20'),
                ('iOS','iPhone 12'),('iOS','iPhone 13')]
            osname,model=self.rng.choice(models)
            # Avoid matching the victim's existing handset model.
            old={self._device_rows[x['Device_ID']]['Device_model'] for x in self._devices_by_cust[cid]
                if x['Device_ID'] in self._device_rows}
            if model in old:
                osname,model=next((o,m) for o,m in models if m not in old)
            d['Device_OS']=osname;d['Device_model']=model
            self._device_rows[did]=d
        newlink=self.customer_devices[-1]
        if newlink['Customer_ID']==cid and newlink['Device_ID']==did and newlink not in self._devices_by_cust[cid]:
            self._devices_by_cust[cid].append(newlink)
        return did
    def add_session(self,cid,did,start,minutes=30,city=None):
        sid,end=super().add_session(cid,did,start,minutes,city)
        row=self.sessions[-1]
        row['ISP']=self.rng.choice(['Jazz','Zong','Telenor','Ufone']) if row['Network_type']=='mobile_data' else self.rng.choice(['PTCL','Nayatel','StormFiber'])
        self._session_rows[sid]=row
        return sid,end
    def set_network(self,sid,network,isp,ip):
        r=self._session_rows[sid];r['Network_type']=network;r['ISP']=isp;r['IP_address']=ip
    def add_auth(self,*args,**kwargs):
        super().add_auth(*args,**kwargs)
        a=self.auth[-1];self._auth_history[(a['Customer_ID'],a['Device_ID'])].append(a)
    def add_beneficiary(self,cid,when,internal=True,receiver=None):
        if receiver is None:
            receiver=self.choose_receiver(cid) if internal else ''
        self.ben_counter+=1;bid=f'B{self.ben_counter:07d}'
        self.beneficiaries.append(dict(Beneficiary_ID=bid,Customer_ID=cid,
            Beneficiary_customer_ID=receiver,
            Beneficiary_account=f'INT{int(receiver[1:]):010d}' if internal else f'EXT{self.ben_counter:010d}',
            Beneficiary_type='internal' if internal else 'external',Beneficiary_added_time=fmt_dt(when),
            Beneficiary_status='active'))
        return bid,receiver
    def add_transaction(self,cid,sid,when,tx_type,amount,beneficiary_id='',agent_id='',receiver_id=''):
        tid,amt=super().add_transaction(cid,sid,when,tx_type,amount,beneficiary_id,agent_id,receiver_id)
        tx=self.transactions[-1]
        # Match the baseline TX identifier and canonical numeric format.
        tid=f'TX{self.tx_counter:09d}'
        tx['Transaction_ID']=tid
        for key in ('Amount','Sender_balance_before','Sender_balance_after'):
            tx[key]=str(round(float(tx[key]),2))
        self._tx_rows[tid]=tx
        self._tx_by_id[tid]=tx
        self._history[cid].append(tx)
        return tid,amt
    def add_biometric(self,cid,tid,agent_id,when,attempts=1,failed=0,result='success'):
        super().add_biometric(cid,tid,agent_id,when,attempts,failed,result)
        self.biometrics[-1]['Biometric_required']='True'
    def add_case(self,cid,scenario,fraud_type,created,transaction_id='',alert_type=None,
                 criticality=None,complaint_id='',source='alert',notes='',is_fraud=True):
        # Scores intentionally overlap for fraud and legitimate alerts.
        score=self.rng.randint(64,90)
        case_id=super().add_case(cid,scenario,fraud_type,created,transaction_id,alert_type,
            score,complaint_id,source,notes,is_fraud)
        return case_id
    def suitable(self,cid,minimum=10000,status='active',tx_type=None,min_tx=5):
        return self._cust[cid]['Acc_Status']==status and self.post_balance[cid]>=minimum and len(self.customer_transactions(cid,tx_type))>=min_tx
    def choose_amount(self,cid,tx_type='transfer',mode='significant'):
        vals=[float(x['Amount']) for x in self._by_type.get((cid,tx_type),[])]
        avg=sum(vals)/len(vals) if vals else 2800
        prior=max(vals) if vals else 0
        bal=self.post_balance[cid]
        if mode=='large':wanted=max(3000,avg*self.rng.uniform(2.2,3.1),prior*self.rng.uniform(1.2,1.5))
        elif mode=='significant':wanted=max(1800,avg*self.rng.uniform(1.2,1.9))
        else:wanted=max(250,avg*self.rng.uniform(.4,.8))
        if wanted>bal*.92:wanted=bal*self.rng.uniform(.42,.82)
        if tx_type=='cash_out':wanted=round(wanted/100)*100
        return round(wanted,2)

    def inject_ato_new_device(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,9000,min_tx=12))
        t=self.now(offset);did=self.add_device(cid,t)
        self.add_security(cid,did,t,'DEVICE_REGISTRATION_REQUEST','received','otp')
        self.add_security(cid,did,self.minutes(t,6),'DEVICE_REGISTRATION_VERIFICATION','approved','otp')
        sid,_=self.add_session(cid,did,self.minutes(t,18),26)
        self.add_auth(cid,did,sid,self.minutes(t,19),'LOGIN','mpin','failed','wrong_mpin',1)
        self.add_auth(cid,did,sid,self.minutes(t,21),'LOGIN','mpin','failed','wrong_mpin',2)
        self.add_security(cid,did,self.minutes(t,25),'MPIN_RECOVERY_VERIFICATION','approved','otp',sid)
        self.add_auth(cid,did,sid,self.minutes(t,26),'MPIN_RESET','otp','success')
        # >=2h cooling after recovery, not a claim about any specific wallet's exact policy.
        start=self.minutes(t,165)
        sid2,_=self.add_session(cid,did,start,32)
        self.add_auth(cid,did,sid2,self.minutes(start,1),'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,self.minutes(start,5))
        amount=self.choose_amount(cid,'transfer','significant')
        at=self.minutes(start,14);tid,_=self.add_transaction(cid,sid2,at,'transfer',amount,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(start,12))
        ct=self.minutes(at,160)
        self.add_complaint(cid,tid,ct,'disputed_account_activity',
            'Customer denies registering the new handset, resetting the MPIN and authorizing this transfer. Customer statement requires independent review.')
        self.add_case(cid,'ATO_NEW_DEVICE','ACCOUNT_TAKEOVER',self.minutes(at,3),tid,
            'unusual_account_access_activity',None,'','alert',
            'New device binding, MPIN recovery, cooling interval and unfamiliar beneficiary. Subsequent customer denial is not available at alert creation.')

    def inject_ut_new_beneficiary(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,14000,tx_type='transfer',min_tx=3)
            and self.post_balance[c]>self._transfer_prior_max.get(c,0)*1.25)
        t=self.now(offset);did=self.primary_device(cid)
        sid,_=self.add_session(cid,did,t,27)
        self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','failed','wrong_mpin',1)
        self.add_auth(cid,did,sid,self.minutes(t,3),'LOGIN','mpin','success','',2)
        bid,receiver=self.add_beneficiary(cid,self.minutes(t,5))
        prior=self._transfer_prior_max.get(cid,0)
        amount=round(min(prior*self.rng.uniform(1.12,1.28),self.post_balance[cid]*.88),2)
        if amount<=prior:raise ValueError('UT amount must exceed prior max')
        at=self.minutes(t,9);tid,_=self.add_transaction(cid,sid,at,'transfer',amount,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(t,8))
        ct=self.minutes(at,118)
        cmpid=self.add_complaint(cid,tid,ct,'disputed_transfer',
            'Customer denies adding the beneficiary or authorizing the transfer despite activity on the registered device. Authentication and transfer confirmation need investigation.')
        self.add_case(cid,'UT_NEW_BENEFICIARY','UNAUTHORIZED_TRANSFER',ct,tid,
            None,None,cmpid,'complaint',
            'One MPIN failure, successful login, fast new-beneficiary transfer and amount above prior transfer maximum. Complaint remains an allegation.')

    def inject_se_new_beneficiary(self,offset):
        def eligible(c):
            if not self.suitable(c,8500,tx_type='transfer',min_tx=2):return False
            did=self.primary_device(c)
            return sum(1 for a in self._auth_history[(c,did)] if a['Event_type']=='LOGIN' and a['Result']=='success')>=3
        cid=self.choose_customer(eligible)
        t=self.now(offset);did=self.primary_device(cid)
        sid,_=self.add_session(cid,did,t,28)
        self.add_auth(cid,did,sid,self.minutes(t,1),'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,self.minutes(t,4))
        amount=self.choose_amount(cid,'transfer','significant')
        at=self.minutes(t,11);tid,_=self.add_transaction(cid,sid,at,'transfer',amount,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,self.minutes(t,9))
        ct=self.minutes(at,255)
        cmpid=self.add_complaint(cid,tid,ct,'disputed_transfer',
            'Customer reports a caller impersonated wallet support and instructed them to send money to fix an account issue. Customer confirms using their own app and MPIN to make the transfer. Private call content is not institution-verified.')
        self.add_case(cid,'SE_NEW_BENEFICIARY','SOCIAL_ENGINEERING',ct,tid,
            None,None,cmpid,'complaint',
            'Previously established device and normal logins; self-initiated transfer after customer-reported deception. No fabricated private communication logs.')

    def inject_dc_shared_device(self,offset):
        t=self.now(offset)
        pools={city:[c for c in self._cust if self._cust[c]['City']==city and c not in self.used_customers
              and c not in self.reserved_receivers and self.suitable(c,6500,min_tx=5)]
              for city in ['Karachi','Lahore','Multan','Rawalpindi','Islamabad']}
        cities=[city for city,p in pools.items() if len(p)>=3]
        if not cities:raise ValueError('Insufficient local multi-account customers')
        city=self.rng.choice(cities);pool=pools[city]
        members=self.rng.sample(pool,3)
        self.used_customers.update(members)
        receiver=self.choose_receiver(members[0])
        did=self.add_device(members[0],t)
        carrier=self.rng.choice(['Jazz','Zong','Telenor','Ufone'])
        carrier_ip=f'100.{self.rng.randint(64,127)}.{self.rng.randint(0,255)}.{self.rng.randint(1,254)}'
        wifi_ip=f'100.{self.rng.randint(64,127)}.{self.rng.randint(0,255)}.{self.rng.randint(1,254)}'
        main_tid='';last=None
        for i,cid in enumerate(members):
            bind_at=t+timedelta(minutes=i*18)
            if i:self.add_device(cid,bind_at,shared_existing_device=did)
            # One short nonoverlapping binding session for each account.
            sid,_=self.add_session(cid,did,bind_at,12,city)
            self.set_network(sid,'mobile_data',carrier,carrier_ip)
            self.add_security(cid,did,bind_at,'DEVICE_REGISTRATION_REQUEST','received','otp',sid)
            self.add_security(cid,did,bind_at+timedelta(minutes=3),'DEVICE_REGISTRATION_VERIFICATION','approved','otp',sid)
        for i,cid in enumerate(members):
            start=t+timedelta(minutes=160+i*37)
            sid,_=self.add_session(cid,did,start,28,city)
            self.set_network(sid,'wifi','PTCL',wifi_ip)
            self.add_auth(cid,did,sid,start+timedelta(minutes=2),'LOGIN','mpin','success')
            bid,_=self.add_beneficiary(cid,start+timedelta(minutes=5),receiver=receiver)
            amt=self.choose_amount(cid,'transfer','significant')
            at=start+timedelta(minutes=12)
            tid,_=self.add_transaction(cid,sid,at,'transfer',amt,bid,receiver_id=receiver)
            self.add_authorization(cid,tid,did,start+timedelta(minutes=10))
            if i==0:main_tid=tid
            last=at
        self.add_case(members[0],'DC_MULTI_ACCOUNT_SHARED_DEVICE','DEVICE_COMPROMISE',
            last+timedelta(minutes=4),main_tid,'rapid_multi_account_device_use',None,'','alert',
            'Three account bindings on one device, sequential sessions, common binding IP, shared Wi-Fi IP and converging beneficiary. Coordinated device misuse observed; malware unproven.')

    def inject_cc_mpin_failures(self,offset):
        cid=self.choose_customer(lambda c:self.suitable(c,10500,min_tx=10))
        t=self.now(offset)
        old_models={self._device_rows[x['Device_ID']]['Device_model'] for x in self._devices_by_cust[cid]}
        did=self.add_device(cid,t)
        away=self.rng.choice([c for c in ['Multan','Karachi','Lahore','Islamabad'] if c!=self._cust[cid]['City']])
        sid,_=self.add_session(cid,did,t,16,away)
        self.add_security(cid,did,t,'DEVICE_REGISTRATION_REQUEST','received','otp',sid)
        self.add_security(cid,did,t+timedelta(minutes=4),'DEVICE_REGISTRATION_VERIFICATION','approved','otp',sid)
        start=t+timedelta(minutes=146)
        sid2,_=self.add_session(cid,did,start,29,away)
        self.add_auth(cid,did,sid2,start+timedelta(minutes=1),'LOGIN','mpin','success','',1)
        bid,receiver=self.add_beneficiary(cid,start+timedelta(minutes=4))
        amt=self.choose_amount(cid,'transfer','significant')
        at=start+timedelta(minutes=12)
        tid,_=self.add_transaction(cid,sid2,at,'transfer',amt,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,start+timedelta(minutes=10))
        ct=at+timedelta(hours=2,minutes=17)
        self.add_complaint(cid,tid,ct,'account_access_dispute',
            f'Customer says they retained their usual handset, did not bind another device from {away}, and did not approve the transfer. How the verification code and MPIN were obtained remains unknown.')
        self.add_case(cid,'CC_STOLEN_CREDENTIAL_NEW_CONTEXT','CREDENTIAL_COMPROMISE',at+timedelta(minutes=3),tid,
            'unusual_authenticated_transaction',None,'','alert',
            'New device bound from unfamiliar city using OTP, >=2-hour gap, first-try MPIN login, new beneficiary and transfer. Subsequent denial not visible at alert time.')

    def inject_sco_large(self,offset):
        def eligible(c):
            if not self.suitable(c,6500,tx_type='cash_out',min_tx=3):return False
            mx=self._cashout_prior_max.get(c,0)
            return 300<=mx<=9000 and self.post_balance[c]>3000
        cid=self.choose_customer(eligible)
        t=self.now(offset);did=self.primary_device(cid);city=self._cust[cid]['City'];aid=self.add_retailer(city)
        sid,_=self.add_session(cid,did,t,42,city)
        self.add_auth(cid,did,sid,t+timedelta(minutes=1),'LOGIN','mpin','success')
        prior=self._cashout_prior_max[cid]
        desired=max(1000,round(prior*self.rng.uniform(2.12,2.45)/100)*100)
        # In-and-out: incoming cash covers most of the cash-out; no impossible balance.
        cashin=max(1000,round(desired*self.rng.uniform(1.025,1.07)/100)*100)
        self.add_transaction(cid,sid,t+timedelta(minutes=5),'cash_in',cashin,agent_id=aid)
        at=t+timedelta(minutes=19)
        tid,amt=self.add_transaction(cid,sid,at,'cash_out',desired,agent_id=aid)
        self.add_biometric(cid,tid,aid,t+timedelta(minutes=17),1,0)
        self.add_case(cid,'SCO_LARGE','SUSPICIOUS_CASH_OUT',at+timedelta(minutes=3),tid,
            'unusual_cashout_velocity',None,'','alert',
            'Same retailer cash-in then near-equivalent cash-out 14 minutes later, >2x historical cash-out max. Unusual movement, not independent proof of criminal intent.')

    def inject_kyc_dormant(self,offset):
        t=self.now(offset)
        cid=self.choose_customer(lambda c:self._cust[c]['Acc_Status']=='dormant'
            and (t-self._historical_last.get(c,datetime(2026,4,1))).days>=120
            and self.post_balance[c]>4500,prefer_status='dormant')
        did=self.add_device(cid,t)
        sid,_=self.add_session(cid,did,t,18)
        self.add_auth(cid,did,sid,t,'ACCOUNT_REACTIVATION_REQUEST','kyc_otp','success')
        self.add_auth(cid,did,sid,t+timedelta(minutes=5),'ACCOUNT_REACTIVATION_VERIFICATION','kyc_otp','success')
        self.add_security(cid,did,t+timedelta(minutes=7),'DEVICE_REGISTRATION_VERIFICATION','approved','otp',sid)
        self._cust[cid]['Acc_Status']='active'
        start=t+timedelta(minutes=149)
        sid2,_=self.add_session(cid,did,start,30)
        self.add_auth(cid,did,sid2,start+timedelta(minutes=1),'LOGIN','mpin','success')
        bid,receiver=self.add_beneficiary(cid,start+timedelta(minutes=5))
        amt=self.choose_amount(cid,'transfer','significant')
        at=start+timedelta(minutes=12)
        tid,_=self.add_transaction(cid,sid2,at,'transfer',amt,bid,receiver_id=receiver)
        self.add_authorization(cid,tid,did,start+timedelta(minutes=10))
        audit=at+timedelta(minutes=73)
        self.add_id_event(cid,did,audit,'POST_REACTIVATION_KYC_RECONCILIATION','requires_review','No')
        self.add_case(cid,'KYC_REACTIVATION_IDENTITY_MISMATCH','IDENTITY_KYC_RELATED_FRAUD',
            audit+timedelta(minutes=3),tid,'identity_reverification_required',None,'','alert',
            'At least four months inactivity, reactivation and new device, transfer, later rejected identity document with inconsistent CNIC and guardian name.')

    def inject_bio_failure_success(self,offset):
        super().inject_bio_failure_success(offset)
        case=self.cases[-1]
        cmpid=case['Complaint_ID']
        complaint=next(c for c in self.complaints if c['Complaint_ID']==cmpid)
        complaint['Complaint_description']=(
            'Customer states they opened the wallet app near the retailer for a different purpose, '
            'but did not approve this cash-out or give fingerprint verification for it. '
            'The transaction and conflicting agent biometric records require investigation; '
            'customer statement is not independently authenticated.')

    def inject_benign_lookalikes(self):
        # Include legitimate complaint-origin cases; otherwise Case_source=complaint
        # becomes a perfect fraud-label shortcut. Preserve all five benign patterns.
        super().inject_benign_lookalikes()
        for case,gt in zip(self.cases[-5:],self.ground_truth[-5:]):
            scenario=gt['Scenario_ID']
            if scenario not in ('BENIGN_NEW_BENEFICIARY','BENIGN_BIOMETRIC_RETRY'):
                continue
            old_alert=case['Alert_ID']
            alert=next(a for a in self.alerts if a['Alert_ID']==old_alert)
            tid=alert['Transaction_ID']
            when=parse_dt(case['Case_created_timestamp'])
            if scenario=='BENIGN_NEW_BENEFICIARY':
                desc=('Customer initially reports not recognizing the newly added beneficiary and asks for a transfer review. '
                      'Authorization and recipient history need checking; customer account of events is not independently confirmed.')
                ctype='disputed_transfer'
            else:
                desc=('Customer reports repeated fingerprint attempts at the retailer and is unsure whether the cash-out was processed correctly. '
                      'Requests a review of the biometric verification and transaction record.')
                ctype='disputed_cash_withdrawal'
            cmpid=self.add_complaint(case['Customer_ID'],tid,when,ctype,desc)
            case['Complaint_ID']=cmpid
            case['Case_source']='complaint'
            case['Alert_ID']=''
            self.alerts.remove(alert)
            gt['Validation_notes']+=' Complaint was resolved as a legitimate transaction after human review; not evidence available at case creation.'


    def run(self):
        for batch in range(self.batches):
            self.base_time=self.reference_time+timedelta(days=self.rng.randint(0,8),
                hours=self.rng.randint(0,8),minutes=self.rng.randint(0,59),seconds=self.rng.randint(0,59))
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
            if batch%5==4 or batch==0:print(f'V3 batch {batch+1}/{self.batches}: {len(self.cases)} cases',flush=True)
        self._finish_consistency()
        self.validate()
        self.export()

    def _finish_consistency(self):
        # Remove future complaint pointers from alert-origin cases. Complaints
        # remain queryable by customer and transaction AFTER their timestamps.
        complaints={r['Complaint_ID']:r for r in self.complaints}
        for case in self.cases:
            if case['Case_source']=='alert' and case['Complaint_ID']:
                cmp=complaints[case['Complaint_ID']]
                if parse_dt(cmp['Complaint_timestamp'])>parse_dt(case['Case_created_timestamp']):
                    case['Complaint_ID']=''
        # Reconcile physical-device Last_seen and customer links to observed session END.
        bydev={};bylink={}
        for s in self.sessions:
            end=parse_dt(s['Session_end']);did=s['Device_ID'];key=(s['Customer_ID'],did)
            bydev[did]=max(bydev.get(did,end),end)
            bylink[key]=max(bylink.get(key,end),end)
        for link in self.customer_devices:
            first=parse_dt(link['First_seen']);end=bylink.get((link['Customer_ID'],link['Device_ID']),first)
            link['Last_seen']=fmt_dt(max(first,end))
        for dev in self.devices:
            first=parse_dt(dev['Device_first_seen'])
            dev['Device_last_seen']=fmt_dt(max(first,bydev.get(dev['Device_ID'],first)))
        # Canonical formatting across ALL normal and injected transactions.
        for tx in self.transactions:
            for k in ('Amount','Sender_balance_before','Sender_balance_after'):
                tx[k]=str(round(float(tx[k]),2))
        for b in self.biometrics:b['Biometric_required']='True' if str(b['Biometric_required']).lower() in ('true','yes','1') else 'False'
        # Cases are numbered by actual creation time rather than the repeating
        # 9-fraud/5-benign generation loop (which would leak labels via IDs).
        self.cases.sort(key=lambda c:(c['Case_created_timestamp'],c['Case_ID']))
        remap={case['Case_ID']:f'CASE{i:07d}' for i,case in enumerate(self.cases,1)}
        for case in self.cases:case['Case_ID']=remap[case['Case_ID']]
        for truth in self.ground_truth:truth['Case_ID']=remap[truth['Case_ID']]
        self.ground_truth.sort(key=lambda g:g['Case_ID'])

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='cyfinx_normal_v3')
    p.add_argument('--output',default='cyfinx_investigations_v3')
    p.add_argument('--seed',type=int,default=20261009)
    p.add_argument('--batches',type=int,default=15)
    a=p.parse_args()
    V3Injector(a.input,a.output,a.seed,a.batches).run()
