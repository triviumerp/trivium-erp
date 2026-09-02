import html
import io
import os
import re
import time
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta


# Carrega as variáveis do arquivo .env automaticamente
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

# Relatórios PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

# Extensões e Modelos Modulares
from extensions import db, login_manager
from models import (
    Empresa, Usuario, Cliente, Documento, TipoServico, 
    ServicoCliente, Proposta, ItemProposta, ContratoRecorrente, 
    Fatura, ParcelaFatura, Documento, ChamadoSuporte, MensagemChamado, 
)
from auth.routes import auth_bp

from datetime import datetime
from functools import wraps
from flask import abort, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user, login_user
import time
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from extensions import db
from models import Empresa, Usuario, ChamadoSuporte, MensagemChamado

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA APLICAÇÃO
# -----------------------------------------------------------------------------
app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'trivium_erp_chave_secreta_producao_2026')

# Conexão com o PostgreSQL Local
URL_LOCAL_POSTGRES = "postgresql://postgres:admin@127.0.0.1:5432/trivium_db?client_encoding=utf8"
# Ajuste obrigatório da URL do PostgreSQL no Render
uri_banco = os.getenv('DATABASE_URL', '')
if uri_banco.startswith("postgres://"):
    uri_banco = uri_banco.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri_banco
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# CORREÇÃO DO POOL DE CONEXÃO SSL
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300
}
# Inicialização
db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor, faça login para acessar o sistema.'
login_manager.login_message_category = 'warning'

app.register_blueprint(auth_bp)

# Cria automaticamente todas as tabelas no PostgreSQL na inicialização (mesmo rodando via Gunicorn)
with app.app_context():
    try:
        db.create_all()
    except Exception as e:
        print(f"[ERRO AO CRIAR TABELAS]: {e}")

def _limpar_texto(texto):
    """Garante que caracteres especiais como & e tags não quebrem o parser XML do ReportLab."""
    if not texto:
        return ""
    return html.escape(str(texto))


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

def master_required(f):
  @wraps(f)
  def decorated_function(*args, **kwargs):
    if not current_user.is_authenticated or current_user.nivel_acesso != 'master':
      abort(403)
    return f(*args, **kwargs)

  return decorated_function

# 1. Painel Master Geral & Gestão de Empresas
@app.route('/admin/master')
@login_required
@master_required
def admin_master_dashboard():
  empresas = Empresa.query.order_by(Empresa.data_criacao.desc()).all()
  total_empresas = len(empresas)
  total_ativas = len([e for e in empresas if e.status_assinatura == 'ativo'])
  total_trial = len([e for e in empresas if e.status_assinatura == 'trial'])
  total_bloqueadas = len(
      [e for e in empresas if e.status_assinatura not in ['ativo', 'trial']]
  )

  return render_template(
      'admin/master_dashboard.html',
      empresas=empresas,
      total_empresas=total_empresas,
      total_ativas=total_ativas,
      total_trial=total_trial,
      total_bloqueadas=total_bloqueadas,
  )


# 2. Central Global de Chamados (Todos os Clientes)
@app.route('/admin/master/chamados')
@login_required
@master_required
def admin_master_chamados():
  filtro = request.args.get('status', 'todos')
  query = ChamadoSuporte.query

  if filtro == 'abertos':
    query = query.filter_by(status='Aberto')
  elif filtro == 'em_atendimento':
    query = query.filter_by(status='Em Atendimento')
  elif filtro == 'resolvidos':
    query = query.filter_by(status='Resolvido')

  chamados = query.order_by(ChamadoSuporte.data_abertura.desc()).all()

  qtd_abertos = ChamadoSuporte.query.filter_by(status='Aberto').count()
  qtd_em_analise = ChamadoSuporte.query.filter_by(
      status='Em Atendimento'
  ).count()
  qtd_resolvidos = ChamadoSuporte.query.filter_by(status='Resolvido').count()
  total_historico = ChamadoSuporte.query.count()

  return render_template(
      'admin/master_chamados.html',
      chamados=chamados,
      filtro_atual=filtro,
      qtd_abertos=qtd_abertos,
      qtd_em_analise=qtd_em_analise,
      qtd_resolvidos=qtd_resolvidos,
      total_historico=total_historico,
  )


# 3. Atendimento e Resposta ao Chamado como Administrador Master
@app.route('/admin/master/chamados/<int:id>', methods=['GET', 'POST'])
@login_required
@master_required
def admin_atender_chamado(id):
  chamado = ChamadoSuporte.query.get_or_404(id)

  if request.method == 'POST':
    conteudo = request.form.get('mensagem')
    novo_status = request.form.get('novo_status')
    arquivo = request.files.get('anexo')

    filename = None
    if arquivo and arquivo.filename:
      filename = f'suporte_{chamado.id}_{int(time.time())}_{secure_filename(arquivo.filename)}'
      upload_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads')
      os.makedirs(upload_folder, exist_ok=True)
      arquivo.save(os.path.join(upload_folder, filename))

    if conteudo:
      msg_suporte = MensagemChamado(
          chamado_id=chamado.id,
          usuario_id=current_user.id,
          conteudo=conteudo,
          is_suporte=True,  # Identifica que a resposta partiu do Master
          anexo_filename=filename,
      )
      db.session.add(msg_suporte)

    if novo_status:
      chamado.status = novo_status
      if novo_status == 'Resolvido':
        chamado.data_fechamento = datetime.utcnow()

    db.session.commit()
    flash(f'Chamado {chamado.numero_protocolo} atualizado!', 'success')
    return redirect(url_for('admin_atender_chamado', id=chamado.id))

  return render_template('admin/master_atender_chamado.html', chamado=chamado)


@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

# -----------------------------------------------------------------------------
# 3. CONTEXT PROCESSOR (Injeção de Perfil)
# -----------------------------------------------------------------------------

@app.context_processor
def utility_processor():
    perfil = None
    if current_user.is_authenticated:
        perfil = current_user.empresa
    return dict(perfil_empresa=perfil)

# -----------------------------------------------------------------------------
# 4. ROTAS DO PAINEL DASHBOARD & CARTEIRA DE CLIENTES
# -----------------------------------------------------------------------------

@app.route('/')
@login_required
def index():
    hoje = date.today()
    proximos_7_dias = hoje + timedelta(days=7)

    # 1. Indicadores de Contagem e Valores
    total_clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).count()

    propostas_abertas = Proposta.query.filter_by(empresa_id=current_user.empresa_id, status='Aguardando Aprovação').all()
    qtd_propostas_negociacao = len(propostas_abertas)
    valor_propostas_abertas = sum(p.valor_total for p in propostas_abertas)

    qtd_servicos_execucao = ServicoCliente.query.filter_by(empresa_id=current_user.empresa_id).filter(
        ServicoCliente.status.in_(['Em Andamento', 'Bloqueado'])
    ).count()

    # 2. Financeiro do Mês
    todas_parcelas = ParcelaFatura.query.filter_by(empresa_id=current_user.empresa_id).all()
    total_recebido_mes = sum(p.valor for p in todas_parcelas if p.status == 'Pago')

    # 3. Títulos em Atraso
    titulos_atrasados = [p for p in todas_parcelas if p.status != 'Pago' and p.data_vencimento and p.data_vencimento < hoje]
    qtd_titulos_atrasados = len(titulos_atrasados)
    valor_titulos_atrasados = sum(p.valor for p in titulos_atrasados)

    # 4. Listagens Dinâmicas da Tela Inicial
    proximos_servicos = ServicoCliente.query.filter_by(empresa_id=current_user.empresa_id).filter(
        ServicoCliente.status.in_(['Em Andamento', 'Pendente', 'Bloqueado'])
    ).order_by(ServicoCliente.data_previsao.asc().nullslast()).limit(6).all()

    titulos_proximos = ParcelaFatura.query.filter_by(empresa_id=current_user.empresa_id).filter(
        ParcelaFatura.status != 'Pago',
        ParcelaFatura.data_vencimento >= hoje,
        ParcelaFatura.data_vencimento <= proximos_7_dias
    ).order_by(ParcelaFatura.data_vencimento.asc()).limit(5).all()

    return render_template(
        'index.html',
        hoje=hoje,
        total_clientes=total_clientes,
        qtd_propostas_negociacao=qtd_propostas_negociacao,
        valor_propostas_abertas=valor_propostas_abertas,
        qtd_servicos_execucao=qtd_servicos_execucao,
        total_recebido_mes=total_recebido_mes,
        qtd_titulos_atrasados=qtd_titulos_atrasados,
        valor_titulos_atrasados=valor_titulos_atrasados,
        proximos_servicos=proximos_servicos,
        titulos_proximos=titulos_proximos
    )


@app.route('/clientes')
@login_required
def listar_clientes():
    busca = request.args.get('busca', '')
    query = Cliente.query.filter_by(empresa_id=current_user.empresa_id)

    if busca:
        query = query.filter(
            (Cliente.nome.ilike(f'%{busca}%')) | 
            (Cliente.cnpj_cpf.ilike(f'%{busca}%')) |
            (Cliente.cidade.ilike(f'%{busca}%'))
        )

    clientes = query.order_by(Cliente.nome).all()
    return render_template('clientes.html', clientes=clientes, busca=busca)


@app.route('/cliente/novo', methods=['GET', 'POST'])
@login_required
def novo_cliente():
    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa', 'PJ')
        nome = request.form.get('nome')
        nome_fantasia = request.form.get('nome_fantasia')
        cnpj_cpf = request.form.get('cnpj') if tipo_pessoa == 'PJ' else request.form.get('cpf')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        
        # Criação e persistência do novo cliente
        novo_cli = Cliente(
            empresa_id=current_user.empresa_id,
            nome=nome,
            nome_fantasia=nome_fantasia,
            cnpj_cpf=cnpj_cpf,
            inscricao_estadual=request.form.get('inscricao_estadual'),
            responsavel=request.form.get('responsavel'),
            telefone=telefone,
            telefone_secundario=request.form.get('telefone_secundario'),
            email=email,
            email_financeiro=request.form.get('email_financeiro'),
            cep=request.form.get('cep'),
            logradouro=request.form.get('logradouro'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado'),
            observacoes=request.form.get('observacoes')
        )
        db.session.add(novo_cli)
        db.session.commit()

        flash(f'Cliente "{novo_cli.nome}" cadastrado com sucesso!', 'success')

        # Se o usuário clicou em "Salvar e Gerar Proposta"
        acao = request.form.get('acao')
        if acao == 'salvar_e_proposta':
            # Redireciona para a lista de propostas abrindo automaticamente o modal com o cliente pré-selecionado
            return redirect(url_for('listar_propostas', cliente_id=novo_cli.id, abrir_modal='true'))

        return redirect(url_for('listar_clientes'))

    return render_template('cadastro.html', cliente=None)


@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_cliente(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()

    if request.method == 'POST':
        tipo_pessoa = request.form.get('tipo_pessoa')
        doc_identificacao = request.form.get('cnpj') if tipo_pessoa == 'PJ' else request.form.get('cpf')

        if tipo_pessoa == 'PF' and doc_identificacao:
            if not is_cpf_valido(doc_identificacao):
                flash('O CPF informado é inválido. Por favor, revise os dígitos.', 'danger')
                return render_template('cadastro.html', cliente=cliente)

        cliente.nome = request.form.get('nome')
        cliente.nome_fantasia = request.form.get('nome_fantasia') if tipo_pessoa == 'PJ' else None
        cliente.cnpj_cpf = doc_identificacao
        cliente.inscricao_estadual = request.form.get('inscricao_estadual') if tipo_pessoa == 'PJ' else None
        cliente.responsavel = request.form.get('responsavel')
        cliente.telefone = request.form.get('telefone')
        cliente.telefone_secundario = request.form.get('telefone_secundario')
        cliente.email = request.form.get('email')
        cliente.email_financeiro = request.form.get('email_financeiro')
        cliente.cep = request.form.get('cep')
        cliente.logradouro = request.form.get('logradouro')
        cliente.numero = request.form.get('numero')
        cliente.complemento = request.form.get('complemento')
        cliente.bairro = request.form.get('bairro')
        cliente.cidade = request.form.get('cidade')
        cliente.estado = request.form.get('estado')
        cliente.observacoes = request.form.get('observacoes')

        db.session.commit()
        flash('Cadastro atualizado com sucesso!', 'success')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    return render_template('cadastro.html', cliente=cliente)


@app.route('/cliente/deletar/<int:id>')
@login_required
def deletar_cliente(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente e todo o histórico vinculado foram removidos.', 'warning')
    return redirect(url_for('index'))


@app.route('/cliente/<int:id>')
@login_required
def detalhe_cliente(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    documentos = Documento.query.filter_by(cliente_id=id).order_by(Documento.data_upload.desc()).all()
    return render_template('detalhe_cliente.html', cliente=cliente, documentos=documentos)


@app.route('/cliente/<int:id>/upload', methods=['POST'])
@login_required
def upload_documento(id):
    cliente = Cliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    if 'arquivo' not in request.files:
        flash('Nenhum arquivo enviado!', 'danger')
        return redirect(url_for('detalhe_cliente', id=id))
        
    file = request.files['arquivo']
    tipo = request.form.get('tipo_documento')

    if file.filename == '':
        flash('Nenhum arquivo selecionado!', 'danger')
        return redirect(url_for('detalhe_cliente', id=id))

    if file:
        nome_limpo = secure_filename(file.filename)
        nome_salvo = f"doc_{cliente.id}_{int(datetime.utcnow().timestamp())}_{nome_limpo}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_salvo))

        doc = Documento(cliente_id=cliente.id, nome_arquivo=nome_salvo, tipo_documento=tipo)
        db.session.add(doc)
        db.session.commit()
        flash('Documento anexado com sucesso!', 'success')

    return redirect(url_for('detalhe_cliente', id=id))


@app.route('/documento/deletar/<int:doc_id>')
@login_required
def deletar_documento(doc_id):
    doc = Documento.query.join(Cliente).filter(Documento.id == doc_id, Cliente.empresa_id == current_user.empresa_id).first_or_404()
    cliente_id = doc.cliente_id

    caminho = os.path.join(app.config['UPLOAD_FOLDER'], doc.nome_arquivo)
    if os.path.exists(caminho):
        os.remove(caminho)

    db.session.delete(doc)
    db.session.commit()
    flash('Documento removido com sucesso.', 'info')
    return redirect(url_for('detalhe_cliente', id=cliente_id))


@app.route('/uploads/<path:filename>')
@login_required
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# -----------------------------------------------------------------------------
# 5. ROTAS DE PROPOSTAS COMERCIAIS
# -----------------------------------------------------------------------------

@app.route('/propostas')
@login_required
def listar_propostas():
    filtro_atual = request.args.get('filtro', 'ativas')
    query = Proposta.query.filter_by(empresa_id=current_user.empresa_id)

    if filtro_atual == 'ativas':
        propostas = query.filter_by(status='Aguardando Aprovação').order_by(Proposta.data_criacao.desc()).all()
    elif filtro_atual == 'aprovadas':
        propostas = query.filter_by(status='Aprovado').order_by(Proposta.data_criacao.desc()).all()
    elif filtro_atual == 'canceladas':
        propostas = query.filter_by(status='Cancelado').order_by(Proposta.data_criacao.desc()).all()
    else:
        propostas = query.order_by(Proposta.data_criacao.desc()).all()

    todas = query.all()
    total_aguardando = sum(p.valor_total for p in todas if p.status == 'Aguardando Aprovação')
    total_aprovadas = sum(p.valor_total for p in todas if p.status == 'Aprovado')
    qtd_aguardando = len([p for p in todas if p.status == 'Aguardando Aprovação'])

    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome).all()
    tipos_servico = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()

    return render_template(
        'propostas.html',
        propostas=propostas,
        filtro_atual=filtro_atual,
        total_aguardando=total_aguardando,
        total_aprovadas=total_aprovadas,
        qtd_aguardando=qtd_aguardando,
        clientes=clientes,
        tipos_servico=tipos_servico
    )


@app.route('/propostas/nova', methods=['POST'])
@login_required
def criar_proposta():
    cliente_id = int(request.form.get('cliente_id'))
    validade_dias = int(request.form.get('validade_dias') or 15)
    condicoes = request.form.get('condicoes_pagamento') or 'Conforme alinhamento comercial'
    observacoes = request.form.get('observacoes')
    
    tipo_cobranca = request.form.get('tipo_cobranca', 'pontual')
    periodicidade = request.form.get('periodicidade', 'mensal')
    dia_vencimento = int(request.form.get('dia_vencimento') or 10)

    # Dados de Entrada e Parcelamento
    exige_entrada = request.form.get('exige_entrada') == 'on' or request.form.get('exige_entrada') == 'true'
    valor_entrada = float(request.form.get('valor_entrada') or 0.0)
    forma_pagamento_entrada = request.form.get('forma_pagamento_entrada', 'PIX')
    qtd_parcelas = int(request.form.get('qtd_parcelas') or 1)
    forma_pagamento_parcelas = request.form.get('forma_pagamento_parcelas', 'Boleto Bancário')
    intervalo_dias = int(request.form.get('intervalo_dias') or 30)
    
    total_existentes = Proposta.query.filter_by(empresa_id=current_user.empresa_id).count() + 1
    numero_proposta = f"PROP-{date.today().year}-{total_existentes:03d}"

    nova_prop = Proposta(
        empresa_id=current_user.empresa_id,
        numero_proposta=numero_proposta,
        cliente_id=cliente_id,
        validade_dias=validade_dias,
        condicoes_pagamento=condicoes,
        observacoes=observacoes,
        status='Aguardando Aprovação',
        tipo_cobranca=tipo_cobranca,
        periodicidade=periodicidade,
        dia_vencimento=dia_vencimento,
        exige_entrada=exige_entrada,
        valor_entrada=valor_entrada,
        forma_pagamento_entrada=forma_pagamento_entrada,
        qtd_parcelas=qtd_parcelas,
        forma_pagamento_parcelas=forma_pagamento_parcelas,
        intervalo_dias=intervalo_dias
    )
    db.session.add(nova_prop)
    db.session.flush()

    servicos_ids = request.form.getlist('tipo_servico_id[]')
    valores = request.form.getlist('valor_unitario[]')
    descricoes = request.form.getlist('descricao[]')

    for s_id, val, desc in zip(servicos_ids, valores, descricoes):
        if s_id and val:
            item = ItemProposta(
                proposta_id=nova_prop.id,
                tipo_servico_id=int(s_id),
                valor_unitario=float(val),
                descricao_personalizada=desc
            )
            db.session.add(item)

    db.session.commit()
    flash(f'Proposta {nova_prop.numero_proposta} gerada com sucesso!', 'success')
    return redirect(url_for('listar_propostas'))


@app.route('/propostas/<int:id>/status', methods=['POST'])
@login_required
def atualizar_status_proposta(id):
    proposta = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    novo_status = request.form.get('novo_status')
    
    if novo_status in ['Aguardando Aprovação', 'Aprovado', 'Cancelado']:
        status_anterior = proposta.status
        proposta.status = novo_status

        if novo_status == 'Aprovado' and status_anterior != 'Aprovado':
            hoje = date.today()

            # 1. CRIA A FATURA PAI
            fatura = Fatura(
                empresa_id=current_user.empresa_id,
                cliente_id=proposta.cliente_id,
                proposta_id=proposta.id,
                descricao=f"Proposta {proposta.numero_proposta} ({len(proposta.itens)} itens)",
                valor_total=proposta.valor_total,
                data_emissao=hoje
            )
            db.session.add(fatura)
            db.session.flush()

            # 2. CONTRATO RECORRENTE (SE MENSALISTA)
            if proposta.tipo_cobranca == 'recorrente':
                contrato = ContratoRecorrente(
                    empresa_id=current_user.empresa_id,
                    cliente_id=proposta.cliente_id,
                    tipo_servico_id=proposta.itens[0].tipo_servico_id if proposta.itens else None,
                    proposta_origem_id=proposta.id,
                    titulo=f"Contrato Mensal - {proposta.cliente.nome}",
                    valor_periodo=proposta.valor_total,
                    periodicidade=proposta.periodicidade,
                    dia_vencimento=proposta.dia_vencimento,
                    status='Ativo',
                    data_inicio=hoje,
                    observacoes=proposta.observacoes
                )
                db.session.add(contrato)
                db.session.flush()
                fatura.contrato_id = contrato.id

            # 3. GERAÇÃO DINÂMICA DAS PARCELAS (ENTRADA + PARCELAS 1 A 12X)
            exige_entrada = proposta.exige_entrada and (proposta.valor_entrada or 0) > 0
            valor_entrada = float(proposta.valor_entrada or 0) if exige_entrada else 0.0
            saldo_parcelar = max(0.0, proposta.valor_total - valor_entrada)
            qtd_parc = max(1, min(12, proposta.qtd_parcelas or 1))
            total_titulos = (1 if exige_entrada else 0) + (qtd_parc if saldo_parcelar > 0 else 0)

            num_seq = 1

            # A) Parcela de Entrada / Sinal
            if exige_entrada:
                p_entrada = ParcelaFatura(
                    empresa_id=current_user.empresa_id,
                    fatura_id=fatura.id,
                    numero_parcela=num_seq,
                    total_parcelas=total_titulos,
                    descricao_parcela="Entrada / Sinal de Mobilização",
                    is_entrada=True,
                    forma_pagamento=proposta.forma_pagamento_entrada or "PIX",
                    valor=valor_entrada,
                    data_vencimento=hoje,
                    status="A Faturar"
                )
                db.session.add(p_entrada)
                num_seq += 1

            # B) Parcelas Restantes
            if saldo_parcelar > 0:
                valor_cada_parcela = round(saldo_parcelar / qtd_parc, 2)
                intervalo = proposta.intervalo_dias or 30

                for i in range(1, qtd_parc + 1):
                    dt_venc = hoje + relativedelta(days=i * intervalo)
                    p_normal = ParcelaFatura(
                        empresa_id=current_user.empresa_id,
                        fatura_id=fatura.id,
                        numero_parcela=num_seq,
                        total_parcelas=total_titulos,
                        descricao_parcela=f"Parcela {i}/{qtd_parc}",
                        is_entrada=False,
                        forma_pagamento=proposta.forma_pagamento_parcelas or "Boleto Bancário",
                        valor=valor_cada_parcela,
                        data_vencimento=dt_venc,
                        status="A Faturar"
                    )
                    db.session.add(p_normal)
                    num_seq += 1

            # 4. CRIA AS ORDENS DE SERVIÇO NA AGENDA COM TRAVA DE SINAL
            status_inicial_os = 'Bloqueado' if exige_entrada else ('Em Andamento' if proposta.tipo_cobranca != 'recorrente' else 'Pendente')

            for item in proposta.itens:
                nova_ordem = ServicoCliente(
                    empresa_id=current_user.empresa_id,
                    cliente_id=proposta.cliente_id,
                    tipo_servico_id=item.tipo_servico_id,
                    fatura_id=fatura.id,
                    valor_cobrado=item.valor_unitario,
                    status=status_inicial_os,
                    data_solicitacao=hoje,
                    data_previsao=hoje + relativedelta(days=proposta.validade_dias or 30),
                    observacoes=f"[Ref. {proposta.numero_proposta}] {item.descricao_personalizada or ''}".strip()
                )
                db.session.add(nova_ordem)
            
            db.session.commit()
            flash(f'Proposta {proposta.numero_proposta} aprovada! Fatura gerada com {total_titulos} título(s).', 'success')
            return redirect(url_for('listar_propostas'))

        db.session.commit()
        flash(f'Status da Proposta alterado para "{novo_status}"!', 'info')
    
    return redirect(url_for('listar_propostas'))


@app.route('/propostas/<int:id>/editar', methods=['POST'])
@login_required
def editar_proposta(id):
    proposta = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    proposta.cliente_id = int(request.form.get('cliente_id'))
    proposta.validade_dias = int(request.form.get('validade_dias') or 15)
    proposta.condicoes_pagamento = request.form.get('condicoes_pagamento') or 'Conforme alinhamento comercial'
    proposta.observacoes = request.form.get('observacoes')
    
    ItemProposta.query.filter_by(proposta_id=proposta.id).delete()
    
    servicos_ids = request.form.getlist('tipo_servico_id[]')
    valores = request.form.getlist('valor_unitario[]')
    descricoes = request.form.getlist('descricao[]')

    for s_id, val, desc in zip(servicos_ids, valores, descricoes):
        if s_id and val:
            item = ItemProposta(
                proposta_id=proposta.id,
                tipo_servico_id=int(s_id),
                valor_unitario=float(val),
                descricao_personalizada=desc
            )
            db.session.add(item)

    db.session.commit()
    flash(f'Proposta {proposta.numero_proposta} atualizada com sucesso!', 'success')
    return redirect(url_for('listar_propostas'))

@app.route('/proposta/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_proposta(id):
    prop = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    # Trava de segurança: impede exclusão se já houver fatura ou contrato vinculado
    if prop.faturas or ContratoRecorrente.query.filter_by(proposta_origem_id=prop.id).first():
        flash('Não é possível excluir esta proposta pois ela já gerou faturas ou contratos ativos.', 'danger')
    else:
        numero = prop.numero_proposta
        db.session.delete(prop)
        db.session.commit()
        flash(f'Proposta "{numero}" excluída com sucesso!', 'info')
        
    return redirect(url_for('listar_propostas'))

@app.route('/propostas/<int:id>/pdf')
@login_required
def gerar_pdf_proposta(id):
    proposta = Proposta.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    cliente = proposta.cliente
    empresa = current_user.empresa
    buffer = io.BytesIO()

    # Margens de 36pt (0.5 pol) = 540pt de largura útil (7.5 polegadas exatas)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    elementos = []
    styles = getSampleStyleSheet()

    cor_primaria_hex = empresa.cor_primaria if empresa.cor_primaria and empresa.cor_primaria.startswith('#') else "#1e3a8a"
    cor_marca = colors.HexColor(cor_primaria_hex)

    # Estilos Tipográficos Seguros
    estilo_empresa_nome = ParagraphStyle('PDF_EmpresaNome', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=cor_marca)
    estilo_empresa_sub = ParagraphStyle('PDF_EmpresaSub', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#475569"))
    estilo_secao = ParagraphStyle('PDF_SecaoTit', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9.5, leading=13, textColor=cor_marca)
    estilo_corpo = ParagraphStyle('PDF_CorpoDoc', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, leading=12, textColor=colors.HexColor("#334155"))
    estilo_corpo_bold = ParagraphStyle('PDF_CorpoBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=8.5, leading=12, textColor=colors.HexColor("#0f172a"))
    estilo_escopo = ParagraphStyle('PDF_Escopo', parent=styles['Normal'], fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor("#64748b"))
    estilo_total = ParagraphStyle('PDF_TotalNum', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor("#16a34a"), alignment=2)

    # =========================================================================
    # 1. CABEÇALHO COM LOGOTIPO OU RAZÃO SOCIAL
    # =========================================================================
    logo_elemento = None
    if empresa.logo_filename:
        caminho_logo = os.path.join(app.config['UPLOAD_FOLDER'], empresa.logo_filename)
        if os.path.exists(caminho_logo):
            try:
                logo_elemento = RLImage(caminho_logo, width=1.5*inch, height=0.6*inch)
                logo_elemento.hAlign = 'LEFT'
            except Exception:
                logo_elemento = None

    razao_empresa = _limpar_texto(empresa.razao_social or 'EMPRESA PRESTADORA')
    fantasia_empresa = _limpar_texto(empresa.nome_fantasia or '')
    cnpj_empresa = _limpar_texto(empresa.cnpj or 'Não informado')
    tel_empresa = _limpar_texto(empresa.telefone or 'Não informado')
    email_empresa = _limpar_texto(empresa.email or '')
    site_empresa = _limpar_texto(empresa.site or '')
    end_empresa = _limpar_texto(empresa.endereco_completo or '')

    info_empresa_html = f"""
    <b>{razao_empresa.upper()}</b><br/>
    {f"Nome Fantasia: {fantasia_empresa}<br/>" if fantasia_empresa else ""}
    CNPJ/CPF: {cnpj_empresa} | Tel: {tel_empresa}<br/>
    {f"E-mail: {email_empresa} | " if email_empresa else ""}{site_empresa}<br/>
    {end_empresa}
    """.strip()

    if logo_elemento:
        tab_topo = Table([[logo_elemento, Paragraph(info_empresa_html, estilo_empresa_sub)]], colWidths=[1.8*inch, 5.7*inch])
    else:
        tab_topo = Table([[Paragraph(f"<b>{razao_empresa.upper()}</b>", estilo_empresa_nome), Paragraph(info_empresa_html, estilo_empresa_sub)]], colWidths=[2.8*inch, 4.7*inch])

    tab_topo.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ]))
    elementos.append(tab_topo)
    elementos.append(Spacer(1, 6))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=cor_marca, spaceAfter=10))

    # =========================================================================
    # 2. DADOS DA PROPOSTA & CLIENTE
    # =========================================================================
    nome_cli = _limpar_texto(cliente.nome or 'Cliente')
    doc_cli = _limpar_texto(cliente.cnpj_cpf or '--')
    resp_cli = _limpar_texto(cliente.responsavel or cliente.nome or '--')
    tel_cli = _limpar_texto(cliente.telefone or '--')
    email_cli = _limpar_texto(cliente.email or '--')
    num_prop = _limpar_texto(proposta.numero_proposta or f"PROP-{proposta.id}")
    dt_emissao = proposta.data_criacao.strftime('%d/%m/%Y') if proposta.data_criacao else datetime.today().strftime('%d/%m/%Y')
    
    end_cli_fmt = _limpar_texto(
        f"{cliente.logradouro or ''}, {cliente.numero or 'S/N'} {cliente.complemento or ''} - {cliente.bairro or ''}, {cliente.cidade or ''}/{cliente.estado or ''}".strip(" ,-/")
    ) or "Endereço não informado"

    dados_painel = [
        [
            Paragraph(f"<b>PROPOSTA COMERCIAL:</b> {num_prop}", estilo_corpo_bold),
            Paragraph(f"<b>DATA DE EMISSÃO:</b> {dt_emissao}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>CLIENTE:</b> {nome_cli}", estilo_corpo_bold),
            Paragraph(f"<b>VALIDADE:</b> {proposta.validade_dias or 15} dias", estilo_corpo)
        ],
        [
            Paragraph(f"<b>CNPJ / CPF:</b> {doc_cli}", estilo_corpo),
            Paragraph(f"<b>RESPONSÁVEL TÉCNICO:</b> {_limpar_texto(current_user.nome)}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>LOCAL / ENDEREÇO:</b> {end_cli_fmt}", estilo_corpo),
            Paragraph(f"<b>CONTATO / TEL:</b> {resp_cli} | {tel_cli}", estilo_corpo)
        ]
    ]
    tab_painel = Table(dados_painel, colWidths=[4.2*inch, 3.3*inch])
    tab_painel.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
        ('PADDING', (0,0), (-1,-1), 4.5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(tab_painel)
    elementos.append(Spacer(1, 10))

    # =========================================================================
    # 3. ESCOPO DOS SERVIÇOS
    # =========================================================================
    elementos.append(Paragraph("1. ESCOPO TÉCNICO & INVESTIMENTO", estilo_secao))
    elementos.append(Spacer(1, 4))

    dados_servicos = [
        [
            Paragraph("<b>Item / Serviço</b>", estilo_corpo_bold),
            Paragraph("<b>Detalhamento Técnico / Metodologia</b>", estilo_corpo_bold),
            Paragraph("<b>Valor (R$)</b>", estilo_corpo_bold)
        ]
    ]

    for idx, item in enumerate(proposta.itens, 1):
        nome_serv = _limpar_texto(item.tipo_servico.nome if item.tipo_servico else 'Serviço Técnico')
        escopo_raw = item.descricao_personalizada or (item.tipo_servico.descricao_padrao if item.tipo_servico else '') or "Conforme alinhamento técnico e comercial."
        escopo_fmt = _limpar_texto(escopo_raw)

        dados_servicos.append([
            Paragraph(f"<b>{idx:02d}. {nome_serv}</b>", estilo_corpo),
            Paragraph(escopo_fmt, estilo_escopo),
            Paragraph(f"R$ {item.valor_unitario:,.2f}", estilo_corpo_bold)
        ])

    label_total = "VALOR DA MENSALIDADE" if proposta.tipo_cobranca == 'recorrente' else "TOTAL GLOBAL DO INVESTIMENTO"
    sufixo_mes = "/mês" if proposta.tipo_cobranca == 'recorrente' else ""

    dados_servicos.append([
        Paragraph(f"<b>{label_total}</b>", estilo_corpo_bold),
        Paragraph(f"<font color='#64748b'>Ref. {len(proposta.itens)} serviço(s) listado(s)</font>", estilo_escopo),
        Paragraph(f"R$ {proposta.valor_total:,.2f} {sufixo_mes}", estilo_total)
    ])

    tab_servicos = Table(dados_servicos, colWidths=[2.3*inch, 4.0*inch, 1.2*inch])
    tab_servicos.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#f1f5f9")),
        ('LINEABOVE', (0,-1), (-1,-1), 1.2, colors.HexColor("#0f172a")),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elementos.append(tab_servicos)
    elementos.append(Spacer(1, 10))

    # =========================================================================
    # 4. CONDIÇÕES FINANCEIRAS, SINAL E PARCELAS
    # =========================================================================
    elementos.append(Paragraph("2. CONDIÇÕES COMERCIAIS & MOBILIZAÇÃO", estilo_secao))
    elementos.append(Spacer(1, 4))

    linhas_condicoes = []

    if proposta.tipo_cobranca == 'recorrente':
        periodo_txt = _limpar_texto(proposta.periodicidade or 'mensal').capitalize()
        dia_venc_txt = proposta.dia_vencimento or 10
        linhas_condicoes.append(f"• <b>Modelo Contratual:</b> Contrato de Prestação de Serviços Contínuos ({periodo_txt}).")
        linhas_condicoes.append(f"• <b>Vencimento das Mensalidades:</b> Todo dia <b>{dia_venc_txt}</b> de cada mês via Boleto Bancário.")
    else:
        if proposta.exige_entrada and (proposta.valor_entrada or 0) > 0:
            forma_ent = _limpar_texto(proposta.forma_pagamento_entrada or 'PIX')
            linhas_condicoes.append(f"• <b>Sinal de Entrada:</b> <font color='#b91c1c'><b>R$ {proposta.valor_entrada:,.2f}</b></font> ({forma_ent}) para confirmação e liberação da agenda técnica.")
            
            saldo = max(0.0, proposta.valor_total - (proposta.valor_entrada or 0))
            if saldo > 0:
                qtd_p = max(1, proposta.qtd_parcelas or 1)
                v_p = saldo / qtd_p
                forma_parc = _limpar_texto(proposta.forma_pagamento_parcelas or 'Boleto Bancário')
                inter_dias = proposta.intervalo_dias or 30
                linhas_condicoes.append(f"• <b>Saldo Restante:</b> R$ {saldo:,.2f} parcelado em <b>{qtd_p}x de R$ {v_p:,.2f}</b> no {forma_parc} (intervalo de {inter_dias} dias).")
        elif (proposta.qtd_parcelas or 1) > 1:
            qtd_p = proposta.qtd_parcelas
            v_p = proposta.valor_total / qtd_p
            forma_parc = _limpar_texto(proposta.forma_pagamento_parcelas or 'Boleto Bancário')
            inter_dias = proposta.intervalo_dias or 30
            linhas_condicoes.append(f"• <b>Condição Parcelada:</b> Dividido em <b>{qtd_p}x de R$ {v_p:,.2f}</b> no {forma_parc} a cada {inter_dias} dias (Sem entrada).")
        else:
            linhas_condicoes.append("• <b>Condição de Pagamento:</b> À Vista / Faturamento em parcela única.")

    if proposta.condicoes_pagamento:
        linhas_condicoes.append(f"• <b>Termos Gerais:</b> {_limpar_texto(proposta.condicoes_pagamento)}")
    if proposta.observacoes:
        linhas_condicoes.append(f"• <b>Observações Técnicas:</b> {_limpar_texto(proposta.observacoes)}")

    tab_cond = Table([[Paragraph("<br/>".join(linhas_condicoes), estilo_corpo)]], colWidths=[7.5*inch])
    tab_cond.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elementos.append(tab_cond)
    elementos.append(Spacer(1, 24))

    # =========================================================================
    # 5. TERMO DE ACEITE & ASSINATURAS
    # =========================================================================
    cargo_resp = _limpar_texto(current_user.cargo or 'Responsável Técnico')
    nome_usuario = _limpar_texto(current_user.nome)

    dados_assinaturas = [
        [
            Paragraph(f"____________________________________________<br/><b>{razao_empresa.upper()}</b><br/>{nome_usuario} - {cargo_resp}", estilo_corpo),
            Paragraph("____________________________________________<br/><b>DE ACORDO DO CLIENTE / CONTRATANTE</b><br/>Carimbo / Assinatura / Data", estilo_corpo)
        ]
    ]
    tab_ass = Table(dados_assinaturas, colWidths=[3.75*inch, 3.75*inch])
    tab_ass.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(tab_ass)

    doc.build(elementos)
    buffer.seek(0)

    nome_arquivo_pdf = f"Carta_Proposta_{num_prop.replace('/', '_')}.pdf"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_arquivo_pdf,
        mimetype='application/pdf'
    )

# -----------------------------------------------------------------------------
# 6. ROTAS DE OPERAÇÃO & AGENDA DE SERVIÇOS
# -----------------------------------------------------------------------------
@app.route('/servicos')
@login_required
def consultar_servicos():
    filtro_atual = request.args.get('status', 'agenda')
    periodo_atual = request.args.get('periodo', 'todos')
    hoje = date.today()

    query_base = ServicoCliente.query.filter_by(empresa_id=current_user.empresa_id)

    # 1. Filtro por Categoria / Tipo de Atividade
    if filtro_atual == 'agenda':
        query = query_base.filter(ServicoCliente.status.in_(['Em Andamento', 'Pendente', 'Bloqueado']))
    elif filtro_atual == 'recorrentes':
        query = query_base.filter(ServicoCliente.contrato_id.isnot(None))
    elif filtro_atual == 'avulsos':
        query = query_base.filter(ServicoCliente.contrato_id.is_(None))
    elif filtro_atual == 'concluidos':
        query = query_base.filter_by(status='Concluido')
    else:
        query = query_base

    # 2. Filtro Temporal Dinâmico a partir de HOJE
    if periodo_atual == 'semana':
        fim_periodo = hoje + timedelta(days=7)
        if filtro_atual in ['agenda', 'recorrentes', 'avulsos']:
            query = query.filter(ServicoCliente.data_previsao <= fim_periodo)
        else:
            query = query.filter(ServicoCliente.data_previsao.between(hoje, fim_periodo))

    elif periodo_atual == 'mes':
        fim_periodo = hoje + relativedelta(months=1)
        if filtro_atual in ['agenda', 'recorrentes', 'avulsos']:
            query = query.filter(ServicoCliente.data_previsao <= fim_periodo)
        else:
            query = query.filter(ServicoCliente.data_previsao.between(hoje, fim_periodo))

    elif periodo_atual == 'ano':
        fim_periodo = hoje + relativedelta(years=1)
        if filtro_atual in ['agenda', 'recorrentes', 'avulsos']:
            query = query.filter(ServicoCliente.data_previsao <= fim_periodo)
        else:
            query = query.filter(ServicoCliente.data_previsao.between(hoje, fim_periodo))

    # Ordenação Cronológica
    servicos_operacionais = query.order_by(ServicoCliente.data_previsao.asc().nullslast()).all()

    # Métricas gerais dos cards
    qtd_em_andamento = query_base.filter_by(status='Em Andamento').count()
    qtd_pendentes = query_base.filter(ServicoCliente.status.in_(['Pendente', 'Bloqueado'])).count()
    qtd_concluidos = query_base.filter_by(status='Concluido').count()

    catalogo = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()
    clientes = Cliente.query.filter_by(empresa_id=current_user.empresa_id).order_by(Cliente.nome).all()

    return render_template(
        'servicos.html',
        servicos_operacionais=servicos_operacionais,
        filtro_atual=filtro_atual,
        periodo_atual=periodo_atual,
        qtd_em_andamento=qtd_em_andamento,
        qtd_pendentes=qtd_pendentes,
        qtd_concluidos=qtd_concluidos,
        catalogo=catalogo,
        clientes=clientes,
        hoje=hoje
    )


@app.route('/catalogo', methods=['GET'])
@login_required
def listar_catalogo():
    catalogo = TipoServico.query.filter_by(empresa_id=current_user.empresa_id).all()
    return render_template('catalogo.html', catalogo=catalogo)

@app.route('/catalogo/novo', methods=['POST'])
@login_required
def novo_tipo_servico():
    nome = request.form.get('nome')
    modelo_cobranca = request.form.get('modelo_cobranca', 'pontual')
    valor_sugerido = float(request.form.get('valor_sugerido') or 0.0)
    descricao = request.form.get('descricao')

    novo_item = TipoServico(
        empresa_id=current_user.empresa_id,
        nome=nome,
        modelo_cobranca=modelo_cobranca,
        valor_sugerido=valor_sugerido,
        descricao_padrao=descricao
    )
    db.session.add(novo_item)
    db.session.commit()
    flash(f'Serviço "{nome}" cadastrado no catálogo com sucesso!', 'success')
    return redirect(url_for('listar_catalogo'))

@app.route('/catalogo/excluir/<int:id>', methods=['POST'])
@login_required
def excluir_tipo_servico(id):
    item = TipoServico.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    # Valida se o serviço já possui propostas ou execuções vinculadas
    if item.execucoes or ItemProposta.query.filter_by(tipo_servico_id=item.id).first():
        flash('Não é possível excluir este item pois ele já está vinculado a propostas ou serviços emitidos.', 'danger')
    else:
        db.session.delete(item)
        db.session.commit()
        flash('Item removido do catálogo.', 'info')
        
    return redirect(url_for('listar_catalogo'))

@app.route('/servicos/atualizar-operacao/<int:id>', methods=['POST'])
@login_required
def atualizar_operacao_servico(id):
    servico = ServicoCliente.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    # Trava de segurança no backend para não permitir iniciar sem sinal
    if servico.status == 'Bloqueado':
        flash('Esta atividade está bloqueada pelo Financeiro aguardando o pagamento do sinal.', 'danger')
        return redirect(url_for('consultar_servicos', status=request.form.get('filtro_retorno', 'agenda')))

    servico.status = request.form.get('status', servico.status)
    data_prev_str = request.form.get('data_previsao')
    servico.data_previsao = datetime.strptime(data_prev_str, '%Y-%m-%d').date() if data_prev_str else None
    servico.observacoes = request.form.get('observacoes')

    db.session.commit()

    if servico.status == 'Concluido':
        flash(f'Atividade "{servico.tipo_servico.nome}" ({servico.cliente.nome}) concluída e liberada para o Financeiro!', 'success')
    else:
        flash('Acompanhamento técnico atualizado.', 'info')

    return redirect(url_for('consultar_servicos', status=request.form.get('filtro_retorno', 'agenda')))

# -----------------------------------------------------------------------------
# 7. ROTAS DO MÓDULO FINANCEIRO
# -----------------------------------------------------------------------------

@app.route('/financeiro')
@login_required
def financeiro():
    filtro_atual = request.args.get('status', 'todos')
    hoje = date.today()

    query_faturas = Fatura.query.filter_by(empresa_id=current_user.empresa_id)
    todas_faturas = query_faturas.all()

    # Métricas globais
    todas_parcelas = ParcelaFatura.query.filter_by(empresa_id=current_user.empresa_id).all()
    total_a_faturar = sum(p.valor for p in todas_parcelas if p.status == 'A Faturar')
    total_aguardando = sum(p.valor for p in todas_parcelas if p.status == 'Boleto Emitido' and (not p.data_vencimento or p.data_vencimento >= hoje))
    total_recebido = sum(p.valor for p in todas_parcelas if p.status == 'Pago')
    
    parcelas_atrasadas = [p for p in todas_parcelas if p.status != 'Pago' and p.data_vencimento and p.data_vencimento < hoje]
    total_atrasado = sum(p.valor for p in parcelas_atrasadas)
    qtd_atrasados = len(parcelas_atrasadas)

    # Filtragem
    if filtro_atual == 'afaturar':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'A Faturar']
    elif filtro_atual == 'aguardando':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'Aguardando Pagamento']
    elif filtro_atual == 'atrasados':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'Em Atraso']
    elif filtro_atual == 'pagos':
        faturas_filtradas = [f for f in todas_faturas if f.status_geral == 'Pago']
    else:
        faturas_filtradas = todas_faturas

    itens = []
    for f in faturas_filtradas:
        parcs_pendentes = [p for p in f.parcelas if p.status != 'Pago']
        primeira_parc = parcs_pendentes[0] if parcs_pendentes else (f.parcelas[0] if f.parcelas else None)
        data_venc = primeira_parc.data_vencimento if primeira_parc else None
        esta_vencida = f.status_geral == 'Em Atraso'

        boleto_anexo = None
        for p in f.parcelas:
            if p.arquivo_comprovante_boleto:
                boleto_anexo = p.arquivo_comprovante_boleto
                break

        itens.append({
            'fatura': f,
            'data_vencimento': data_venc,
            'esta_vencido': esta_vencida,
            'status_calculado': f.status_geral,
            'arquivo_boleto': boleto_anexo,
            'arquivo_nf': f.arquivo_nf
        })

    return render_template(
        'financeiro.html',
        itens=itens,
        filtro_atual=filtro_atual,
        total_a_faturar=total_a_faturar,
        total_aguardando=total_aguardando,
        total_atrasado=total_atrasado,
        total_recebido=total_recebido,
        qtd_atrasados=qtd_atrasados,
        hoje=hoje
    )


@app.route('/financeiro/fatura/<int:id>/atualizar', methods=['POST'])
@login_required
def atualizar_cobranca_fatura(id):
    fatura = Fatura.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    novo_status = request.form.get('status_pagamento')
    dt_venc = request.form.get('data_vencimento')
    data_formatada = datetime.strptime(dt_venc, '%Y-%m-%d').date() if dt_venc else None

    # Upload da NF
    if 'arquivo_nf' in request.files:
        f = request.files['arquivo_nf']
        if f.filename:
            nome_arq = secure_filename(f"nf_fat_{fatura.id}_{int(datetime.utcnow().timestamp())}_{f.filename}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_arq))
            fatura.arquivo_nf = nome_arq

    # Upload do Boleto Principal
    boleto_salvo = None
    if 'arquivo_boleto' in request.files:
        f_bol = request.files['arquivo_boleto']
        if f_bol.filename:
            boleto_salvo = secure_filename(f"boleto_fat_{fatura.id}_{int(datetime.utcnow().timestamp())}_{f_bol.filename}")
            f_bol.save(os.path.join(app.config['UPLOAD_FOLDER'], boleto_salvo))

    nova_obs = request.form.get('nova_ocorrencia')

    # Atualiza as parcelas
    if fatura.parcelas:
        for p in fatura.parcelas:
            if novo_status in ['Pago', 'Boleto Emitido', 'A Faturar', 'Em Atraso']:
                p.status = novo_status
            if data_formatada and len(fatura.parcelas) == 1:
                p.data_vencimento = data_formatada
            if boleto_salvo:
                p.arquivo_comprovante_boleto = boleto_salvo
            if nova_obs:
                registro = f"[{datetime.now().strftime('%d/%m/%Y %H:%M')}] {nova_obs}\n"
                p.historico_cobranca = (p.historico_cobranca or "") + registro

    # Liberação automática da Agenda caso pago
    if novo_status == 'Pago':
        servicos_bloqueados = ServicoCliente.query.filter_by(fatura_id=fatura.id).filter(ServicoCliente.status.in_(['Bloqueado', 'Pendente'])).all()
        for sc in servicos_bloqueados:
            sc.status = 'Em Andamento'
            sc.observacoes = (sc.observacoes or "") + " | [Pagamento Confirmado: Execução Liberada]"

    db.session.commit()
    flash(f'Fatura "{fatura.descricao}" atualizada com sucesso!', 'success')
    return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))


@app.route('/financeiro/parcela/<int:id>/atualizar', methods=['POST'])
@login_required
def atualizar_cobranca_parcela(id):
    parcela = ParcelaFatura.query.filter_by(id=id, empresa_id=current_user.empresa_id).first_or_404()
    
    dt_venc = request.form.get('data_vencimento')
    if dt_venc:
        parcela.data_vencimento = datetime.strptime(dt_venc, '%Y-%m-%d').date()

    status_anterior = parcela.status
    novo_status = request.form.get('status_pagamento')
    parcela.status = novo_status
    parcela.forma_pagamento = request.form.get('forma_pagamento', parcela.forma_pagamento)

    if 'arquivo_comprovante_boleto' in request.files:
        f = request.files['arquivo_comprovante_boleto']
        if f.filename:
            nome_arq = secure_filename(f"parc_{parcela.id}_{int(datetime.utcnow().timestamp())}_{f.filename}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_arq))
            parcela.arquivo_comprovante_boleto = nome_arq

    nova_obs = request.form.get('nova_ocorrencia')
    if nova_obs:
        registro = f"[{datetime.now().strftime('%d/%m/%Y %H:%M')}] {nova_obs}\n"
        parcela.historico_cobranca = (parcela.historico_cobranca or "") + registro

    # Gatilho de Liberação da Entrada na Agenda
    if parcela.is_entrada and novo_status == 'Pago' and status_anterior != 'Pago':
        fatura = parcela.fatura
        servicos_bloqueados = ServicoCliente.query.filter_by(fatura_id=fatura.id, status='Bloqueado').all()
        for sc in servicos_bloqueados:
            sc.status = 'Em Andamento'
            sc.observacoes = (sc.observacoes or "") + " | [Sinal Confirmado: Execução Liberada]"
        flash(f'Sinal de Entrada quitado! {len(servicos_bloqueados)} atividade(s) liberadas na Agenda.', 'success')

    db.session.commit()
    flash(f'{parcela.descricao_parcela} atualizada com sucesso!', 'info')
    return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))


@app.route('/contratos/faturar-mes', methods=['POST'])
@login_required
def faturar_mes_contratos():
    hoje = date.today()
    mes_ano_ref = hoje.strftime('%m/%Y')
    
    contratos_ativos = ContratoRecorrente.query.filter_by(
        empresa_id=current_user.empresa_id,
        status='Ativo'
    ).all()

    gerados = 0
    for c in contratos_ativos:
        obs_identificador = f"[Ciclo {mes_ano_ref}]"
        
        ja_faturado = Fatura.query.filter(
            Fatura.contrato_id == c.id,
            Fatura.descricao.ilike(f"%{obs_identificador}%")
        ).first()

        if not ja_faturado:
            dia = min(c.dia_vencimento, 28)
            vencimento = date(hoje.year, hoje.month, dia)
            if vencimento < hoje:
                vencimento += relativedelta(months=1)

            nova_fatura = Fatura(
                empresa_id=current_user.empresa_id,
                cliente_id=c.cliente_id,
                contrato_id=c.id,
                descricao=f"{obs_identificador} Mensalidade - {c.titulo}",
                valor_total=c.valor_periodo,
                data_emissao=hoje
            )
            db.session.add(nova_fatura)
            db.session.flush()

            # Cria Parcela do Ciclo
            parc_ciclo = ParcelaFatura(
                empresa_id=current_user.empresa_id,
                fatura_id=nova_fatura.id,
                numero_parcela=1,
                total_parcelas=1,
                descricao_parcela=f"Mensalidade {mes_ano_ref}",
                forma_pagamento="Boleto Bancário",
                valor=c.valor_periodo,
                data_vencimento=vencimento,
                status="A Faturar"
            )
            db.session.add(parc_ciclo)

            nova_ordem = ServicoCliente(
                empresa_id=current_user.empresa_id,
                cliente_id=c.cliente_id,
                tipo_servico_id=c.tipo_servico_id,
                contrato_id=c.id,
                fatura_id=nova_fatura.id,
                valor_cobrado=c.valor_periodo,
                status='Pendente',
                data_solicitacao=hoje,
                data_previsao=vencimento,
                observacoes=f"{obs_identificador} Vistoria/Assessoria Mensal"
            )
            db.session.add(nova_ordem)
            gerados += 1

    db.session.commit()
    
    if gerados > 0:
        flash(f'{gerados} fatura(s) e ordem(ns) de serviço foram geradas para o ciclo {mes_ano_ref}!', 'success')
    else:
        flash(f'Todos os contratos ativos já foram faturados para o ciclo {mes_ano_ref}.', 'info')

    return redirect(url_for('financeiro'))

# -----------------------------------------------------------------------------
# 8. PERFIL DA EMPRESA & WHITE-LABEL
# -----------------------------------------------------------------------------

@app.route('/configuracoes/perfil', methods=['GET', 'POST'])
@login_required
def perfil_empresa():
    empresa = current_user.empresa
    usuario = current_user
    
    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'dados_empresa':
            tipo_pessoa = request.form.get('tipo_pessoa')
            
            if tipo_pessoa == 'PF':
                empresa.razao_social = request.form.get('nome_profissional')
                empresa.nome_fantasia = "Profissional Autônomo"
                empresa.cnpj = request.form.get('cpf')
            else:
                empresa.razao_social = request.form.get('razao_social')
                empresa.nome_fantasia = request.form.get('nome_fantasia')
                empresa.cnpj = request.form.get('cnpj')

            empresa.telefone = request.form.get('telefone')
            empresa.email = request.form.get('email')
            empresa.site = request.form.get('site')
            empresa.endereco_completo = request.form.get('endereco_completo')
            empresa.cor_primaria = request.form.get('cor_primaria', '#1e3a8a')

            logo_file = request.files.get('logo')
            if logo_file and logo_file.filename != '':
                ext = logo_file.filename.rsplit('.', 1)[-1].lower()
                if ext in ['png', 'jpg', 'jpeg', 'webp']:
                    filename = f"logo_emp_{empresa.id}_{int(datetime.utcnow().timestamp())}.{ext}"
                    logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    empresa.logo_filename = filename

            db.session.commit()
            flash('Dados cadastrais e identidade visual atualizados com sucesso!', 'success')

        elif form_type == 'dados_usuario':
            novo_nome = request.form.get('nome_usuario')
            novo_email = request.form.get('email_login', '').strip().lower()
            senha_atual = request.form.get('senha_atual')
            nova_senha = request.form.get('nova_senha')
            confirma_senha = request.form.get('confirma_senha')

            outro_usuario = Usuario.query.filter(Usuario.email == novo_email, Usuario.id != usuario.id).first()
            if outro_usuario:
                flash('Este e-mail já está sendo utilizado por outro usuário.', 'danger')
                return redirect(url_for('perfil_empresa'))

            usuario.nome = novo_nome
            usuario.email = novo_email

            if nova_senha:
                if not usuario.check_senha(senha_atual):
                    flash('A senha atual digitada está incorreta.', 'danger')
                    return redirect(url_for('perfil_empresa'))
                if nova_senha != confirma_senha:
                    flash('A nova senha e a confirmação não conferem.', 'warning')
                    return redirect(url_for('perfil_empresa'))
                
                usuario.set_senha(nova_senha)
                flash('Senha e dados de acesso alterados com sucesso!', 'success')
            else:
                flash('Dados da conta atualizados com sucesso!', 'success')

            db.session.commit()

        return redirect(url_for('perfil_empresa'))

    return render_template('perfil_empresa.html', perfil=empresa)

@app.route('/faq')
@login_required
def faq():
    return render_template('faq.html')


@app.route('/suporte')
@login_required
def suporte():
    chamados = ChamadoSuporte.query.filter_by(
        empresa_id=current_user.empresa_id
    ).order_by(ChamadoSuporte.data_abertura.desc()).all()
    
    return render_template('suporte.html', chamados=chamados)


@app.route('/suporte/novo', methods=['POST'])
@login_required
def novo_chamado():
    assunto = request.form.get('assunto')
    categoria = request.form.get('categoria', 'Dúvida')
    prioridade = request.form.get('prioridade', 'Média')
    mensagem_texto = request.form.get('mensagem')
    arquivo = request.files.get('anexo')

    # Gera protocolo único (ex: TIK-2026-178814)
    protocolo = f"TIK-{int(time.time())}"

    novo_ticket = ChamadoSuporte(
        empresa_id=current_user.empresa_id,
        usuario_id=current_user.id,
        numero_protocolo=protocolo,
        assunto=assunto,
        categoria=categoria,
        prioridade=prioridade,
        status='Aberto'
    )
    db.session.add(novo_ticket)
    db.session.flush()

    # Salva anexo se houver
    filename = None
    if arquivo and arquivo.filename:
        filename = f"chamado_{novo_ticket.id}_{int(time.time())}_{secure_filename(arquivo.filename)}"
        upload_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads')
        os.makedirs(upload_folder, exist_ok=True)
        arquivo.save(os.path.join(upload_folder, filename))

    primeira_msg = MensagemChamado(
        chamado_id=novo_ticket.id,
        usuario_id=current_user.id,
        conteudo=mensagem_texto,
        is_suporte=False,
        anexo_filename=filename
    )
    db.session.add(primeira_msg)
    db.session.commit()

    flash(f'Chamado {protocolo} aberto com sucesso! Nossa equipe analisará sua solicitação.', 'success')
    return redirect(url_for('suporte'))


@app.route('/suporte/<int:id>', methods=['GET', 'POST'])
@login_required
def detalhe_chamado(id):
    chamado = ChamadoSuporte.query.filter_by(
        id=id, 
        empresa_id=current_user.empresa_id
    ).first_or_404()

    if request.method == 'POST':
        conteudo = request.form.get('mensagem')
        arquivo = request.files.get('anexo')

        filename = None
        if arquivo and arquivo.filename:
            filename = f"chamado_{chamado.id}_{int(time.time())}_{secure_filename(arquivo.filename)}"
            upload_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads')
            os.makedirs(upload_folder, exist_ok=True)
            arquivo.save(os.path.join(upload_folder, filename))

        nova_msg = MensagemChamado(
            chamado_id=chamado.id,
            usuario_id=current_user.id,
            conteudo=conteudo,
            is_suporte=False,
            anexo_filename=filename
        )
        chamado.status = 'Em Atendimento'
        db.session.add(nova_msg)
        db.session.commit()
        flash('Mensagem enviada com sucesso!', 'success')
        return redirect(url_for('detalhe_chamado', id=chamado.id))

    return render_template('detalhe_chamado.html', chamado=chamado)

@app.route('/admin/master/usuarios')
@login_required
@master_required
def admin_master_usuarios():
  usuarios = (
      Usuario.query.join(Empresa)
      .order_by(Usuario.nivel_acesso.desc(), Usuario.nome.asc())
      .all()
  )
  return render_template('admin/master_usuarios.html', usuarios=usuarios)


@app.route(
    '/admin/master/usuarios/<int:id>/alterar-nivel', methods=['POST']
)
@login_required
@master_required
def admin_alterar_nivel_usuario(id):
  usuario = Usuario.query.get_or_404(id)
  novo_nivel = request.form.get('nivel_acesso')

  # Trava de segurança: impede que você remova seu próprio acesso master
  if usuario.id == current_user.id and novo_nivel != 'master':
    flash('Você não pode remover seu próprio privilégio de Master.', 'danger')
    return redirect(url_for('admin_master_usuarios'))

  if novo_nivel in ['operador', 'admin', 'master']:
    usuario.nivel_acesso = novo_nivel
    db.session.commit()
    flash(
        f'Nível de acesso de "{usuario.nome}" atualizado para "{novo_nivel.upper()}".',
        'success',
    )
  else:
    flash('Nível de acesso inválido informado.', 'danger')

  return redirect(url_for('admin_master_usuarios'))

from flask import session
from werkzeug.security import generate_password_hash


# 1. Impersonação de Conta (Logar como o Inquilino)
@app.route('/admin/master/impersonar/<int:empresa_id>')
@login_required
@master_required
def admin_impersonar_empresa(empresa_id):
  alvo_empresa = Empresa.query.get_or_404(empresa_id)
  usuario_alvo = Usuario.query.filter_by(empresa_id=alvo_empresa.id).first()

  if not usuario_alvo:
    flash(
        'Esta empresa não possui nenhum usuário cadastrado para acesso.',
        'danger',
    )
    return redirect(url_for('admin_master_dashboard'))

  # Armazena o ID original do Master na sessão
  session['original_master_id'] = current_user.id
  login_user(usuario_alvo)

  flash(
      f'Modo Suporte Ativado: Você está navegando como "{usuario_alvo.nome}" ({alvo_empresa.razao_social}).',
      'warning',
  )
  return redirect(url_for('index'))


# 2. Sair da Impersonação e Voltar para a Conta Master
@app.route('/admin/master/sair-impersonacao')
@login_required
def admin_sair_impersonacao():
  master_id = session.pop('original_master_id', None)
  if master_id:
    usuario_master = Usuario.query.get(master_id)
    if usuario_master and usuario_master.nivel_acesso == 'master':
      login_user(usuario_master)
      flash('Você retornou ao seu painel Master.', 'info')
      return redirect(url_for('admin_master_dashboard'))

  return redirect(url_for('auth.logout'))


# 3. Alterar Status Manualmente (Ativar / Suspender / Trial)
@app.route(
    '/admin/master/empresa/<int:id>/alterar-status', methods=['POST']
)
@login_required
@master_required
def admin_alterar_status_empresa(id):
  empresa = Empresa.query.get_or_404(id)
  novo_status = request.form.get('status_assinatura')

  if novo_status in ['ativo', 'trial', 'bloqueado', 'cancelado']:
    empresa.status_assinatura = novo_status
    db.session.commit()
    flash(
        f'Status da empresa "{empresa.razao_social}" atualizado para "{novo_status.upper()}".',
        'success',
    )
  else:
    flash('Status inválido.', 'danger')

  return redirect(url_for('admin_master_dashboard'))


# 4. Redefinir Senha Forçada de um Usuário
@app.route(
    '/admin/master/usuario/<int:id>/redefinir-senha', methods=['POST']
)
@login_required
@master_required
def admin_redefinir_senha_usuario(id):
  usuario = Usuario.query.get_or_404(id)
  nova_senha = request.form.get('nova_senha')

  if not nova_senha or len(nova_senha) < 6:
    flash('A nova senha deve ter pelo menos 6 caracteres.', 'danger')
  else:
    usuario.senha_hash = generate_password_hash(nova_senha)
    db.session.commit()
    flash(
        f'Senha de "{usuario.nome}" redefinida com sucesso para: {nova_senha}',
        'success',
    )

  return redirect(url_for('admin_master_usuarios'))

# -----------------------------------------------------------------------------
# 9. INICIALIZAÇÃO DO SERVIDOR
# -----------------------------------------------------------------------------

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
