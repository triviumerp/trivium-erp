from app import app
from extensions import db
from sqlalchemy import text

with app.app_context():
    db.session.execute(text("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='empresas' AND column_name='forma_pagamento_asaas') THEN 
                ALTER TABLE empresas ADD COLUMN valor_mensalidade FLOAT DEFAULT 0.0;
                ALTER TABLE empresas ADD COLUMN forma_pagamento_asaas VARCHAR(30);
                ALTER TABLE empresas ADD COLUMN asaas_customer_id VARCHAR(50);
                ALTER TABLE empresas ADD COLUMN asaas_subscription_id VARCHAR(50);
                ALTER TABLE empresas ADD COLUMN data_ultimo_pagamento DATE;
                ALTER TABLE empresas ADD COLUMN observacoes_master TEXT;
            END IF; 
        END $$;
    """))
    db.session.commit()
    print(">> Sucesso! Novas colunas de gestão de pagamentos e Asaas adicionadas na tabela de empresas.")