#!/usr/bin/env python3
"""Freeze population denominators for scale comparisons, never unique applicants."""
from pathlib import Path
import hashlib,json,re,sys
import pycountry,requests
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/demographic_context';OUT=ROOT/'data/research/demographic_context'
CATALOG=[('worldbank_population_2011_2025.json','https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&date=2011:2025&per_page=20000','population_wdi','世界银行 WDI 总人口（2011—2025）','World Bank'),('china_taiwan_population_dec2025.html','https://www.moi.gov.tw/News_Content.aspx?n=2&s=335870','population_china_taiwan_2025','中国台湾地区2025年12月户籍人口统计','中国台湾地区户政统计部门')]
def main():
 RAW.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True);sources=[]
 for filename,url,sid,title,publisher in CATALOG:
  p=RAW/filename
  if '--refresh' in sys.argv or not p.exists():
   r=requests.get(url,timeout=45);r.raise_for_status();p.write_bytes(r.content)
  sources.append(dict(source_id=sid,title=title,publisher=publisher,url=url,local_path=p.relative_to(ROOT).as_posix(),retrieved_at='2026-11-16',sha256=hashlib.sha256(p.read_bytes()).hexdigest(),source_quality='official_original',purpose='population_scale_denominator_not_visa_quantity'))
 payload=json.loads((RAW/CATALOG[0][0]).read_text());assert payload[0]['pages']==1
 codes={c.alpha_3 for c in pycountry.countries};population=[]
 for r in payload[1]:
  if r['countryiso3code'] not in codes or not isinstance(r.get('value'),(float,int)) or r['value']<=0:continue
  population.append(dict(code=r['countryiso3code'],year=int(r['date']),value=r['value'],basis='total_population',label='世界银行总人口',source_id='population_wdi',source_locator=f'SP.POP.TOTL; {r["countryiso3code"]}; {r["date"]}',is_estimate=True))
 text=BeautifulSoup((RAW/CATALOG[1][0]).read_bytes(),'html.parser').get_text(' ',strip=True)
 match=re.search(r'月底人口數為([\d,]+)人，與上年同月比較減少([\d,]+)人',text);assert match
 n,delta=[int(s.replace(',','')) for s in match.groups()]
 for year,value in [(2025,n),(2024,n+delta)]:population.append(dict(code='TWN',year=year,value=value,basis='year_end_registered_population',label='年末户籍人口',source_id='population_china_taiwan_2025',source_locator='第二段；2024值=2025年末人口+同比减少人数',is_estimate=False))
 for filename,value in [('sources.json',sources),('population.json',population),('observations.json',[]),('fee_rules.json',[])]:
  (OUT/filename).write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')
 checks=[dict(check='population is positive, code-year unique and source-linked',passed=len({(p['code'],p['year']) for p in population})==len(population) and all(p['value']>0 and p['source_id'] in {s['source_id'] for s in sources} for p in population)),dict(check='China mainland and Hong Kong Macao Taiwan retain distinct source population scopes',passed=all(any(p['code']==c and p['year']==2025 for p in population) for c in ['CHN','HKG','MAC','TWN']))]
 (OUT/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));assert all(c['passed'] for c in checks)
 (OUT/'README.md').write_text('人口只用于费用规模折算：费用／人口，不是每位居民真实支出，也不是独立申请人数。WDI按自身统计区域保留中国大陆、中国香港、中国澳门分项；中国台湾使用当地户籍年末人口并标注口径。只用同年人口，缺年不前移或回填；申根由当年成员同年人口相加，成员缺失则不提供合计。\n')
 print(json.dumps(dict(population_records=len(population),jurisdictions=len({p['code'] for p in population}),sources=len(sources),checks=checks),ensure_ascii=False))
if __name__=='__main__':main()
