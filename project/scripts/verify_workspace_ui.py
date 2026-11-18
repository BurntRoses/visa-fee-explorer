#!/usr/bin/env python3
"""Check scope, first-load data, chart camera and inspectors in the real browser."""
import argparse
import json
import math
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


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
            page.wait_for_function("window.VISA_WORKBENCH?.index.meta.ui_version==='4.7.0'")
            state = lambda: page.evaluate('VISA_WORKBENCH.state')
            totals = lambda: page.evaluate('[VISA_WORKBENCH.analysis.total,VISA_WORKBENCH.analysis.globalTotal]')
            initial = state()
            amount, global_amount = totals()
            assert initial['flowScope'] == 'connected' and initial['year'] == 2025 and initial['view'] == 'chord'
            assert len(initial['countries']) > 200 and not initial['flowLight'] and math.isclose(amount, global_amount)
            assert 'countries=all' in page.url
            data_requests = [url for url in requested if '/data/' in url]
            assert [url.rsplit('/', 1)[-1] for url in data_requests] == ['boot-4.7.0.json.gz'], data_requests
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
                assert math.isclose(float(page.locator('[data-view]').first.get_attribute('data-graph-total')), amount)
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
            checks[str(width)] = 'global summary, four chart modes, zoom/drag/reset, draft selection, country, route and sources'
            page.close()
        page = browser.new_page(offline=True, reduced_motion='reduce', accept_downloads=True)
        application = ROOT / 'app/签证这笔钱-离线版.html'
        page.goto(application.as_uri(), wait_until='domcontentloaded')
        page.locator('.viz-main-svg').wait_for()
        assert page.evaluate("VISA_WORKBENCH.state.countries.length>200 && VISA_WORKBENCH.index.meta.ui_version==='4.7.0'")
        page.evaluate("VISA_WORKBENCH.openSources(['spx_ae_tourist_fee'])")
        page.get_by_role('link', name='脱敏归档').wait_for()
        checks['offline'] = 'global view and lazy references under file:// with networking disabled'
    args.report.write_text(json.dumps(checks, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(checks, ensure_ascii=False))


if __name__ == '__main__':
    main()
