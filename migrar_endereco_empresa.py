from app import app
from extensions import db
from sqlalchemy import text

with app.app_context():
    db.session.execute(text("""
        DO $$ 
        BEGIN 
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='empresas' AND column_name='cep') THEN 
                ALTER TABLE empresas ADD COLUMN cep VARCHAR(10);
                ALTER TABLE empresas ADD COLUMN logradouro VARCHAR(150);
                ALTER TABLE empresas ADD COLUMN numero VARCHAR(20);
                ALTER TABLE empresas ADD COLUMN complemento VARCHAR(100);
                ALTER TABLE empresas ADD COLUMN bairro VARCHAR(100);
                ALTER TABLE empresas ADD COLUMN cidade VARCHAR(100);
                ALTER TABLE empresas ADD COLUMN estado VARCHAR(2);
            END IF; 
        END $$;
    """))
    db.session.commit()
    print(">> Sucesso! Colunas estruturadas de endereço adicionadas à tabela empresas.")