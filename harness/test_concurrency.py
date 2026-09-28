"""Test del parsing SSE, della misura e dell'aggregazione.

Solo le parti con logica: il giro HTTP si valida con lo smoke test reale
contro un server vllm/ds4 (vedi README), non con un mock cerimoniale.
"""

import unittest

import concurrency
from concurrency import aggrega, contenuto_del_chunk, misura, prompt_unico


class TestContenutoDelChunk(unittest.TestCase):
    def test_chunk_con_contenuto(self):
        line = 'data: {"choices":[{"delta":{"content":"ciao"}}]}'
        contenuto, usage = contenuto_del_chunk(line)
        self.assertEqual(contenuto, "ciao")
        self.assertIsNone(usage)

    def test_spazio_dopo_data_opzionale(self):
        # La spec SSE non impone lo spazio: llama.cpp e vari gateway lo
        # omettono, e ignorarli significherebbe un run intero senza contenuti.
        line = 'data:{"choices":[{"delta":{"content":"ciao"}}]}'
        self.assertEqual(contenuto_del_chunk(line)[0], "ciao")

    def test_chunk_solo_ruolo_non_conta_come_primo_token(self):
        line = 'data: {"choices":[{"delta":{"role":"assistant"}}]}'
        contenuto, usage = contenuto_del_chunk(line)
        self.assertIsNone(contenuto)
        self.assertIsNone(usage)

    def test_delta_e_choices_null_espliciti(self):
        # Alcuni shim OpenAI-compatibili chiudono con null espliciti.
        self.assertEqual(contenuto_del_chunk(
            'data: {"choices":[{"delta":null,"finish_reason":"stop"}]}'), (None, None))
        self.assertEqual(contenuto_del_chunk(
            'data: {"choices":null,"usage":{"completion_tokens":3}}')[0], None)

    def test_chunk_finale_con_usage(self):
        line = 'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":3}}'
        contenuto, usage = contenuto_del_chunk(line)
        self.assertIsNone(contenuto)
        self.assertEqual(usage["completion_tokens"], 3)

    def test_done_e_righe_vuote(self):
        self.assertEqual(contenuto_del_chunk("data: [DONE]"), (None, None))
        self.assertEqual(contenuto_del_chunk("data:[DONE]"), (None, None))
        self.assertEqual(contenuto_del_chunk(""), (None, None))
        self.assertEqual(contenuto_del_chunk(": keep-alive"), (None, None))

    def test_json_troncato_ed_errore_in_band_sono_errori(self):
        # Un frame troncato (server morto a meta') o un errore in-band non
        # devono passare per "chunk senza contenuto": la richiesta va marcata.
        with self.assertRaises(ValueError):
            contenuto_del_chunk('data: {"choices":[{"del')
        with self.assertRaises(ValueError):
            contenuto_del_chunk('data: {"error":{"message":"boom"}}')


class TestMisura(unittest.TestCase):
    def chunk(self, testo):
        return f'data: {{"choices":[{{"delta":{{"content":"{testo}"}}}}]}}'

    def test_ttft_e_tok_s_dai_timestamp_di_arrivo(self):
        eventi = [(1.0, self.chunk("a")), (3.0, self.chunk("b")),
                  (3.0, 'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":4}}')]
        r = misura(eventi, t_invio=0.5)
        self.assertEqual(r["ttft_ms"], 500.0)
        self.assertEqual(r["completion_tokens"], 4)
        self.assertEqual(r["conteggio"], "usage")
        # (4-1) token / (3.0-1.0) s
        self.assertEqual(r["tok_s"], 1.5)

    def test_senza_usage_si_contano_i_chunk_e_lo_si_dichiara(self):
        eventi = [(1.0, self.chunk("a")), (2.0, self.chunk("b"))]
        r = misura(eventi, t_invio=0.0)
        self.assertEqual(r["completion_tokens"], 2)
        self.assertEqual(r["conteggio"], "chunk")

    def test_tutto_in_un_chunk_solo_non_divide_per_zero(self):
        # Proxy che bufferizza: usage dice 32 token, ma un solo arrivo.
        eventi = [(1.0, self.chunk("tutto")),
                  (1.0, 'data: {"choices":[],"usage":{"completion_tokens":32}}')]
        self.assertEqual(misura(eventi, t_invio=0.0)["tok_s"], 0.0)

    def test_stream_senza_contenuto_e_un_errore(self):
        with self.assertRaises(ValueError):
            misura([(1.0, 'data: {"choices":[{"delta":{"role":"assistant"}}]}')], 0.0)


class TestAggrega(unittest.TestCase):
    def test_un_livello(self):
        # 2 client partiti insieme: 100 token in 10 s e 50 token in 5 s
        # -> aggregato 150 token / 10 s di finestra = 15 tok/s
        righe = [
            {"livello": 2, "esito": "ok", "ttft_ms": 100.0, "tok_s": 10.0,
             "completion_tokens": 100, "t_invio": 0.0, "t_fine": 10.0},
            {"livello": 2, "esito": "ok", "ttft_ms": 300.0, "tok_s": 10.0,
             "completion_tokens": 50, "t_invio": 0.0, "t_fine": 5.0},
        ]
        (agg,) = aggrega(righe)
        self.assertEqual(agg["livello"], 2)
        self.assertEqual(agg["richieste"], 2)
        self.assertEqual(agg["fallite"], 0)
        self.assertAlmostEqual(agg["tok_s_aggregati"], 15.0)
        self.assertAlmostEqual(agg["tok_s_mediana_per_richiesta"], 10.0)
        # p95 nearest-rank su 2 campioni = il massimo
        self.assertAlmostEqual(agg["ttft_ms_p95"], 300.0)

    def test_livelli_ordinati_e_separati(self):
        righe = [
            {"livello": 4, "esito": "ok", "ttft_ms": 1.0, "tok_s": 1.0,
             "completion_tokens": 1, "t_invio": 0.0, "t_fine": 1.0},
            {"livello": 1, "esito": "ok", "ttft_ms": 2.0, "tok_s": 2.0,
             "completion_tokens": 2, "t_invio": 0.0, "t_fine": 1.0},
        ]
        livelli = [a["livello"] for a in aggrega(righe)]
        self.assertEqual(livelli, [1, 4])

    def test_le_fallite_si_contano_e_non_entrano_nelle_statistiche(self):
        # Un livello 3 con 1 caduta: l'aggregato dice 2 riuscite e 1 fallita,
        # mai "3 client" misurati su 2 sopravvissuti.
        righe = [
            {"livello": 3, "esito": "ok", "ttft_ms": 100.0, "tok_s": 10.0,
             "completion_tokens": 10, "t_invio": 0.0, "t_fine": 1.0},
            {"livello": 3, "esito": "ok", "ttft_ms": 200.0, "tok_s": 10.0,
             "completion_tokens": 10, "t_invio": 0.0, "t_fine": 2.0},
            {"livello": 3, "esito": "errore", "errore": "HTTP 503"},
        ]
        (agg,) = aggrega(righe)
        self.assertEqual(agg["richieste"], 2)
        self.assertEqual(agg["fallite"], 1)

    def test_livello_tutto_fallito_non_sparisce(self):
        (agg,) = aggrega([{"livello": 8, "esito": "errore", "errore": "timeout"}])
        self.assertEqual(agg["fallite"], 1)
        self.assertIsNone(agg["tok_s_aggregati"])


class TestPromptUnico(unittest.TestCase):
    def test_teste_diverse_per_client_e_nonce_di_run(self):
        # Il nonce di run rende i prompt diversi anche fra le >=5 ripetizioni
        # del protocollo: senza, dal secondo run il prefix cache e' caldo.
        a = prompt_unico(2, 0, 150)
        b = prompt_unico(2, 1, 150)
        self.assertNotEqual(a, b)
        self.assertIn(concurrency.RUN_ID, a)

    def test_corpi_eterogenei_da_file(self):
        corpi = ["ordini e fatture", "contratti fornitori"]
        self.assertIn(corpi[0], prompt_unico(2, 0, 150, corpi))
        self.assertIn(corpi[1], prompt_unico(2, 1, 150, corpi))
        self.assertIn(corpi[0], prompt_unico(2, 2, 150, corpi))


if __name__ == "__main__":
    unittest.main()


class TestRagionamentoEKwargs(unittest.TestCase):
    def test_chunk_di_solo_ragionamento_conta_come_token_generato(self):
        # Con --reasoning-parser il ragionamento arriva in
        # delta.reasoning_content: e' il primo token generato e fa TTFT.
        line = 'data: {"choices":[{"delta":{"reasoning_content":"Devo"}}]}'
        self.assertEqual(contenuto_del_chunk(line)[0], "Devo")

    def test_delta_del_chunk_separa_contenuto_ragionamento_e_finish(self):
        from concurrency import delta_del_chunk
        d, _ = delta_del_chunk('data: {"choices":[{"delta":{"reasoning_content":"x"},"finish_reason":null}]}')
        self.assertEqual(d, {"content": "", "reasoning": "x", "finish_reason": None})
        d, _ = delta_del_chunk('data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}')
        self.assertEqual(d, {"content": "ok", "reasoning": "", "finish_reason": "stop"})

    def test_misura_raccoglie_testo_e_finish_reason(self):
        eventi = [(1.0, 'data: {"choices":[{"delta":{"reasoning_content":"pensa "}}]}'),
                  (2.0, 'data: {"choices":[{"delta":{"content":"5"},"finish_reason":"length"}]}'),
                  (2.0, 'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}')]
        r = misura(eventi, t_invio=0.0, raccogli_testo=True)
        self.assertEqual(r["ttft_ms"], 1000.0)
        self.assertEqual(r["testo"], "5")
        self.assertEqual(r["ragionamento"], "pensa ")
        self.assertEqual(r["finish_reason"], "length")

    def test_payload_con_chat_template_kwargs(self):
        from concurrency import payload_chat
        p = payload_chat("m", "ciao", 8, {"enable_thinking": False})
        self.assertEqual(p["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("chat_template_kwargs", payload_chat("m", "ciao", 8, None))


class TestDeltaReasoningVllm(unittest.TestCase):
    def test_campo_reasoning_di_vllm(self):
        # vLLM (>=0.11, reasoning parser qwen3) manda il pensiero in
        # delta.reasoning, SGLang in delta.reasoning_content: entrambi timbrano.
        d, _ = concurrency.delta_del_chunk('data: {"choices":[{"delta":{"reasoning":"x"},"finish_reason":null}]}')
        self.assertEqual(d, {"content": "", "reasoning": "x", "finish_reason": None})
