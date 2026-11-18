"""Browser checks for the two-sided ledger and its drill-down views."""
from pathlib import Path
from playwright.sync_api import sync_playwright
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/validation'
OUT.mkdir(exist_ok=True)
EXE = str(Path.home() / 'Library/Caches/ms-playwright/chromium-1254/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing')
checks, errors = [], []


def ck(label, passed, detail=''):
    checks.append({'check': label, 'passed': bool(passed), 'detail': detail})
    if not passed:
        print('FAIL', label, detail)


def view(page, key):
    page.locator(f'[data-view="{key}"]').click()
    page.wait_for_function('(key) => !document.getElementById(key).hidden', arg=key)


def watch(page):
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)


def compact_route_checks(page):
    """Verify the large route drawer without rechecking unrelated views."""
    page.evaluate("VISA_APP.openRoute('CHN','USA')")
    expected = page.evaluate("""() => {const r=VISA_APP.pairRows('CHN','USA');return {count:r.length,amount:VISA_APP.aggregate(r).amount};}""")
    cards = page.locator('#route-content .component-card')
    visible = page.locator('#route-content .component-card:visible')
    ck('compact route initially shows 12 collapsed of 50', expected['count'] == 50 and cards.count() == 50 and visible.count() == 12 and page.locator('#route-content .component-card[open]').count() == 0, {'modelRows': expected['count'], 'visibleCards': visible.count()})
    total_before = page.locator('.route-total-box > strong').inner_text()
    first = visible.first
    first.locator(':scope > summary').click()
    ck('compact route summary exposes quantity and parameters', first.locator('dl').is_visible() and '数量' in first.locator('dl').inner_text() and first.locator('.model-parameters summary').is_visible())
    first.locator('.model-parameters summary').click()
    ck('compact route parameter details expand', first.locator('.model-parameters pre').is_visible())
    first.locator(':scope > .text-link').click()
    ck('compact route expanded item opens nested sources', page.locator('#source-drawer').evaluate('(e)=>e.open') and page.locator('#route-drawer').evaluate('(e)=>e.open') and page.locator('#source-list .source-item').count() > 0)
    page.locator('#close-sources').click()
    ck('compact route remains open after nested source closes', page.locator('#route-drawer').evaluate('(e)=>e.open') and page.evaluate("document.body.style.overflow==='hidden'"))
    search = page.locator('input[aria-label="搜索路线费用分项"]')
    search.fill('F1')
    matches = page.locator('#route-content .component-card:visible')
    ck('compact route F1 search finds matching visa class', matches.count() > 0 and matches.evaluate_all("cards=>cards.every(c=>c.dataset.search.includes('f1'))"), {'visibleMatches': matches.count(), 'labels': matches.locator(':scope > summary h4').all_text_contents()})
    search.fill('')
    page.locator('.component-more').click()
    ck('compact route load more reveals 24 of 50', visible.count() == 24 and '24 / 50' in page.locator('.component-count').inner_text(), {'visibleCards': visible.count()})
    ck('compact route total unchanged by expansion or search', page.locator('.route-total-box > strong').inner_text() == total_before)
    with page.expect_download() as downloaded:
        page.locator('.route-actions button').filter(has_text='下载路线 CSV').click()
    download = downloaded.value
    target = OUT / 'r2-compact-route-china-usa.csv'
    download.save_as(target)
    with target.open(encoding='utf-8-sig', newline='') as source:
        exported = list(csv.DictReader(source))
    amount = sum(float(row.get('amount_cny') or 0) for row in exported)
    ck('compact route CSV preserves all 50 rows and total', len(exported) == expected['count'] and all(row['origin'] == 'CHN' and row['destination'] == 'USA' for row in exported) and abs(amount - expected['amount']) < 1, {'rows': len(exported), 'amountCny': amount})
    page.locator('#close-route').click()


if '--compact-routes-only' in sys.argv:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=EXE)
        context = browser.new_context(accept_downloads=True, reduced_motion='reduce', viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        watch(page)
        try:
            page.goto('http://127.0.0.1:18765/app/')
            page.wait_for_function('!!window.VISA_APP')
            compact_route_checks(page)
            offline = context.new_page()
            watch(offline)
            offline.goto((ROOT / 'app/签证这笔钱-离线版.html').as_uri())
            offline.wait_for_function('!!window.VISA_APP')
            offline.evaluate("VISA_APP.openRoute('CHN','USA')")
            ck('compact route offline reader uses collapsed 12-row view', offline.locator('#route-content .component-card:visible').count() == 12 and offline.locator('#route-content .component-card[open]').count() == 0)
        except Exception as error:
            errors.append(str(error))
            ck('compact route targeted run completed', False, str(error))
        ck('compact route no browser errors', not errors, errors[:5])
        previous = json.loads((OUT / 'app-browser-checks-r2.json').read_text())
        retained = [check for check in previous.get('checks', []) if not check['check'].startswith('compact route')]
        combined = retained + checks
        result = {**previous, 'checks': combined, 'errors': previous.get('errors', []) + errors,
                  'passed': all(check['passed'] for check in combined) and not previous.get('errors') and not errors,
                  'incremental_validation': {'scope': 'compact route drawer and offline copy', 'prior_checks_reused': len(retained), 'targeted_checks': len(checks)}}
        for filename in ['app-browser-checks-r2.json', 'app-acceptance.json']:
            (OUT / filename).write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({'passed': result['passed'], 'prior_checks_reused': len(retained), 'targeted_checks': len(checks), 'failed': [check for check in checks if not check['passed']], 'errors': errors}, ensure_ascii=False))
        browser.close()
        raise SystemExit(0 if result['passed'] else 1)


GEOMETRY = """() => {
  const width = innerWidth;
  const outside = [...document.body.querySelectorAll('*')].filter(e => {
    if (!e.getClientRects().length || e.closest('dialog:not([open])') || e.classList.contains('skip-link')) return false;
    // These contain intentional horizontal scrolling. Their outer frame is still checked.
    if(e.parentElement?.closest('.matrix-scroll,.table-scroll,.category-tabs,.country-shortcuts'))return false;
    const r=e.getBoundingClientRect();
    return r.width>0 && (r.left < -1 || r.right > width+1);
  }).slice(0,8).map(e=>({tag:e.tagName,cls:e.className,id:e.id,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}));
  const clipped=[...document.querySelectorAll('.balance-value,.flow-item-value,.rank-value')].filter(e=>e.getClientRects().length && e.scrollWidth>e.clientWidth+1).map(e=>e.textContent);
  return {width,scroll:document.documentElement.scrollWidth,outside,clipped,bodyOverflow:getComputedStyle(document.body).overflowX};
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, executable_path=EXE)
    context = browser.new_context(accept_downloads=True, reduced_motion='reduce', viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    watch(page)
    try:
        page.goto('http://127.0.0.1:18765/app/')
        page.wait_for_function('!!window.VISA_APP')
        ck('data version r2', page.locator('#version-label').inner_text().startswith('2026.11.15-r2'))
        ck('two ledger sides with no repeated center', page.locator('#country-flow .flow-side').count() == 2 and page.locator('.flow-center,#hero-incoming,#hero-outgoing').count() == 0)
        ck('China received paid and net', page.locator('#balance-cards .balance-card').count() == 3 and all(value in page.locator('#balance-cards').inner_text() for value in ['17.42亿元', '59.84亿元', '-42.42亿元', '方向未确定']))
        ratio = page.evaluate("""() => { const b=VISA_APP.countryBalance('CHN'),bars=[...document.querySelectorAll('.balance-track i')].map(e=>parseFloat(e.style.width));return {bars,expected:b.incoming.amount/b.outgoing.amount}; }""")
        ck('received and paid share one amount scale', abs(ratio['bars'][0] / ratio['bars'][1] - ratio['expected']) < .00001, ratio)
        ck('unallocated source explained beside inflow', '不计入任何具体国家的付出' in page.locator('.incoming .allocation-note').inner_text())
        ck('no video entry', page.locator('video,a[href*="media/"],a[href$=".mp4"]').count() == 0)

        # Each side's full list must remain one direction, including exported raw member attribution.
        for direction, endpoint in [('incoming', 'destination'), ('outgoing', 'origin')]:
            page.locator(f'.flow-side.{direction} .flow-side-foot button').click()
            detail = page.evaluate("""(endpoint) => {const rows=VISA_APP.filteredRows();return {filter:VISA_APP.state.directionFilter,count:rows.length,correct:rows.every(r=>r[endpoint]==='CHN'),sum:rows.reduce((s,r)=>s+(r.amount_cny||0),0)};}""", endpoint)
            ck(f'China complete {direction} routes stay directional', detail['correct'] and detail['count'] > 0 and detail['filter'] == {'country': 'CHN', 'direction': direction} and page.locator('#data').is_visible(), detail)
            ck(f'{direction} pagination stays compact', page.locator('#data-table tbody tr').count() <= 12)
        with page.expect_download() as downloaded:
            page.locator('#download-filtered').click()
        download = downloaded.value
        target = OUT / 'r2-directional-china-outgoing.csv'
        download.save_as(target)
        with target.open(encoding='utf-8-sig', newline='') as source:
            rows = list(csv.DictReader(source))
        ck('directional CSV contains only China payer', len(rows) == 152 and all(row['origin'] == 'CHN' for row in rows), {'rows': len(rows)})
        page.locator('#direction-filter').click()
        ck('direction chip clears filter', page.evaluate('VISA_APP.state.directionFilter === null') and page.locator('#direction-filter').count() == 0)

        # Global rankings aggregate Schengen once while the matrix can expose members.
        view(page, 'global')
        page.wait_for_selector('#global-network .network-flow-svg')
        network = page.evaluate("""() => {const h=document.getElementById('global-network'),r=[...h.querySelectorAll('.network-ribbon')];return {total:Number(h.dataset.total),sources:Number(h.dataset.sourceTotal),destinations:Number(h.dataset.destinationTotal),ribbonSum:r.reduce((s,p)=>s+Number(p.dataset.amount),0),ribbons:r.length,expected:VISA_APP.globalAggregate(VISA_APP.current()).amount};}""")
        ck('global network conserves money across both sides', network['ribbons'] > 1 and all(abs(network[key] - network['expected']) < max(1, network['expected'] * 1e-10) for key in ['total', 'sources', 'destinations', 'ribbonSum']), network)
        ranking = page.locator('#incoming-rank .rank-name').all_text_contents()
        ck('Schengen appears once in received ranking', sum('申根' in label for label in ranking) == 1 and not any(label in ['法国', '德国', '意大利', '西班牙'] for label in ranking), ranking)
        page.locator('[data-year="2025"]').click()
        ck('year switches amounts and context', '2025' in page.locator('#country-subtitle').inner_text() and '61.76亿元' in page.locator('#balance-cards').inner_text())
        page.locator('[data-category="visitor"]').click()
        ck('category switches', page.evaluate("VISA_APP.current().every(r=>r.visa_group==='visitor')") and '访客' in page.locator('#country-subtitle').inner_text())
        page.locator('[data-category="all"]').click()
        for code, label in [('USA', '美国'), ('IND', '印度')]:
            page.select_option('#country-select', code)
            ck(f'{code} country switch', label in page.locator('#country-title-name').inner_text() and page.locator('#country-flow .flow-side').count() == 2)
        page.select_option('#country-select', 'KOR')
        ck('missing Korea receipts remain unknown', page.evaluate("VISA_APP.countryBalance('KOR').incoming.amount === null") and '未识别' in page.locator('.balance-card.incoming').inner_text())
        page.select_option('#country-select', 'SCH')
        ck('Schengen scope names missing long stays', '长期签证未建模' in page.locator('#country-scope').inner_text())
        page.evaluate("VISA_APP.openDirection('SCH','incoming')")
        schengen = page.evaluate("""() => {const members=new Set(VISA_DATA.flow_meta.schengen_members),r=VISA_APP.filteredRows();return {count:r.length,correct:r.every(x=>members.has(x.destination)&&!members.has(x.origin))};}""")
        ck('Schengen direction keeps original member receivers', schengen['count'] > 0 and schengen['correct'], schengen)
        page.select_option('#country-select', 'CHN')
        ck('country switch clears stale direction filter', page.evaluate('VISA_APP.state.directionFilter===null'))
        page.locator('[data-year="2024"]').click()
        free = page.evaluate("""() => { const r=VISA_APP.pairRows('CHN','THA');return {count:r.length,amount:VISA_APP.aggregate(r).amount}; }""")
        ck('known free China Thailand differs from missing', free['count'] > 0 and free['amount'] == 0, free)

        view(page, 'bilateral')
        page.select_option('#bilateral-a', 'CHN')
        page.select_option('#bilateral-b', 'USA')
        ck('bilateral has both directions', page.locator('.bilateral-card').count() == 2 and '→' in page.locator('#bilateral-content').inner_text())
        page.locator('#swap-bilateral').click()
        ck('bilateral swap', page.input_value('#bilateral-a') == 'USA' and page.input_value('#bilateral-b') == 'CHN')
        view(page, 'matrix')
        page.select_option('#matrix-scope', 'major')
        ck('common matrix includes aggregated Schengen', '申根整体' in page.locator('#matrix-table thead').inner_text() and page.locator('#matrix-table tbody tr').count() >= 5)
        page.select_option('#matrix-scope', 'all')
        header = page.locator('#matrix-table thead').inner_text()
        ck('full matrix has members without duplicate region', '列支敦士登' in header and '申根整体' not in header)
        page.select_option('#matrix-scope', 'major')
        page.locator('#tab-matrix').focus()
        page.keyboard.press('End')
        ck('tabs End opens data', page.locator('#data').is_visible() and page.locator('#tab-data').get_attribute('aria-selected') == 'true')
        page.keyboard.press('Home')
        ck('tabs Home opens global', page.locator('#global').is_visible() and page.locator('#tab-global').get_attribute('aria-selected') == 'true')

        compact_route_checks(page)
        page.locator('#country-flow .flow-item').first.click()
        ck('route drawer exposes parameters', page.locator('#route-drawer').evaluate('(e)=>e.open') and page.locator('.model-parameters').count() > 0)
        page.locator('#route-content .component-card .text-link').first.click()
        ck('route source opens evidence library', page.locator('#source-drawer').evaluate('(e)=>e.open') and page.locator('#source-list .source-item').count() > 0)
        page.locator('#close-sources').click()
        page.locator('#close-route').click()
        view(page, 'data')
        for selector, suffix in [('#download-json', '.json'), ('#download-flows', '.csv'), ('#download-balances', '.csv')]:
            with page.expect_download() as downloaded:
                page.locator(selector).click()
            download = downloaded.value
            target = OUT / ('r2-' + download.suggested_filename)
            download.save_as(target)
            ck(selector + ' download', target.stat().st_size > 100 and download.suggested_filename.endswith(suffix), {'bytes': target.stat().st_size})

        # Measure actual geometry in each view. No root overflow hiding can mask it.
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size({'width': width, 'height': 1000 if width >= 768 else 844})
            problems = {}
            for key in ['global', 'bilateral', 'matrix', 'data']:
                page.evaluate('(key)=>VISA_APP.showView(key)', key)
                geometry = page.evaluate(GEOMETRY)
                if geometry['scroll'] > width or geometry['outside'] or geometry['clipped'] or geometry['bodyOverflow'] == 'hidden':
                    problems[key] = geometry
            ck(f'{width}px visible layout stays within frame', not problems, problems)
        ck('mobile detail table becomes cards', page.locator('#data-table').evaluate("e=>getComputedStyle(e).display==='block'"))

        # The downloadable single-file reader must carry the final navigation and direction API.
        offline = context.new_page()
        watch(offline)
        offline.goto((ROOT / 'app/签证这笔钱-离线版.html').as_uri())
        offline.wait_for_function('!!window.VISA_APP')
        offline.evaluate("VISA_APP.openDirection('CHN','outgoing')")
        ck('offline final ledger and directional view load', offline.locator('#country-flow .flow-side').count() == 2 and offline.locator('#data').is_visible() and offline.evaluate("VISA_APP.filteredRows().every(r=>r.origin==='CHN')"))
    except Exception as error:
        errors.append(str(error))
        ck('browser run completed', False, str(error))
    ck('no browser errors', not errors, errors[:5])
    result = {'version': '2026.11.15-r2', 'passed': all(check['passed'] for check in checks) and not errors, 'checks': checks, 'errors': errors, 'browser': browser.version}
    (OUT / 'app-browser-checks-r2.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'passed': result['passed'], 'checks': len(checks), 'failed': [check for check in checks if not check['passed']], 'errors': errors}, ensure_ascii=False))
    browser.close()
    raise SystemExit(0 if result['passed'] else 1)
