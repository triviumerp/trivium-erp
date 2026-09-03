from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from datetime import date
from datetime import datetime
from dateutil.relativedelta import relativedelta
import re

from extensions import db
from models import Empresa, Usuario
from services.auth_token import gerar_token_ativacao, validar_token_ativacao, gerar_token_recuperacao, validar_token_recuperacao
from services.email_service import enviar_email_ativacao, enviar_email_recuperacao_senha

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def is_cpf_valido(cpf):
    """Validação matemática oficial do CPF por algoritmo de módulo 11."""
    if not cpf:
        return False
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


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')

        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and usuario.check_senha(senha):
            # Ativa automaticamente contas antigas que ficaram pendentes nos testes
            if not usuario.ativo:
                usuario.ativo = True
                db.session.commit()

            login_user(usuario, remember=True)
            flash(f'Bem-vindo de volta, {usuario.nome}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('E-mail ou senha incorretos.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/registro', methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa', 'PJ')
        razao_social = request.form.get('razao_social')
        doc_identificacao = request.form.get('cnpj') if tipo_pessoa == 'PJ' else request.form.get('cpf')
        telefone = request.form.get('telefone')
        nome_usuario = request.form.get('nome_usuario')
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha')

        # 1. Validação Obrigatória de CPF para Pessoa Física
        if tipo_pessoa == 'PF':
            if not is_cpf_valido(doc_identificacao):
                flash('O CPF informado é inválido. Por favor, confira os números digitados.', 'danger')
                return render_template('auth/registro.html')

        # 2. Verificação de Duplicidade de E-mail
        if Usuario.query.filter_by(email=email).first():
            flash('Este e-mail já está cadastrado no sistema.', 'warning')
            return render_template('auth/registro.html')

        # 3. Criação da Empresa Inquilina (Tenant)
        nova_empresa = Empresa(
            razao_social=razao_social,
            nome_fantasia="Profissional Autônomo" if tipo_pessoa == 'PF' else None,
            cnpj=doc_identificacao,
            telefone=telefone,
            email=email,
            plano="Founder",
            status_assinatura="trial",
            data_vencimento=date.today() + relativedelta(days=14)
        )
        db.session.add(nova_empresa)
        db.session.flush()

        # 4. Criação do Usuário com status ativo=False (Aguarda validação por e-mail)
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
        db.session.commit()

        # 5. Geração do Token e Envio do E-mail
        
        #try: 
            #token = gerar_token_ativacao(email)
            #link = url_for('auth.ativar_conta', token=token, _external=True)
            #enviar_email_ativacao(email, nome_usuario, link)
        #except Exception as e:
            #print(f"[ERRO DISPARO EMAIL]: {e}")
            
        flash('Cadastro realizado com sucesso! Você já pode entrar com seu e-mail e senha.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/registro.html')

@auth_bp.route('/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        usuario = Usuario.query.filter_by(email=email).first()

        if usuario:
            token = gerar_token_recuperacao(usuario.email)
            link = url_for('auth.redefinir_senha', token=token, _external=True)
            enviar_email_recuperacao_senha(usuario.email, usuario.nome, link)

        # Mensagem com alerta de Spam/Lixo Eletrônico
        flash('Se o e-mail estiver cadastrado, enviamos um link para redefinir sua senha. Caso não visualize na Caixa de Entrada, confira sua pasta de Spam ou Lixo Eletrônico.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/esqueci_senha.html')


@auth_bp.route('/redefinir-senha', methods=['GET', 'POST'])
def redefinir_senha():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    token = request.args.get('token')
    email = validar_token_recuperacao(token)

    if not email:
        flash('O link de recuperação é inválido ou expirou (validade de 30 minutos). Solicite uma nova recuperação.', 'danger')
        return redirect(url_for('auth.esqueci_senha'))

    usuario = Usuario.query.filter_by(email=email).first_or_404()

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha')
        confirma_senha = request.form.get('confirma_senha')

        if nova_senha != confirma_senha:
            flash('As senhas não coincidem. Digite novamente.', 'warning')
            return render_template('auth/redefinir_senha.html', token=token)

        usuario.set_senha(nova_senha)
        db.session.commit()
        flash('Sua senha foi redefinida com sucesso! Faça login com suas novas credenciais.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/redefinir_senha.html', token=token)

@auth_bp.route('/ativar-conta')
def ativar_conta():
    token = request.args.get('token')
    email = validar_token_ativacao(token)

    if not email:
        flash('O link de ativação é inválido ou expirou. Tente fazer login para receber um novo link.', 'danger')
        return redirect(url_for('auth.login'))

    usuario = Usuario.query.filter_by(email=email).first_or_404()
    if usuario.ativo:
        flash('Sua conta já está ativada. Faça login para acessar o sistema.', 'info')
    else:
        usuario.ativo = True
        db.session.commit()
        flash('Conta ativada com sucesso! Você já pode entrar no sistema.', 'success')

    return redirect(url_for('auth.login'))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu da sua conta com segurança.', 'info')
    return redirect(url_for('auth.login'))
