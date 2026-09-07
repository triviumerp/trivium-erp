import os
import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, limiter
from models import Empresa, Usuario

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
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        usuario = Usuario.query.filter_by(email=email).first()

        if usuario and usuario.check_senha(senha):
            if not usuario.ativo:
                flash('Este usuário está inativo no sistema. Entre em contato com o suporte.', 'danger')
                return render_template('auth/login.html')

            session.permanent = True
            login_user(usuario, remember=True)
            flash(f'Bem-vindo de volta, {usuario.nome}!', 'success')
            
            proxima_pagina = request.args.get('next')
            return redirect(proxima_pagina or url_for('index'))
        else:
            flash('E-mail ou senha incorretos. Verifique suas credenciais.', 'danger')

    return render_template('auth/login.html')

@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa', 'PJ')
        razao_social = (request.form.get('razao_social') or '').strip()
        cnpj_raw = request.form.get('cnpj', '')
        cpf_raw = request.form.get('cpf', '')
        doc_identificacao = re.sub(r'\D', '', cnpj_raw if tipo_pessoa == 'PJ' else cpf_raw)
        telefone = re.sub(r'\D', '', request.form.get('telefone', ''))
        nome_usuario = (request.form.get('nome_usuario') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        senha = request.form.get('senha', '')

        # 1. Validação de CPF para Pessoa Física
        if tipo_pessoa == 'PF' and not is_cpf_valido(doc_identificacao):
            flash('O CPF informado é inválido. Por favor, revise os dígitos.', 'danger')
            return render_template('auth/registro.html')

        # 2. Validação de Senha Forte
        senha_valida, msg_erro = validar_senha_forte(senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return render_template('auth/registro.html')

        # 3. Validação prévia de duplicidade de E-mail
        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está cadastrado no sistema. Faça login.', 'warning')
            return render_template('auth/registro.html')

        # 4. Validação prévia de duplicidade de CNPJ/CPF (se informado)
        if doc_identificacao and Empresa.query.filter_by(cnpj=doc_identificacao).first():
            flash('Este CNPJ/CPF já possui uma conta cadastrada.', 'warning')
            return render_template('auth/registro.html')

        try:
            # 5. Criação da Empresa Inquilina
            nova_empresa = Empresa(
                razao_social=razao_social if razao_social else (nome_usuario if tipo_pessoa == 'PF' else 'Minha Empresa'),
                nome_fantasia="Profissional Autônomo" if tipo_pessoa == 'PF' else None,
                cnpj=doc_identificacao if doc_identificacao else None,
                telefone=telefone,
                email=email,
                plano="Founder",
                status_assinatura="trial",
                data_vencimento=date.today() + relativedelta(days=14)
            )
            db.session.add(nova_empresa)
            db.session.flush()

            # 6. Criação do Usuário Administrador
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
            
            # Suporte tanto a método set_senha quanto gravação direta de hash
            if hasattr(novo_usuario, 'set_senha'):
                novo_usuario.set_senha(senha)
            else:
                novo_usuario.senha_hash = generate_password_hash(senha)

            db.session.add(novo_usuario)
            db.session.commit()

            flash('Cadastro realizado com sucesso! Faça login para começar a usar.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            print(f"\n[ERRO DETALHADO NO REGISTRO]: {type(e).__name__} - {e}\n")
            flash(f'Erro ao processar o cadastro: {str(e)}', 'danger')
            return render_template('auth/registro.html')

    return render_template('auth/registro.html')

@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        usuario = Usuario.query.filter_by(email=email).first()

        if usuario:
            flash('Se o e-mail estiver cadastrado, as instruções para redefinição foram enviadas.', 'info')
        else:
            flash('Se o e-mail estiver cadastrado, as instruções para redefinição foram enviadas.', 'info')

        return redirect(url_for('auth.login'))

    return render_template('auth/esqueci_senha.html') if os.path.exists('templates/auth/esqueci_senha.html') else render_template('auth/login.html')

@auth_bp.route('/redefinir-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha', '')
        confirma_senha = request.form.get('confirma_senha', '')

        senha_valida, msg_erro = validar_senha_forte(nova_senha)
        if not senha_valida:
            flash(msg_erro, 'warning')
            return redirect(request.url)

        if nova_senha != confirma_senha:
            flash('A nova senha e a confirmação não conferem.', 'warning')
            return redirect(request.url)

        flash('Senha alterada com sucesso! Faça login com a nova senha.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/redefinir_senha.html', token=token)

@auth_bp.route('/logout')
def logout():
    try:
        logout_user()
    except Exception:
        pass
    
    session.clear()
    
    flash('Você saiu da sua conta com segurança.', 'info')
    resposta = make_response(redirect(url_for('auth.login')))
    
    # Limpa o cookie principal de sessão e o token de "lembrar-me" do Flask-Login
    resposta.set_cookie('session', '', expires=0, max_age=0, path='/')
    resposta.set_cookie('remember_token', '', expires=0, max_age=0, path='/')
    
    return resposta