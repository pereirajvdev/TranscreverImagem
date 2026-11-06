"""Testes da lógica pura (sem Qt): parser de planilha e ordenação.

Executar na raiz do projeto:
    python -m unittest discover -s tests -p "test_logica.py" -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ordenacao import calcular_slot, indice_destino, reordenar  # noqa: E402
from planilha import analisar_planilha, extrair_colunas  # noqa: E402


class TestPlanilha(unittest.TestCase):
    def test_exemplo_do_enunciado(self):
        texto = (
            "Coluna A\tColuna B\tColuna C\r\n"
            "Texto A1\tTexto B1\tTexto C1\r\n"
            "Texto A2\tTexto B2\tTexto C2\r\n"
            "Texto A3\tTexto B3\tTexto C3\r\n"
        )
        self.assertEqual(extrair_colunas(texto), [
            "Coluna A\nTexto A1\nTexto A2\nTexto A3",
            "Coluna B\nTexto B1\nTexto B2\nTexto B3",
            "Coluna C\nTexto C1\nTexto C2\nTexto C3",
        ])

    def test_celula_vazia_no_meio_nao_desloca(self):
        a, b, c = extrair_colunas("A1\t\tC1\nA2\tB2\tC2\nA3\tB3\tC3")
        self.assertEqual(a, "A1\nA2\nA3")
        self.assertEqual(b, "\nB2\nB3")  # B1 vazio mantém a linha
        self.assertEqual(c, "C1\nC2\nC3")

    def test_celula_vazia_no_inicio_da_linha(self):
        a, b = extrair_colunas("\tB1\nA2\tB2")
        self.assertEqual(a, "\nA2")
        self.assertEqual(b, "B1\nB2")

    def test_celulas_vazias_no_fim_da_coluna_sao_aparadas(self):
        a, b = extrair_colunas("A1\tB1\nA2\t\nA3\t")
        self.assertEqual(a, "A1\nA2\nA3")
        self.assertEqual(b, "B1")

    def test_coluna_totalmente_vazia_nao_gera_nota(self):
        self.assertEqual(
            extrair_colunas("A1\t\tC1\nA2\t\tC2"), ["A1\nA2", "C1\nC2"]
        )

    def test_coluna_so_com_espacos_nao_gera_nota(self):
        self.assertEqual(extrair_colunas("A1\t  \nA2\t "), ["A1\nA2"])

    def test_uma_coluna(self):
        p = analisar_planilha("a\nb\nc\n")
        self.assertEqual(p.colunas, ["a\nb\nc"])
        self.assertEqual(p.linhas, 3)

    def test_uma_unica_celula_com_newline_final_do_excel(self):
        self.assertEqual(extrair_colunas("valor\r\n"), ["valor"])

    def test_quebra_de_linha_interna_entre_aspas(self):
        texto = '"linha 1\nlinha 2"\tB1\r\nA2\tB2\r\n'
        a, b = extrair_colunas(texto)
        self.assertEqual(a, "linha 1\nlinha 2\nA2")
        self.assertEqual(b, "B1\nB2")

    def test_quebra_crlf_interna_vira_lf(self):
        a, = extrair_colunas('"x\r\ny"\r\nz\r\n')
        self.assertEqual(a, "x\ny\nz")

    def test_aspas_duplicadas_viram_aspas_simples(self):
        a, = extrair_colunas('"disse ""oi"""\r\n')
        self.assertEqual(a, 'disse "oi"')

    def test_aspas_no_meio_da_celula_sao_literais(self):
        a, b = extrair_colunas('5" tubo\tB\n')
        self.assertEqual(a, '5" tubo')
        self.assertEqual(b, "B")

    def test_linhas_de_tamanhos_diferentes(self):
        a, b, c = extrair_colunas("A1\tB1\tC1\nA2\nA3\tB3")
        self.assertEqual(a, "A1\nA2\nA3")
        self.assertEqual(b, "B1\n\nB3")
        self.assertEqual(c, "C1")

    def test_linhas_finais_vazias_sao_ignoradas(self):
        p = analisar_planilha("A\tB\n1\t2\n\t\n\n")
        self.assertEqual(p.linhas, 2)
        self.assertEqual(p.colunas, ["A\n1", "B\n2"])

    def test_linha_vazia_no_meio_preserva_alinhamento(self):
        a, b = extrair_colunas("A1\tB1\n\nA3\tB3")
        self.assertEqual(a, "A1\n\nA3")
        self.assertEqual(b, "B1\n\nB3")

    def test_vazio_ou_so_espacos(self):
        for texto in ("", "   ", "\n\n", "\t\t\n"):
            self.assertEqual(analisar_planilha(texto).colunas, [], repr(texto))

    def test_ordem_das_colunas_preservada(self):
        cols = extrair_colunas("\t".join(str(i) for i in range(30)))
        self.assertEqual(cols, [str(i) for i in range(30)])

    def test_aspas_nao_fechadas_nao_perdem_conteudo(self):
        cols = extrair_colunas('"aberta\tB\nC\tD')
        self.assertTrue(cols)
        self.assertIn("aberta", "".join(cols))


class TestOrdenacao(unittest.TestCase):
    def test_slot_pela_posicao_do_cursor(self):
        centros = [100, 300, 500, 700, 900]
        self.assertEqual(calcular_slot(centros, 0), 0)
        self.assertEqual(calcular_slot(centros, 200), 1)
        self.assertEqual(calcular_slot(centros, 400), 2)
        self.assertEqual(calcular_slot(centros, 1200), 5)

    def test_exemplo_do_enunciado_5_entre_2_e_3(self):
        # 1|2|3|4|5, arrasta a 5 (índice 4) para entre 2 e 3 (slot 2)
        self.assertEqual(reordenar([1, 2, 3, 4, 5], 4, 2), [1, 2, 5, 3, 4])

    def test_primeira_para_a_ultima(self):
        self.assertEqual(reordenar([1, 2, 3, 4, 5], 0, 5), [2, 3, 4, 5, 1])

    def test_ultima_para_o_meio(self):
        self.assertEqual(reordenar([1, 2, 3, 4, 5], 4, 2), [1, 2, 5, 3, 4])

    def test_para_o_inicio(self):
        self.assertEqual(reordenar([1, 2, 3, 4, 5], 3, 0), [4, 1, 2, 3, 5])

    def test_soltar_na_propria_posicao_nao_muda(self):
        for i in range(5):
            self.assertEqual(indice_destino(i, i), i)
            self.assertEqual(indice_destino(i, i + 1), i)
            self.assertEqual(reordenar(range(5), i, i), list(range(5)))
            self.assertEqual(reordenar(range(5), i, i + 1), list(range(5)))

    def test_toda_combinacao_preserva_itens(self):
        base = list("abcdef")
        for origem in range(len(base)):
            for slot in range(len(base) + 1):
                novo = reordenar(base, origem, slot)
                self.assertEqual(sorted(novo), sorted(base))
                self.assertEqual(len(novo), len(base))

    def test_o_item_cai_antes_do_vizinho_do_slot(self):
        base = list("abcdef")
        for origem in range(6):
            for slot in range(7):
                novo = reordenar(base, origem, slot)
                item = base[origem]
                restantes = [x for x in base if x != item]
                # posição esperada entre os restantes
                esperado = slot if slot <= origem else slot - 1
                esperado = min(esperado, len(restantes))
                if slot in (origem, origem + 1):
                    esperado = origem
                restantes.insert(esperado, item)
                self.assertEqual(novo, restantes, (origem, slot))

    def test_movimentos_repetidos(self):
        ordem = [1, 2, 3, 4, 5]
        ordem = reordenar(ordem, 4, 2)   # 1 2 5 3 4
        ordem = reordenar(ordem, 0, 5)   # 2 5 3 4 1
        ordem = reordenar(ordem, 3, 0)   # 4 2 5 3 1
        self.assertEqual(ordem, [4, 2, 5, 3, 1])


if __name__ == "__main__":
    unittest.main()
