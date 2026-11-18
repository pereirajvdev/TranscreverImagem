"""Testes de integração da interface (precisam de PySide6 e das
dependências do projeto: pytesseract, opencv, numpy, Pillow).

    python -m unittest discover -s tests -p "test_interface.py" -v

Rodam em modo offscreen (sem abrir janelas). Cobrem a lógica das três
mecânicas; arrastar com o mouse real e o hover sobre o X precisam de
teste manual (ver README da entrega).
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main as app_main  # noqa: E402
from planilha import analisar_planilha  # noqa: E402

_app = QApplication.instance() or QApplication([])


class Base(unittest.TestCase):
    def setUp(self):
        self.j = app_main.JanelaPrincipal()
        self.j.resize(1200, 750)
        self.j.show()
        _app.processEvents()

    def tearDown(self):
        self.j.close()
        _app.processEvents()

    def criar(self, quantas):
        for _ in range(quantas):
            self.j.adicionar_nota()
        _app.processEvents()

    def ordem(self):
        return [n.numero for n in self.j.notas]

    def ordem_visual(self):
        layout = self.j.layout_notas
        itens = [layout.itemAt(i).widget() for i in range(layout.count())]
        return [
            w.numero for w in itens if isinstance(w, app_main.NotaWidget)
        ]

    def geometrias(self):
        return {n.numero: n.geometry() for n in self.j.notas}

    def texto(self, nota):
        return nota.editor.editor_texto.toPlainText()


class TestFechamento(Base):
    def test_espaco_reservado_ate_liberar(self):
        self.criar(2)  # notas 1, 2, 3
        antes = self.geometrias()
        meio = self.j.notas[1]

        self.j.remover_nota(meio, manter_vaga=True)
        _app.processEvents()

        self.assertEqual(len(self.j._vagas), 1)
        depois = self.geometrias()
        self.assertEqual(depois[1], antes[1])
        self.assertEqual(depois[3], antes[3])

        # Cursor saiu do X: o espaço é recalculado.
        self.j._colapsar_vagas()
        _app.processEvents()

        self.assertEqual(len(self.j._vagas), 0)
        self.assertGreater(
            self.geometrias()[1].width(), antes[1].width()
        )

    def test_sem_mouse_sobre_o_x_nao_reserva(self):
        self.criar(1)
        self.j.remover_nota(self.j.notas[0])  # underMouse() é False
        _app.processEvents()
        self.assertEqual(len(self.j._vagas), 0)

    def test_ultima_nota_nao_reserva_e_cria_nova(self):
        self.j.remover_nota(self.j.notas[0], manter_vaga=True)
        _app.processEvents()
        self.assertEqual(len(self.j._vagas), 0)
        self.assertEqual(len(self.j.notas), 1)

    def test_fechamentos_consecutivos(self):
        self.criar(3)  # 1..4
        self.j.remover_nota(self.j.notas[1], manter_vaga=True)
        self.j.remover_nota(self.j.notas[1], manter_vaga=True)
        _app.processEvents()
        self.assertEqual(self.ordem(), [1, 4])
        self.assertLessEqual(len(self.j._vagas), 1)
        self.j._colapsar_vagas()
        _app.processEvents()
        self.assertEqual(self.ordem_visual(), [1, 4])

    def test_fechar_nao_altera_ordem_das_demais(self):
        self.criar(4)  # 1..5
        self.j.mover_nota(5, 1)  # 1 5 2 3 4
        self.j.remover_nota(self.j.notas[2], manter_vaga=True)  # fecha 2
        self.j._colapsar_vagas()
        _app.processEvents()
        self.assertEqual(self.ordem(), [1, 5, 3, 4])
        self.assertEqual(self.ordem_visual(), [1, 5, 3, 4])

    def test_numeros_nunca_sao_reaproveitados(self):
        self.criar(2)
        self.j.remover_nota(self.j.notas[2])
        self.j.adicionar_nota()
        self.assertEqual(self.ordem(), [1, 2, 4])


class TestColagemDePlanilha(Base):
    def colar(self, texto):
        self.j.colar_de_planilha(analisar_planilha(texto).colunas)
        _app.processEvents()

    def test_tres_colunas_em_ordem(self):
        self.colar("A1\tB1\tC1\nA2\tB2\tC2\nA3\tB3\tC3")
        self.assertEqual(len(self.j.notas), 4)  # 1 original + 3
        self.assertEqual(
            [self.texto(n) for n in self.j.notas[1:]],
            ["A1\nA2\nA3", "B1\nB2\nB3", "C1\nC2\nC3"],
        )

    def test_nota_existente_nao_e_sobrescrita(self):
        self.j.notas[0].editor.editor_texto.setPlainText("meu texto")
        self.colar("x\ty")
        self.assertEqual(self.texto(self.j.notas[0]), "meu texto")

    def test_celulas_vazias(self):
        self.colar("A1\t\tC1\nA2\tB2\t\n")
        textos = [self.texto(n) for n in self.j.notas[1:]]
        self.assertEqual(textos, ["A1\nA2", "\nB2", "C1"])

    def test_uma_coluna(self):
        self.colar("a\nb\nc")
        self.assertEqual(len(self.j.notas), 2)
        self.assertEqual(self.texto(self.j.notas[1]), "a\nb\nc")

    def test_insere_apos_a_nota_ativa(self):
        self.criar(1)  # 1, 2
        self.j.nota_ativa = self.j.notas[0]
        self.colar("x\ty")
        self.assertEqual(self.ordem(), [1, 3, 4, 2])
        self.assertEqual(self.ordem_visual(), [1, 3, 4, 2])

    def test_colunas_vazias_nao_criam_notas(self):
        self.colar("\t\t")
        self.assertEqual(len(self.j.notas), 1)


class TestReordenacao(Base):
    def test_exemplo_do_enunciado(self):
        self.criar(4)  # 1..5
        self.j.mover_nota(5, 2)
        _app.processEvents()
        self.assertEqual(self.ordem(), [1, 2, 5, 3, 4])
        self.assertEqual(self.ordem_visual(), [1, 2, 5, 3, 4])

    def test_primeira_para_a_ultima(self):
        self.criar(4)
        self.j.mover_nota(1, 5)
        self.assertEqual(self.ordem(), [2, 3, 4, 5, 1])
        self.assertEqual(self.ordem_visual(), [2, 3, 4, 5, 1])

    def test_ultima_para_o_meio(self):
        self.criar(4)
        self.j.mover_nota(5, 2)
        self.assertEqual(self.ordem(), [1, 2, 5, 3, 4])

    def test_soltar_no_mesmo_lugar_nao_faz_nada(self):
        self.criar(2)
        self.assertFalse(self.j.mover_nota(2, 1))
        self.assertFalse(self.j.mover_nota(2, 2))
        self.assertEqual(self.ordem(), [1, 2, 3])

    def test_varias_movimentacoes_seguidas(self):
        self.criar(4)
        self.j.mover_nota(5, 2)  # 1 2 5 3 4
        self.j.mover_nota(1, 5)  # 2 5 3 4 1
        self.j.mover_nota(4, 0)  # 4 2 5 3 1
        _app.processEvents()
        self.assertEqual(self.ordem(), [4, 2, 5, 3, 1])
        self.assertEqual(self.ordem_visual(), [4, 2, 5, 3, 1])

    def test_conteudo_e_imagens_preservados(self):
        self.criar(2)
        for n in self.j.notas:
            n.editor.editor_texto.setPlainText(f"texto {n.numero}")
        self.j.notas[1].editor.adicionar_imagem(
            QImage(20, 20, QImage.Format.Format_RGB32)
        )
        self.j.mover_nota(2, 0)
        self.j.mover_nota(1, 3)
        _app.processEvents()

        por_numero = {n.numero: n for n in self.j.notas}
        self.assertEqual(len(por_numero), 3)

        for numero, nota in por_numero.items():
            self.assertIn(f"texto {numero}", self.texto(nota))

        self.assertEqual(len(por_numero[2].editor.editor_texto.imagens), 1)

    def test_notas_criadas_por_colagem_tambem_se_movem(self):
        self.j.colar_de_planilha(["A", "B", "C"])  # 1, 2, 3, 4
        self.j.mover_nota(4, 1)
        self.assertEqual(self.ordem(), [1, 4, 2, 3])
        self.assertEqual(self.ordem_visual(), [1, 4, 2, 3])

    def test_numero_inexistente_e_ignorado(self):
        self.assertFalse(self.j.mover_nota(99, 0))

    def test_slot_pela_geometria(self):
        self.criar(2)
        area = self.j.area_notas
        self.assertEqual(area.slot_em(0), 0)
        self.assertEqual(area.slot_em(area.width()), 3)


class TestBarraSuperior(Base):
    def test_ctrl_b_alterna_a_visibilidade(self):
        barra = self.j.cabecalho
        self.assertTrue(barra.isVisible())

        self.j.atalho_barra_superior.activated.emit()
        _app.processEvents()
        self.assertFalse(barra.isVisible())

        self.j.atalho_barra_superior.activated.emit()
        _app.processEvents()
        self.assertTrue(barra.isVisible())

    def test_mesmo_widget_e_espaco_redistribuido(self):
        barra = self.j.cabecalho
        altura_antes = self.j.area_notas.height()

        self.j.alternar_barra_superior()
        _app.processEvents()

        self.assertIs(self.j.cabecalho, barra)
        self.assertGreater(self.j.area_notas.height(), altura_antes)

    def test_notas_e_edicao_continuam_funcionando(self):
        self.j.alternar_barra_superior()
        self.j.adicionar_nota()
        self.j.notas[0].editor.editor_texto.setPlainText("oi")
        _app.processEvents()
        self.assertEqual(self.ordem(), [1, 2])
        self.assertEqual(self.texto(self.j.notas[0]), "oi")


class TestRedimensionamentoDeNotas(Base):
    def divisorias_visiveis(self):
        self.j.area_notas._atualizar_divisorias()
        return [
            d for d in self.j.area_notas._divisorias if d.isVisible()
        ]

    def arrastar(self, divisoria, dx):
        """Simula o arraste chamando os handlers da alça."""
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        centro = QPointF(divisoria.width() / 2, 10)
        origem = divisoria.mapToGlobal(centro)

        def evento(tipo, global_, botao, botoes):
            return QMouseEvent(
                tipo, centro, global_, botao, botoes,
                Qt.KeyboardModifier.NoModifier,
            )

        esquerdo = Qt.MouseButton.LeftButton
        divisoria.mousePressEvent(
            evento(QEvent.Type.MouseButtonPress, origem, esquerdo, esquerdo)
        )
        divisoria.mouseMoveEvent(
            evento(
                QEvent.Type.MouseMove,
                QPointF(origem.x() + dx, origem.y()),
                Qt.MouseButton.NoButton, esquerdo,
            )
        )
        _app.processEvents()
        divisoria.mouseReleaseEvent(
            evento(
                QEvent.Type.MouseButtonRelease,
                QPointF(origem.x() + dx, origem.y()),
                esquerdo, Qt.MouseButton.NoButton,
            )
        )
        _app.processEvents()

    def test_uma_divisoria_por_par_de_notas(self):
        self.assertEqual(len(self.divisorias_visiveis()), 0)
        self.criar(2)  # 3 notas
        self.assertEqual(len(self.divisorias_visiveis()), 2)

    def test_arrastar_muda_so_as_duas_notas_vizinhas(self):
        self.criar(2)
        antes = {n.numero: n.width() for n in self.j.notas}
        total_par = antes[1] + antes[2]

        self.arrastar(self.divisorias_visiveis()[0], 60)

        depois = {n.numero: n.width() for n in self.j.notas}
        self.assertAlmostEqual(depois[1], antes[1] + 60, delta=3)
        self.assertAlmostEqual(depois[1] + depois[2], total_par, delta=2)
        self.assertAlmostEqual(depois[3], antes[3], delta=2)

    def test_largura_minima(self):
        import main

        self.criar(1)
        self.arrastar(self.divisorias_visiveis()[0], -5000)
        self.assertGreaterEqual(
            self.j.notas[0].width(), main.LARGURA_MINIMA_NOTA - 2
        )
        self.arrastar(self.divisorias_visiveis()[0], 5000)
        self.assertGreaterEqual(
            self.j.notas[1].width(), main.LARGURA_MINIMA_NOTA - 2
        )

    def test_proporcao_acompanha_a_janela(self):
        self.criar(1)
        self.arrastar(self.divisorias_visiveis()[0], 100)
        a, b = (n.width() for n in self.j.notas)
        razao = a / (a + b)

        self.j.resize(1600, 800)
        _app.processEvents()
        a, b = (n.width() for n in self.j.notas)
        self.assertAlmostEqual(a / (a + b), razao, delta=0.01)

    def test_conteudo_preservado_e_ordem_intacta(self):
        self.criar(1)
        self.j.notas[0].editor.editor_texto.setPlainText("texto 1")
        self.arrastar(self.divisorias_visiveis()[0], 80)
        self.assertEqual(self.texto(self.j.notas[0]), "texto 1")
        self.assertEqual(self.ordem_visual(), [1, 2])

    def test_larguras_sobrevivem_a_mover_e_fechar(self):
        self.criar(2)
        self.arrastar(self.divisorias_visiveis()[0], 80)
        largura_1 = self.j.notas[0].width()

        self.j.mover_nota(1, 3)  # 2 3 1
        _app.processEvents()
        self.assertAlmostEqual(
            self.j.notas[2].width(), largura_1, delta=3
        )

        # Fechar com vaga mantém o tamanho das demais notas.
        antes = self.j.notas[2].width()
        self.j.remover_nota(self.j.notas[0], manter_vaga=True)
        _app.processEvents()
        self.assertAlmostEqual(self.j.notas[1].width(), antes, delta=3)


if __name__ == "__main__":
    unittest.main()
