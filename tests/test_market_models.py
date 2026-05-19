import unittest

from schwab_agent.market import normalize_quote, normalize_stream_equity
from schwab_agent.options_eval import evaluate_calls


class MarketModelTests(unittest.TestCase):
    def test_normalize_quote_prefers_regular_during_regular_session(self):
        data = {
            "quote": {
                "mark": 101,
                "bidPrice": 100.9,
                "askPrice": 101.1,
                "closePrice": 99,
                "netChange": 2,
                "totalVolume": 1234,
            },
            "regular": {"regularMarketLastPrice": 101},
            "extended": {"lastPrice": 98, "tradeTime": 1},
            "reference": {"description": "Example"},
        }
        q = normalize_quote("XYZ", data)
        self.assertEqual(q["symbol"], "XYZ")
        self.assertEqual(q["price"], 101)
        self.assertAlmostEqual(q["spread_pct"], 0.1980198, places=5)

    def test_stream_equity_shape_matches_quote_shape(self):
        q = normalize_stream_equity("XYZ", {
            "LAST_PRICE": 10,
            "BID_PRICE": 9.9,
            "ASK_PRICE": 10.1,
            "CLOSE_PRICE": 8,
            "NET_CHANGE": 2,
        })
        self.assertEqual(q["source"], "schwab-stream")
        self.assertEqual(q["price"], 10)
        self.assertEqual(q["change_pct"], 25)

    def test_options_eval_filters_dte_and_scores_spreads(self):
        chain = {
            "symbol": "XYZ",
            "underlyingPrice": 100,
            "callExpDateMap": {
                "2026-06-18:30": {
                    "100.0": [{"symbol": "C100", "strikePrice": 100, "bid": 9, "ask": 10, "delta": 0.5}],
                    "130.0": [{"symbol": "C130", "strikePrice": 130, "bid": 1, "ask": 2, "delta": 0.2}],
                },
                "2026-06-01:12": {
                    "100.0": [{"symbol": "SHORT", "strikePrice": 100, "bid": 1, "ask": 2}],
                },
            },
        }
        out = evaluate_calls(chain, [30], min_dte=20, max_dte=60)
        self.assertTrue(out["outright_calls"])
        self.assertEqual(out["outright_calls"][0]["expiry"], "2026-06-18")
        self.assertTrue(out["call_spreads"])


if __name__ == "__main__":
    unittest.main()
