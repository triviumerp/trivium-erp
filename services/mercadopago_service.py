import os
import mercadopago
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

PLANOS_CONFIG = {
    'MENSAL': {
        'nome': 'Mensal',
        'valor_total': 39.90,
        'valor_exibicao': 39.90,
        'parcelas': 1,
        'dias_validade': 30
    },
    'SEMESTRAL': {
        'nome': 'Semestral',
        'valor_total': 209.40,
        'valor_exibicao': 34.90,
        'parcelas': 6,
        'dias_validade': 180
    },
    'ANUAL': {
        'nome': 'Anual',
        'valor_total': 358.80,
        'valor_exibicao': 29.90,
        'parcelas': 12,
        'dias_validade': 365
    }
}

def _get_sdk():
    token = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "").strip()
    if not token:
        return None
    return mercadopago.SDK(token)

def _limpar_documento(doc):
    if not doc:
        return ""
    return "".join([c for c in str(doc) if c.isdigit()])

def criar_cobranca_mercadopago(empresa, nome_plano, valor, forma_pagamento, cartao_dados=None, remote_ip=None, parcelas=1):
    sdk = _get_sdk()
    if not sdk:
        return {"sucesso": False, "mensagem": "Credenciais do Mercado Pago não configuradas no servidor."}

    doc_limpo = _limpar_documento(empresa.cnpj)
    tipo_doc = "CNPJ" if len(doc_limpo) == 14 else "CPF"

    chave_plano = str(nome_plano).upper().replace("PLANO ", "").strip()
    if 'ANUAL' in chave_plano:
        cfg = PLANOS_CONFIG['ANUAL']
    elif 'SEMESTRAL' in chave_plano:
        cfg = PLANOS_CONFIG['SEMESTRAL']
    else:
        cfg = PLANOS_CONFIG['MENSAL']

    nome_pagador = empresa.razao_social or empresa.nome_fantasia or "Cliente Trivium"
    partes_nome = nome_pagador.split()
    primeiro_nome = partes_nome[0]
    sobrenome = " ".join(partes_nome[1:]) if len(partes_nome) > 1 else "Empresa"
    email_pagador = empresa.email or "contato@triviumerp.com.br"

    # 1. PIX
    if forma_pagamento == 'PIX':
        payment_data = {
            "transaction_amount": float(valor),
            "description": f"Assinatura Trivium ERP - {cfg['nome']} (PIX)",
            "payment_method_id": "pix",
            "payer": {
                "email": email_pagador,
                "first_name": primeiro_nome,
                "last_name": sobrenome,
                "identification": {
                    "type": tipo_doc,
                    "number": doc_limpo
                }
            },
            "external_reference": f"emp_{empresa.id}_{cfg['nome']}"
        }

        payment_response = sdk.payment().create(payment_data)
        payment = payment_response.get("response", {})

        if payment_response.get("status") in (200, 201) and "id" in payment:
            poi = payment.get("point_of_interaction", {}).get("transaction_data", {})
            return {
                "sucesso": True,
                "dados": payment,
                "pix": {
                    "encodedImage": poi.get("qr_code_base64", ""),
                    "payload": poi.get("qr_code", ""),
                    "ticket_url": poi.get("ticket_url", "")
                },
                "plano_info": cfg
            }
        else:
            msg = payment.get("message", "Erro ao gerar cobrança Pix no Mercado Pago.")
            return {"sucesso": False, "mensagem": msg}

    # 2. BOLETO
    elif forma_pagamento == 'BOLETO':
        payment_data = {
            "transaction_amount": float(valor),
            "description": f"Assinatura Trivium ERP - {cfg['nome']} (Boleto)",
            "payment_method_id": "bolbradesco",
            "payer": {
                "email": email_pagador,
                "first_name": primeiro_nome,
                "last_name": sobrenome,
                "identification": {
                    "type": tipo_doc,
                    "number": doc_limpo
                },
                "address": {
                    "zip_code": _limpar_documento(empresa.cep) or "08696040",
                    "street_name": empresa.logradouro or "Rua Comercial",
                    "street_number": str(empresa.numero or "100"),
                    "neighborhood": empresa.bairro or "Centro",
                    "city": empresa.cidade or "Suzano",
                    "federal_unit": empresa.estado or "SP"
                }
            },
            "external_reference": f"emp_{empresa.id}_{cfg['nome']}"
        }

        payment_response = sdk.payment().create(payment_data)
        payment = payment_response.get("response", {})

        if payment_response.get("status") in (200, 201) and "id" in payment:
            url_boleto = payment.get("transaction_details", {}).get("external_resource_url")
            return {
                "sucesso": True,
                "dados": payment,
                "bankSlipUrl": url_boleto,
                "invoiceUrl": url_boleto,
                "plano_info": cfg
            }
        else:
            msg = payment.get("message", "Erro ao gerar Boleto no Mercado Pago.")
            return {"sucesso": False, "mensagem": msg}

    # 3. CARTÃO DE CRÉDITO
    elif forma_pagamento == 'CREDIT_CARD':
        token_cartao = cartao_dados.get("token") if cartao_dados else None
        payment_data = {
            "transaction_amount": float(valor),
            "token": token_cartao,
            "description": f"Assinatura Trivium ERP - {cfg['nome']}",
            "installments": int(parcelas),
            "payment_method_id": cartao_dados.get("payment_method_id", "visa") if cartao_dados else "visa",
            "payer": {
                "email": email_pagador,
                "identification": {
                    "type": tipo_doc,
                    "number": doc_limpo
                }
            },
            "external_reference": f"emp_{empresa.id}_{cfg['nome']}"
        }

        payment_response = sdk.payment().create(payment_data)
        payment = payment_response.get("response", {})

        if payment_response.get("status") in (200, 201) and payment.get("status") == "approved":
            return {"sucesso": True, "dados": payment, "plano_info": cfg}
        else:
            msg = payment.get("status_detail", "Cartão recusado ou dados inválidos.")
            return {"sucesso": False, "mensagem": f"Transação não autorizada: {msg}"}

    return {"sucesso": False, "mensagem": "Método de pagamento inválido."}

def criar_preferencia_mercado_pago(empresa, plano, valor_total, cupom_codigo=None):
    sdk = _get_sdk()
    if not sdk:
        return {"sucesso": False, "mensagem": "Credenciais do Mercado Pago não configuradas no servidor."}

    chave_plano = str(plano).upper().replace("PLANO ", "").strip()
    if 'ANUAL' in chave_plano:
        cfg = PLANOS_CONFIG['ANUAL']
    elif 'SEMESTRAL' in chave_plano:
        cfg = PLANOS_CONFIG['SEMESTRAL']
    else:
        cfg = PLANOS_CONFIG['MENSAL']

    # Se houver desconto de cupom validado no front, usa o valor com desconto
    valor_final = float(valor_total) if valor_total else float(cfg['valor_total'])

    base_url = "https://app.triviumerp.com.br" # Substitua se necessário pelo seu domínio em produção

    preference_data = {
        "items": [
            {
                "title": f"Assinatura Trivium ERP - Plano {cfg['nome']}",
                "quantity": 1,
                "unit_price": valor_final,
                "currency_id": "BRL"
            }
        ],
        "payer": {
            "email": empresa.email or "contato@triviumerp.com.br",
            "name": empresa.razao_social or "Cliente Trivium"
        },
        "back_urls": {
            "success": f"{base_url}/configuracoes/perfil#tab-planos",
            "failure": f"{base_url}/configuracoes/perfil#tab-planos",
            "pending": f"{base_url}/configuracoes/perfil#tab-planos"
        },
        "auto_return": "approved",
        "external_reference": f"emp_{empresa.id}_{cfg['nome']}"
    }

    try:
        preference_response = sdk.preference().create(preference_data)
        resultado = preference_response.get("response", {})
        
        if preference_response.get("status") in (200, 201) and "init_point" in resultado:
            return {
                "sucesso": True,
                "init_point": resultado.get("init_point"),
                "sandbox_init_point": resultado.get("sandbox_init_point")
            }
        else:
            return {"sucesso": False, "mensagem": "Erro ao criar preferência de pagamento no Mercado Pago."}
    except Exception as e:
        return {"sucesso": False, "mensagem": str(e)}