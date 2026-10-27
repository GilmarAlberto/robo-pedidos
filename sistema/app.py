"""VendaFácil: um sistema web de pedidos de mentira, para o robô trabalhar.

Faz o papel do "sistema da empresa": tem login, lista de pedidos e uma
tela de cadastro que valida os dados como um sistema real faria.
Roda só no seu computador: python sistema/app.py
"""
import random
import sqlite3
import time
from datetime import date
from functools import wraps
from pathlib import Path

from flask import Flask, redirect, render_template, request, session, url_for

PASTA = Path(__file__).parent
BANCO = PASTA / "pedidos.db"

USUARIOS = {"robo": "demo123"}   # usuário fictício, só para a demonstração

CLIENTES = {
    "C001": "Mercado Bom Preço", "C002": "Padaria Pão Quente",
    "C003": "Restaurante Sabor Caseiro", "C004": "Lanchonete do Zé",
    "C005": "Hotel Araucária", "C006": "Cantina Bella Itália",
    "C007": "Empório Natural", "C008": "Café Central",
}

PRODUTOS = {  # código: (descrição, estoque)
    "P01": ("Arroz 5kg", 300), "P02": ("Feijão 1kg", 250),
    "P03": ("Óleo de soja 900ml", 180), "P04": ("Café 500g", 120),
    "P05": ("Açúcar 5kg", 90), "P06": ("Leite 1L (caixa c/12)", 60),
    "P07": ("Farinha de trigo 5kg", 75), "P08": ("Macarrão 500g", 400),
}

app = Flask(__name__)
app.secret_key = "so-para-demonstracao"


@app.template_filter("data_br")
def data_br(texto):
    """2026-11-04 → 04/11/2026 (e mantém a hora, se tiver)."""
    dia, _, hora = texto.partition(" ")
    ano, mes, dia = dia.split("-")
    return f"{dia}/{mes}/{ano} {hora[:5]}".strip()


def banco():
    conexao = sqlite3.connect(BANCO)
    conexao.row_factory = sqlite3.Row
    conexao.execute("""CREATE TABLE IF NOT EXISTS pedidos (
        numero INTEGER PRIMARY KEY AUTOINCREMENT, cliente TEXT, produto TEXT,
        quantidade INTEGER, entrega TEXT, observacao TEXT, criado_em TEXT)""")
    conexao.execute("INSERT OR IGNORE INTO sqlite_sequence (name, seq) "
                    "SELECT 'pedidos', 1000 WHERE NOT EXISTS "
                    "(SELECT 1 FROM sqlite_sequence WHERE name = 'pedidos')")
    return conexao


def exige_login(funcao):
    @wraps(funcao)
    def verificar(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return verificar


def validar(cliente, produto, quantidade, entrega):
    """As mesmas regras que um sistema real teria."""
    if cliente not in CLIENTES:
        return f"Cliente {cliente} não cadastrado."
    if produto not in PRODUTOS:
        return "Selecione um produto."
    try:
        quantidade = int(quantidade)
    except ValueError:
        return "Quantidade inválida."
    if quantidade <= 0:
        return "A quantidade deve ser maior que zero."
    descricao, estoque = PRODUTOS[produto]
    if quantidade > estoque:
        return f"Estoque insuficiente de {descricao}: disponível {estoque}."
    try:
        dia = date.fromisoformat(entrega)
    except ValueError:
        return "Data de entrega inválida."
    if dia < date.today():
        return "A data de entrega não pode estar no passado."
    return None


@app.route("/", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        usuario = request.form.get("usuario", "")
        if USUARIOS.get(usuario) == request.form.get("senha"):
            session["usuario"] = usuario
            return redirect(url_for("pedidos"))
        erro = "Usuário ou senha incorretos."
    return render_template("login.html", erro=erro)


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/pedidos")
@exige_login
def pedidos():
    with banco() as conexao:
        lista = conexao.execute("SELECT * FROM pedidos ORDER BY numero DESC").fetchall()
    return render_template("pedidos.html", pedidos=lista, clientes=CLIENTES,
                           produtos=PRODUTOS)


@app.route("/pedidos/novo", methods=["GET", "POST"])
@exige_login
def novo_pedido():
    # Sistemas reais nem sempre respondem na hora: o robô tem que esperar
    time.sleep(random.uniform(0.2, 1.2))
    erro = sucesso = None
    dados = request.form
    if request.method == "POST":
        erro = validar(dados.get("cliente", "").strip().upper(), dados.get("produto", ""),
                       dados.get("quantidade", ""), dados.get("entrega", ""))
        if not erro:
            with banco() as conexao:
                cursor = conexao.execute(
                    "INSERT INTO pedidos (cliente, produto, quantidade, entrega, "
                    "observacao, criado_em) VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                    (dados["cliente"].strip().upper(), dados["produto"],
                     int(dados["quantidade"]), dados["entrega"], dados.get("observacao", "")))
            sucesso = f"Pedido nº {cursor.lastrowid} gravado com sucesso."
            dados = {}
    return render_template("novo_pedido.html", erro=erro, sucesso=sucesso, dados=dados,
                           produtos=PRODUTOS, hoje=date.today().isoformat())


if __name__ == "__main__":
    app.run(port=5000)
