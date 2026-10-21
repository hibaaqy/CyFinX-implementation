#!/usr/bin/env python3
"""Independent CSV-only CyFinX V3 integrity and scenario audit. Exits nonzero on failure."""
import argparse,csv,json,collections,re,hashlib
from datetime import datetime,timedelta
from pathlib import Path
from decimal import Decimal
DT='%Y-%m-%d %H:%M:%S'
def dt(s):return datetime.strptime(s,DT)
def dec(s):return Decimal(str(s))
def read(p):
    with open(p,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def audit(folder,expected_customers=None,expected_batches=None):
    root=Path(folder)
    names=['customers','KYC_records','Devices','Customer_Device','Agent_Retailers','Beneficiaries',
        'Network_Sessions','Authentication_Logs','Transactions','Biometric_Logs','Complaints',
        'Fraud_Alerts','Cases','Ground_Truth']
    data={n:read(root/(n+'.csv')) for n in names}
    failures=[];warnings=[];counts={n:len(data[n]) for n in names}
    def ck(test,description,example=''):
        if not test and len(failures)<200:failures.append(f'{description}: {example}')
    def ix(name,key):
        rows=data[name];out={r[key]:r for r in rows}
        ck(len(out)==len(rows),'Duplicate '+name+'.'+key)
        return out
    cu=ix('customers','Customer_ID');ky=ix('KYC_records','KYC_ID');dv=ix('Devices','Device_ID')
    links=ix('Customer_Device','Customer_Device_ID');ag=ix('Agent_Retailers','Agent_ID')
    be=ix('Beneficiaries','Beneficiary_ID');se=ix('Network_Sessions','Session_ID')
    au=ix('Authentication_Logs','Auth_event_ID');tx=ix('Transactions','Transaction_ID')
    bio=ix('Biometric_Logs','Biometric_event_ID');co=ix('Complaints','Complaint_ID')
    al=ix('Fraud_Alerts','Alert_ID');ca=ix('Cases','Case_ID');gt=ix('Ground_Truth','Case_ID')
    if expected_customers:ck(len(cu)==expected_customers,'Incorrect customer count')
    if expected_batches:
        ck(len(ca)==14*expected_batches,'Incorrect case count')
        ck(sum(g['is_fraud']=='Yes' for g in gt.values())==9*expected_batches,'Incorrect fraud count')
        ck(sum(g['is_fraud']=='No' for g in gt.values())==5*expected_batches,'Incorrect benign count')
    pair={};link_seen=collections.defaultdict(list)
    for l in links.values():
        ck(l['Customer_ID'] in cu and l['Device_ID'] in dv,'Broken device-link FK',l['Customer_Device_ID'])
        key=(l['Customer_ID'],l['Device_ID']);ck(key not in pair,'Duplicate customer-device pair',key)
        pair[key]=l
        ck(dt(l['First_seen'])<=dt(l['Last_seen']),'Invalid device-link timestamps',l['Customer_Device_ID'])
    for d in dv.values():
        ck(dt(d['Device_first_seen'])<=dt(d['Device_last_seen']),'Device last before first',d['Device_ID'])
        if d['Device_model'].lower().startswith('iphone'):ck(d['Device_OS']=='iOS','iPhone/OS mismatch',d['Device_ID'])
        else:ck(d['Device_OS']=='Android','Android/OS mismatch',d['Device_ID'])
    for k in ky.values():
        ck(k['Customer_ID'] in cu,'Broken KYC FK',k['KYC_ID'])
        ck(dt(k['KYC_Reg_Date'])<=dt(k['KYC_last_updated_date']),'KYC dates inverted',k['KYC_ID'])
    for b in be.values():
        ck(b['Customer_ID'] in cu,'Broken beneficiary owner',b['Beneficiary_ID'])
        if b['Beneficiary_type']=='internal':
            ck(b['Beneficiary_customer_ID'] in cu,'Unknown internal recipient',b['Beneficiary_ID'])
            if b['Beneficiary_customer_ID'] in cu:
                expected=f'INT{int(b["Beneficiary_customer_ID"][1:]):010d}'
                ck(b['Beneficiary_account']==expected,'Internal account format',b['Beneficiary_ID'])
        else:ck(b['Beneficiary_account'].startswith('EXT'),'External account format',b['Beneficiary_ID'])
    bydevice=collections.defaultdict(list);bycustomer=collections.defaultdict(list)
    for s in se.values():
        sid=s['Session_ID'];cid=s['Customer_ID'];did=s['Device_ID']
        ck(cid in cu and did in dv,'Broken session owner',sid)
        start,end=dt(s['Session_start']),dt(s['Session_end'])
        ck(start<=end,'Session inverted',sid)
        link=pair.get((cid,did));ck(link is not None,'Session has no customer-device link',sid)
        if link:
            ck(dt(link['First_seen'])<=start,'Session before binding',sid)
            ck(end<=dt(link['Last_seen']),'Session after link Last_seen',sid)
        if did in dv:ck(end<=dt(dv[did]['Device_last_seen']),'Session after physical device last seen',sid)
        bydevice[did].append((start,end,sid));bycustomer[cid].append((start,end,sid))
        ck((s['Network_type']=='wifi' and s['ISP'] in ('PTCL','Nayatel','StormFiber')) or
           (s['Network_type']=='mobile_data' and s['ISP'] in ('Jazz','Zong','Telenor','Ufone')),
           'ISP/network incoherent',sid)
    overlap=0
    for name,group in [('physical_device',bydevice),('customer',bycustomer)]:
        for key,rows in group.items():
            rows.sort()
            for a,b in zip(rows,rows[1:]):
                if a[1]>b[0]:
                    overlap+=1;ck(False,name+' overlapping sessions',f'{key}: {a[2]}, {b[2]}')
    for a in au.values():
        sid=a['Session_ID'];s=se.get(sid)
        ck(s is not None,'Broken auth session',a['Auth_event_ID'])
        if s:
            ck(a['Customer_ID']==s['Customer_ID'] and a['Device_ID']==s['Device_ID'],'Auth owner mismatch',a['Auth_event_ID'])
            ck(dt(s['Session_start'])<=dt(a['Event_timestamp'])<=dt(s['Session_end']),'Auth outside session',a['Auth_event_ID'])
    customer_txs=collections.defaultdict(list)
    for t in tx.values():
        tid=t['Transaction_ID'];s=se.get(t['Session_ID']);cid=t['Customer_ID']
        ck(cid in cu and s is not None,'Transaction owner/session missing',tid)
        if s:
            ck(s['Customer_ID']==cid,'Transaction session mismatch',tid)
            ck(dt(s['Session_start'])<=dt(t['Timestamp'])<=dt(s['Session_end']),'Transaction outside session',tid)
        if t['Beneficiary_ID']:
            b=be.get(t['Beneficiary_ID']);ck(b is not None,'Broken beneficiary FK',tid)
            if b:
                ck(b['Customer_ID']==cid,'Transaction beneficiary wrong owner',tid)
                ck(dt(b['Beneficiary_added_time'])<=dt(t['Timestamp']),'Transfer before beneficiary creation',tid)
                ck(t['Receiver_ID']==(b['Beneficiary_customer_ID'] or b['Beneficiary_account']),'Receiver mismatch',tid)
        if t['Agent_ID']:
            agent=ag.get(t['Agent_ID']);ck(agent is not None,'Broken agent FK',tid)
            if agent and s and t['Transaction_Type'] in ('cash_in','cash_out'):
                ck(agent['City']==s['City'],'Physical cash agent in wrong city',tid)
        amount=dec(t['Amount']);before=dec(t['Sender_balance_before']);after=dec(t['Sender_balance_after'])
        ck(amount>0 and before>=0 and after>=0,'Invalid amount or negative balance',tid)
        expected=before if t['Transaction_status']!='success' else (before+amount if t['Transaction_Type']=='cash_in' else before-amount)
        ck(after==expected,'Transaction arithmetic mismatch',tid)
        if t['Transaction_Type'] in ('cash_in','cash_out'):
            ck(amount%100==0,'Fractional/odd physical cash denomination',tid)
        customer_txs[cid].append(t)
    for cid,rows in customer_txs.items():
        rows.sort(key=lambda t:(t['Timestamp'],t['Transaction_ID']))
        for prev,nxt in zip(rows,rows[1:]):
            ck(dec(prev['Sender_balance_after'])==dec(nxt['Sender_balance_before']),
               'Chronological balance discontinuity',f'{cid}: {prev["Transaction_ID"]} -> {nxt["Transaction_ID"]}')
    mismatch_bio=0
    for b in bio.values():
        t=tx.get(b['Transaction_ID']);ck(t is not None,'Biometric missing transaction',b['Biometric_event_ID'])
        if t:
            ck(t['Customer_ID']==b['Customer_ID'],'Biometric customer mismatch',b['Biometric_event_ID'])
            ck(dt(b['Event_Timestamp'])<=dt(t['Timestamp']),'Biometric after cash withdrawal',b['Biometric_event_ID'])
            if b['Agent_ID']!=t['Agent_ID']:mismatch_bio+=1
        ck(b['Biometric_required'] in ('True','False'),'Biometric_required wrong format',b['Biometric_event_ID'])
        ck(int(b['Attempt_count'])>=int(b['Failed_attempts']),'Biometric attempts inconsistent',b['Biometric_event_ID'])
    for c in co.values():
        ck(c['Customer_ID'] in cu,'Complaint customer missing',c['Complaint_ID'])
        if c['Transaction_ID']:
            t=tx.get(c['Transaction_ID']);ck(t is not None,'Complaint transaction missing',c['Complaint_ID'])
            if t:ck(t['Customer_ID']==c['Customer_ID'],'Complaint transaction wrong customer',c['Complaint_ID'])
    for a in al.values():
        ck(a['Customer_ID'] in cu,'Alert customer missing',a['Alert_ID'])
        if a['Transaction_ID']:
            t=tx.get(a['Transaction_ID']);ck(t is not None,'Alert transaction missing',a['Alert_ID'])
            if t:ck(t['Customer_ID']==a['Customer_ID'],'Alert transaction wrong customer',a['Alert_ID'])
        ck(a['Criticality_level']==('high' if int(a['Criticality_score'])>=80 else 'medium'),
            'Alert score/level mismatch',a['Alert_ID'])
    for c in ca.values():
        cid=c['Customer_ID'];ck(cid in cu,'Case customer missing',c['Case_ID'])
        a=al.get(c['Alert_ID']) if c['Alert_ID'] else None
        complaint=co.get(c['Complaint_ID']) if c['Complaint_ID'] else None
        ck(bool(a or complaint),'Case has no origin',c['Case_ID'])
        if a:ck(a['Customer_ID']==cid and dt(a['Alert_timestamp'])<=dt(c['Case_created_timestamp']),
            'Case alert timing',c['Case_ID'])
        if complaint:
            ck(complaint['Customer_ID']==cid,'Case complaint wrong customer',c['Case_ID'])
            ck(dt(complaint['Complaint_timestamp'])<=dt(c['Case_created_timestamp']),
               'Case contains future complaint link',c['Case_ID'])
        if c['Case_source']=='complaint':ck(complaint is not None,'Complaint case without complaint',c['Case_ID'])
        if c['Case_source']=='alert':ck(a is not None,'Alert case without alert',c['Case_ID'])
    ck(set(gt)==set(ca),'Ground truth and cases differ')
    sc=collections.Counter(g['Scenario_ID'] for g in gt.values())
    for scenario in ['ATO_NEW_DEVICE','UT_NEW_BENEFICIARY','SE_NEW_BENEFICIARY','DC_MULTI_ACCOUNT_SHARED_DEVICE',
        'CC_STOLEN_CREDENTIAL_NEW_CONTEXT','SCO_LARGE','RF_MULTI_CUSTOMER_CASH_SHORTFALL',
        'BIO_CROSS_AGENT_VERIFICATION_MISMATCH','KYC_REACTIVATION_IDENTITY_MISMATCH',
        'BENIGN_NEW_BENEFICIARY','BENIGN_MPIN_RETRIES','BENIGN_BIOMETRIC_RETRY','BENIGN_NEW_DEVICE','BENIGN_LARGE_CASHOUT']:
        ck(sc[scenario]==(expected_batches or sc[scenario]),'Scenario count mismatch',scenario)
    # Evidence-specific checks, all instances not just the last scenario.
    bytx=collections.defaultdict(list)
    post_by_cust=collections.defaultdict(list)
    prior_by_cust=collections.defaultdict(list)
    for t in tx.values():
        cid=t['Customer_ID'];bytx[cid].append(t)
        (post_by_cust if t['Timestamp']>='2026-10-01' else prior_by_cust)[cid].append(t)
    bydev_auth=collections.defaultdict(list)
    for a in au.values():bydev_auth[(a['Customer_ID'],a['Device_ID'])].append(a)
    for g in gt.values():
        c=ca[g['Case_ID']];cid=c['Customer_ID'];scenario=g['Scenario_ID'];created=dt(c['Case_created_timestamp'])
        post=post_by_cust[cid]
        if scenario=='UT_NEW_BENEFICIARY':
            relevant=[t for t in post if t['Transaction_Type']=='transfer' and dt(t['Timestamp'])<=created]
            if relevant:
                newest=max(relevant,key=lambda t:t['Timestamp'])
                prior=max((dec(t['Amount']) for t in prior_by_cust[cid] if t['Transaction_Type']=='transfer'),default=Decimal('0'))
                ck(dec(newest['Amount'])>prior,'UT not above prior max',g['Case_ID'])
        if scenario=='SCO_LARGE':
            cashouts=sorted([t for t in post if t['Transaction_Type']=='cash_out' and dt(t['Timestamp'])<=created],key=lambda t:t['Timestamp'])
            if cashouts:
                out=cashouts[-1];ins=[t for t in post if t['Transaction_Type']=='cash_in' and t['Agent_ID']==out['Agent_ID']
                    and timedelta(minutes=10)<=dt(out['Timestamp'])-dt(t['Timestamp'])<=timedelta(minutes=20)]
                ck(bool(ins),'Cashout lacks recent same-agent cashin',g['Case_ID'])
                mx=max((dec(t['Amount']) for t in prior_by_cust[cid] if t['Transaction_Type']=='cash_out'),default=Decimal('0'))
                ck(dec(out['Amount'])>2*mx,'Cashout not >2x prior max',g['Case_ID'])
        if scenario=='KYC_REACTIVATION_IDENTITY_MISMATCH':
            prior=prior_by_cust[cid]
            ck(bool(prior) and (created-max(dt(t['Timestamp']) for t in prior)).days>=120,
               'KYC insufficient dormancy',g['Case_ID'])
            rows=[k for k in ky.values() if k['Customer_ID']==cid]
            ck(any(k['KYC_status']=='rejected' for k in rows) and len(rows)>=2,'KYC mismatch missing',g['Case_ID'])
        if scenario=='DC_MULTI_ACCOUNT_SHARED_DEVICE':
            tlist=sorted(post,key=lambda t:t['Timestamp'])
            if tlist:
                d=se[tlist[0]['Session_ID']]['Device_ID']
                users={l['Customer_ID'] for l in links.values() if l['Device_ID']==d}
                ck(len(users)>=3,'Shared device has <3 accounts',g['Case_ID'])
                recent=[t for member in users for t in post_by_cust[member] if t['Transaction_Type']=='transfer'
                    and se[t['Session_ID']]['Device_ID']==d]
                common=collections.Counter(t['Receiver_ID'] for t in recent)
                ck(bool(common) and max(common.values())>=3,'Shared device transfers lack common recipient',g['Case_ID'])
        if scenario=='BIO_CROSS_AGENT_VERIFICATION_MISMATCH':
            complaint=co.get(c['Complaint_ID'])
            if complaint:
                bset={b['Agent_ID'] for b in bio.values() if b['Transaction_ID']==complaint['Transaction_ID'] and b['Result']=='success'}
                ck(len(bset)>=2,'Biometric mismatch not corroborated',g['Case_ID'])

    # V3 reviewed evidence requirements: check EVERY instance of each fraud family.
    auth_by_cust=collections.defaultdict(list)
    sessions_by_device=collections.defaultdict(list)
    for a in au.values():auth_by_cust[a['Customer_ID']].append(a)
    for s in se.values():sessions_by_device[s['Device_ID']].append(s)
    case_by_scenario=collections.defaultdict(list)
    for g in gt.values():case_by_scenario[g['Scenario_ID']].append(ca[g['Case_ID']])
    for scenario in ('ATO_NEW_DEVICE','CC_STOLEN_CREDENTIAL_NEW_CONTEXT'):
        for case in case_by_scenario[scenario]:
            cid=case['Customer_ID'];created=dt(case['Case_created_timestamp'])
            recent=[t for t in post_by_cust[cid] if t['Transaction_Type']=='transfer' and dt(t['Timestamp'])<=created]
            ck(bool(recent),'Missing new-device transfer',case['Case_ID'])
            if not recent:continue
            transfer=max(recent,key=lambda x:x['Timestamp'])
            did=se[transfer['Session_ID']]['Device_ID']
            binding=[a for a in auth_by_cust[cid] if a['Device_ID']==did and a['Event_type']=='DEVICE_BINDING_VERIFICATION' and a['Result']=='success'
                     and dt(a['Event_timestamp'])<dt(transfer['Timestamp'])]
            ck(bool(binding),'No verified device binding',case['Case_ID'])
            if binding:
                ck((dt(transfer['Timestamp'])-max(dt(a['Event_timestamp']) for a in binding)).total_seconds()>=7200,
                    'Device cooling interval <2h',case['Case_ID'])
            if scenario=='ATO_NEW_DEVICE':
                resets=[a for a in auth_by_cust[cid] if a['Device_ID']==did and a['Event_type']=='MPIN_RESET' and a['Result']=='success']
                ck(bool(resets),'ATO missing MPIN reset',case['Case_ID'])
                if resets:ck((dt(transfer['Timestamp'])-max(dt(a['Event_timestamp']) for a in resets)).total_seconds()>=7200,
                    'ATO MPIN reset cooling <2h',case['Case_ID'])
            else:
                logins=[a for a in auth_by_cust[cid] if a['Session_ID']==transfer['Session_ID'] and a['Event_type']=='LOGIN']
                ck(len(logins)==1 and logins[0]['Result']=='success' and int(logins[0]['Attempt_count'])==1,
                   'Credential scenario not first-try login',case['Case_ID'])
    for case in case_by_scenario['UT_NEW_BENEFICIARY']:
        cid=case['Customer_ID'];t=dt(case['Case_created_timestamp'])
        post=[x for x in post_by_cust[cid] if x['Transaction_Type']=='transfer' and dt(x['Timestamp'])<=t]
        if post:
            txrow=max(post,key=lambda x:x['Timestamp'])
            failed=[a for a in auth_by_cust[cid] if a['Session_ID']==txrow['Session_ID'] and a['Event_type']=='LOGIN' and a['Result']=='failed']
            ck(len(failed)>=1,'UT missing failed MPIN corroboration',case['Case_ID'])
            ben=be[txrow['Beneficiary_ID']]
            ck((dt(txrow['Timestamp'])-dt(ben['Beneficiary_added_time'])).total_seconds()<=600,
                'UT beneficiary-transfer sequence too slow',case['Case_ID'])
    for case in case_by_scenario['SE_NEW_BENEFICIARY']:
        cid=case['Customer_ID'];t=dt(case['Case_created_timestamp'])
        post=[x for x in post_by_cust[cid] if x['Transaction_Type']=='transfer' and dt(x['Timestamp'])<=t]
        if post:
            txrow=max(post,key=lambda x:x['Timestamp']);did=se[txrow['Session_ID']]['Device_ID']
            historical=[a for a in auth_by_cust[cid] if a['Device_ID']==did and a['Event_type']=='LOGIN'
                and a['Result']=='success' and a['Event_timestamp']<'2026-10-01']
            ck(len(historical)>=3,'Social engineering device lacks 3 historical logins',case['Case_ID'])
    agent_cashouts=collections.defaultdict(list)
    for x in tx.values():
        if x['Transaction_Type']=='cash_out' and x['Timestamp']>='2026-10-01':agent_cashouts[x['Agent_ID']].append(x)
    for case in case_by_scenario['RF_MULTI_CUSTOMER_CASH_SHORTFALL']:
        cmp=co[case['Complaint_ID']];t=tx[cmp['Transaction_ID']]
        agent=t['Agent_ID'];event=dt(t['Timestamp'])
        nearby=[x for x in agent_cashouts[agent] if abs((dt(x['Timestamp'])-event).total_seconds())<=3600]
        # Bounded to 15 cases; bank ledger corroborates cash-out but NOT the cash shortage.
        ck(len({x['Customer_ID'] for x in nearby})>=3,'Retailer case lacks 3 customers',case['Case_ID'])
        disputed=[c for c in co.values() if c['Complaint_Type']=='cash_disbursement_dispute'
            and c['Transaction_ID'] in {x['Transaction_ID'] for x in nearby}]
        ck(len({c['Customer_ID'] for c in disputed})>=2,'Retailer case lacks 2 complaints',case['Case_ID'])
    # A complaint is NOT synonymous with fraud; ensure legitimate complaint-origin cases.
    for scenario in ('BENIGN_NEW_BENEFICIARY','BENIGN_BIOMETRIC_RETRY'):
        ck(all(c['Case_source']=='complaint' for c in case_by_scenario[scenario]),
            'Benign complaint-origin lookalike missing',scenario)
    ck(any(c['Case_source']=='complaint' and gt[c['Case_ID']]['is_fraud']=='No' for c in ca.values()),
       'No legitimate complaint-origin cases')

    hashes={n:hashlib.sha256((root/(n+'.csv')).read_bytes()).hexdigest() for n in names}
    return dict(status='PASS' if not failures else 'FAIL',customer_count=len(cu),row_counts=counts,
        fraud_cases=sum(g['is_fraud']=='Yes' for g in gt.values()),legitimate_cases=sum(g['is_fraud']=='No' for g in gt.values()),
        scenario_counts=dict(sc),physical_device_session_overlaps=overlap,biometric_agent_mismatches=mismatch_bio,
        checks=['unique IDs','foreign keys','session chronology','auth within session','physical device overlap',
            'customer overlap','beneficiary ownership and creation','ISP/network','device OS/model',
            'transaction arithmetic','chronological account balances','cash denomination','KYC chronology',
            'complaint/alert timing','case ground truth','fraud scenario evidence'],
        errors=failures,warnings=warnings,sha256=hashes)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True)
    p.add_argument('--customers',type=int);p.add_argument('--batches',type=int)
    p.add_argument('--output',default='VALIDATION_REPORT.json')
    a=p.parse_args();result=audit(a.input,a.customers,a.batches)
    Path(a.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result['status'],len(result['errors']),'errors')
    for e in result['errors'][:30]:print(' -',e)
    if result['status']!='PASS':raise SystemExit(1)
