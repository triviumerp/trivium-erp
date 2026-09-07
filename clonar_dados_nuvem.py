import os
import pandas as pd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

# 1. Cole aqui a URL EXTERNA copiada do Render
URL_RENDER_RAW = "postgresql://trivium_db_59c0_user:VBPuxtHTv04AHMy7maLyhPGwKqDEMbVZ@dpg-dab1flijnfac73a9k3b0-a.ohio-postgres.render.com/trivium_db_59c0"

# Garante o sslmode obrigatório do Render e o driver correto
if "sslmode=" not in URL_RENDER_RAW:
    separador = "&" if "?" in URL_RENDER_RAW else "?"
    URL_RENDER = f"{URL_RENDER_RAW}{separador}sslmode=require"
else:
    URL_RENDER = URL_RENDER_RAW

if URL_RENDER.startswith("postgres://"):
    URL_RENDER = URL_RENDER.replace("postgres://", "postgresql://", 1)

URL_LOCAL = os.getenv("DATABASE_URL")
if not URL_LOCAL:
    raise Exception("DATABASE_URL local não encontrada no .env")

print("🔄 Conectando aos bancos de dados...")
engine_remoto = create_engine(URL_RENDER, pool_pre_ping=True)
engine_local = create_engine(URL_LOCAL)

tabelas = [
    "empresas",
    "usuarios",
    "clientes",
    "documentos",
    "tipos_servico",
    "propostas",
    "itens_proposta",
    "contratos_recorrentes",
    "faturas",
    "parcelas_fatura",
    "servicos_cliente",
    "chamados_suporte",
    "mensagens_chamado"
]

print("📥 Baixando dados do Render e inserindo no banco local...")

for tabela in tabelas:
    try:
        df = pd.read_sql_table(tabela, engine_remoto)
        if not df.empty:
            df.to_sql(tabela, engine_local, if_exists="append", index=False)
            print(f"✅ Tabela '{tabela}': {len(df)} registro(s) sincronizado(s).")
        else:
            print(f"ℹ️ Tabela '{tabela}' está vazia na nuvem.")
    except Exception as e:
        print(f"⚠️ Erro ao copiar '{tabela}': {e}")

print("\n🚀 Sincronização concluída com sucesso!")