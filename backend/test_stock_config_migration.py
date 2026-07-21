# -*- coding: utf-8 -*-
import unittest

from monitors.stock_price_monitor import migrate_legacy_config, DEFAULT_ALERTS_CFG


class MigrationTests(unittest.TestCase):
    def test_legacy_stock_with_name_code_gets_full_price_alerts(self):
        legacy = {
            'enabled': True,
            'stocks': [
                {'enabled': True, 'name': '贵州茅台', 'code': '600519', 'keywords': ['茅台']},
            ],
        }
        cfg = migrate_legacy_config(legacy)
        self.assertTrue(cfg['enabled'])
        item = cfg['watchlist'][0]
        self.assertEqual(item['type'], 'name')
        self.assertEqual(item['value'], '贵州茅台')
        self.assertEqual(item['price_alerts'], DEFAULT_ALERTS_CFG)

    def test_new_schema_passes_through(self):
        new = {'enabled': True, 'poll_interval_seconds': 25, 'cooldown_minutes': 30, 'watchlist': []}
        self.assertEqual(migrate_legacy_config(new), new)

    def test_missing_fields_get_defaults(self):
        cfg = migrate_legacy_config({})
        self.assertEqual(cfg['poll_interval_seconds'], 25)
        self.assertEqual(cfg['cooldown_minutes'], 30)
        self.assertEqual(cfg['watchlist'], [])

    def test_keyword_only_entry_has_no_price_alerts(self):
        legacy = {'stocks': [{'enabled': True, 'name': '', 'code': '', 'keywords': ['降息']}]}
        cfg = migrate_legacy_config(legacy)
        item = cfg['watchlist'][0]
        self.assertEqual(item['type'], 'keyword')
        self.assertNotIn('price_alerts', item)


if __name__ == '__main__':
    unittest.main()
