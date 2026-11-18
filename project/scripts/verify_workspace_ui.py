#!/usr/bin/env python3
"""Check scope, first-load data, chart camera and inspectors in the real browser."""
import argparse
import json
import math
from pathlib import Path
from release_config import UI_VERSION
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

def verify_matrix(page, total):
    graph = page.locator('[data-view="heatmap"]')
    result = graph.evaluate('''g => {
      const axes = name => Array.from(g.querySelectorAll('[data-axis='+name+']'), n=>n.dataset.nodeCode);
      const origin=axes('origin'), destination=axes('destination');
      const cells = Array.from(g.querySelectorAll('[data-origin][data-destination][data-amount]'), n=>{
       const rect=n.querySelector('rect'), text=n.querySelector('text').getBBox();
       return {key:n.dataset.origin+'|'+n.dataset.destination,value:Number(n.dataset.amount),
        square:rect.getAttribute('width')===rect.getAttribute('height'),
        fits:!text.width || (text.x>=rect.x.baseVal.value-0.5 && text.x+text.width<=rect.x.baseVal.value+rect.width.baseVal.value+0.5)};
      });
      return {origin,destination,cells,scale:Number(g.querySelector('[data-scale-max]').dataset.scaleMax)};
    }''')
    assert result['origin'] == result['destination'] and len(result['origin']) > 2
    codes = set(result['origin'])
    assert 'UNK' not in codes
    expected, separate = {}, 0
    for edge in page.evaluate('VISA_WORKBENCH.analysis.edges'):
        origin, destination = edge['origin'], edge['destination']
        if 'UNK' in (origin, destination):
            separate += edge['amount']
        else:
            key = '|'.join(code if code in codes else '__OTHER__' for code in (origin, destination))
            expected[key] = expected.get(key, 0) + edge['amount']
    actual = {cell['key']: cell['value'] for cell in result['cells']}
    assert actual.keys() == expected.keys() and all(math.isclose(value, expected[key]) for key, value in actual.items())
    assert all(cell['square'] for cell in result['cells'])
    assert all(cell['fits'] for cell in result['cells'])
    assert math.isclose(max((v for k, v in expected.items() if '__OTHER__' not in k), default=0), result['scale']) and math.isclose(sum(actual.values()) + separate, total)
    return result['scale']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='Workbench /app/ URL')
    parser.add_argument('--browser', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    checks = {}
    with sync_playwright() as pw:
        path = str(args.browser) if args.browser else None
        browser = pw.chromium.launch(executable_path=path)
        for width in (1440, 390, 320):
            page = browser.new_page(viewport={'width': width, 'height': 845}, reduced_motion='reduce', accept_downloads=True)
            errors, requested = [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requested.append(request.url))
            page.goto(args.url, wait_until='domcontentloaded')
            page.locator('.viz-main-svg').wait_for()
            page.wait_for_function('version=>window.VISA_WORKBENCH?.index.meta.ui_version===version',arg=UI_VERSION)
            state = lambda: page.evaluate('VISA_WORKBENCH.state')
            totals = lambda: page.evaluate('[VISA_WORKBENCH.analysis.total,VISA_WORKBENCH.analysis.globalTotal]')
            initial = state()
            amount, global_amount = totals()
            assert initial['flowScope'] == 'connected' and initial['year'] == 2025 and initial['view'] == 'chord'
            assert len(initial['countries']) > 200 and not initial['flowLight'] and math.isclose(amount, global_amount)
            assert 'countries=all' in page.url
            assert page.evaluate('VISA_WORKBENCH.index.records.every(row=>row[0]===2025)')
            data_requests = [url for url in requested if '/data/' in url]
            assert [url.rsplit('/', 1)[-1] for url in data_requests] == [f'boot-{UI_VERSION}.json.gz'], data_requests
            assert page.evaluate('document.scrollingElement.scrollWidth===innerWidth')
            viewport = page.locator('.plot-viewport')
            if args.screenshots:
                args.screenshots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=args.screenshots / f'global-{width}.png')
            modes = page.get_by_role('group', name='图形', exact=True)
            assert modes.get_by_role('button').count() == 4
            for label, view in [('桑基', 'sankey'), ('比较', 'compare'), ('热图', 'heatmap'), ('环形', 'chord')]:
                modes.get_by_role('button', name=label, exact=True).click()
                page.locator(f'[data-view="{view}"] .viz-main-svg').wait_for()
                assert math.isclose(totals()[0], amount)
                if view == 'heatmap':
                    verify_matrix(page, amount)
                    if args.screenshots:
                        page.screenshot(path=args.screenshots / f'heatmap-{width}.png')
                    page.locator('.unallocated-button').click()
                    panel = page.get_by_role('complementary', name='国籍未分配', exact=True)
                    assert panel.get_by_text('不参与双边矩阵及色阶', exact=False).is_visible()
                    panel.get_by_role('button', name='澳大利亚', exact=False).click()
                    evidence = page.get_by_role('complementary', name='付款国籍未分配 → 澳大利亚', exact=True)
                    evidence.locator('.evidence-card').first.wait_for()
                    evidence.get_by_role('button', name='关闭面板').click()
                    if width == 1440:
                        scale_menu = page.get_by_role('group', name='空间尺度')
                        scale_menu.get_by_role('button', name='大区', exact=True).click()
                        page.locator('[data-axis][data-node-code^="REG_"]').first.wait_for()
                        assert page.locator('[data-axis="origin"]').count() == page.locator('[data-axis="destination"]').count()
                        assert page.locator('[data-axis][data-node-code="UNK"]').count() == 0
                        assert page.locator('.viz-main-svg [data-origin="REG_0"][data-destination="REG_0"]').count() == 1
                        scale_menu.get_by_role('button', name='国家', exact=True).click()
                else:
                    assert math.isclose(float(page.locator('[data-view]').first.get_attribute('data-graph-total')), amount)
                if view == 'compare':
                    page.wait_for_function('VISA_WORKBENCH.analysis.comparisonYear===2024')
                    assert page.evaluate('VISA_WORKBENCH.analysis.previousNodes.length>0')
                    sort = page.get_by_role('group', name='国家对照排序')
                    sort.get_by_role('button', name='付出', exact=True).click()
                    assert sort.get_by_role('button', name='付出', exact=True).get_attribute('aria-current') == 'true'
            if width == 1440:
                page.get_by_role('group',name='年份',exact=True).get_by_role('button',name='2018',exact=True).click()
                page.wait_for_function('VISA_WORKBENCH.state.year===2018 && document.querySelector(".chart-stage").getAttribute("aria-busy")==="false"')
                assert math.isclose(totals()[0],page.evaluate('VISA_WORKBENCH.index.globalTrend.find(y=>y.year===2018).total'))
                page.get_by_role('group',name='年份',exact=True).get_by_role('button',name='2025',exact=True).click()
                page.locator('.viz-main-svg').wait_for()
            page.get_by_role('button', name='放大', exact=True).click()
            assert float(viewport.get_attribute('data-scale')) > 1
            box = viewport.bounding_box()
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.down()
            page.mouse.move(box['x'] + box['width'] / 2 + 38, box['y'] + box['height'] / 2 + 30, steps=5)
            page.mouse.up()
            assert float(viewport.get_attribute('data-x')) > 10 and float(viewport.get_attribute('data-y')) > 10
            assert not page.get_by_role('complementary').count()
            page.get_by_role('button', name='恢复适配').click()
            assert float(viewport.get_attribute('data-scale')) == 1
            page.get_by_role('button', name='自选').click()
            picker = page.get_by_role('complementary', name='选择分析范围')
            region = picker.get_by_role('button', name='按地区筛选')
            region.focus()
            page.keyboard.press('ArrowDown')
            picker.get_by_role('listbox').wait_for()
            if args.screenshots:
                page.screenshot(path=args.screenshots / f'choices-{width}.png')
            page.keyboard.press('ArrowDown')
            page.keyboard.press('Enter')
            assert region.get_attribute('data-value') == '亚洲'
            region.click()
            picker.get_by_role('option', name='所有地区').click()
            region.click()
            picker.get_by_role('listbox').wait_for()
            page.keyboard.press('Escape')
            assert region.get_attribute('aria-expanded') == 'false' and picker.is_visible()
            assert page.locator('select').count() == 0
            picker.get_by_role('textbox', name='搜索国家').fill('CAN')
            picker.get_by_role('button', name='全选本列表').click()
            picker.get_by_role('textbox', name='搜索国家').fill('USA')
            picker.get_by_role('button', name='全选本列表').click()
            assert state()['countries'] == initial['countries']
            panel_box, chart_box = picker.bounding_box(), page.locator('.chart-stage').bounding_box()
            if width > 880:
                assert panel_box['x'] + panel_box['width'] <= chart_box['x']
            else:
                assert panel_box['y'] >= chart_box['y'] + chart_box['height']
            if args.screenshots:
                page.screenshot(path=args.screenshots / f'picker-{width}.png')
            picker.get_by_role('button', name='应用选择').click()
            assert set(state()['countries']) == {'USA', 'CAN'}
            page.get_by_role('button', name='单国', exact=True).click()
            picker = page.get_by_role('complementary', name='选择一个国家／辖区')
            picker.get_by_role('textbox', name='搜索国家').fill('CAN')
            picker.get_by_role('button', name='加拿大 CAN').click()
            assert state()['countries'] == ['CAN'] and state()['view'] == 'single' and state()['flowScope'] == 'connected'
            assert page.get_by_role('group', name='图形', exact=True).count() == 0
            page.get_by_role('group', name='单国往来方向').get_by_role('button', name='收到', exact=True).click()
            if width != 320:
                page.locator('[data-testid="country-summary"] button').click()
                page.get_by_role('button', name='签证与出入境', exact=True).click()
                metric = page.get_by_role('button', name='选择背景指标', exact=True)
                metric.click()
                assert page.get_by_role('listbox', name='选择背景指标').get_by_role('option', selected=True).count() == 1
                page.keyboard.press('Escape')
                partner = page.get_by_role('button', name='选择背景来源', exact=True)
                partner.click()
                search = page.get_by_role('textbox', name='选择背景来源：搜索选项')
                search.fill('CHN')
                if args.screenshots:
                    page.locator('.choice-surface').scroll_into_view_if_needed()
                    page.screenshot(path=args.screenshots / f'country-choices-{width}.png')
                page.get_by_role('listbox', name='选择背景来源').locator('[data-value="CHN"]').click()
                assert partner.get_attribute('data-value') == 'CHN' and page.locator('.context-trend').is_visible()
                page.get_by_role('button', name='关闭面板').click()
            page.get_by_role('button', name='全球', exact=True).click()
            assert math.isclose(totals()[0], amount)
            mark = page.locator('.viz-chord-link[data-origin][data-destination]').filter(visible=True).first
            mark.focus()
            assert page.locator('.viz-tooltip.visible').count() == 1
            status_box, plot_box = page.locator('.viz-tooltip').bounding_box(), viewport.bounding_box()
            assert status_box['y'] >= plot_box['y']+plot_box['height']-1
            page.evaluate("VISA_WORKBENCH.openRoute('IND','USA')")
            route = page.get_by_role('complementary', name='印度 → 美国')
            route.get_by_role('button', name='完整路线 CSV').wait_for()
            if args.screenshots:
                page.screenshot(path=args.screenshots / f'route-{width}.png')
            route.get_by_role('button', name='关闭面板').click()
            page.get_by_role('button', name='打开资料菜单').click()
            page.get_by_role('navigation', name='资料菜单').get_by_role('button', name='来源').click()
            source = page.get_by_role('complementary', name='来源', exact=True)
            source.get_by_role('textbox', name='搜索来源').fill('spx_ae_tourist_fee')
            source.get_by_role('link', name='脱敏归档').wait_for()
            assert page.get_by_role('dialog').count() == 0 and not errors, errors
            checks[str(width)] = 'global summary, four chart modes, directional square heatmap, unallocated fees and sources, choice controls, zoom/drag/reset, country and route'
            page.close()
        page = browser.new_page(offline=True, reduced_motion='reduce', accept_downloads=True)
        application = ROOT / 'app/签证这笔钱-离线版.html'
        page.goto(application.as_uri(), wait_until='domcontentloaded')
        page.locator('.viz-main-svg').wait_for()
        assert page.evaluate('version=>VISA_WORKBENCH.state.countries.length>200 && VISA_WORKBENCH.index.meta.ui_version===version',UI_VERSION)
        page.evaluate("VISA_WORKBENCH.openSources(['spx_ae_tourist_fee'])")
        page.get_by_role('link', name='脱敏归档').wait_for()
        checks['offline'] = 'global view and lazy references under file:// with networking disabled'
        deep = browser.new_page(offline=True, reduced_motion='reduce')
        deep.goto(application.as_uri()+'#countries=all&year=2018&view=compare',wait_until='domcontentloaded')
        deep.wait_for_function('window.VISA_WORKBENCH?.state.year===2018 && window.VISA_WORKBENCH?.analysis.comparisonYear===2017')
        assert deep.locator('.viz-main-svg').count()==1
        checks['offline_history'] = 'opening a shared previous-year view loads its comparison without networking'
    args.report.write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == '__main__':
    main()
