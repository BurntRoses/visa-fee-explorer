"""Build the initial chart payload and the optional data used by inspectors."""
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
    datasets['boot'] = {key: value for key, value in index.items() if key not in optional}
    version = index['meta']['ui_version']
    return {
        f'{name}-{version}.json.gz': gzip.compress(
            json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0
        )
        for name, data in datasets.items()
    }
