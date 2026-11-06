"""Análise de conteúdo tabular (TSV) da área de transferência.

Módulo sem dependência de Qt, para poder ser testado isoladamente.
"""

import csv
import io
from dataclasses import dataclass, field


@dataclass
class Planilha:
    """Resultado da análise: uma string por coluna não vazia."""

    colunas: list = field(default_factory=list)
    linhas: int = 0


def _ler_linhas(texto: str) -> list:
    """Divide o TSV em linhas de células.

    O módulo csv trata aspas como o Excel e o Google Sheets as geram:
    células com quebra de linha, tab ou aspas vêm entre aspas, e as
    aspas internas são duplicadas.
    """
    try:
        leitor = csv.reader(
            io.StringIO(texto, newline=""),
            delimiter="\t",
            quotechar='"',
        )
        linhas = [list(linha) for linha in leitor]
    except csv.Error:
        # Texto fora do padrão (ex.: campo gigante): divisão simples.
        linhas = [
            linha.split("\t") for linha in texto.splitlines()
        ]

    return [
        [
            celula.replace("\r\n", "\n").replace("\r", "\n")
            for celula in linha
        ]
        for linha in linhas
    ]


def analisar_planilha(texto: str) -> Planilha:
    """Converte conteúdo tabular (TSV) em uma nota por coluna.

    - A ordem das colunas é preservada.
    - Células vazias mantêm sua linha, então nada é deslocado.
    - Linhas finais totalmente vazias são ignoradas.
    - Colunas sem nenhum conteúdo não geram nota.
    """
    if not texto or not texto.strip():
        return Planilha()

    linhas = _ler_linhas(texto)

    while linhas and not any(c.strip() for c in linhas[-1]):
        linhas.pop()

    if not linhas:
        return Planilha()

    largura = max(len(linha) for linha in linhas)
    colunas = []

    for i in range(largura):
        celulas = [
            linha[i] if i < len(linha) else "" for linha in linhas
        ]
        conteudo = "\n".join(celulas).rstrip("\n")

        if conteudo.strip():
            colunas.append(conteudo)

    return Planilha(colunas=colunas, linhas=len(linhas))


def extrair_colunas(texto: str) -> list:
    return analisar_planilha(texto).colunas


def plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"
