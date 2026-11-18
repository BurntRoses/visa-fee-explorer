"""Split the initial chart, other years and on-demand inspectors."""
from collections import defaultdict
import gzip
import json

DETAILS = {
    'coverage': ('coverage',),
    'profiles': ('countryProfiles', 'countryContext'),
    'references': ('sources', 'models', 'feeRules', 'bills', 'finances'),
}


def workbench_payloads(index):
    optional = {key for keys in DETAILS.values() for key in keys}
    datasets = {name: {k: index[k] for k in keys} for name, keys in DETAILS.items()}
    boot = {key: value for key, value in index.items() if key not in optional | {'records'}}
    by_year = defaultdict(list)
    for record in index['records']:
        by_year[record[0]].append(record)
    years = sorted(by_year)
    latest = years[-1]
    codes = [entity['code'] for entity in index['entities']]
    members = set(index['schengenMembers'])
    def display(i):
        code = codes[i]
        if code.startswith(('UNK', 'RAW_', 'OTHER', 'WORLD', 'TOTAL', 'UNALLOCATED')):
            return 'UNK'
        return 'SCH' if code in members else code
    trend = []
    for year, rows in sorted(by_year.items()):
        total, receivers = 0, set()
        for _, oi, di, _, amount, *_ in rows:
            origin, destination = display(oi), display(di)
            if origin != destination:
                total += amount
                receivers.add(destination)
        trend.append(dict(year=year,total=total,receivers=len(receivers),onlySchengen=receivers=={'SCH'}))
    boot.update(records=by_year[latest], globalTrend=trend, initialYear=latest)
    datasets['boot'] = boot
    for year, rows in by_year.items():
        if year != latest:
            datasets[f'year-{year}'] = rows
    version = index['meta']['ui_version']
    return {
        f'{name}-{version}.json.gz': gzip.compress(
            json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0
        )
        for name, data in datasets.items()
    }
