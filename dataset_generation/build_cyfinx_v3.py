#!/usr/bin/env python3
"""One-command reproducible CyFinX V3 build with independent validation."""
import argparse,json,sys
from pathlib import Path
from normal_population_generator_v3 import NormalV3
from normal_population_generator_v2_full_modified import DEFAULT_START,DEFAULT_END
from fraud_scenario_injector_v3 import V3Injector
from validate_cyfinx_v3 import audit

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--customers',type=int,default=2500)
    p.add_argument('--batches',type=int,default=15)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--fraud-seed',type=int,default=20261009)
    p.add_argument('--output-root',default='CyFinX_2500_Final')
    p.add_argument('--skip-normal',action='store_true')
    a=p.parse_args()
    if a.customers<100 or a.batches<1 or a.batches*17>a.customers:
        p.error('Need >=100 customers and enough unique customers for 9 fraud + 5 benign and linked actors per batch')
    root=Path(a.output_root);norm=root/'normal';final=root/'investigations'
    if not a.skip_normal:
        print('Generating corrected normal population...',flush=True)
        NormalV3(a.customers,DEFAULT_START,DEFAULT_END,a.seed,str(norm)).run()
    print('Injecting V3-reviewed scenarios...',flush=True)
    V3Injector(norm,final,a.fraud_seed,a.batches).run()
    print('Running independent 14-table validation...',flush=True)
    result=audit(final,a.customers,a.batches)
    (root/'VALIDATION_REPORT.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if result['status']!='PASS':
        print('\n'.join(result['errors'][:30]));raise SystemExit('Independent audit failed')
    print('PASS:',result['customer_count'],'customers',result['fraud_cases'],'fraud cases',
          result['legitimate_cases'],'legitimate cases; 0 validation errors',flush=True)

if __name__=='__main__':main()
