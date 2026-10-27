"""Robô que lança no sistema web os pedidos de uma planilha Excel.

Lê entrada/pedidos.xlsx, entra no sistema, preenche a tela de novo
pedido linha por linha e anota o resultado na própria planilha:
Situação, Pedido nº e Motivo, com a linha em verde ou vermelho e um
print da tela de cada erro. Ao rodar de novo, pula o que já foi lançado.

Uso:
    python robo.py             roda sem abrir a janela do navegador
    python robo.py --mostrar   abre o navegador e vai devagar, para acompanhar
    python robo.py --demo      liga junto o sistema de demonstração (VendaFácil)
"""
import logging
import os
import shutil
import sys
import threading
from datetime import datetime
from pathlib import Path

import pandas as pd
from playwright.sync_api import TimeoutError as Demorou
from playwright.sync_api import sync_playwright

from formatar import anotar_resultados

ENDERECO = os.environ.get("ROBO_ENDERECO", "http://127.0.0.1:5000")
USUARIO = os.environ.get("ROBO_USUARIO", "robo")
SENHA = os.environ.get("ROBO_SENHA", "demo123")
TENTATIVAS = 2              # se o sistema não responder, tenta de novo uma vez
ESPERA_MAXIMA = 15_000      # milissegundos

PLANILHA = Path("entrada/pedidos.xlsx")
PASTA_SAIDA = Path("saida")
PASTA_ERROS = PASTA_SAIDA / "erros"

log = logging.getLogger("robo")


def configurar_log():
    PASTA_ERROS.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%d/%m/%Y %H:%M:%S")
    for destino in (logging.FileHandler(PASTA_SAIDA / "robo.log", encoding="utf-8"),
                    logging.StreamHandler(sys.stdout)):
        destino.setFormatter(formato)
        log.addHandler(destino)
    log.setLevel(logging.INFO)


def conferir_linha(pedido):
    """Confere a planilha antes de ir ao sistema: campo vazio nem tenta."""
    faltando = [campo for campo in ("Cliente", "Produto", "Quantidade", "Entrega")
                if pd.isna(pedido[campo]) or str(pedido[campo]).strip() == ""]
    if faltando:
        return "Planilha: " + ", ".join(faltando).lower() + " em branco"
    return None


def entrar(pagina):
    pagina.goto(ENDERECO)
    pagina.fill("#usuario", USUARIO)
    pagina.fill("#senha", SENHA)
    pagina.click("#entrar")
    if pagina.locator("#mensagem-erro").count():
        raise RuntimeError("Não consegui entrar no sistema: " +
                           pagina.inner_text("#mensagem-erro"))
    log.info("Entrou no sistema como %s", USUARIO)


def lancar(pagina, pedido):
    """Preenche e salva um pedido. Devolve (número do pedido, motivo do erro)."""
    pagina.goto(f"{ENDERECO}/pedidos/novo")
    if "/pedidos/novo" not in pagina.url:      # a sessão caiu: entra de novo
        entrar(pagina)
        pagina.goto(f"{ENDERECO}/pedidos/novo")

    produto = str(pedido["Produto"]).strip().upper()
    if not pagina.locator(f"#produto option[value='{produto}']").count():
        return None, f"Produto {produto} não existe no sistema"

    pagina.fill("#cliente", str(pedido["Cliente"]).strip())
    pagina.select_option("#produto", produto)
    pagina.fill("#quantidade", str(int(pedido["Quantidade"])))
    pagina.fill("#entrega", pd.Timestamp(pedido["Entrega"]).strftime("%Y-%m-%d"))
    observacao = pedido.get("Observação")
    pagina.fill("#observacao", "" if pd.isna(observacao) else str(observacao))
    pagina.click("#salvar")

    # Espera o sistema responder com sucesso ou com erro
    pagina.wait_for_selector("#mensagem-sucesso, #mensagem-erro", timeout=ESPERA_MAXIMA)
    if pagina.locator("#mensagem-sucesso").count():
        texto = pagina.inner_text("#mensagem-sucesso")   # "Pedido nº 1001 gravado..."
        return int(texto.split("nº")[1].split()[0]), None
    return None, pagina.inner_text("#mensagem-erro")


def planilha_aberta(caminho):
    """O Excel e o LibreOffice criam um arquivo de trava enquanto a planilha está aberta."""
    travas = (f"~${caminho.name}", f".~lock.{caminho.name}#")
    return any(caminho.with_name(trava).exists() for trava in travas)


def guardar_copia(caminho):
    pasta = caminho.parent / "backup"
    pasta.mkdir(exist_ok=True)
    copia = pasta / f"{caminho.stem}_{datetime.now():%Y-%m-%d_%H%M%S}{caminho.suffix}"
    shutil.copy2(caminho, copia)
    return copia


def ligar_sistema_de_demonstracao():
    """Sobe o VendaFácil junto com o robô, para a demonstração rodar com um clique só."""
    from werkzeug.serving import make_server

    sys.path.insert(0, str(Path(__file__).parent / "sistema"))
    from app import app

    logging.getLogger("werkzeug").setLevel(logging.ERROR)   # sem o vaivém de cada página
    servidor = make_server("127.0.0.1", 5000, app)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    log.info("Sistema de demonstração ligado em %s", ENDERECO)


def main():
    mostrar = "--mostrar" in sys.argv
    configurar_log()
    if "--demo" in sys.argv:
        ligar_sistema_de_demonstracao()

    if planilha_aberta(PLANILHA):
        log.error("Feche a planilha %s antes de rodar o robô: ele precisa gravar nela.", PLANILHA)
        sys.exit(1)

    pedidos = pd.read_excel(PLANILHA)
    if "Situação" not in pedidos.columns:
        pedidos["Situação"] = None
    pendentes = pedidos[pedidos["Situação"] != "Lançado"]
    log.info("Início: %d pedidos na planilha, %d já lançados antes, %d a lançar",
             len(pedidos), len(pedidos) - len(pendentes), len(pendentes))
    if pendentes.empty:
        log.info("Nada a fazer: todos os pedidos já foram lançados.")
        return
    log.info("Cópia de segurança da planilha: %s", guardar_copia(PLANILHA))

    resultados = {}
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=not mostrar,
                                               slow_mo=400 if mostrar else 0)
        pagina = navegador.new_page(viewport={"width": 1100, "height": 800})
        pagina.set_default_timeout(ESPERA_MAXIMA)
        entrar(pagina)

        for indice, pedido in pendentes.iterrows():
            linha = indice + 2          # linha no Excel (a 1 é o cabeçalho)
            numero, motivo, imagem = None, conferir_linha(pedido), ""
            if not motivo:
                for tentativa in range(1, TENTATIVAS + 1):
                    try:
                        numero, motivo = lancar(pagina, pedido)
                        break
                    except Demorou:
                        motivo = "O sistema não respondeu a tempo"
                        log.warning("Linha %d: sistema demorou (tentativa %d)", linha, tentativa)
                if motivo:
                    imagem = str(PASTA_ERROS / f"linha_{linha:03d}.png")
                    pagina.screenshot(path=imagem, full_page=True)

            if numero:
                log.info("Linha %d: pedido nº %d lançado", linha, numero)
            else:
                log.error("Linha %d: %s", linha, motivo)
            # O link do print é relativo à pasta da planilha, para abrir direto do Excel
            link = os.path.relpath(imagem, PLANILHA.parent) if imagem else ""
            resultados[linha] = ("Lançado" if numero else "Erro", numero, motivo, link)
        navegador.close()

    anotar_resultados(PLANILHA, resultados)
    lancados = sum(1 for situacao, *_ in resultados.values() if situacao == "Lançado")
    log.info("Fim: %d lançados agora, %d com erro. Resultado anotado em %s",
             lancados, len(resultados) - lancados, PLANILHA)
    if lancados < len(resultados):
        log.info("Corrija as linhas vermelhas na planilha e rode o robô de novo: "
                 "as linhas verdes serão puladas.")


if __name__ == "__main__":
    main()
