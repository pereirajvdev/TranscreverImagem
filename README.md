# TranscreverImagem

Editor de notas com transcrição de imagens (OCR), feito em Python com PySide6.

## Descrição

O TranscreverImagem permite colar ou abrir imagens (capturas de tela, fotos
de documentos etc.) dentro de notas de texto e transcrever o texto contido
nelas com o Tesseract OCR. O resultado aparece logo abaixo da imagem, na
própria nota, onde pode ser editado e copiado como texto puro.

As notas ficam lado a lado, podem ser reordenadas e redimensionadas, e o
conteúdo de planilhas (Excel, Google Sheets, Calc) pode ser colado criando
uma nota por coluna.

## Funcionalidades

**OCR**
- Transcrição de uma imagem selecionada, em segundo plano (a interface não
  trava), com indicador de progresso no botão e mensagens na barra de status.
- Pré-processamento antes do Tesseract: tons de cinza, ampliação, ajuste leve
  de contraste e margem branca. Idioma: português (`por`).

**Edição de texto**
- Seleção múltipla estilo editores de código (`Ctrl+D`): digitação, apagar,
  Enter, recortar, copiar, colar e setas (inclusive por palavra) valem para
  todos os cursores; um único `Ctrl+Z` desfaz a edição.
- `Ctrl` + clique recorta o texto da linha, deixando a linha vazia.
- Zoom do editor com `Ctrl` + roda do mouse (individual por nota).
- "Copiar texto" e as cópias do editor enviam sempre texto puro.

**Imagens e notas**
- Imagens coladas (`Ctrl+V`) ou abertas por arquivo (`Ctrl+O`:
  png, jpg, jpeg, bmp, tif, tiff, webp). Cada imagem recebe um número
  (`Imagem #N`) e fica em parágrafo próprio.
- Várias notas lado a lado; adicionar, fechar e numerar (os números nunca são
  reaproveitados).
- Reordenação arrastando o cabeçalho da nota.
- Redimensionamento arrastando a divisória entre duas notas (largura mínima
  de 160 px por nota). As larguras são proporcionais e acompanham o tamanho
  da janela.
- Ao fechar uma nota com o mouse, as demais deslizam para a esquerda sem
  mudar de tamanho; o espaço fica reservado no fim até o cursor sair do
  botão X.
- Colagem especial (`Ctrl+Shift+V`), opção **Paste from Sheet**: uma nota por
  coluna, preservando linhas vazias; notas totalmente vazias são removidas
  antes; acima de 10 colunas é pedida confirmação.

**Interface**
- Tema claro e escuro (a escolha é salva).
- Barra superior que pode ser ocultada com `Ctrl+B`.

## Tecnologias utilizadas

- Python
- [PySide6](https://doc.qt.io/qtforpython-6/) (interface Qt)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (executável distribuído na pasta `tesseract/`)
- pytesseract
- Pillow
- OpenCV (`opencv-python`)
- NumPy

## Estrutura do projeto

```
TranscreverImagem/
├── requirements.txt
├── tesseract/            # Tesseract para Windows (tesseract.exe)
├── src/
│   ├── main.py             # Janela principal, notas, editor, OCR e atalhos
│   ├── temas.py            # Paletas clara/escura, QSS e persistência do tema
│   ├── icones.py           # Ícones desenhados em código (QPainter)
│   ├── colagem.py          # Janela da colagem especial (Paste from Sheet)
│   ├── planilha.py         # Análise de TSV da área de transferência (sem Qt)
│   ├── ordenacao.py        # Cálculo da reordenação por arrastar e soltar (sem Qt)
│   └── redimensionamento.py# Cálculo do redimensionamento pela divisória (sem Qt)
└── tests/
    ├── test_logica.py      # Testes da lógica pura
    └── test_interface.py   # Testes de integração (modo offscreen)
```

## Instalação

```bash
git clone https://github.com/pereirajvdev/TranscreverImagem.git
cd TranscreverImagem

python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

## Execução

Na raiz do repositório:

```bash
python src/main.py
```

O programa procura o Tesseract em `tesseract/tesseract.exe`, dentro da pasta
do projeto. Se o arquivo não existir, a janela abre normalmente, mas a
transcrição mostra uma mensagem de erro.

## Atalhos de teclado

| Atalho | Função |
|---|---|
| `Ctrl+O` | Abrir imagens na nota ativa |
| `Ctrl+Shift+C` | Copiar o texto da nota ativa |
| `Ctrl+Shift+V` | Colagem especial (Paste from Sheet) |
| `Ctrl+Shift+T` | Alternar tema claro/escuro |
| `Ctrl+B` | Mostrar/ocultar a barra superior |
| `Ctrl+D` | Seleção múltipla: seleciona a próxima ocorrência |
| `Esc` | Sai da seleção múltipla |
| `Ctrl` + roda do mouse | Zoom do editor |
| `Ctrl` + clique | Recorta a linha clicada (a linha permanece, vazia) |
| `Ctrl+V` | Cola imagem ou texto no editor |

Também por mouse: arrastar o cabeçalho de uma nota reordena; arrastar a
divisória entre duas notas ajusta suas larguras.

## Testes

```bash
python -m unittest discover -s tests -p "test_logica.py" -v
python -m unittest discover -s tests -p "test_interface.py" -v
```

Os testes de interface rodam em modo offscreen e exigem PySide6 e as demais
dependências instaladas.

## Observações

- O caminho do Tesseract e o idioma `por` (dados de idioma português) são
  esperados dentro da pasta `tesseract/` distribuída com o projeto.
- O projeto foi escrito para Windows (usa `tesseract.exe` e a fonte Segoe UI).
- Com a barra superior oculta, os botões de tema e de nova nota ficam
  escondidos; o tema continua acessível por `Ctrl+Shift+T`.
- A transcrição acontece em uma thread; não é possível fechar a nota ou o
  aplicativo enquanto ela estiver em andamento.
