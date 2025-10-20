from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from assistant_cli.tools import _ddg_html_search
from assistant_cli.tools import tool_crypto_multi_price, tool_crypto_price
from assistant_cli.tools import tool_fx_rate
from assistant_cli.tools import tool_web_get_many

class TestTools(unittest.TestCase):
    @patch("assistant_cli.tools.DDG_SEARCH_AVAILABLE", False)
    @patch("assistant_cli.tools.PLAYWRIGHT_AVAILABLE", True)
    @patch("assistant_cli.tools.sync_playwright")
    def test_ddg_html_search_parsing(self, mock_sync_playwright: MagicMock, *_mocks):
        """
        Testa se _ddg_html_search consegue extrair corretamente os links e títulos
        de uma página HTML simulada do DuckDuckGo.
        """
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_playwright = MagicMock()

        sample_html = """
        <div class="web-result">
            <h2><a href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage1">Resultado 1</a></h2>
            <div class="result__snippet">Snippet 1</div>
        </div>
        <div class="web-result">
            <h2><a href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage2">Resultado 2</a></h2>
            <div class="result__snippet">Snippet 2</div>
        </div>
        """

        mock_page.content.return_value = sample_html
        mock_sync_playwright.return_value.__enter__.return_value = mock_playwright
        mock_playwright.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page

        results = _ddg_html_search("qualquer coisa")

        self.assertEqual(len(results), 2)
        self.assertEqual(
            results[0],
            {"title": "Resultado 1", "url": "https://example.com/page1", "snippet": "Snippet 1"},
        )
        self.assertEqual(
            results[1],
            {"title": "Resultado 2", "url": "https://example.com/page2", "snippet": "Snippet 2"},
        )

        mock_page.content.assert_called_once()

    @patch("assistant_cli.tools.PLAYWRIGHT_AVAILABLE", True)
    @patch("assistant_cli.tools.tool_web_get")
    def test_web_get_many(self, mock_tool_web_get: MagicMock):
        """
        Testa se tool_web_get_many chama a função de busca para cada URL
        e retorna os resultados agregados.
        """
        # Configura o mock para retornar diferentes resultados para cada URL
        mock_tool_web_get.side_effect = [
            {"ok": True, "title": "Página 1", "text": "Conteúdo 1"},
            {"ok": True, "title": "Página 2", "text": "Conteúdo 2"},
            {"ok": False, "error": "Não encontrado"},
        ]

        urls = ["http://example.com/1", "http://example.com/2", "http://example.com/invalid"]
        result = tool_web_get_many({"urls": urls})

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["pages"]), 3)
        self.assertEqual(mock_tool_web_get.call_count, 3)

        # Verifica se os resultados estão corretos (a ordem pode variar devido ao ThreadPool)
        texts = {p.get("text") for p in result["pages"] if p.get("ok")}
        self.assertIn("Conteúdo 1", texts)
        self.assertIn("Conteúdo 2", texts)

    @patch("assistant_cli.tools.PLAYWRIGHT_AVAILABLE", False)
    @patch("assistant_cli.tools.tool_web_get")
    def test_web_get_many_without_playwright(self, mock_tool_web_get: MagicMock):
        """Mesmo sem Playwright, a ferramenta deve continuar funcionando."""
        mock_tool_web_get.side_effect = [
            {"ok": True, "text": "Página A"},
            {"ok": False, "error": "timeout"},
        ]

        result = tool_web_get_many({"urls": ["http://a.com", "http://b.com"]})

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(mock_tool_web_get.call_count, 2)

    @patch("assistant_cli.tools.requests.get")
    def test_crypto_price_success(self, mock_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "bitcoin": {
                "usd": 100.0,
                "usd_24h_change": 2.5,
                "brl": 500.0,
                "brl_24h_change": -1.0,
                "last_updated_at": 1_700_000_000,
            }
        }
        mock_get.return_value = mock_resp

        result = tool_crypto_price({"asset": "bitcoin", "vs_currencies": ["usd", "brl"]})

        self.assertTrue(result["ok"])
        self.assertEqual(result["asset_id"], "bitcoin")
        self.assertAlmostEqual(result["prices"]["usd"], 100.0)
        self.assertEqual(result["changes_24h"]["brl"], -1.0)
        self.assertEqual(result["source"], "https://www.coingecko.com")
        self.assertTrue(result["last_updated_iso"].endswith("Z"))
        self.assertIsNotNone(result.get("last_updated_hours_ago"))
        mock_get.assert_called_once()

    def test_crypto_price_unknown_asset(self):
        result = tool_crypto_price({"asset": "moeda-inexistente"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "asset_desconhecido")

    @patch("assistant_cli.tools.requests.get")
    def test_crypto_multi_price_success(self, mock_get: MagicMock):
        responses = []

        # CoinGecko
        resp1 = MagicMock()
        resp1.raise_for_status.return_value = None
        resp1.json.return_value = {"bitcoin": {"usd": 65000.0, "last_updated_at": 1_700_000_000}}
        responses.append(resp1)

        # Coinbase
        resp2 = MagicMock()
        resp2.raise_for_status.return_value = None
        resp2.json.return_value = {"data": {"amount": "65010.23"}}
        responses.append(resp2)

        # Binance
        resp3 = MagicMock()
        resp3.raise_for_status.return_value = None
        resp3.json.return_value = {"price": "65005.00"}
        responses.append(resp3)

        # Kraken
        resp4 = MagicMock()
        resp4.raise_for_status.return_value = None
        resp4.json.return_value = {"error": [], "result": {"XXBTZUSD": {"c": ["64995.10", "1.0"]}}}
        responses.append(resp4)

        # Bitstamp
        resp5 = MagicMock()
        resp5.raise_for_status.return_value = None
        resp5.json.return_value = {"last": "64990.00", "timestamp": "1700000010"}
        responses.append(resp5)

        mock_get.side_effect = responses

        result = tool_crypto_multi_price({"asset": "btc"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["asset"], "BTC")
        self.assertEqual(len(result["sources"]), 5)
        self.assertIn("Coinbase", result["table"])
        self.assertEqual(mock_get.call_count, 5)

        prices = [row["price"] for row in result["sources"]]
        self.assertTrue(all(isinstance(price, float) for price in prices))

    @patch("assistant_cli.tools.requests.get")
    def test_fx_rate_success(self, mock_get: MagicMock):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "result": 25.0,
            "info": {"rate": 5.0, "timestamp": 1_700_000_000},
            "date": "2025-01-01",
        }
        mock_get.return_value = mock_resp

        result = tool_fx_rate({"base": "USD", "target": "BRL", "amount": 5})

        self.assertTrue(result["ok"])
        self.assertEqual(result["base"], "USD")
        self.assertEqual(result["target"], "BRL")
        self.assertAlmostEqual(result["converted"], 25.0)
        self.assertAlmostEqual(result["rate"], 5.0)
        self.assertTrue(result["last_updated_iso"].endswith("Z"))
        self.assertIsNotNone(result.get("last_updated_hours_ago"))
        self.assertEqual(mock_get.call_count, 1)

    def test_fx_rate_invalid_amount(self):
        result = tool_fx_rate({"base": "USD", "target": "BRL", "amount": -3})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "amount deve ser positivo")
