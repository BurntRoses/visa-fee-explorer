#!/usr/bin/env python3
"""Rebuild frozen Americas evidence offline; add only identified visa-fee scopes.

Ecuador: actual visa collections of named zonal offices, never a national estimate.
Chile: nationality/type issuances and the documented Bolivia Mercosur fee waiver.
Brazil: 2021–2023 history from the existing original SCI archive; birth country is
not nationality. Repeated control totals and monthly receipts are not extra flows.
"""
from __future__ import annotations

import calendar
from collections import Counter
import csv
import hashlib
import io
import json
import logging
from pathlib import Path
import re
import sys
import zipfile

from pypdf import PdfReader

sys.dont_write_bytecode = True
logging.getLogger('pypdf').setLevel(logging.ERROR)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/americas_expansion_v4'
OUT = ROOT / 'data/research/americas_expansion_v4'
EST = ROOT / 'data/estimates/americas_expansion_v4_flows.json'
ASOF = '2026-11-17'
SHIFT = ('2025年11月26日起各分局暂停线下签证受理、转入中央数字服务CESDI。'
         '本项只覆盖指定分局账簿，下降不能解释为厄瓜多尔全国签证收入下降；未补算中央或其他分局。')

SPECS = [
    ('ecu_zone4_2024.pdf', 'ECU', 'https://www.cancilleria.gob.ec/wp-content/uploads/2025/06/vf-informe_dz4-manta_20240090325001750193117.pdf', 'Ecuador MREMH', 'Rendición de Cuentas 2024: Dirección Zonal4, Manta'),
    ('ecu_zone6_2024.pdf', 'ECU', 'https://www.cancilleria.gob.ec/wp-content/uploads/2025/06/vf-informe_de_rendiciOn_de_cuentas_dz6_20240488882001750193117.pdf', 'Ecuador MREMH', 'Rendición de Cuentas 2024: Dirección Zonal6, Azogues'),
    ('ecu_zone6_2025.pdf', 'ECU', 'https://www.cancilleria.gob.ec/wp-content/uploads/2026/04/informe_de_rendiciOn_de_cuentas_dz6_2025-signed.pdf', 'Ecuador MREMH', 'Rendición de Cuentas 2025: Dirección Zonal6, Azogues'),
    ('ecu_zone7_2024.pdf', 'ECU', 'https://www.cancilleria.gob.ec/wp-content/uploads/2025/06/vf-formato_informe_dz7-final0871343001750193117.pdf', 'Ecuador MREMH', 'Rendición de Cuentas 2024: Dirección Zonal7, Machala and Loja'),
    ('ecu_zone8_2024.pdf', 'ECU', 'https://www.cancilleria.gob.ec/wp-content/uploads/2025/06/vf-rendicion_cuentas_2024_guayaquil_20240250565001750193118.pdf', 'Ecuador MREMH', 'Rendición de Cuentas 2024: Dirección Zonal8, Guayaquil'),
    ('ecu_zone8_2025.pdf', 'ECU', 'https://www.cancilleria.gob.ec/wp-content/uploads/2026/04/Informe_Rendicion_cuentas_2025_GUAYAQUIL_1_04_2026.docx16H21.docxREV.pdf', 'Ecuador MREMH', 'Rendición de Cuentas 2025: Dirección Zonal8, Guayaquil'),
    ('chl_final2026.pdf', 'CHL', 'https://wp-web.dev.senamig.cl/wp-content/uploads/2026/03/Informe-Final-Gestion-2022-2026-Servicio-Nacional-de-Migraciones.pdf', 'Chile Servicio Nacional de Migraciones', 'Informe Final Gestión2022–2026, published March2026; Tables5–7'),
    ('per_revenue2024.pdf', 'PER', 'https://cdn.www.gob.pe/uploads/document/file/7484867/6369474-resumen-de-recaudacion-de-ingresos-de-enero-a-diciembre-2024.pdf?v=1736811073', 'Peru Ministerio de Relaciones Exteriores', 'Resumen de recaudación de ingresos, January–December2024, published13January2025'),
]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sid(filename):
    return 'amx4_' + Path(filename).stem


def norm(text):
    return ' '.join(text.split())


def parse_eu(value):
    return float(value.replace('.', '').replace(',', '.'))


class Research:
    def __init__(self):
        self.sources, self.obs, self.flows, self.models, self.ranges = [], [], [], [], []
        self.fees, self.coverage, self.excluded, self.readers = [], [], [], {}

    def archives(self):
        for filename, dest, url, publisher, title in SPECS:
            p = RAW / filename
            assert p.read_bytes().startswith(b'%PDF'), filename
            self.sources.append(dict(source_id=sid(filename), destination=dest, url=url,
                                     publisher=publisher, institution=publisher, title=title,
                                     retrieved_at=ASOF, source_quality='official_original',
                                     local_path=str(p.relative_to(ROOT)), path=str(p.relative_to(ROOT)),
                                     sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size,
                                     content_type='application/pdf', archive_kind='original_document',
                                     archive_status='original_archived', capture_method='http_download_original'))
            self.readers[filename] = PdfReader(p)
            (OUT / (p.stem + '.txt')).write_text('\n\n'.join(
                f'PDF PAGE {i+1}\n{norm(page.extract_text())}'
                for i, page in enumerate(self.readers[filename].pages)))
        prior = json.loads((ROOT / 'data/research/global_americas_africa/sources.json').read_text())
        br = next(r for r in prior if r['source_id'] == 'gaa_br_microdata2021_2025').copy()
        br['source_id'] = 'amx4_br_sci_history'
        br['reuse_note'] = 'Existing frozen original; this package extracts previously unused2021–2023 history only.'
        br['research_cutoff'] = ASOF
        assert hashlib.sha256((ROOT / br['local_path']).read_bytes()).hexdigest() == br['sha256']
        self.sources.append(br)

    def page(self, filename, page):
        return norm(self.readers[filename].pages[page-1].extract_text())

    def observation(self, slug, dest, year, metric, value, unit, filename, locator, *,
                    origin='UNK', basis='unallocated', group='other', typ='unclassified', **extra):
        oid = 'amx4_' + slug
        income = metric == 'visa_fee_actual_revenue'
        office = extra.get('collecting_office')
        if dest == 'CHL':
            label = {'family_reunification':'家庭团聚签证签发', 'mercosur_residence_visa':'Mercosur居留签证签发',
                     'nna_humanitarian_visa':'未成年人人道签证' + ('申请' if metric=='visa_applications' else '签发')}[typ]
            series = 'chile_' + typ + '_' + metric
            role = 'country_total' if origin == 'WORLD' or typ == 'nna_humanitarian_visa' else 'citizenship_component'
        elif dest == 'BRA':
            label = '巴西' + {'Visita':'访问', 'Estudo':'学生', 'Trabalho':'工作', 'Reunião familiar':'家属',
                            'Oficial':'公务', 'Diplomático':'外交', 'Cortesia':'礼遇', 'Acolhida humanitária':'人道',
                            'Demais Temporários':'其他临时', 'Outros':'其他', 'all_visas':'全部'}[typ] + '签证签发'
            series = 'brazil_visas_issued_' + re.sub(r'[^a-z0-9]+', '_', typ.lower()).strip('_')
            role = 'country_total'
        else:
            label = '厄瓜多尔' + office + {'temporary_visa':'临时签证', 'permanent_visa':'永久签证',
                                           'all_visa':'签证', 'temporary_visitor_visa':'临时访问签证',
                                           'visa_service_actions':'签证服务'}[typ] + ('费实收' if income else '活动件数' if metric=='visa_service_actions' else '签发')
            series = f'ecuador_{office}_{typ}_{metric}'
            role = 'subset'
        period_type = extra.pop('period_type', 'calendar_year')
        period_start = extra.pop('period_start', f'{year}-01-01')
        period_end = extra.pop('period_end', f'{year}-12-31')
        if period_type == 'calendar_month':
            series += '_monthly'
            label += '（月度）'
            role = 'subset'
        if dest=='ECU' and year==2025 and metric=='visa_service_actions':
            variant='summary' if 'p16;' in locator else 'body'
            series += '_' + variant
            label += '（报告汇总版）' if variant=='summary' else '（报告正文版）'
            extra.update(quality_issue='conflicting_quantity',context_selection_default=False)
        self.obs.append(dict(observation_id=oid, destination=dest, year=year, metric=metric,
                             value=value, unit=unit, source_id=sid(filename) if filename else 'amx4_br_sci_history',
                             source_locator=locator, origin=origin, nationality=origin,
                             origin_basis=basis, visa_group=group, visa_type=typ,
                             observation_domain='government_visa_revenue' if income else 'visa_activity',
                             series_id=series, series_label=label, aggregation_role=role,
                             context_only=not extra.get('eligible_money_ledger',False), flow_direction='inbound',
                             period_start=period_start,period_end=period_end,period_type=period_type,
                             time_grain='month' if period_type=='calendar_month' else 'year',
                             period_key=period_start[:7] if period_type=='calendar_month' else str(year),
                             source_quality='official_original',
                             calculation_type='direct_observation', **extra))
        return oid

    def receipt(self, year, office, typ, label, amount, filename, page, *, count_conflict=False):
        t = self.page(filename, page)
        representations = [f'{amount:,.2f}', f'{amount:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')]
        assert any(value in t for value in representations), (filename, page, amount)
        oid = self.observation(f'ecu_{year}_{office}_{typ}_actual', 'ECU', year,
                               'visa_fee_actual_revenue', amount, 'USD', filename,
                               f'PDF p{page}; {office}; ' + ('Visas' if typ == 'all_visa' else 'Visas Temporales' if typ == 'temporary_visa' else 'Visas Permanentes'),
                               typ=typ, collecting_office=office, eligible_money_ledger=True,
                               account_scope='Named zonal-office visa collections only; not national receipts',
                               notes=('指定分局单列签证费实收；不含身份证、归化、护照、公证认证、其他服务。'
                                      + ('报告2025汇总服务件数与正文不一致；金额一致，未构造人数分母。' if count_conflict else '')
                                      + (SHIFT if year == 2025 else '')))
        method = f'amx4_ecu_{year}_office_actual_receipts'
        self.flows.append(dict(id=f'amx4_ecu_{year}_{office}_{typ}', payer='UNK', receiver='ECU',
                               year=year, visa_group='other', visa_type=f'{office}_{typ}_actual_receipts',
                               visa_label=label, category_detail_status='unclassified',
                               amount=amount, lower=amount, upper=amount, currency='USD', quantity=None,
                               quantity_basis='actual_collections_without_matched_fee_payment_denominator',
                               source_ids=[sid(filename)] + ([sid('ecu_zone6_2025.pdf')] if year == 2025 and office != 'DZ6' else []),
                               observation_ids=[oid], method_id=method,
                               model_status='observed_receipts_partial', calculation_type='direct_observation',
                               origin_basis='unallocated', period_start=f'{year}-01-01', period_end=f'{year}-12-31',
                               period_type='calendar_year', period_label=str(year),
                               notes=(f'厄瓜多尔{office}签证费实收子集；各办公室互斥，只计该服务行，未外推全国。'
                                      '付款国籍未知；签发/服务件数未与实际收费队列一一匹配。' + (SHIFT if year == 2025 else '')),
                               parameters=dict(actual_receipts_observed=True, collecting_office=office,
                                               government_scope='zonal_office_subset',
                                               national_extrapolation=False, payer_nationality_allocation='none',
                                               excluded=['cedulación/residence identity cards', 'naturalisation', 'passport', 'apostille/legalisation', 'mixed visa and other services'],
                                               reported_precision_USD=.01,
                                               range_method='原币官方收款值；精确报告金额，不是全国金额的上下界',
                                               collection_channel_shift_2025=SHIFT if year == 2025 else None)))

    def ecuador(self):
        self.receipt(2024, 'DZ4', 'temporary_visa', '临时签证费', 26375, 'ecu_zone4_2024.pdf', 11)
        self.receipt(2024, 'DZ4', 'permanent_visa', '永久签证费', 121087.5, 'ecu_zone4_2024.pdf', 11)
        self.receipt(2024, 'DZ6', 'all_visa', '签证费（类别未拆）', 586697.5, 'ecu_zone6_2024.pdf', 15)
        self.receipt(2024, 'DZ8', 'temporary_visa', '临时签证费', 447590, 'ecu_zone8_2024.pdf', 28)
        self.receipt(2024, 'DZ8', 'permanent_visa', '永久签证费', 339512.5, 'ecu_zone8_2024.pdf', 28)
        self.receipt(2025, 'DZ6', 'all_visa', '签证费（类别未拆）', 412697.5, 'ecu_zone6_2025.pdf', 16, count_conflict=True)
        self.receipt(2025, 'DZ8', 'temporary_visa', '临时签证费', 280875, 'ecu_zone8_2025.pdf', 32)
        self.receipt(2025, 'DZ8', 'permanent_visa', '永久签证费', 122360, 'ecu_zone8_2025.pdf', 32)
        assert '26 de noviembre de 2025' in self.page('ecu_zone6_2025.pdf', 5)
        assert 'SUSPENSIÓN TOTAL' in self.page('ecu_zone6_2025.pdf', 5)

        # Real monthly detail is the same cash already included in the annual flow.
        series = {
            (2024, 'temporary_visa'): (29, [55995,37915,43670,40120,37280,40015,45635,42065,28360,27475,20385,28675],447590),
            (2024, 'permanent_visa'): (30, [35800,27710,34627.5,27657.5,26417.5,22600,24702.5,31685,30080,26895,29200,22137.5],339512.5),
            (2025, 'temporary_visa'): (33, [25020,31170,31490,39825,19485,12275,26905,29095,28520,29445,7335,310],280875),
            (2025, 'permanent_visa'): (34, [16315,16365,20410,19620,13012.5,15130,6597.5,5955,4145,4220,590,0],122360),
        }
        for (year, typ), (page, monthly, annual) in series.items():
            filename = f'ecu_zone8_{year}.pdf'
            t = self.page(filename, page)
            floats = [float(s.replace(',', '')) for s in re.findall(r'(?<![\d,])(\d[\d,]*\.\d{2})(?!\d)', t)]
            expected = monthly + [annual]
            assert any(floats[i:i+13] == expected for i in range(len(floats)-12)), (year, typ, floats)
            assert sum(monthly) == annual
            for month, value in enumerate(monthly, 1):
                self.observation(f'ecu_{year}_DZ8_{typ}_m{month:02d}', 'ECU', year,
                                 'visa_fee_actual_revenue', value, 'USD', filename,
                                 f'PDF p{page}; DZ8; {typ}; month{month}', typ=typ,
                                 collecting_office='DZ8', period_start=f'{year}-{month:02d}-01',
                                 period_end=f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}',
                                 period_type='calendar_month', eligible_money_ledger=False,
                                 notes='同一DZ8年度收款的月份分解，不能与年度总行再相加。' + (SHIFT if year == 2025 else ''))

        # Issuances and service actions remain distinct from payments and people.
        counts = [(2024,'DZ4','temporary_visa',878,11,'ecu_zone4_2024.pdf'),
                  (2024,'DZ4','permanent_visa',754,11,'ecu_zone4_2024.pdf'),
                  (2024,'DZ8','temporary_visa',3524,10,'ecu_zone8_2024.pdf'),
                  (2024,'DZ8','permanent_visa',1575,11,'ecu_zone8_2024.pdf'),
                  (2025,'DZ8','temporary_visa',1846,10,'ecu_zone8_2025.pdf'),
                  (2025,'DZ8','permanent_visa',476,11,'ecu_zone8_2025.pdf'),
                  (2025,'DZ8','temporary_visitor_visa',9,11,'ecu_zone8_2025.pdf')]
        for year, office, typ, count, page, filename in counts:
            t = self.page(filename, page)
            assert any(v in t for v in [str(count), f'{count:,}', f'{count:,}'.replace(',','.')])
            self.observation(f'ecu_{year}_{office}_{typ}_issued','ECU',year,'visas_issued',count,'visas',filename,
                             f'PDF p{page}; {office}; {typ}; annual total',typ=typ,
                             collecting_office=office,eligible_money_ledger=False,
                             notes='实际签发，非申请、付费件数或独立人数；不与实际收款队列假定一一对应。')
        for year, count, page in [(2024,9033,5),(2025,4731,5),(2025,7763,16)]:
            self.observation(f'ecu_{year}_DZ6_visa_actions_p{page}','ECU',year,'visa_service_actions',count,'service_actions',
                             f'ecu_zone6_{year}.pdf',f'PDF p{page}; Visas quantity row',typ='visa_service_actions',
                             collecting_office='DZ6',eligible_money_ledger=False,
                             notes=('2025正文4731与汇总7763不一致；两处均报收入USD412697.50。均作为原始服务件数保留，不选一个当申请人数。'
                                    if year==2025 else '服务活动件数；未证明是独立申请或付费人数。'))
        for year in [2024,2025]:
            filename=f'ecu_zone8_{year}.pdf'; page=30 if year==2024 else 34
            assert '2023' in self.page(filename,page) and '0.00' in self.page(filename,page)
            self.fees.append(dict(fee_rule_id=f'amx4_ecu_DZ8_protection_{year}',destination='ECU',year=year,
                                  visa_type='international_protection_visa',visa_group='other',amount=0,currency='USD',
                                  source_id=sid(filename),source_locator=f'PDF p{page}; International Protection visa service free from April2023',
                                  main_money_eligible=False,notes='明确免费政策；本包没有匹配签发队列，不生成收费或人数。'))
        self.excluded.extend([
            dict(destination='ECU',year=2024,source_id=sid('ecu_zone7_2024.pdf'),source_locator='PDF p13',reported_amount=171580,currency='USD',reason='Visas y más servicios mixes visa and other services; not monetized.',quantities_retained='1007 permanent/temporary visa services on PDF p7; not used as fee denominator'),
            dict(destination='ECU',year=2024,source_id=sid('ecu_zone4_2024.pdf'),source_locator='PDF p11',reported_amount=87825,currency='USD',reason='Solicitudes de visas, transferencias y cancelaciones is a mixed service line, not added to separately identified visa issuance receipts.'),
            dict(destination='PER',year=2024,source_id=sid('per_revenue2024.pdf'),source_locator='PDF pp1–2; classifier1.9.1.1.1.1',reported_amount=127126462.90,currency='PEN',reason='Institutional balance/transfer summary has no isolated visa-fee revenue line. Total is not visa receipts.'),
        ])
        for year, offices in [(2024,['DZ4','DZ6','DZ8']),(2025,['DZ6','DZ8'])]:
            rr=[r for r in self.flows if r['receiver']=='ECU' and r['year']==year]
            amount=round(sum(r['amount'] for r in rr),2)
            assert amount=={2024:1521262.5,2025:815932.5}[year]
            mid=f'amx4_ecu_{year}_office_actual_receipts'
            self.models.append(dict(model_id=mid,destination='ECU',year=year,
                                    target='指定分局单列签证费实际收款之和',status='observed_office_receipts_partial',
                                    formula='Sum mutually exclusive named office and visa-service rows; no tariff or arrivals multiplication',
                                    source_ids=sorted({s for r in rr for s in r['source_ids']}),
                                    collecting_offices=offices,central_native=amount,lower_native=amount,upper_native=amount,currency='USD',
                                    limitations=['仅列明办公室账簿；不是全国总额。','付款国籍未拆，保留UNK。','居留身份证、护照、归化、认证与混合其他服务排除。',
                                                 '签发和服务件数不是经过匹配的实际收费分母。']+([SHIFT] if year==2025 else [])))
            self.ranges.append(dict(receiver='ECU',year=year,amount=amount,lower=amount,upper=amount,currency='USD',
                                    range_method='官方实际收款子集之和；不是全国不确定性区间'))
            self.coverage.append(dict(destination='ECU',receiver='ECU',year=year,visa_group='other',
                                      status='observed_receipts_partial',collecting_offices=offices,amount=amount,currency='USD',
                                      payer_basis='unallocated',national_total_identified=False,
                                      notes='同一办公室内临时/永久签证行互斥；分局之间为各自账簿。'+(SHIFT if year==2025 else '')))

    def chile(self):
        filename='chl_final2026.pdf'
        family=[('Venezuela','VEN'),('Haití','HTI'),('Colombia','COL'),('Perú','PER'),('Bolivia','BOL'),
                ('Otros','UNK'),('Ecuador','ECU'),('R. Dominicana','DOM'),('Cuba','CUB'),('Argentina','ARG'),
                ('China','CHN'),('Brasil','BRA'),('España','ESP')]
        mercosur=[('Bolivia','BOL'),('Argentina','ARG'),('Brasil','BRA'),('Paraguay','PRY'),('Uruguay','URY'),('Otros','UNK')]
        for page,rows,typ,group,expected in [(23,family,'family_reunification','family',[8717,18909,37518,38478]),
                                               (25,mercosur,'mercosur_residence_visa','other',[4543,9920,28251,119679])]:
            t=self.readers[filename].pages[page-1].extract_text(extraction_mode='layout')
            totals=Counter()
            for country,origin in rows:
                line=next(line.strip() for line in t.splitlines() if re.match(re.escape(country)+r'\s+\d',line.strip()))
                values=[int(s.replace('.','')) for s in re.findall(r'\d[\d.]*',line[len(country):])]
                assert len(values)==(5 if page==23 else 4),(country,values)
                if page==23:assert sum(values[:4])==values[4]
                for year,count in zip(range(2022,2026),values[:4]):
                    totals[year]+=count
                    self.observation(f'chl_{year}_{typ}_{origin}','CHL',year,'visas_issued',count,'visas',filename,
                                     f'PDF p{page}; Table{5 if page==23 else 7}; nationality={country}; year={year}',
                                     origin=origin,basis='nationality' if origin!='UNK' else 'other_nationalities_unallocated',group=group,typ=typ,
                                     eligible_money_ledger=False,notes='按国籍的实际签发；属于全部临时居留签证的子集，不能额外加到全国临时签证总量。')
            assert list(totals.values())==expected,(typ,totals)
            for year,value in totals.items():
                self.observation(f'chl_{year}_{typ}_control','CHL',year,'visas_issued',value,'visas',filename,
                                 f'PDF p{page}; Table{5 if page==23 else 7}; TOTAL',origin='WORLD',basis='aggregate_control',group=group,typ=typ,
                                 eligible_money_ledger=False,is_aggregate_control=True,
                                 notes='国籍行控制总计；不能与对应国籍明细重复相加。')
        t=self.page(filename,24)
        assert 'septiembre de 2023' in t and 'exención recíproca del pago de los derechos por visas' in t
        for year in [2024,2025]:
            oid=f'amx4_chl_{year}_mercosur_residence_visa_BOL'
            count=next(r['value'] for r in self.obs if r['observation_id']==oid)
            mid=f'amx4_chl_{year}_bol_mercosur_waiver'
            self.fees.append(dict(fee_rule_id=mid,destination='CHL',nationality='BOL',year=year,
                                  visa_group='other',visa_type='mercosur_residence_visa',amount=0,currency='USD',
                                  source_id=sid(filename),source_locator='PDF p24; September2023 Chile–Bolivia cooperation and reciprocal visa-fee exemption',
                                  evidence_policy_start_month='2023-09',coverage_start=f'{year}-01-01',coverage_end=f'{year}-12-31',
                                  notes='仅玻利维亚国籍Mercosur签证的签证费免收；不推断其他国籍、身份证或附加服务免费。'))
            self.flows.append(dict(id=mid,payer='BOL',receiver='CHL',year=year,visa_group='other',
                                   visa_type='bol_mercosur_visa_fee_exempt',visa_label='Mercosur签证费（双边互免）',
                                   category_detail_status='unclassified',amount=0,lower=0,upper=0,currency='USD',quantity=count,
                                   quantity_basis='observed_visa_issuances_in_documented_fee_exempt_category',source_ids=[sid(filename)],
                                   observation_ids=[oid],method_id=mid,model_status='statutory_fee_exempt_observed_quantity',
                                   calculation_type='direct_fee_exemption',origin_basis='nationality',
                                   period_start=f'{year}-01-01',period_end=f'{year}-12-31',period_type='calendar_year',period_label=str(year),
                                   notes='官方说明2023年9月起玻利维亚国籍Mercosur签证免签证费；0金额代表有依据的免费签证队列。未计居留身份证、延续、其他服务或其他国籍。',
                                   parameters=dict(issued_count=count,statutory_visa_fee=0,currency='USD',fee_exemption_observed=True,
                                                   policy_start_month='2023-09',scope='Bolivian nationality; Mercosur visa initial government visa fee only',
                                                   range_method='已识别免签证费类别；0不是缺失值')))
            self.models.append(dict(model_id=mid,destination='CHL',year=year,status='documented_fee_exemption',
                                    formula='Observed Bolivia Mercosur visa issuances × statutory visa fee0',central_native=0,lower_native=0,upper_native=0,currency='USD',
                                    source_ids=[sid(filename)],quantity=count,limitations=['仅玻利维亚Mercosur签证费；未声称其他许可及服务收费为零。']))
            self.ranges.append(dict(receiver='CHL',year=year,amount=0,lower=0,upper=0,currency='USD',
                                    range_method='有证据的玻利维亚Mercosur签证费免收队列'))
        # NNA table is a separate application/issuance series, with a preserved discrepancy.
        for metric,values in [('visa_applications',[10940,34520,54598,66699]),('visas_issued',[11017,29440,52591,52806])]:
            assert sum(values)==(166757 if metric=='visa_applications' else 145854)
            for year,value in zip(range(2022,2026),values):
                assert f'{value:,}'.replace(',','.') in t
                self.observation(f'chl_{year}_nna_{metric}','CHL',year,metric,value,'applications' if metric=='visa_applications' else 'visas',
                                 filename,'PDF p24; Table6; '+metric,typ='nna_humanitarian_visa',
                                 eligible_money_ledger=False,notes='未成年人人道签证；Table6申请总和166757，正文166575有差异，采用原表逐年值且保留冲突。申请与签发不是同一队列的同期审批率。')
        for year in range(2022,2026):
            for group in ['family','other']:
                self.coverage.append(dict(destination='CHL',receiver='CHL',year=year,visa_group=group,
                                          status='observed_quantity_partial_with_bolivia_fee_waiver' if year>=2024 and group=='other' else 'observed_quantity_partial_fee_gap',
                                          source_ids=[sid(filename)],quantity_basis='nationality',
                                          notes='家庭团聚及Mercosur为临时签证子集。2026收费表不回填历史；仅2024/25玻利维亚Mercosur签证免收有直接证据。'))

    def brazil_history(self):
        archive=ROOT/'data/raw/global_americas_africa/br_microdata2021_2025.zip'
        totals,months,birth=Counter(),Counter(),Counter()
        with zipfile.ZipFile(archive) as z:
            with z.open('Base_Tratada_MRE_jan21_abr25.csv') as f:
                for row in csv.DictReader(io.TextIOWrapper(f,encoding='utf-8')):
                    year=int(row['ano'])
                    if year not in [2021,2022,2023]:continue
                    value=int(row['qtd']);month=int(row['mes']);typ=row['tipovisto_tab']
                    totals[year,typ]+=value;months[year,month]+=value;birth[year,row['pais_nasc'],typ]+=value
        groups={'Visita':'visitor','Estudo':'student','Trabalho':'work','Reunião familiar':'family'}
        expected={2021:55896,2022:94525,2023:153715}
        for year,annual in expected.items():
            assert sum(v for (y,t),v in totals.items() if y==year)==annual
            assert sum(v for (y,m),v in months.items() if y==year)==annual
            assert {m for (y,m),v in months.items() if y==year}==set(range(1,13))
            for (y,typ),value in sorted(totals.items()):
                if y!=year:continue
                group=groups.get(typ,'other')
                self.observation(f'bra_{year}_type_'+re.sub(r'[^a-zA-Z0-9]','_',typ),'BRA',year,'visas_issued',value,'visas',None,
                                 f'Base_Tratada_MRE_jan21_abr25.csv; SUM(qtd) WHERE ano={year} AND tipovisto_tab={typ}',group=group,typ=typ,
                                 eligible_money_ledger=False,notes='官方完整自然年签发；仅出生国和签发地可拆，付款国籍未识别。未套用2025费率生成历史金额。')
            self.observation(f'bra_{year}_all_issued_control','BRA',year,'visas_issued',annual,'visas',None,
                             f'Base_Tratada_MRE_jan21_abr25.csv; SUM(qtd) WHERE ano={year}',origin='WORLD',basis='aggregate_control',typ='all_visas',
                             is_aggregate_control=True,eligible_money_ledger=False,
                             notes='分类型年度签发的控制合计；不与类型明细相加。')
            for (y,month),value in sorted(months.items()):
                if y!=year:continue
                self.observation(f'bra_{year}_all_issued_m{month:02d}','BRA',year,'visas_issued',value,'visas',None,
                                 f'Base_Tratada_MRE_jan21_abr25.csv; ano={year},mes={month}; SUM(qtd)',typ='all_visas',
                                 period_start=f'{year}-{month:02d}-01',period_end=f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}',
                                 period_type='calendar_month',eligible_money_ledger=False,
                                 notes='全年签发的月份分解；不能再加到年度签发总计。')
            for group in ['visitor','student','work','family','other']:
                self.coverage.append(dict(destination='BRA',receiver='BRA',year=year,visa_group=group,
                                          status='observed_annual_quantity_historical_fee_gap',source_ids=['amx4_br_sci_history'],
                                          notes='已从原始SCI工作表补齐2021—2023；pais_nasc为出生国，不是国籍。历史免收/互惠费率缺，保留数量而不强加金额。'))
        dump(OUT/'brazil_historical_birth_country_type_cells.json',[
            dict(year=year,birth_country=country,visa_type=typ,quantity=value,
                 origin_basis='country_of_birth_not_nationality',source_id='amx4_br_sci_history',
                 source_locator=f'Base_Tratada_MRE_jan21_abr25.csv; ano={year},pais_nasc={country},tipovisto_tab={typ}; SUM(qtd)',
                 eligible_money_ledger=False)
            for (year,country,typ),value in sorted(birth.items())])

    def finish(self):
        self.coverage.append(dict(destination='ECU',receiver='ECU',year=2024,visa_group='other',collecting_offices=['DZ7'],
                                  status='mixed_services_not_monetized',source_ids=[sid('ecu_zone7_2024.pdf')],
                                  notes='Visas y más servicios含其他服务，未加入收款；与已识别分局不混合。'))
        self.coverage.append(dict(destination='PER',receiver='PER',year=2024,visa_group='other',
                                  status='institutional_account_no_isolated_visa_revenue',source_ids=[sid('per_revenue2024.pdf')],
                                  notes='本次新取得财政原件仅余额/转移总表；不能把部门收入写成签证实收。'))
        for receiver in ['ECU','CHL']:
            prior=[]
            for p in (ROOT/'data/estimates').glob('*flows.json'):
                if p==EST:continue
                obj=json.loads(p.read_text());rows=obj.get('flows',[]) if isinstance(obj,dict) else obj
                prior += [r.get('id') for r in rows if isinstance(r,dict) and r.get('receiver')==receiver]
            assert not prior,(receiver,'would overlap existing receiver scopes',prior[:5])
        source_ids={r['source_id'] for r in self.sources}
        obs_ids={r['observation_id'] for r in self.obs}
        assert len(source_ids)==len(self.sources) and len(obs_ids)==len(self.obs)
        assert all(r['source_id'] in source_ids for r in self.obs)
        assert all(set(r['source_ids'])<=source_ids and set(r['observation_ids'])<=obs_ids for r in self.flows)
        assert len({r['id'] for r in self.flows})==len(self.flows)
        assert all(0<=r['lower']<=r['amount']<=r['upper'] for r in self.flows)
        assert all(r['payer']=='UNK' for r in self.flows if r['receiver']=='ECU')
        assert all(r['amount']==0 and r['payer']=='BOL' for r in self.flows if r['receiver']=='CHL')
        assert len(self.flows)==10
        dump(OUT/'sources.json',self.sources)
        dump(RAW/'download_manifest.json',self.sources)
        dump(OUT/'observations.json',self.obs)
        dump(OUT/'fee_rules.json',self.fees)
        dump(OUT/'coverage.json',self.coverage)
        dump(OUT/'excluded_candidates.json',self.excluded)
        dump(OUT/'retrieval_log.json',[
            dict(url=url,result=result,research_cutoff=ASOF,observations_created=False)
            for url,result in [
                ('https://travel.state.gov/content/dam/visas/Statistics/Non-Immigrant-Statistics/NIVDetailTables/FYs97-24_NIVDetailTable.xlsx','HTTP403 via requests and curl; original not archived'),
                ('https://www.cancilleria.gov.co/sites/default/files/FOTOS2025/notas%20Fondo%20Rotatorio%20MRE%20vigencia%202024.pdf','HTTP403; original not archived'),
                ('https://www.cancilleria.gov.co/sites/default/files/FOTOS2025/Notas%20a%20los%20estados%20financieros%20Fondo%20Rotatorio%20MRE%20vigencia%202025.pdf','HTTP403; original not archived'),
                ('https://catalogo.senacyt.gob.gt/api/3/action/package_show?id=visas','HTTP403; original API response not archived'),
                ('https://www.datos.gob.mx/api/3/action/package_show?id=produccion_visas_rme','HTTP403 via curl; original API response not archived'),
                ('https://www.one.gob.do/datos-y-estadisticas/temas/estadisticas-demograficas/migracion/','HTTP403 via curl; original not archived'),
            ]])
        dump(EST,dict(models=self.models,flows=self.flows,destination_ranges=self.ranges))
        report=dict(research_cutoff=ASOF,source_count=len(self.sources),new_original_pdf_count=8,
                    reused_original_zip_count=1,observation_count=len(self.obs),flow_count=len(self.flows),
                    positive_receipt_flows=8,fee_exempt_flows=2,coverage_rows=len(self.coverage),
                    historical_birth_country_type_cells=len(json.loads((OUT/'brazil_historical_birth_country_type_cells.json').read_text())),
                    years=sorted({r['year'] for r in self.obs}),destinations=sorted({r['destination'] for r in self.obs}),
                    ecuador_observed_office_receipts_USD={str(r['year']):r['amount'] for r in self.ranges if r['receiver']=='ECU'},
                    chile_bolivia_mercosur_visa_fee_exempt_issuances={str(r['year']):r['quantity'] for r in self.flows if r['receiver']=='CHL'},
                    visually_reviewed_receipt_tables=['ecu_zone4_2024.pdf p11','ecu_zone8_2024.pdf p28','ecu_zone8_2025.pdf p32'],
                    validation='Source hashes, PDF signatures, exact receipt rows, monthly-to-annual sums, nationality-table sums, category control totals, source/observation references and receiver-scope nonoverlap passed.')
        dump(OUT/'validation.json',report)
        (OUT/'README.md').write_text('''# Americas expansion v4

Rebuild offline with `.research-venv/bin/python scripts/research_americas_expansion_v4.py`.

Eight new frozen official PDF originals and one reused official Brazil SCI ZIP are registered with SHA-256. This package adds the exact visa-fee collections of specified Ecuador offices in2024–2025; it makes no nationwide extrapolation. Office and visa-service rows are mutually exclusive. Permanent visa fees are distinguished from residence identity cards; cedulación, naturalisation, passports, apostilles and mixed services are excluded. Monthly DZ8 receipts are decompositions of the annual flows, never additional ledger money.

Ecuador changed collection channels: the2025 DZ6 report records suspension of zonal physical visa processing from26November2025 in favour of CESDI. A decline in these office accounts does not establish a national decline. The2025 DZ6 visa-service quantity is4731 in the body and7763 in the consolidated table; both report USD412697.50. Both quantity observations are retained, and no disputed or unmatched quantity becomes the money-flow denominator.

Chile Table5 supplies2022–2025 nationality-by-family-reunification issuances and Table7 nationality-by-Mercosur issuances. These are subsets of temporary residence visas. Table6 contains separate NNA humanitarian applications and issuances; its application rows total166757 while narrative text says166575. No same-year acceptance rate is inferred. The report explicitly describes reciprocal visa-fee exemption for Bolivia Mercosur visas fromSeptember2023. Only the2024/25 Bolivian category is represented by verified zero government-visa-fee flows; other nationalities and residence cards are not assumed free.

Brazil2021–2023 full-year type and monthly series are extracted from the existing SCI original. The separate historical birth-country/type file retains `pais_nasc` as birth country, never nationality. Control totals, monthly decompositions and type cells must not be added together. Current2025 tariffs are not backdated to fabricate historic money.

Peru's newly archived institutional balance/transfer report lacks an isolated visa-fee line and is excluded from money. Ecuador DZ7 `Visas y más servicios` and DZ4 mixed application/transfer/cancellation fees are also retained as exclusions. Official US nationality workbooks, Colombia financial PDFs and Mexico/Guatemala open-data APIs were identified but original retrieval was blocked; they do not generate observations or money here.
''')
        print(json.dumps(report,ensure_ascii=False))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    r=Research();r.archives();r.ecuador();r.chile();r.brazil_history();r.finish()


if __name__=='__main__':main()
