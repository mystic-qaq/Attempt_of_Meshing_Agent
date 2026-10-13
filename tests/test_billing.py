import unittest
from cfdmesh.scientific_advisor import cached_peak_charge,budget_charge,transport_failure_charge,request_price_factor

class BillingTest(unittest.TestCase):
    def test_observed_offpeak_and_peak_crossing_use_safe_rate(self):
        from datetime import datetime,timezone
        def stamp(day,h,m=0):return datetime(2026,10,day,h,m,tzinfo=timezone.utc).timestamp()
        self.assertEqual(request_price_factor(stamp(12,5),stamp(12,5,5)),.5)
        self.assertEqual(request_price_factor(stamp(12,6),stamp(12,6,1)),1.)
        self.assertEqual(request_price_factor(stamp(12,5,59),stamp(12,6,1)),1.)
        self.assertEqual(request_price_factor(stamp(11,6),stamp(11,6,1)),.5)
        self.assertEqual(request_price_factor(stamp(11,23,59),stamp(12,0,1)),1.)
        self.assertEqual(request_price_factor(float('nan'),stamp(12,5)),1.)

    def test_settled_offpeak_receipt_is_not_discounted_again(self):
        usage=dict(prompt_tokens=100000,completion_tokens=1000,prompt_cache_hit_tokens=90000)
        peak=cached_peak_charge(usage)
        state=dict(estimated_usd=peak*.5,requests=[dict(model='deepseek-flash',usage=usage,usd_at_peak_price_ceiling=peak,budget_charge_usd=peak*.5)])
        self.assertAlmostEqual(budget_charge(state),peak*.5)
    def test_dns_not_sent_is_nonbillable_but_timeout_is_uncertain(self):
        import socket,urllib.error
        self.assertEqual(transport_failure_charge(urllib.error.URLError(socket.gaierror(-2,'Name or service not known')),.05),0.)
        self.assertEqual(transport_failure_charge(urllib.error.URLError(socket.timeout('timed out')),.05),.05)
        self.assertEqual(transport_failure_charge(urllib.error.HTTPError('https://example.test',429,'too many requests',{},None),.05),.05)
    def test_cache_charge_and_legacy_pending_reservation(self):
        usage=dict(prompt_tokens=100000,completion_tokens=1000,prompt_cache_hit_tokens=90000,prompt_cache_miss_tokens=10000)
        cached=.00054+.003+.0012
        self.assertAlmostEqual(cached_peak_charge(usage),cached)
        state=dict(estimated_usd=.0812,requests=[dict(model='deepseek-flash',usage=usage,usd_at_peak_price_ceiling=.0312),dict(error='URLError',reserved_usd=.05)])
        self.assertAlmostEqual(budget_charge(state),cached+.05)
        self.assertEqual(state['estimated_usd'],.0812)
        self.assertAlmostEqual(budget_charge(dict(estimated_usd=cached,requests=[dict(model='deepseek-flash',usage=usage,usd_at_peak_price_ceiling=cached)])),cached)

    def test_unknown_cache_and_inconsistent_receipt(self):
        self.assertAlmostEqual(cached_peak_charge(dict(prompt_tokens=1000,completion_tokens=100)),.00042)
        with self.assertRaises(ValueError):cached_peak_charge(dict(prompt_tokens=1000,completion_tokens=100,prompt_cache_hit_tokens=1001))
        with self.assertRaises(ValueError):cached_peak_charge(dict(prompt_tokens=1000,completion_tokens=100,prompt_cache_hit_tokens=500,prompt_cache_miss_tokens=400))
