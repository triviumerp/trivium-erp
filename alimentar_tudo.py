from datetime import date
from dateutil.relativedelta import relativedelta
from app import app
from extensions import db
from models import Empresa, Cliente, TipoServico, Proposta, ItemProposta, Fatura, ServicoCliente, ContratoRecorrente

with app.app_context():
    empresa = Empresa.query.first()

    if not empresa:
        print("ERRO: Nenhuma empresa encontrada.")
    else:
        hoje = date.today()

        # 1. Garantir serviços no Catálogo
        servicos = {
            "Assessoria Mensal": TipoServico.query.filter_by(empresa_id=empresa.id, nome="Assessoria Mensal em Segurança & Conformidade").first(),
            "Laudo Pericial": TipoServico.query.filter_by(empresa_id=empresa.id, nome="Elaboração de Laudo Técnico Pericial com ART").first(),
            "Treinamento": TipoServico.query.filter_by(empresa_id=empresa.id, nome="Treinamento e Capacitação Técnica de Equipe").first(),
            "SPDA": TipoServico.query.filter_by(empresa_id=empresa.id, nome="Inspeção e Medição Ôhmica de SPDA (Pára-raios)").first(),
        }

        # Cria serviços faltantes
        if not servicos["Assessoria Mensal"]:
            s = TipoServico(empresa_id=empresa.id, nome="Assessoria Mensal em Segurança & Conformidade", valor_sugerido=1200.0, modelo_cobranca="mensal")
            db.session.add(s)
            servicos["Assessoria Mensal"] = s
        if not servicos["Laudo Pericial"]:
            s = TipoServico(empresa_id=empresa.id, nome="Elaboração de Laudo Técnico Pericial com ART", valor_sugerido=2800.0, modelo_cobranca="pontual")
            db.session.add(s)
            servicos["Laudo Pericial"] = s
        if not servicos["Treinamento"]:
            s = TipoServico(empresa_id=empresa.id, nome="Treinamento e Capacitação Técnica de Equipe", valor_sugerido=950.0, modelo_cobranca="pontual")
            db.session.add(s)
            servicos["Treinamento"] = s
        if not servicos["SPDA"]:
            s = TipoServico(empresa_id=empresa.id, nome="Inspeção e Medição Ôhmica de SPDA (Pára-raios)", valor_sugerido=1500.0, modelo_cobranca="pontual")
            db.session.add(s)
            servicos["SPDA"] = s
        db.session.flush()

        # 2. Localizar Clientes
        c_parque = Cliente.query.filter_by(empresa_id=empresa.id, nome="Condomínio Residencial Parque das Flores").first()
        c_horizonte = Cliente.query.filter_by(empresa_id=empresa.id, nome="Logística & Transportes Horizonte Ltda").first()
        c_marcelo = Cliente.query.filter_by(empresa_id=empresa.id, nome="Marcelo Henrique da Silva").first()
        c_posto = Cliente.query.filter_by(empresa_id=empresa.id, nome="Auto Posto Estrela de Suzano Ltda").first()

        # -------------------------------------------------------------
        # PROPOSTA 1 (Aguardando Aprovação) - Marcelo (3 Itens)
        # -------------------------------------------------------------
        if c_marcelo and not Proposta.query.filter_by(empresa_id=empresa.id, numero_proposta="PROP-2026-001").first():
            p1 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-001",
                cliente_id=c_marcelo.id,
                data_criacao=hoje,
                validade_dias=15,
                condicoes_pagamento="Boleto Bancário / Faturamento em 30 dias",
                observacoes="Pacote completo com laudo, inspeção e treinamento.",
                status="Aguardando Aprovação",
                tipo_cobranca="pontual",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(p1)
            db.session.flush()

            db.session.add_all([
                ItemProposta(proposta_id=p1.id, tipo_servico_id=servicos["Treinamento"].id, valor_unitario=950.0, descricao_personalizada="Treinamento de Equipe"),
                ItemProposta(proposta_id=p1.id, tipo_servico_id=servicos["SPDA"].id, valor_unitario=1500.0, descricao_personalizada="Medição de SPDA"),
                ItemProposta(proposta_id=p1.id, tipo_servico_id=servicos["Laudo Pericial"].id, valor_unitario=2800.0, descricao_personalizada="Laudo com ART")
            ])

        # -------------------------------------------------------------
        # PROPOSTA 2 (Aprovada com Fatura Única) - Logística Horizonte
        # -------------------------------------------------------------
        if c_horizonte and not Proposta.query.filter_by(empresa_id=empresa.id, numero_proposta="PROP-2026-002").first():
            p2 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-002",
                cliente_id=c_horizonte.id,
                data_criacao=hoje - relativedelta(days=5),
                validade_dias=20,
                condicoes_pagamento="Boleto Bancário em 30 dias",
                status="Aprovado",
                tipo_cobranca="pontual",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(p2)
            db.session.flush()

            item_p2 = ItemProposta(
                proposta_id=p2.id,
                tipo_servico_id=servicos["Laudo Pericial"].id,
                valor_unitario=2800.0,
                descricao_personalizada="Vistoria técnica presencial do Galpão 03"
            )
            db.session.add(item_p2)
            db.session.flush()

            # Gera a Fatura Única no Financeiro
            fatura2 = Fatura(
                empresa_id=empresa.id,
                cliente_id=c_horizonte.id,
                proposta_id=p2.id,
                descricao=f"Proposta {p2.numero_proposta} (1 serviço)",
                valor_total=2800.0,
                data_emissao=hoje - relativedelta(days=5),
                data_vencimento=hoje + relativedelta(days=25),
                status="A Faturar"
            )
            db.session.add(fatura2)
            db.session.flush()

            # Gera a Ordem na Agenda
            sc2 = ServicoCliente(
                empresa_id=empresa.id,
                cliente_id=c_horizonte.id,
                tipo_servico_id=servicos["Laudo Pericial"].id,
                fatura_id=fatura2.id,
                valor_cobrado=2800.0,
                status="Em Andamento",
                data_solicitacao=hoje - relativedelta(days=5),
                data_previsao=hoje + relativedelta(days=10),
                observacoes="[Ref. PROP-2026-002] Perícia e emissão de laudo técnico"
            )
            db.session.add(sc2)

        # -------------------------------------------------------------
        # PROPOSTA 3 (Contrato Recorrente Aprovado) - Condomínio Parque das Flores
        # -------------------------------------------------------------
        if c_parque and not Proposta.query.filter_by(empresa_id=empresa.id, numero_proposta="PROP-2026-003").first():
            p3 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-003",
                cliente_id=c_parque.id,
                data_criacao=hoje - relativedelta(days=10),
                validade_dias=15,
                condicoes_pagamento="Mensalidade via boleto todo dia 10",
                status="Aprovado",
                tipo_cobranca="recorrente",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(p3)
            db.session.flush()

            item_p3 = ItemProposta(
                proposta_id=p3.id,
                tipo_servico_id=servicos["Assessoria Mensal"].id,
                valor_unitario=1200.0,
                descricao_personalizada="Assessoria mensal preventiva"
            )
            db.session.add(item_p3)
            db.session.flush()

            # Contrato Ativo
            contrato = ContratoRecorrente(
                empresa_id=empresa.id,
                cliente_id=c_parque.id,
                tipo_servico_id=servicos["Assessoria Mensal"].id,
                proposta_origem_id=p3.id,
                titulo=f"Contrato Mensal - {c_parque.nome}",
                valor_periodo=1200.0,
                periodicidade="mensal",
                dia_vencimento=10,
                status="Ativo",
                data_inicio=hoje - relativedelta(days=10)
            )
            db.session.add(contrato)
            db.session.flush()

            # Fatura Mensal
            fatura3 = Fatura(
                empresa_id=empresa.id,
                cliente_id=c_parque.id,
                proposta_id=p3.id,
                contrato_id=contrato.id,
                descricao=f"Mensalidade - {contrato.titulo}",
                valor_total=1200.0,
                data_emissao=hoje,
                data_vencimento=date(hoje.year, hoje.month, 10) if hoje.day <= 10 else date(hoje.year, hoje.month, 10) + relativedelta(months=1),
                status="A Faturar"
            )
            db.session.add(fatura3)
            db.session.flush()

            # Ordem na Agenda
            sc3 = ServicoCliente(
                empresa_id=empresa.id,
                cliente_id=c_parque.id,
                tipo_servico_id=servicos["Assessoria Mensal"].id,
                contrato_id=contrato.id,
                fatura_id=fatura3.id,
                valor_cobrado=1200.0,
                status="Pendente",
                data_solicitacao=hoje,
                data_previsao=date(hoje.year, hoje.month, 10) if hoje.day <= 10 else date(hoje.year, hoje.month, 10) + relativedelta(months=1),
                observacoes="[Ciclo Atual] Vistoria mensal preventiva"
            )
            db.session.add(sc3)

        db.session.commit()
        print(">> Sucesso! Propostas ativas, aprovadas e faturas consolidadas foram cadastradas.")