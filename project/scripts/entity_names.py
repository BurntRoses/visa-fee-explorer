"""Chinese product names for statistical jurisdictions; source labels stay verbatim."""
CHINESE_NAMES = {'CHN': '中国大陆', 'HKG': '中国香港', 'MAC': '中国澳门', 'TWN': '中国台湾'}
JURISDICTION_NOTE = '本项目遵循一个中国原则。中国香港、中国澳门、中国台湾是中国的组成部分；图中按原始出入境、护照及收费统计口径分列，均不代表独立国家。CHN对应中国大陆统计口径。国家／地区代码和来源原称仅用于资料关联；申根作为合并统计区域。'

def canonical_name(code, fallback):
    return CHINESE_NAMES.get(code, fallback)
