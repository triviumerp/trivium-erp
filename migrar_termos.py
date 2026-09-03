from app import app
from extensions import db
from sqlalchemy import text

with app.app_context():
    db.session.execute(text("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='usuarios' AND column_name='aceitou_termos_beta') THEN 
                ALTER TABLE usuarios ADD COLUMN aceitou_termos_beta BOOLEAN DEFAULT FALSE;
                ALTER TABLE usuarios ADD COLUMN data_aceite_termos TIMESTAMP;
            END IF; 
        END $$;
    """))
    db.session.commit()
    print(">> Sucesso! Colunas de aceite dos termos Beta adicionadas na tabela de usuários.")