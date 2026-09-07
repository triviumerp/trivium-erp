import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# Pega a URL do banco do Render (.env local ou configurada)
db_url = os.getenv('DATABASE_URL')
if not db_url:
    # Cole aqui a External Database URL do seu PostgreSQL do Render se não estiver no .env
    db_url = input("Cole a External Database URL do Render: ").strip()

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

engine = create_engine(db_url)

comandos_sql = [
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS cep VARCHAR(20);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS logradouro VARCHAR(255);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS numero VARCHAR(50);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS complemento VARCHAR(100);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS bairro VARCHAR(100);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS cidade VARCHAR(100);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS estado VARCHAR(10);",
    "ALTER TABLE empresas ADD COLUMN IF NOT EXISTS forma_pagamento_asaas VARCHAR(50);"
]

print("Iniciando migração de colunas no Render...")
with engine.connect() as conn:
    for sql in comandos_sql:
        try:
            conn.execute(text(sql))
            conn.commit()
            print(f"Executado com sucesso: {sql}")
        except Exception as e:
            print(f"Aviso/Erro ao executar '{sql}': {e}")

print("\nMigração concluída com sucesso!")