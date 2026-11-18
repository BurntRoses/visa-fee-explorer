#!/usr/bin/env python3
"""Package the offline reader with every referenced, available source archive."""
from pathlib import Path
import hashlib,json,zipfile
from research_packages import DATA_PACKAGES
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'deliverables';OUT.mkdir(exist_ok=True)
data=json.loads((ROOT/'app/data.json').read_text());manifest=json.loads((ROOT/'app/build-manifest.json').read_text())
files={Path('app/签证这笔钱-离线版.html'),Path('app/build-manifest.json'),Path('data/processed/sources.json'),Path('data/processed/coverage_inventory.json'),Path('docs/前端处方采用.md'),Path('data/research/history/REPORT.md'),Path('data/research/spatial_extension/README.md'),Path('data/research/time_space/README.md'),Path('data/research/history_expansion/README.md'),Path('data/research/spatial_expansion_v2/README.md'),Path('data/research/demographic_context/README.md'),Path('data/research/temporal_expansion_v2/README.md'),Path('data/research/uk_history_v2/README.md'),Path('data/research/africa_expansion_v3/README.md'),Path('data/research/asia_expansion_v3/README.md'),Path('docs/研究结论与模型.md'),Path('docs/数据规范.md')}
files.update(p.relative_to(ROOT) for p in (ROOT/'data/research/evidence_refinement').glob('*/README.md'))
files.update(Path('data/research')/pkg/'README.md' for pkg in DATA_PACKAGES if (ROOT/'data/research'/pkg/'README.md').is_file())
source_archives=set()
for source in data['sources']:
 for path in [source.get('local_path')]+[f.get('path') for f in source.get('files',[]) if isinstance(f,dict)]:
  if path and (ROOT/path).is_file():files.add(Path(path));source_archives.add(Path(path))
files={p for p in files if (ROOT/p).is_file()}
years=sorted({r['year'] for r in data['flows']})
version=data['meta']['version'].rsplit('-',1)[-1]
counts={y:len({r['receiver'] for r in data['flows'] if r['year']==y}) for y in years}
totals={r['year']:r['amount_cny']/1e8 for r in data['flow_meta']['annual_ranges']}
readme=f'''# 签证费用 · 工作台 {version}

解压后打开 app/签证这笔钱-离线版.html。无需安装或联网。

多选国家，切换所选之间／全球往来。支持半透明环形色带、单国加权环形流向、桑基、比较和热图，{years[0]}–{years[-1]}时间轴可播放。环形、单国与桑基的流光默认沿付款方到收款方持续移动，可独立开关；系统减少动态时暂停。申根固定合并，全部签证类别进入同一范围。画布自动适配窗口，可全屏查看；点击连接查看费用和来源，支持SVG、PNG、CSV和完整JSON导出。

本包包含离线程序、证据数据、来源登记、全球覆盖底册和{len(source_archives)}个可用来源归档文件。请保留app与data的相对位置，使归档链接有效。事实摘录与原始文件在来源面板分别标记；原始网站链接需要联网。

全球250个国家／辖区底册，2024金额覆盖{counts[2024]}个收款政府、2025为{counts[2025]}个（原始申根成员计入）。2024已建模中心{totals[2024]:.2f}亿元、2025为{totals[2025]:.2f}亿元人民币。本轮增加印尼、尼泊尔和冈比亚签证费财政实收、塞浦路斯官方财政事实摘录，并用澳大利亚相邻完整财年修订2025桥接。印度补入FY2024/25签证费实收INR14,883,800,000，更新自然年桥接与最近财年水平代理。印尼和尼泊尔全国实收替换同范围旧估算，付款国籍未知额保留未分配。各年来源范围不同，总额按对应范围阅读。国家摘要包含收付、主要往来、匹配数量的每次费用及同年人口折算；人口折算是规模参照。中国港澳台按统计口径分列，名称统一为中国香港、中国澳门、中国台湾。

单国摘要的“签证与出入境”可切换指标、来源国籍或居住地、出境目的地与历史期间，查看真实折线并导出该序列CSV。背景来自WDI、OECD、Eurostat与各国签证、旅游、边境资料，包含最新2026年内已发布期间；主费用时间轴仍为2011–2025。本轮补充哥伦比亚逐月国籍签发、多米尼加领事签发、美国申请与裁决背景、尼泊尔类别与国籍、东欧签发、阿曼旅游签证入境人次和菲律宾季度处理指标，并开放已归档的美日英加核心签证统计。中国“超过／约数”和不完整财年按原始定义显示；旅游签证入境、护照与签证混合收入、限定流程处理量均保留各自口径。

韩国为签证收入预算锚定情景，越南为eVisa数量与费用组合情景，付款国籍均保留未分配。缺失与明确免费分别表示。主账不含ETA等旅行授权及私人服务费。所有原始观测可在工作台导出完整JSON。

工程源代码及离线复算脚本保留在原项目目录。产品无视频或地图。
'''
archive=OUT/f'签证费用流向工作台-{version}-含来源归档.zip';prefix=f'签证费用流向工作台-{version}/'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 z.writestr(prefix+'README.md',readme)
 for path in sorted(files):z.write(ROOT/path,prefix+path.as_posix())
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 assert z.read(prefix+'app/签证这笔钱-离线版.html')==(ROOT/'app/签证这笔钱-离线版.html').read_bytes()
result={'version':data['meta']['version'],'ui_version':manifest['ui_version'],'archive':archive.name,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(files)+1,'source_archives':len(source_archives),'offline_html_sha256':manifest['sha256'],'validation':'ZIP CRC and offline HTML identity verified'}
(OUT/'release-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
