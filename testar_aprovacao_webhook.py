import os
import psycopg2
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("❌ Erro: DATABASE_URL não encontrada no arquivo .env")
    exit()

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

print("🔄 Conectando ao banco de dados...")
conn = psycopg2.connect(db_url)
cur = conn.cursor()

hoje = date.today()
vencimento = hoje + timedelta(days=30)

cur.execute("""
    UPDATE empresas 
    SET status_assinatura = 'ativo',
        data_ultimo_pagamento = %s,
        data_vencimento = %s,
        valor_mensalidade = %s
    WHERE id = %s
""", (hoje, vencimento, 32.32, 15))

conn.commit()
cur.close()
conn.close()

print("✅ Sucesso! Empresa 15 atualizada para 'ativo' no banco de dados.")
print("👉 Agora acerte/atualize a página no Render para conferir o acesso liberado.")