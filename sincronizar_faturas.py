from datetime import date
from dateutil.relativedelta import relativedelta
from app import app
from extensions import db
from models import Empresa, Proposta, Fatura, ServicoCliente, ContratoRecorrente

with app.app_context():
    empresa = Empresa.query.first()

    if not empresa:
        print("ERRO: Nenhuma empresa encontrada.")
    else:
        hoje = date.today()
        
        # 1. Sincronizar Propostas Aprovadas que estão sem Fatura
        propostas_aprovadas = Proposta.query.filter_by(empresa_id=empresa.id, status='Aprovado').all()
        faturas_geradas = 0

        for prop in propostas_aprovadas:
            fatura_existente = Fatura.query.filter_by(proposta_id=prop.id).first()
            
            if not fatura_existente:
                vencimento = hoje + relativedelta(days=prop.validade_dias or 30)
                nova_fatura = Fatura(
                    empresa_id=empresa.id,
                    cliente_id=prop.cliente_id,
                    proposta_id=prop.id,
                    descricao=f"Proposta {prop.numero_proposta} ({len(prop.itens)} serviços)",
                    valor_total=prop.valor_total,
                    data_emissao=prop.data_criacao or hoje,
                    data_vencimento=vencimento,
                    status='A Faturar'
                )
                db.session.add(nova_fatura)
                db.session.flush()

                # Vincula os serviços existentes a essa fatura única
                servicos_da_proposta = ServicoCliente.query.filter_by(
                    cliente_id=prop.cliente_id,
                    empresa_id=empresa.id
                ).filter(ServicoCliente.observacoes.ilike(f"%{prop.numero_proposta}%")).all()

                for s in servicos_da_proposta:
                    s.fatura_id = nova_fatura.id

                faturas_geradas += 1

        # 2. Sincronizar Contratos Recorrentes Ativos que estão sem Fatura no ciclo atual
        contratos_ativos = ContratoRecorrente.query.filter_by(empresa_id=empresa.id, status='Ativo').all()
        for c in contratos_ativos:
            fatura_contrato = Fatura.query.filter_by(contrato_id=c.id).first()
            if not fatura_contrato:
                dia = min(c.dia_vencimento, 28)
                venc = date(hoje.year, hoje.month, dia)
                nova_fatura_c = Fatura(
                    empresa_id=empresa.id,
                    cliente_id=c.cliente_id,
                    contrato_id=c.id,
                    descricao=f"Mensalidade - {c.titulo}",
                    valor_total=c.valor_periodo,
                    data_emissao=hoje,
                    data_vencimento=venc,
                    status='A Faturar'
                )
                db.session.add(nova_fatura_c)
                db.session.flush()

                servicos_do_contrato = ServicoCliente.query.filter_by(contrato_id=c.id).all()
                for sc in servicos_do_contrato:
                    sc.fatura_id = nova_fatura_c.id

                faturas_geradas += 1

        db.session.commit()
        print(f">> Sucesso! {faturas_geradas} fatura(s) consolidada(s) foram geradas e vinculadas aos serviços.")