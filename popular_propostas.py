from datetime import date
from dateutil.relativedelta import relativedelta
from app import app
from extensions import db
from models import Empresa, Cliente, TipoServico, Proposta, ItemProposta

with app.app_context():
    empresa = Empresa.query.first()

    if not empresa:
        print("ERRO: Nenhuma empresa cadastrada.")
    else:
        # ---------------------------------------------------------------------
        # 1. POPULAR CATÁLOGO DE SERVIÇOS
        # ---------------------------------------------------------------------
        catalogo = [
            {
                "nome": "Assessoria Técnica Mensal em Segurança & Conformidade",
                "descricao_padrao": "Acompanhamento contínuo, vistorias mensais presenciais e elaboração de relatórios técnicos periódicos.",
                "valor_sugerido": 1200.00,
                "modelo_cobranca": "mensal"
            },
            {
                "nome": "Elaboração de Laudo Técnico Pericial com ART",
                "descricao_padrao": "Vistoria técnica presencial com ensaios, análise estrutural/operacional e emissão de laudo conclusivo com recolhimento de ART.",
                "valor_sugerido": 2800.00,
                "modelo_cobranca": "pontual"
            },
            {
                "nome": "Treinamento e Capacitação Técnica de Equipe",
                "descricao_padrao": "Curso presencial com carga horária de 8 horas, fornecimento de apostilas didáticas e certificados individuais de conclusão.",
                "valor_sugerido": 950.00,
                "modelo_cobranca": "pontual"
            },
            {
                "nome": "Inspeção e Medição Ôhmica de SPDA (Pára-raios)",
                "descricao_padrao": "Medição de continuidade das descidas, malha de aterramento e emissão de relatório fotográfico com laudo técnico.",
                "valor_sugerido": 1500.00,
                "modelo_cobranca": "pontual"
            }
        ]

        servicos_criados = {}
        for item in catalogo:
            serv = TipoServico.query.filter_by(empresa_id=empresa.id, nome=item["nome"]).first()
            if not serv:
                serv = TipoServico(
                    empresa_id=empresa.id,
                    nome=item["nome"],
                    descricao_padrao=item["descricao_padrao"],
                    valor_sugerido=item["valor_sugerido"],
                    modelo_cobranca=item["modelo_cobranca"]
                )
                db.session.add(serv)
                db.session.flush()
            servicos_criados[serv.nome] = serv

        # ---------------------------------------------------------------------
        # 2. LOCALIZAR CLIENTES CADASTRADOS
        # ---------------------------------------------------------------------
        c_parque = Cliente.query.filter_by(empresa_id=empresa.id, nome="Condomínio Residencial Parque das Flores").first()
        c_horizonte = Cliente.query.filter_by(empresa_id=empresa.id, nome="Logística & Transportes Horizonte Ltda").first()
        c_marcelo = Cliente.query.filter_by(empresa_id=empresa.id, nome="Marcelo Henrique da Silva").first()
        c_posto = Cliente.query.filter_by(empresa_id=empresa.id, nome="Auto Posto Estrela de Suzano Ltda").first()

        propostas_cadastradas = 0

        # PROPOSTA 1: CONTRATO MENSAL (Condomínio Parque das Flores)
        if c_parque:
            prop1 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-001",
                cliente_id=c_parque.id,
                data_criacao=date.today() - relativedelta(days=5),
                validade_dias=15,
                condicoes_pagamento="Boleto bancário com faturamento mensal todo dia 10",
                observacoes="Inclusa visita mensal de conformidade e suporte via WhatsApp em horário comercial.",
                status="Aguardando Aprovação",
                tipo_cobranca="recorrente",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(prop1)
            db.session.flush()

            item1 = ItemProposta(
                proposta_id=prop1.id,
                tipo_servico_id=servicos_criados["Assessoria Técnica Mensal em Segurança & Conformidade"].id,
                valor_unitario=1200.00,
                descricao_personalizada="Assessoria mensal preventiva para o condomínio com 4 torres residenciais."
            )
            db.session.add(item1)
            propostas_cadastradas += 1

        # PROPOSTA 2: SERVIÇO PONTUAL (Logística Horizonte)
        if c_horizonte:
            prop2 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-002",
                cliente_id=c_horizonte.id,
                data_criacao=date.today() - relativedelta(days=3),
                validade_dias=20,
                condicoes_pagamento="Faturamento em 30 dias após emissão da Nota Fiscal e entrega do laudo",
                observacoes="Emissão de ART inclusa no valor da proposta técnica.",
                status="Aguardando Aprovação",
                tipo_cobranca="pontual",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(prop2)
            db.session.flush()

            item2 = ItemProposta(
                proposta_id=prop2.id,
                tipo_servico_id=servicos_criados["Elaboração de Laudo Técnico Pericial com ART"].id,
                valor_unitario=2800.00,
                descricao_personalizada="Perícia e emissão de laudo técnico das estruturas de armazenagem do Galpão 03."
            )
            db.session.add(item2)
            propostas_cadastradas += 1

        # PROPOSTA 3: SERVIÇO PONTUAL / TREINAMENTO (Marcelo Silva - PF)
        if c_marcelo:
            prop3 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-003",
                cliente_id=c_marcelo.id,
                data_criacao=date.today() - relativedelta(days=1),
                validade_dias=10,
                condicoes_pagamento="PIX / Transferência bancária no encerramento do treinamento",
                observacoes="Material didático digital e emissão de certificados individuais inclusos.",
                status="Aguardando Aprovação",
                tipo_cobranca="pontual",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(prop3)
            db.session.flush()

            item3 = ItemProposta(
                proposta_id=prop3.id,
                tipo_servico_id=servicos_criados["Treinamento e Capacitação Técnica de Equipe"].id,
                valor_unitario=950.00,
                descricao_personalizada="Capacitação presencial técnica para equipe operacional de 6 pessoas."
            )
            db.session.add(item3)
            propostas_cadastradas += 1

        # PROPOSTA 4: INSPEÇÃO DE SPDA (Posto Estrela)
        if c_posto:
            prop4 = Proposta(
                empresa_id=empresa.id,
                numero_proposta="PROP-2026-004",
                cliente_id=c_posto.id,
                data_criacao=date.today(),
                validade_dias=15,
                condicoes_pagamento="Boleto bancário em 2x (Entrada + 30 dias)",
                observacoes="Relatório fotográfico completo em conformidade com as normas vigentes.",
                status="Aguardando Aprovação",
                tipo_cobranca="pontual",
                periodicidade="mensal",
                dia_vencimento=10
            )
            db.session.add(prop4)
            db.session.flush()

            item4 = ItemProposta(
                proposta_id=prop4.id,
                tipo_servico_id=servicos_criados["Inspeção e Medição Ôhmica de SPDA (Pára-raios)"].id,
                valor_unitario=1500.00,
                descricao_personalizada="Medição ôhmica da cobertura das bombas e prédio de conveniência."
            )
            db.session.add(item4)
            propostas_cadastradas += 1

        db.session.commit()
        print(f">> Sucesso! {len(catalogo)} serviços cadastrados no Catálogo e {propostas_cadastradas} propostas comerciais vinculadas aos clientes.")