from datetime import date
from app import app
from extensions import db
from models import Empresa, Fatura, ParcelaFatura, ServicoCliente

with app.app_context():
    empresa = Empresa.query.first()
    if empresa:
        hoje = date.today()
        faturas = Fatura.query.filter_by(empresa_id=empresa.id).all()
        ajustadas = 0

        for f in faturas:
            if len(f.parcelas) == 0:
                # Se não tem parcela, cria a parcela principal única
                dt_venc = hoje
                # Tenta pegar a data de previsão do primeiro serviço vinculado
                if f.servicos and f.servicos[0].data_previsao:
                    dt_venc = f.servicos[0].data_previsao

                p = ParcelaFatura(
                    empresa_id=empresa.id,
                    fatura_id=f.id,
                    numero_parcela=1,
                    total_parcelas=1,
                    descricao_parcela="Parcela Única",
                    is_entrada=False,
                    forma_pagamento="Boleto Bancário",
                    valor=f.valor_total,
                    data_vencimento=dt_venc,
                    status="A Faturar"
                )
                db.session.add(p)
                ajustadas += 1

        db.session.commit()
        print(f">> Sucesso! {ajustadas} faturas foram regularizadas com seus títulos e vencimentos.")