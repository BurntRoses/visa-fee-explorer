#!/usr/bin/env python3
"""One offline path from frozen originals to master data and the application."""
from pathlib import Path
import subprocess,sys,json,time
ROOT=Path(__file__).resolve().parents[1];LOG=ROOT/'docs/validation';LOG.mkdir(parents=True,exist_ok=True)
names=['research_schengen_fx.py','research_us.py','research_uk_canada.py','research_asia_pacific.py','research_china_seasia.py','research_india_korea.py','research_turkey_russia_saudi.py','research_global_americas_africa.py','research_global_asia_me_europe.py','research_refine_schengen.py','research_refine_uk_canada.py','research_refine_korea_vietnam.py','research_history.py','research_spatial_extension.py','research_time_space.py','research_history_expansion.py','research_spatial_expansion_v2.py','research_demographic_context.py','research_temporal_expansion_v2.py','research_uk_history_v2.py','research_africa_expansion_v3.py','research_asia_expansion_v3.py','research_mobility_context_v4.py','research_europe_expansion_v4.py','research_americas_expansion_v4.py','research_asia_mobility_expansion_v4.py','research_africa_fiscal_expansion_v4.py','research_canada_history_v4.py','research_global_recent_mobility_v4.py','research_china_visa_context_v4.py','research_us_history_v4.py','research_africa_visa_issuance_v5.py','research_newzealand_history_v5.py','research_thailand_history_v5.py','research_americas_expansion_v6.py','research_africa_expansion_v6.py','research_asia_expansion_v6.py','research_australia_recent_v6.py','research_europe_fiscal_v6.py','research_us_recent_v6.py','research_middleeast_europe_v7.py','research_philippines_expansion_v7.py','research_south_asia_expansion_v7.py','research_india_recent_v7.py','audit_legacy.py','build_dataset.py','build_money_model.py']
names.insert(0, 'sanitize_source_archives.py')
names[names.index('audit_legacy.py'):names.index('audit_legacy.py')] = ['research_r12_public_statistics.py','model_r12_fiscal.py']
report=[]
for name in names:
 args = ['--evidence-only'] if name == 'model_r12_fiscal.py' else []
 t=time.monotonic();r=subprocess.run([sys.executable,str(ROOT/'scripts'/name),*args],cwd=ROOT,text=True,capture_output=True)
 (LOG/(name+'.log')).write_text(r.stdout+'\n'+r.stderr)
 report.append(dict(script=name,exit_code=r.returncode,seconds=round(time.monotonic()-t,2)))
 print(json.dumps(report[-1]),flush=True)
 if r.returncode:
  print(r.stderr[-3000:]);sys.exit(r.returncode)
checks=json.loads((ROOT/'data/processed/checks.json').read_text());assert all(c['passed'] for c in checks),checks
(LOG/'offline-build.json').write_text(json.dumps({'steps':report,'master_checks':checks,'network':'not_used'},ensure_ascii=False,indent=2))
subprocess.run([sys.executable,str(ROOT/'scripts/build_app.py')],cwd=ROOT,check=True)
print('Offline rebuild complete.',flush=True)
