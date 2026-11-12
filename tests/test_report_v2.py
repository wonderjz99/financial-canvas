"""V2 acceptance: unknown issuers, period identity, provenance and offline delivery."""
import copy
import json
import contextlib
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from financial_visualizer.exporting import render_single_html
from financial_visualizer.filing_xbrl import parse_filing
from financial_visualizer.providers import ReportError
from financial_visualizer.report_v2 import VERSION, build_workspace, identify, prepare, select_periods
from financial_visualizer.sec_cache import SecCache, json_validator, read_json, sha, write_json
from scripts.report import main


def inputs(count=6):
    ends = ['2021-08-29', '2022-08-28', '2023-09-03', '2024-09-01', '2025-08-31', '2026-08-30'][-count:]
    starts = {'2021-08-29': '2020-08-31', '2022-08-28': '2021-08-30', '2023-09-03': '2022-08-29',
              '2024-09-01': '2023-09-04', '2025-08-31': '2024-09-02', '2026-08-30': '2025-09-01'}
    rows = [{'form': '10-K', 'reportDate': e, 'filingDate': e[:4] + '-10-01',
             'accessionNumber': '0000123456-' + e[2:4] + '-000001', 'primaryDocument': 'annual.html'} for e in reversed(ends)]
    columns = {k: [r[k] for r in rows] for k in rows[0]}
    submissions = {'cik': '123456', 'name': 'New Issuer', 'tickers': ['NEW'], 'exchanges': ['Nasdaq'],
                   'sic': '3571', 'filings': {'recent': columns, 'files': []}}
    gaap = {}
    amounts = {'Revenues': 1000, 'CostOfRevenue': 600, 'OperatingExpenses': 250, 'OperatingIncomeLoss': 150,
               'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest': 140,
               'IncomeTaxExpenseBenefit': 40, 'NetIncomeLoss': 90, 'ProfitLoss': 100,
               'NetCashProvidedByUsedInOperatingActivities': 120, 'NetCashProvidedByUsedInInvestingActivities': -80,
               'NetCashProvidedByUsedInFinancingActivities': -40,
               'EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents': 0}
    for tag, amount in amounts.items():
        gaap[tag] = {'label': tag, 'units': {'USD': [dict(start=starts[r['reportDate']], end=r['reportDate'], val=amount,
                        accn=r['accessionNumber'], filed=r['filingDate'], form='10-K', fy=int(r['reportDate'][:4]), fp='FY') for r in rows]}}
    points = sorted(set(ends + ['2020-08-30', '2021-08-29', '2022-08-28', '2023-09-03', '2024-09-01', '2025-08-31']))
    for tag, value in {'Assets': 500, 'Liabilities': 300, 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest': 200,
                       'StockholdersEquity': 190, 'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents': 50,
                       'CashAndCashEquivalentsAtCarryingValue': 40}.items():
        gaap[tag] = {'units': {'USD': [dict(end=e, val=value, accn=rows[0]['accessionNumber'], filed=rows[0]['filingDate'], form='10-K', fy=2026, fp='FY') for e in points]}}
    return [{'ticker': 'NEW', 'cik': 123456}], submissions, {'cik': 123456, 'entityName': 'New Issuer', 'facts': {'us-gaap': gaap}}, rows


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tickers, self.submissions, self.raw, self.rows = inputs()

    def prepare(self):
        def get(cache, url, validator):
            if 'company_tickers' in url:
                data = {'fields': ['cik', 'ticker'], 'data': [[123456, 'NEW']]}
            elif 'companyfacts' in url:
                data = self.raw
            else:
                data = self.submissions
            body = json.dumps(data).encode()
            validator(body)
            return body, {'url': url, 'sha256': sha(body), 'version': sha(body), 'retrievedAt': '2026-11-01T00:00:00+00:00', 'mode': 'network'}
        with patch.object(SecCache, 'get', get):
            return Path(prepare('new', data_root=self.root, workspace=self.root / 'run', skip_filings=True)['workspace'])

    def test_unknown_ticker_needs_no_registry_and_build_never_fetches(self):
        workspace = self.prepare()
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
            report, registry, checks = build_workspace(workspace)
            html = render_single_html(report, registry)
        self.assertEqual(report['symbol'], 'NEW')
        self.assertEqual(report['years'], [2022, 2023, 2024, 2025, 2026])
        self.assertEqual(list(registry['issuers']), ['NEW'])
        self.assertEqual(report['periods'][1]['fiscalDays'], 371)
        self.assertIn('window.__FV_OFFLINE__=true', html)
        self.assertNotIn('"NVDA"', html)
        self.assertFalse(any(c['status'] == 'mismatch' for c in checks['checks']))
        # Consolidated net income/equity are not their parent-only counterparts.
        self.assertEqual(report['periods'][0]['metrics']['net_income']['valueDecimal'], '100')
        self.assertEqual(report['periods'][0]['metrics']['equity']['valueDecimal'], '200')

    def test_less_than_five_years_and_true_week_periods(self):
        t, s, raw, rows = inputs(2)
        periods = select_periods(rows, raw['facts']['us-gaap'], 'USD', '2026-11-12')
        self.assertEqual([p['year'] for p in periods], [2025, 2026])
        self.assertEqual(periods[0]['start'], '2024-09-02')
        self.assertEqual(periods[0]['fiscalDays'], 364)

    def test_ambiguous_duration_stops(self):
        facts = self.raw['facts']['us-gaap']
        for tag in ['Revenues', 'NetCashProvidedByUsedInOperatingActivities']:
            value = copy.deepcopy(facts[tag]['units']['USD'][0]);value['start'] = '2025-08-31'
            facts[tag]['units']['USD'].append(value)
        with self.assertRaisesRegex(ReportError, 'full-year'):
            select_periods(self.rows, facts, 'USD', '2026-11-12')

    def test_unsupported_identity_currency_and_accounting_stop(self):
        for change, error in [('financial', 'financial'), ('currency', 'currency'), ('ifrs', 'IFRS'), ('cik', 'identities')]:
            s, raw = copy.deepcopy(self.submissions), copy.deepcopy(self.raw)
            if change == 'financial': s['sic'] = '6022'
            if change == 'currency': raw['facts']['us-gaap']['Assets']['units'] = {'EUR': raw['facts']['us-gaap']['Assets']['units']['USD']}
            if change == 'ifrs': raw['facts']['ifrs-full'] = raw['facts']['us-gaap']
            if change == 'cik': raw['cik'] = 999
            with self.subTest(change=change), self.assertRaisesRegex(ReportError, error):
                identify('NEW', self.tickers, s, raw, self.rows, '2026-11-12')

    def test_missing_cash_is_unknown_not_zero_or_closed_bridge(self):
        del self.raw['facts']['us-gaap']['CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents']
        workspace = self.prepare()
        report, _, _ = build_workspace(workspace)
        p = report['periods'][0]
        self.assertIsNone(p['metrics']['cash_begin'])
        self.assertEqual(p['cash']['status'], 'partial')
        self.assertEqual(p['cash']['steps'], [])
        self.assertEqual(p['metrics']['bs_cash']['valueDecimal'], '40')

    def test_restatement_versions_and_latest_conflict_remain_visible(self):
        tag = self.raw['facts']['us-gaap']['Revenues']
        earlier = copy.deepcopy(tag['units']['USD'][0]);earlier['val'] = 900;earlier['filed'] = '2026-09-01'
        tag['units']['USD'].append(earlier)
        workspace = self.prepare()
        report, _, _ = build_workspace(workspace)
        fact = report['periods'][-1]['metrics']['revenue']
        self.assertTrue(fact['versionValuesChanged'])
        self.assertEqual(fact['valueDecimal'], '1000')
        self.assertEqual(len(fact['versions']), 2)

    def test_conflicting_latest_tags_are_a_gap_not_a_priority_guess(self):
        other = copy.deepcopy(self.raw['facts']['us-gaap']['Revenues'])
        other['units']['USD'][0]['val'] = 800
        self.raw['facts']['us-gaap']['RevenueFromContractWithCustomerExcludingAssessedTax'] = other
        workspace = self.prepare()
        report, _, _ = build_workspace(workspace)
        self.assertIsNone(report['periods'][-1]['metrics']['revenue'])
        self.assertTrue(any(g['key'] == 'revenue' and g['status'] == 'ambiguous_latest_values' for g in report['delivery']['gaps']))

    def test_normalized_and_source_tampering_are_rejected(self):
        workspace = self.prepare()
        path = workspace / 'normalized.json'
        original = path.read_bytes()
        data = read_json(path);data['facts'][0]['fact']['valueDecimal'] = '999999';write_json(path, data)
        with self.assertRaisesRegex(ReportError, 'Normalized'):
            build_workspace(workspace)
        path.write_bytes(original)
        (workspace / 'sources' / 'companyfacts.json').write_text('{}')
        with self.assertRaisesRegex(ReportError, 'hash mismatch'):
            build_workspace(workspace)

    def test_output_requires_explicit_overwrite_and_portable_workspace(self):
        workspace = self.prepare()
        output = self.root / 'out.html'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['build', '--workspace', str(workspace), '--output', str(output)]), 0)
            original = output.read_bytes()
            self.assertEqual(main(['build', '--workspace', str(workspace), '--output', str(output)]), 1)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(main(['build', '--workspace', str(workspace), '--output', str(output), '--overwrite']), 0)
        moved = self.root / 'another-machine' / 'workspace'
        shutil.copytree(workspace, moved)
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network forbidden')):
            report, registry, _ = build_workspace(moved)
            self.assertEqual(render_single_html(report, registry).encode(), original)

    def research(self, workspace):
        body = b'<html><table>Income 100 Adjustment 20 CFO 120</table></html>'
        (workspace / 'evidence.html').write_bytes(body)
        source = {'id': 'official', 'url': 'https://www.sec.gov/Archives/edgar/data/123456/2026/annual.html',
                  'file': 'evidence.html', 'sha256': sha(body), 'cik': '0000123456', 'currency': 'USD',
                  'publishedAt': '2026-10-01', 'retrievedAt': '2026-11-01T00:00:00+00:00'}
        facts = []
        for identity, key, value in [('income', 'net_income', '100'), ('adjust', 'cf_other_adjustment', '20')]:
            facts.append({'id': identity, 'key': key, 'year': 2026, 'start': '2025-09-01', 'end': '2026-08-30',
                          'currency': 'USD', 'scope': 'consolidated', 'unit': 'currency', 'sourceId': 'official',
                          'location': key + ' row, FY2026 column', 'mappingNote': 'Selected from consolidated cashflow statement',
                          'documentValue': value, 'multiplier': '1', 'rawText': value})
        return {'version': VERSION, 'sources': [source], 'facts': facts, 'business': [], 'notes': [],
                'reconciliations': [{'year': 2026, 'facts': ['income', 'adjust'],
                                     'review': {'complete': True, 'rows': ['income', 'adjust'], 'sourceId': 'official', 'location': 'Full CFO table'}}]}

    def test_official_supplement_closes_only_explicit_reviewed_row_set(self):
        workspace = self.prepare()
        data = self.research(workspace)
        write_json(workspace / 'supplements.json', data)
        report, _, _ = build_workspace(workspace)
        self.assertEqual(report['periods'][-1]['reconciliation']['status'], 'eligible')
        self.assertEqual(len(report['periods'][-1]['reconciliation']['steps']), 3)
        income = report['periods'][-1]['metrics']['net_income']
        self.assertIn(income['equivalentFactId'], report['facts'])
        self.assertEqual(report['periods'][0]['reconciliation']['status'], 'partial')

    def test_reconciliation_rejects_subtotals_duplicate_rows_and_missing_review(self):
        workspace = self.prepare()
        for bad in ['total', 'duplicate', 'review', 'conflict', 'multiplier']:
            data = self.research(workspace)
            if bad == 'total': data['facts'][1]['role'] = 'subtotal'
            if bad == 'duplicate': data['reconciliations'][0]['facts'].append('adjust')
            if bad == 'review': data['reconciliations'][0]['review']['complete'] = False
            if bad == 'conflict': data['facts'][0]['documentValue'] = '20';data['facts'][0]['rawText'] = '20'
            if bad == 'multiplier': data['facts'][0]['valueDecimal'] = '1000000'
            write_json(workspace / 'supplements.json', data)
            with self.subTest(bad=bad), self.assertRaises(ReportError): build_workspace(workspace)

    def test_reclassification_note_and_business_total_child_rejection(self):
        workspace = self.prepare()
        data = self.research(workspace);data['reconciliations'] = [];data['facts'] = []
        for identity, amount in [('products', '600'), ('services', '400')]:
            fact = copy.deepcopy(self.research(workspace)['facts'][0])
            fact.update(id=identity, key='business_revenue', name=identity, documentValue=amount, rawText=amount,
                        location=identity, dimensions={'RevenueAxis': identity})
            data['facts'].append(fact)
        body = b'<html><table>products 600 services 400</table></html>'
        (workspace / 'evidence.html').write_bytes(body);data['sources'][0]['sha256'] = sha(body)
        data['business'] = [{'year': 2026, 'dimension': 'revenue_category', 'definition': 'Products and services',
                             'comparableToPrevious': False, 'comparabilityNote': 'Historical category definition changed',
                             'complete': True, 'facts': ['products', 'services']}]
        write_json(workspace / 'supplements.json', data)
        report, _, _ = build_workspace(workspace)
        self.assertFalse(report['periods'][-1]['business']['comparableToPrevious'])
        self.assertEqual(report['periods'][-1]['business']['status'], 'eligible')
        data['facts'][0]['role'] = 'total';write_json(workspace / 'supplements.json', data)
        with self.assertRaisesRegex(ReportError, 'totals'):
            build_workspace(workspace)

    def test_income_formation_requires_review_and_never_adds_total_with_children(self):
        workspace = self.prepare()
        data = self.research(workspace)
        body = b'<html><table>Income 100 Adjustment 20 CFO 120 Nonoperating -10</table></html>'
        (workspace / 'evidence.html').write_bytes(body);data['sources'][0]['sha256'] = sha(body)
        fact = copy.deepcopy(data['facts'][0]);fact.update(id='nonop', key='nonoperating_income', location='Nonoperating row', documentValue='-10', rawText='-10', role='total')
        data['facts'].append(fact)
        data['incomeFormations'] = [{'year': 2026, 'facts': ['nonop'], 'review': {'complete': True, 'sourceId': 'official', 'location': 'Complete nonoperating section', 'rows': ['nonop']}}]
        write_json(workspace / 'supplements.json', data)
        report, _, _ = build_workspace(workspace)
        section = report['periods'][-1]['analysis']['sections'][0]
        self.assertEqual(section['formationChart']['status'], 'eligible')
        self.assertIsNone(report['periods'][0]['analysis']['sections'][0]['formationChart'])
        data['incomeFormations'][0]['review']['complete'] = False;write_json(workspace / 'supplements.json', data)
        with self.assertRaisesRegex(ReportError, 'complete nonoperating'):
            build_workspace(workspace)


class AcquisitionTests(unittest.TestCase):
    def test_failed_refresh_keeps_verified_version_and_corrupt_cache_stops_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = SecCache(directory, 'Test')
            url = 'https://data.sec.gov/test'
            body = b'{"cik":123}'
            response = unittest.mock.MagicMock()
            response.__enter__.return_value = response
            response.status = 200;response.read.return_value = body;response.headers = {}
            with patch('urllib.request.urlopen', return_value=response):
                _, meta = cache.get(url, json_validator(['cik']))
            cache.refresh = True
            with patch('urllib.request.urlopen', side_effect=OSError('network down')):
                saved, old = cache.get(url, json_validator(['cik']))
            self.assertEqual(saved, body)
            self.assertEqual(old['mode'], 'stale_cache')
            self.assertEqual(old['version'], meta['version'])
            self.assertEqual(cache.warnings[-1]['code'], 'refresh_failed_using_cache')
            pointer = Path(directory) / sha(url.encode())
            (pointer / (meta['version'] + '.body')).write_bytes(b'corrupt')
            cache.offline = True
            with self.assertRaisesRegex(ReportError, 'corrupt'):
                cache.get(url, json_validator(['cik']))

    def test_no_cache_network_failure_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory, patch('urllib.request.urlopen', side_effect=OSError('network down')):
            with self.assertRaisesRegex(ReportError, 'no verified cache'):
                SecCache(directory, 'Test').get('https://data.sec.gov/test', json_validator(['cik']))

    def test_inline_xbrl_preserves_scale_context_and_dimensions(self):
        body = b'''<html><xbrli:context id="annual"><xbrli:entity><xbrli:identifier>123456</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2025-09-01</xbrli:startDate><xbrli:endDate>2026-08-30</xbrli:endDate></xbrli:period><xbrldi:explicitMember dimension="x:BusinessAxis">x:Hardware</xbrldi:explicitMember></xbrli:context><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit><ix:nonFraction name="x:HardwareRevenue" contextRef="annual" unitRef="usd" scale="6" format="ixt:num-dot-decimal">1,234</ix:nonFraction></html>'''
        facts, text = parse_filing(body)
        self.assertEqual(facts[0]['valueDecimal'], '1234000000')
        self.assertEqual(facts[0]['dimensions'], {'x:BusinessAxis': 'x:Hardware'})
        self.assertEqual(facts[0]['measures'], ['iso4217:USD'])
        self.assertIn('1,234', text)
