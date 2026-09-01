from app import app
from extensions import db
from sqlalchemy import text

with app.app_context():
    # 1. Novas colunas na tabela propostas
    db.session.execute(text("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='propostas' AND column_name='exige_entrada') THEN 
                ALTER TABLE propostas ADD COLUMN exige_entrada BOOLEAN DEFAULT FALSE;
                ALTER TABLE propostas ADD COLUMN valor_entrada FLOAT DEFAULT 0.0;
                ALTER TABLE propostas ADD COLUMN forma_pagamento_entrada VARCHAR(50) DEFAULT 'PIX';
                ALTER TABLE propostas ADD COLUMN qtd_parcelas INTEGER DEFAULT 1;
                ALTER TABLE propostas ADD COLUMN forma_pagamento_parcelas VARCHAR(50) DEFAULT 'Boleto Bancário';
                ALTER TABLE propostas ADD COLUMN intervalo_dias INTEGER DEFAULT 30;
            END IF; 
        END $$;
    """))

    # 2. Tabela de parcelas
    db.session.execute(text("""
        CREATE TABLE IF NOT EXISTS parcelas_fatura (
            id SERIAL PRIMARY KEY,
            empresa_id INTEGER NOT NULL REFERENCES empresas(id) ON DELETE CASCADE,
            fatura_id INTEGER NOT NULL REFERENCES faturas(id) ON DELETE CASCADE,
            numero_parcela INTEGER DEFAULT 1,
            total_parcelas INTEGER DEFAULT 1,
            descricao_parcela VARCHAR(100) DEFAULT 'Parcela Única',
            is_entrada BOOLEAN DEFAULT FALSE,
            forma_pagamento VARCHAR(50) DEFAULT 'Boleto Bancário',
            valor FLOAT DEFAULT 0.0,
            data_vencimento DATE NOT NULL,
            status VARCHAR(30) DEFAULT 'A Faturar',
            arquivo_comprovante_boleto VARCHAR(255),
            historico_cobranca TEXT
        );
    """))

    db.session.commit()
    print(">> Sucesso! Tabela de parcelas e regras de entrada configuradas.")