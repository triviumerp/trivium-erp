import os
import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from services.auth_token import gerar_token_recuperacao, validar_token_recuperacao
from services.email_service import enviar_email_recuperacao_senha

from extensions import db, limiter
from models import Empresa, Usuario, CupomDesconto

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# -----------------------------------------------------------------------------
# FUNÇÕES DE VALIDAÇÃO
# -----------------------------------------------------------------------------
def is_cpf_valido(cpf):
    if not cpf:
        return True
    cpf_limpo = re.sub(r'\D', '', cpf)
    if len(cpf_limpo) != 11 or cpf_limpo == cpf_limpo[0] * 11:
        return False
    soma = sum(int(cpf_limpo[i]) * (10 - i) for i in range(9))
    resto = 11 - (soma % 11)
    digito1 = 0 if resto in [10, 11] else resto
    if digito1 != int(cpf_limpo[9]):
        return False
    soma = sum(int(cpf_limpo[i]) * (11 - i) for i in range(10))
    resto = 11 - (soma % 11)
    digito2 = 0 if resto in [10, 11] else resto
    return digito2 == int(cpf_limpo[10])

def validar_senha_forte(senha):
    if not senha or len(senha) < 8:
        return False, "A senha deve conter no mínimo 8 caracteres."
    if not re.search(r"[A-Z]", senha):
        return False, "A senha deve conter pelo menos uma letra maiúscula."
    if not re.search(r"[a-z]", senha):
        return False, "A senha deve conter pelo menos uma letra minúscula."
    if not re.search(r"[0-9]", senha):
        return False, "A senha deve conter pelo menos um número."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-\\\/\[\]~+=\`]", senha):
        return False, "A senha deve conter pelo menos um caractere especial (ex: @, #, $, !)."
    return True, ""

# -----------------------------------------------------------------------------
# ROTAS DE AUTENTICAÇÃO
# -----------------------------------------------------------------------------

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        if current_user.nivel_acesso == 'afiliado':
            return redirect(url_for('painel_afiliado'))
        elif current_user.nivel_acesso == 'master':
            return redirect(url_for('admin_master_dashboard'))
        return redirect(url_for('index'))

    if request.method == 'POST':
        identificador = request.form.get('email', '').strip()
        senha = request.form.get('senha', '')

        usuario = None
        if '@' in identificador:
            usuario = Usuario.query.filter_by(email=identificador.lower()).first()
        else:
            doc_limpo = re.sub(r'\D', '', identificador)
            if doc_limpo:
                empresa_alvo = Empresa.query.filter_by(cnpj=doc_limpo).first()
                if empresa_alvo:
                    usuario = Usuario.query.filter_by(empresa_id=empresa_alvo.id).first()

        if usuario and usuario.check_senha(senha):
            if not usuario.ativo:
                flash('Este usuário está inativo no sistema. Entre em contato com o suporte.', 'danger')
                return render_template('auth/login.html')

            session.permanent = True
            login_user(usuario, remember=True)
            flash(f'Bem-vindo de volta, {usuario.nome}!', 'success')
            
            proxima_pagina = request.args.get('next')
            if proxima_pagina:
                return redirect(proxima_pagina)

            if usuario.nivel_acesso == 'afiliado':
                return redirect(url_for('painel_afiliado'))
            elif usuario.nivel_acesso == 'master':
                return redirect(url_for('admin_master_dashboard'))
            
            return redirect(url_for('index'))
        else:
            flash('Credenciais incorretas. Verifique seu e-mail ou CPF/CNPJ e senha.', 'danger')

    return render_template('auth/login.html')

@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    cupom_url = (request.args.get('ref') or '').strip().upper()
    afiliado_id_url = request.args.get('afiliado', type=int)

    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa', 'PJ')
        razao_social = (request.form.get('razao_social') or '').strip()
        cnpj_raw = request.form.get('cnpj', '')
        cpf_raw = request.form.get('cpf', '')
        doc_identificacao = re.sub(r'\D', '', cnpj_raw if tipo_pessoa == 'PJ' else cpf_raw)
        telefone = re.sub(r'\D', '', request.form.get('telefone', ''))
        nome_usuario = (request.form.get('nome_usuario') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        confirma_email = (request.form.get('confirma_email') or '').strip().lower()
        senha = request.form.get('senha', '')
        confirma_senha = request.form.get('confirma_senha', '')
        
        cupom_indicacao = (request.form.get('cupom_indicacao') or cupom_url).strip().upper()
        afiliado_form_id = request.form.get('afiliado_id', type=int) or afiliado_id_url

        # Validação de E-mail duplicado/confirmação
        if email != confirma_email:
            flash('O e-mail e a confirmação de e-mail não conferem.', 'warning')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

        # Validação de CPF
        if tipo_pessoa == 'PF' and not is_cpf_valido(doc_identificacao):
            flash('O CPF informado é inválido. Por favor, revise os dígitos.', 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

        # Identificação e Validação Antifraude do Parceiro
        cupom_obj = None
        parceiro_obj = None

        if cupom_indicacao:
            cupom_obj = CupomDesconto.query.filter_by(codigo=cupom_indicacao).first()
            if cupom_obj and cupom_obj.is_valido:
                parceiro_obj = cupom_obj.parceiro
            else:
                flash('O cupom informado é inválido ou está expirado.', 'warning')
                cupom_indicacao = None

        if not parceiro_obj and afiliado_form_id:
            parceiro_obj = Usuario.query.filter_by(id=afiliado_form_id, nivel_acesso='afiliado').first()

        if parceiro_obj:
            doc_afiliado = re.sub(r'\D', '', parceiro_obj.cpf_cnpj or '')
            if parceiro_obj.email.lower() == email or (doc_identificacao and doc_identificacao == doc_afiliado):
                flash('Não é permitido utilizar seu próprio vínculo ou cupom de afiliado.', 'danger')
                return render_template('auth/registro.html', cupom_ref='', afiliado_id=None)

        # Validação de Senha Forte
        senha_valida, msg_erro = validar_senha_forte(senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

        if senha != confirma_senha:
            flash('A senha e a confirmação de senha não conferem.', 'warning')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está cadastrado no sistema. Faça login.', 'warning')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

        if doc_identificacao and Empresa.query.filter_by(cnpj=doc_identificacao).first():
            flash('Este CNPJ/CPF já possui uma conta cadastrada.', 'warning')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

        try:
            comissao_pct = cupom_obj.percentual_comissao if cupom_obj else 20.0
            meses_limite = getattr(cupom_obj, 'meses_comissao_limite', 3) if cupom_obj else 3

            nova_empresa = Empresa(
                razao_social=razao_social if razao_social else (nome_usuario if tipo_pessoa == 'PF' else 'Minha Empresa'),
                nome_fantasia="Profissional Autônomo" if tipo_pessoa == 'PF' else None,
                cnpj=doc_identificacao if doc_identificacao else None,
                telefone=telefone,
                email=email,
                plano="Período de Testes (Trial)",
                status_assinatura="trial",
                valor_mensalidade=0.0,
                data_vencimento=date.today() + relativedelta(days=14),
                cupom_utilizado=cupom_obj.codigo if cupom_obj else None,
                afiliado_id=cupom_obj.id if cupom_obj else None
            )
            
            if hasattr(nova_empresa, 'percentual_comissao_parceiro'):
                nova_empresa.percentual_comissao_parceiro = comissao_pct
            if hasattr(nova_empresa, 'meses_comissao_limite'):
                nova_empresa.meses_comissao_limite = meses_limite

            db.session.add(nova_empresa)
            db.session.flush()

            novo_usuario = Usuario(
                empresa_id=nova_empresa.id,
                nome=nome_usuario,
                email=email,
                cargo="Administrador",
                nivel_acesso="admin",
                ativo=True,
                aceitou_termos_beta=True,
                data_aceite_termos=datetime.utcnow()
            )
            novo_usuario.set_senha(senha)
            db.session.add(novo_usuario)

            if cupom_obj:
                cupom_obj.usos_atuais = (cupom_obj.usos_atuais or 0) + 1

            db.session.commit()

            flash('Cadastro realizado com sucesso! Faça login para começar a usar.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao processar o cadastro: {str(e)}', 'danger')
            return render_template('auth/registro.html', cupom_ref=cupom_indicacao, afiliado_id=afiliado_form_id)

    return render_template('auth/registro.html', cupom_ref=cupom_url, afiliado_id=afiliado_id_url)


@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    email_enviado_mascarado = None
    disparo_solicitado = False

    if request.method == 'POST':
        identificador = request.form.get('email', '').strip().lower()
        usuario = None

        if '@' in identificador:
            usuario = Usuario.query.filter_by(email=identificador).first()
        else:
            doc_limpo = re.sub(r'\D', '', identificador)
            if doc_limpo:
                empresa_alvo = Empresa.query.filter_by(cnpj=doc_limpo).first()
                if empresa_alvo:
                    usuario = Usuario.query.filter_by(empresa_id=empresa_alvo.id).first()

        if usuario:
            token = gerar_token_recuperacao(usuario.email)
            link_reset = url_for('auth.redefinir_senha', token=token, _external=True)
            enviar_email_recuperacao_senha(usuario.email, usuario.nome, link_reset)

            # Mascara o e-mail: sergio@gmail.com -> s***o@g***.com
            partes = usuario.email.split('@')
            user_parte = partes[0]
            dom_parte = partes[1] if len(partes) > 1 else ""
            
            user_masc = user_parte[0] + "***" + (user_parte[-1] if len(user_parte) > 1 else "")
            dom_masc = dom_parte[0] + "***." + dom_parte.split('.')[-1] if '.' in dom_parte else dom_parte
            email_enviado_mascarado = f"{user_masc}@{dom_masc}"

        disparo_solicitado = True
        return render_template('auth/esqueci_senha.html', 
                               sucesso_envio=disparo_solicitado, 
                               email_destino=email_enviado_mascarado)

    return render_template('auth/esqueci_senha.html', sucesso_envio=False)


@auth_bp.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    # Valida o token criptográfico (tempo limite: 30 min)
    email = validar_token_recuperacao(token, max_age_segundos=1800)
    if not email:
        flash('O link de recuperação é inválido ou expirou. Solicite um novo envio.', 'danger')
        return redirect(url_for('auth.esqueci_senha'))

    usuario = Usuario.query.filter_by(email=email).first_or_404()

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha', '')
        confirma_senha = request.form.get('confirma_senha', '')

        senha_valida, msg_erro = validar_senha_forte(nova_senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return redirect(request.url)

        if nova_senha != confirma_senha:
            flash('A nova palavra-passe e a confirmação não conferem.', 'warning')
            return redirect(request.url)

        # Grava a nova palavra-passe com hash seguro
        usuario.set_senha(nova_senha)
        db.session.commit()

        flash('Palavra-passe atualizada com sucesso! Inicie sessão com os novos dados.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/redefinir_senha.html', token=token)

@auth_bp.route('/seja-parceiro', methods=['GET', 'POST'])
def registro_afiliado():
    if current_user.is_authenticated:
        return redirect(url_for('painel_afiliado'))

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        confirma_email = (request.form.get('confirma_email') or '').strip().lower()
        cpf_cnpj = (request.form.get('cpf_cnpj') or '').strip()
        rede_social = (request.form.get('rede_social_principal') or '').strip()
        tipo_parceiro = request.form.get('tipo_parceiro', 'Outros')
        senha = request.form.get('senha', '')
        confirma_senha = request.form.get('confirma_senha', '')

        if email != confirma_email:
            flash('O e-mail e a confirmação de e-mail não conferem.', 'warning')
            return render_template('auth/registro_afiliado.html')

        senha_valida, msg_erro = validar_senha_forte(senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return render_template('auth/registro_afiliado.html')

        if senha != confirma_senha:
            flash('As senhas não conferem.', 'warning')
            return render_template('auth/registro_afiliado.html')

        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está cadastrado. Faça login na sua conta.', 'warning')
            return render_template('auth/registro_afiliado.html')

        novo_user = Usuario(
            empresa_id=None,
            nome=nome,
            email=email,
            cpf_cnpj=cpf_cnpj,
            rede_social_principal=rede_social,
            tipo_parceiro=tipo_parceiro,
            cargo="Afiliado Parceiro",
            nivel_acesso="afiliado",
            ativo=True,
            status_aprovacao="pendente"
        )
        novo_user.set_senha(senha)
        db.session.add(novo_user)
        db.session.flush()

        codigo_sugerido = re.sub(r'[^A-Z0-9]', '', nome.split()[0].upper()) + "10"
        
        novo_cupom = CupomDesconto(
            usuario_id=novo_user.id,
            codigo=codigo_sugerido,
            percentual_desconto=10.0,
            percentual_comissao=20.0,
            limite_usos=100,
            ativo=False
        )
        db.session.add(novo_cupom)
        db.session.commit()

        login_user(novo_user)
        flash('Cadastro realizado! Seus dados foram enviados para análise da equipe.', 'info')
        return redirect(url_for('painel_afiliado'))

    return render_template('auth/registro_afiliado.html')

@auth_bp.route('/logout')
def logout():
    try:
        logout_user()
    except Exception:
        pass
    
    session.clear()
    
    flash('Você saiu da sua conta com segurança.', 'info')
    resposta = make_response(redirect(url_for('auth.login')))
    resposta.set_cookie('session', '', expires=0, max_age=0, path='/')
    resposta.set_cookie('remember_token', '', expires=0, max_age=0, path='/')
    
    return resposta