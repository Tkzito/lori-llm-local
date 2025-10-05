from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch, call

from assistant_cli.agent import Agent


class TestAgentRun(unittest.TestCase):
    def setUp(self):
        # Evita que o construtor da classe Agent tente ler o registro de ferramentas real
        with patch("assistant_cli.agent.tools_registry", return_value={}):
            self.agent = Agent(model="test-model")

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_simple_conversation(self, mock_chat):
        """Testa uma conversa simples sem o uso de ferramentas."""
        mock_chat.return_value = {"message": {"content": "Olá! Como posso ajudar?"}}

        answer = self.agent.run("oi")

        self.assertEqual(answer, "Olá! Como posso ajudar?")
        # Verifica se a mensagem do usuário foi adicionada
        self.assertEqual(self.agent.messages[-2]["role"], "user")
        self.assertEqual(self.agent.messages[-2]["content"], "oi")
        # Verifica se a resposta do assistente foi adicionada
        self.assertEqual(self.agent.messages[-1]["role"], "assistant")
        self.assertEqual(self.agent.messages[-1]["content"], "Olá! Como posso ajudar?")

    @patch("assistant_cli.agent.call_tool")
    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_tool_call(self, mock_chat, mock_call_tool):
        """Testa o fluxo de uma chamada de ferramenta pelo modelo."""
        # 1. Modelo pede para chamar a ferramenta fs.list
        mock_chat.side_effect = [
            {"message": {"content": '<tool_call>{"tool": "fs.list", "args": {"directory": "."}}</tool_call>'}},
            {"message": {"content": "Encontrei 2 arquivos."}},
        ]
        # 2. A ferramenta retorna um resultado
        mock_call_tool.return_value = {"ok": True, "items": ["file1.txt", "file2.txt"]}

        answer = self.agent.run("liste os arquivos")

        self.assertEqual(answer, "Encontrei 2 arquivos.")
        mock_call_tool.assert_called_once_with("fs.list", {"directory": "."})

        # Verifica o histórico de mensagens
        self.assertEqual(self.agent.messages[1]["content"], "liste os arquivos")
        self.assertEqual(self.agent.messages[2]["content"], '<tool_call>{"tool": "fs.list", "args": {"directory": "."}}</tool_call>')
        self.assertIn('<tool_result>{"ok": true, "items": ["file1.txt", "file2.txt"]}</tool_result>', self.agent.messages[3]["content"])
        self.assertEqual(self.agent.messages[4]["content"], "Encontrei 2 arquivos.")

    @patch("assistant_cli.agent.call_tool")
    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_heuristic_shortcut(self, mock_chat, mock_call_tool):
        """Testa uma chamada de ferramenta heurística que tem um atalho para a resposta final."""
        mock_call_tool.return_value = {"ok": True, "texto": "10/10/2025 10:00:00 -03", "tz": "America/Sao_Paulo"}

        answer = self.agent.run("que horas são em são paulo?")

        self.assertEqual(answer, "Data e hora em são paulo: 10/10/2025 10:00:00 -03 (America/Sao_Paulo).")
        mock_call_tool.assert_called_once_with("sys.time", {"location": "são paulo", "verify_online": False})

    @patch("assistant_cli.agent.OllamaClient.chat")
    @patch("assistant_cli.agent.call_tool")
    def test_run_with_price_heuristic(self, mock_call_tool, mock_chat):
        """Testa a heurística para perguntas sobre preços/cotações."""
        mock_call_tool.side_effect = [
            {
                "ok": True,
                "asset": "bitcoin",
                "asset_id": "bitcoin",
                "prices": {"usd": 100.0},
                "changes_24h": {},
                "last_updated_iso": "2025-01-01T00:00:00Z",
            },
            {"ok": True, "results": []},
        ]
        mock_chat.return_value = {"message": {"content": "Busca sem resultados."}}
        self.agent.run("qual é o valor do bitcoin?")

        calls = mock_call_tool.call_args_list
        self.assertEqual(calls[0][0][0], "crypto.price")
        self.assertEqual(calls[0][0][1]["asset"], "bitcoin")
        self.assertIn("web.search", {call[0][0] for call in calls})

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_heuristic_and_main_loop(self, mock_chat):
        """Testa uma heurística que alimenta o loop principal para obter a resposta final."""
        mock_chat.return_value = {"message": {"content": "O valor do dólar é R$ 5,00."}}

        def fake_call_tool(name: str, args: dict | None = None):
            if name == "fx.rate":
                return {
                    "ok": True,
                    "base": args.get("base", "USD") if args else "USD",
                    "target": args.get("target", "BRL") if args else "BRL",
                    "amount": args.get("amount", 1) if args else 1,
                    "rate": 5.0,
                    "converted": 5.0,
                    "last_updated_iso": "2025-01-01T00:00:00Z",
                    "last_updated_hours_ago": 0.5,
                }
            if name == "crypto.price":
                return {
                    "ok": True,
                    "asset": (args or {}).get("asset", "bitcoin"),
                    "asset_id": "bitcoin",
                    "prices": {"usd": 100.0, "brl": 500.0},
                    "changes_24h": {"usd": 1.0, "brl": -0.5},
                    "last_updated_iso": "2025-01-01T00:00:00Z",
                }
            if name == "web.search":
                return {
                    "ok": True,
                    "results": [
                        {"title": "Dólar Hoje", "url": "http://example.com/1", "snippet": "Cotação atual"},
                        {"title": "Mercado", "url": "http://example.com/2", "snippet": "Análise"},
                    ],
                }
            if name == "web.get_many":
                return {
                    "ok": True,
                    "pages": [
                        {"ok": True, "url": "http://example.com/1", "text": "O dólar está R$ 5,00."},
                        {"ok": True, "url": "http://example.com/2", "text": "Previsão estável."},
                    ],
                }
            return {"ok": False, "error": "unexpected tool"}

        with patch("assistant_cli.agent.call_tool", side_effect=fake_call_tool) as mock_call_tool_inner:

            answer = self.agent.run("pesquisa na internet o valor do dolar")
            self.assertEqual(answer, "O valor do dólar é R$ 5,00.")

            # Verifica se a busca foi disparada (a heurística pode ajustar a query internamente)
            search_calls = [c for c in mock_call_tool_inner.call_args_list if c[0][0] == "web.search"]
            self.assertTrue(search_calls, "Nenhuma chamada a web.search foi registrada")
            query_args = search_calls[0][0][1]
            self.assertIn("USD", query_args.get("query", "").upper())
            self.assertEqual(query_args.get("limit"), 3)
            # A heurística agora busca o conteúdo de múltiplos resultados
            mock_call_tool_inner.assert_any_call(
                "web.get_many", {"urls": ["http://example.com/1", "http://example.com/2"]}
            )
            self.assertTrue(any(c[0][0] == "fx.rate" for c in mock_call_tool_inner.call_args_list))

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_user_correction_triggers_refresh(self, mock_chat):
        """A Lori deve refazer consultas quando o usuário aponta divergências."""
        mock_chat.side_effect = [
            {"message": {"content": "Primeira resposta."}},
            {"message": {"content": "Atualizei os dados."}},
        ]

        search_payloads = [
            {"ok": True, "results": [{"title": "Fonte A", "url": "http://example.com/a", "snippet": "A"}]},
            {"ok": True, "results": [{"title": "Fonte B", "url": "http://example.com/b", "snippet": "B"}]},
        ]
        search_index = {"value": 0}
        call_log: list[str] = []

        def fake_call_tool(name: str, args: dict | None = None):
            call_log.append(name)
            if name == "crypto.price":
                return {
                    "ok": True,
                    "asset": "bitcoin",
                    "asset_id": "bitcoin",
                    "prices": {"usd": 100.0, "brl": 500.0},
                    "changes_24h": {"usd": 1.0, "brl": -0.5},
                    "last_updated_iso": "2025-01-01T00:00:00Z",
                }
            if name == "web.search":
                payload = search_payloads[search_index["value"]]
                search_index["value"] += 1
                return payload
            if name == "web.get_many":
                urls = (args or {}).get("urls", [])
                return {
                    "ok": True,
                    "pages": [{"ok": True, "url": url, "text": f"Conteúdo {url}"} for url in urls],
                }
            return {"ok": False, "error": "unexpected"}

        with patch("assistant_cli.agent.call_tool", side_effect=fake_call_tool):
            self.agent.run("qual é o valor do bitcoin?")
            self.agent.run("o valor informado está diferente, verifique novamente")

        self.assertGreaterEqual(call_log.count("crypto.price"), 2)
        self.assertGreaterEqual(call_log.count("web.search"), 2)
        self.assertIn("atualizado", (self.agent._last_search_query or ""))

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_web_search_with_site_hint(self, mock_chat):
        mock_chat.return_value = {"message": {"content": "Ok."}}

        captured_query: dict[str, str] = {}

        def fake_call_tool(name: str, args: dict | None = None):
            if name == "crypto.price":
                return {
                    "ok": True,
                    "asset": (args or {}).get("asset", "bitcoin"),
                    "asset_id": "bitcoin",
                    "prices": {"usd": 100.0},
                    "changes_24h": {"usd": 0.5},
                    "last_updated_iso": "2025-01-01T00:00:00Z",
                }
            if name == "web.search":
                captured_query["query"] = args.get("query")
                return {"ok": True, "results": []}
            return {"ok": True}

        with patch("assistant_cli.agent.call_tool", side_effect=fake_call_tool):
            self.agent.run("pesquise no br.investing.com o valor do btc")

        self.assertIn("site:br.investing.com", captured_query.get("query", ""))

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_fx_heuristic(self, mock_chat):
        mock_chat.return_value = {"message": {"content": "Conversão concluída."}}

        def fake_call_tool(name: str, args: dict | None = None):
            if name == "fx.rate":
                return {
                    "ok": True,
                    "base": args.get("base", "USD"),
                    "target": args.get("target", "BRL"),
                    "amount": args.get("amount", 1),
                    "rate": 5.0,
                    "converted": 25.0,
                    "last_updated_iso": "2025-01-01T00:00:00Z",
                    "last_updated_hours_ago": 1.0,
                }
            if name == "web.search":
                return {"ok": True, "results": []}
            return {"ok": False, "error": "unexpected"}

        with patch("assistant_cli.agent.call_tool", side_effect=fake_call_tool) as mock_call_tool_inner:
            self.agent.run("quanto custa 5 dólares em reais?")

        self.assertEqual(mock_call_tool_inner.call_args_list[0][0][0], "fx.rate")
        self.assertTrue(any(call[0][0] == "web.search" for call in mock_call_tool_inner.call_args_list))
        self.assertEqual(self.agent._last_fx_request, {"base": "USD", "target": "BRL", "amount": 5.0})

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_fx_correction_triggers_refresh(self, mock_chat):
        mock_chat.side_effect = [
            {"message": {"content": "Primeira conversão."}},
            {"message": {"content": "Atualizei com novos dados."}},
        ]

        fx_payloads = [
            {
                "ok": True,
                "base": "USD",
                "target": "BRL",
                "amount": 1,
                "rate": 5.0,
                "converted": 5.0,
                "last_updated_iso": "2025-01-01T00:00:00Z",
                "last_updated_hours_ago": 0.5,
            },
            {
                "ok": True,
                "base": "USD",
                "target": "BRL",
                "amount": 1,
                "rate": 5.1,
                "converted": 5.1,
                "last_updated_iso": "2025-01-01T01:00:00Z",
                "last_updated_hours_ago": 0.2,
            },
        ]
        search_payloads = [
            {"ok": True, "results": [{"title": "Site 1", "url": "http://exemplo.com/1", "snippet": "A"}]},
            {"ok": True, "results": [{"title": "Site 2", "url": "http://exemplo.com/2", "snippet": "B"}]},
        ]

        fx_index = {"value": 0}
        search_index = {"value": 0}

        def fake_call_tool(name: str, args: dict | None = None):
            if name == "fx.rate":
                payload = fx_payloads[fx_index["value"]]
                fx_index["value"] += 1
                return payload
            if name == "web.search":
                payload = search_payloads[search_index["value"]]
                search_index["value"] += 1
                return payload
            if name == "web.get_many":
                urls = (args or {}).get("urls", [])
                return {"ok": True, "pages": [{"ok": True, "url": url, "text": "conteúdo"} for url in urls]}
            return {"ok": False, "error": "unexpected"}

        with patch("assistant_cli.agent.call_tool", side_effect=fake_call_tool):
            self.agent.run("qual é o valor do dólar em reais?")
            self.agent.run("o valor está diferente, atualize")

        self.assertGreaterEqual(fx_index["value"], 2)
        self.assertIn("atualizado", (self.agent._last_search_query or ""))

    @patch("builtins.input", return_value="y")
    @patch("assistant_cli.agent.call_tool")
    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_user_confirmation(self, mock_chat, mock_call_tool, mock_input):
        """Testa o fluxo que exige confirmação do usuário para uma ação."""
        # 1. Modelo pede para escrever fora da raiz
        mock_chat.side_effect = [
            {"message": {"content": '<tool_call>{"tool": "fs.write", "args": {"path": "/etc/hosts", "content": "..."}}</tool_call>'}},
            {"message": {"content": "Arquivo modificado com sucesso."}},
        ]

        # 2. call_tool retorna que a confirmação é necessária
        # 3. Após confirmação, a ferramenta é chamada novamente com __allow_outside_root
        mock_call_tool.side_effect = [
            {"ok": False, "confirm_required": True, "action": "fs.write", "path": "/etc/hosts", "reason": "..."},
            {"ok": True, "path": "/etc/hosts", "bytes": 3},
        ]

        answer = self.agent.run("modifique o /etc/hosts")
        self.assertEqual(answer, "Arquivo modificado com sucesso.")

        self.assertEqual(mock_call_tool.call_count, 2)
        # Primeira chamada, sem a flag de permissão
        mock_call_tool.assert_any_call("fs.write", {"path": "/etc/hosts", "content": "..."})
        # Segunda chamada, com a flag de permissão
        mock_call_tool.assert_any_call("fs.write", {"path": "/etc/hosts", "content": "...", "__allow_outside_root": True})
        mock_input.assert_called_once()

    @patch("assistant_cli.agent.call_tool")
    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_tool_error_and_self_correction(self, mock_chat, mock_call_tool):
        """Testa o fluxo de autocorreção do modelo após um erro de ferramenta."""
        # 1. Modelo chama a ferramenta com args errados
        mock_chat.side_effect = [
            {"message": {"content": '<tool_call>{"tool": "fs.read", "args": {"path": "nao_existe.txt"}}</tool_call>'}},
            # 3. Modelo tenta de novo com args corretos
            {"message": {"content": '<tool_call>{"tool": "fs.read", "args": {"path": "existe.txt"}}</tool_call>'}},
            # 5. Modelo resume o resultado
            {"message": {"content": "O conteúdo é: olá."}},
        ]
        # 2. Ferramenta retorna erro
        # 4. Ferramenta retorna sucesso
        mock_call_tool.side_effect = [
            {"ok": False, "error": "file not found"},
            {"ok": True, "content": "olá"},
        ]

        answer = self.agent.run("leia o arquivo")

        self.assertEqual(answer, "O conteúdo é: olá.")
        self.assertEqual(mock_call_tool.call_count, 2)
        mock_call_tool.assert_any_call("fs.read", {"path": "nao_existe.txt"})
        mock_call_tool.assert_any_call("fs.read", {"path": "existe.txt"})

        # Verifica se a mensagem de erro foi enviada para o modelo
        self.assertIn("Erro: A chamada da ferramenta falhou: file not found", self.agent.messages[3]["content"])

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_no_tool_call_and_nudging(self, mock_chat):
        """Testa o 'empurrão' no modelo quando uma chamada de ferramenta era esperada."""
        mock_chat.side_effect = [
            {"message": {"content": "Claro, aqui está o conteúdo."}},  # Resposta sem tool_call
            {"message": {"content": 'Ah, desculpe. <tool_call>{"tool": "fs.read", "args": {"path": "a.txt"}}</tool_call>'}},
            # Chamada final após o resultado da ferramenta
            {"message": {"content": "Finalizado."}},
        ]

        with patch("assistant_cli.agent.call_tool", return_value={"ok": True, "content": "..."}):
            answer = self.agent.run("leia o arquivo a.txt")

        self.assertEqual(answer, "Finalizado.")
        # Verifica se a mensagem de incentivo foi enviada
        self.assertIn("Use estritamente a sintaxe <tool_call>", self.agent.messages[3]["content"])

    @patch("builtins.input", return_value="n")
    @patch("assistant_cli.agent.call_tool")
    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_with_user_denial(self, mock_chat, mock_call_tool, mock_input):
        """Testa o fluxo quando o usuário nega uma ação que requer confirmação."""
        mock_chat.side_effect = [
            {"message": {"content": '<tool_call>{"tool": "fs.write", "args": {"path": "/root/file", "content": "..."}}</tool_call>'}},
            {"message": {"content": "Ok, a ação foi cancelada pelo usuário."}},
        ]
        mock_call_tool.return_value = {"ok": False, "confirm_required": True, "reason": "write outside root"}

        answer = self.agent.run("escreva em /root/file")
        self.assertEqual(answer, "Ok, a ação foi cancelada pelo usuário.")

        # A ferramenta é chamada uma vez, mas não é chamada novamente com a flag de permissão
        mock_call_tool.assert_called_once_with("fs.write", {"path": "/root/file", "content": "..."})
        mock_input.assert_called_once()

        # Verifica se o resultado da negação do usuário foi adicionado ao histórico
        self.assertIn('<tool_result>{"ok": false, "error": "user_denied"}</tool_result>', self.agent.messages[-2]["content"])

    @patch("assistant_cli.agent.OllamaClient.chat")
    def test_run_max_retries_no_tool_call(self, mock_chat):
        """Testa o comportamento quando o modelo esgota as tentativas de chamar uma ferramenta."""
        # Modelo responde com texto simples repetidamente
        mock_chat.return_value = {"message": {"content": "Não consigo usar a ferramenta."}}

        answer = self.agent.run("use uma ferramenta")
        self.assertEqual(answer, "Não consigo usar a ferramenta.")
        self.assertEqual(mock_chat.call_count, 3) # 1 chamada inicial + 2 retentativas


if __name__ == "__main__":
    unittest.main()
