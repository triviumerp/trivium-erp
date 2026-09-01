from datetime import date
from app import app
from extensions import db
from models import Empresa, ContratoRecorrente, ServicoCliente

with app.app_context():
    empresa = Empresa.query.first()

    if not empresa:
        print("ERRO: Nenhuma empresa cadastrada.")
    else:
        # Simulamos a data de execução como 01/10/2026
        mes_ano_simulado = "10/2026"
        ano_simulado = 2026
        mes_simulado = 10

        contratos_ativos = ContratoRecorrente.query.filter_by(
            empresa_id=empresa.id,
            status='Ativo'
        ).all()

        gerados = 0
        for c in contratos_ativos:
            obs_identificador = f"[Ciclo {mes_ano_simulado}]"
            
            # Verifica se já foi gerado para não duplicar
            ja_gerado = ServicoCliente.query.filter(
                ServicoCliente.contrato_id == c.id,
                ServicoCliente.observacoes.ilike(f"%{obs_identificador}%")
            ).first()

            if not ja_gerado:
                dia = min(c.dia_vencimento, 28)
                data_execucao = date(ano_simulado, mes_simulado, dia)

                novo_lancamento = ServicoCliente(
                    empresa_id=empresa.id,
                    cliente_id=c.cliente_id,
                    tipo_servico_id=c.tipo_servico_id,
                    contrato_id=c.id,
                    valor_cobrado=c.valor_periodo,
                    status='Pendente',  # Aparece na Agenda como Pendente
                    data_solicitacao=date(ano_simulado, mes_simulado, 1),
                    data_previsao=data_execucao,
                    data_vencimento_boleto=data_execucao,
                    status_pagamento='A Faturar',
                    observacoes=f"{obs_identificador} Vistoria/Assessoria Mensal - {c.titulo}"
                )
                db.session.add(novo_lancamento)
                gerados += 1

        db.session.commit()
        print(f">> Sucesso! {gerados} serviço(s) mensalista(s) gerados com status PENDENTE para {mes_ano_simulado}.")