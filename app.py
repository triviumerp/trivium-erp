import io
import os
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

# Relatórios PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch

# -----------------------------------------------------------------------------
# 1. CONFIGURAÇÃO DA APLICAÇÃO
# -----------------------------------------------------------------------------
app = Flask(__name__)
uri_banco = os.getenv('DATABASE_URL', 'sqlite:///database.db')
if uri_banco.startswith("postgres://"):
    uri_banco = uri_banco.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri_banco
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'drd2_engenharia_seguranca_chave_secreta_2026'

uri_banco = os.getenv('DATABASE_URL', 'sqlite:///database.db')
if uri_banco.startswith("postgres://"):
    uri_banco = uri_banco.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri_banco
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# 2. MODELOS DO BANCO DE DADOS (ORM)
# -----------------------------------------------------------------------------

class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)

    # 1. Identificação Jurídica e Fiscal
    nome = db.Column(db.String(150), nullable=False) # Razão Social / Nome Completo
    nome_fantasia = db.Column(db.String(150), nullable=True)
    cnpj_cpf = db.Column(db.String(30), nullable=True)
    inscricao_estadual = db.Column(db.String(30), nullable=True)

    # 2. Dados de Contato e Responsável
    responsavel = db.Column(db.String(100), nullable=True) # Síndico, Gestor, Administrador
    telefone = db.Column(db.String(50), nullable=False)
    telefone_secundario = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=False)
    email_financeiro = db.Column(db.String(120), nullable=True) # Para envio de NFs e boletos

    # 3. Endereço Completo do Imóvel / Edificação
    cep = db.Column(db.String(20), nullable=True)
    logradouro = db.Column(db.String(200), nullable=True)
    numero = db.Column(db.String(20), nullable=True)
    complemento = db.Column(db.String(100), nullable=True) # Bloco, Torre, Galpão
    bairro = db.Column(db.String(100), nullable=True)
    cidade = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(10), nullable=True)

    # 4. Dados Técnicos da Edificação (Engenharia & Bombeiros)
    area_construida = db.Column(db.Float, nullable=True) # em m²
    tipo_ocupacao = db.Column(db.String(100), nullable=True) # Residencial, Comercial, Industrial, etc.
    numero_pavimentos = db.Column(db.Integer, nullable=True)
    numero_projeto_cb = db.Column(db.String(50), nullable=True) # Nº Projeto no Via Fácil / Bombeiros
    data_inicio_avcb = db.Column(db.Date, nullable=False)
    data_vencimento_avcb = db.Column(db.Date, nullable=False)

    # 5. Observações Gerais
    observacoes = db.Column(db.Text, nullable=True)

    # Relacionamentos
    documentos = db.relationship('Documento', backref='cliente', lazy=True, cascade="all, delete-orphan")
    servicos = db.relationship('ServicoCliente', backref='cliente', lazy=True, cascade="all, delete-orphan")
    propostas = db.relationship('Proposta', backref='cliente', lazy=True, cascade="all, delete-orphan")

    @property
    def total_concluido(self):
        return sum(s.valor_cobrado for s in self.servicos if s.status == 'Concluido')

    @property
    def total_em_aberto(self):
        return sum(s.valor_cobrado for s in self.servicos if s.status in ['Pendente', 'Em Andamento'])


class Documento(db.Model):
    __tablename__ = 'documentos'
    id = db.Column(db.Integer, primary_key=True)
    tipo_documento = db.Column(db.String(50), nullable=False)
    nome_arquivo = db.Column(db.String(255), nullable=False)
    data_upload = db.Column(db.DateTime, default=datetime.utcnow)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)


class TipoServico(db.Model):
    __tablename__ = 'tipos_servico'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), unique=True, nullable=False)
    descricao_padrao = db.Column(db.Text, nullable=True)
    valor_sugerido = db.Column(db.Float, default=0.0)

    execucoes = db.relationship('ServicoCliente', backref='tipo_servico', lazy=True)


class ServicoCliente(db.Model):
    __tablename__ = 'servicos_cliente'
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    
    # Execução Técnica
    valor_cobrado = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='Em Andamento')  # Pendente, Em Andamento, Concluido, Cancelado
    data_solicitacao = db.Column(db.Date, default=date.today)
    data_previsao = db.Column(db.Date, nullable=True)
    observacoes = db.Column(db.Text, nullable=True)

    # Gestão Financeira & Cobrança
    data_vencimento_boleto = db.Column(db.Date, nullable=True)
    status_pagamento = db.Column(db.String(30), default='A Faturar')  # A Faturar, Boleto Emitido, Pago, Em Atraso
    arquivo_boleto = db.Column(db.String(255), nullable=True)
    arquivo_nf = db.Column(db.String(255), nullable=True)
    historico_cobranca = db.Column(db.Text, nullable=True)


class Proposta(db.Model):
    __tablename__ = 'propostas'
    id = db.Column(db.Integer, primary_key=True)
    numero_proposta = db.Column(db.String(30), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    data_criacao = db.Column(db.Date, default=date.today)
    validade_dias = db.Column(db.Integer, default=15)
    condicoes_pagamento = db.Column(db.String(255), default='Boleto Bancário / Transferência em 30 dias')
    observacoes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default='Aguardando Aprovação')

    itens = db.relationship('ItemProposta', backref='proposta', lazy=True, cascade="all, delete-orphan")

    @property
    def valor_total(self):
        return sum(item.valor_unitario for item in self.itens)


class ItemProposta(db.Model):
    __tablename__ = 'itens_proposta'
    id = db.Column(db.Integer, primary_key=True)
    proposta_id = db.Column(db.Integer, db.ForeignKey('propostas.id'), nullable=False)
    tipo_servico_id = db.Column(db.Integer, db.ForeignKey('tipos_servico.id'), nullable=False)
    valor_unitario = db.Column(db.Float, nullable=False, default=0.0)
    descricao_personalizada = db.Column(db.Text, nullable=True)

    tipo_servico = db.relationship('TipoServico')

# -----------------------------------------------------------------------------
# 3. REGRAS AUXILIARES
# -----------------------------------------------------------------------------

def calcular_alerta_avcb(data_vencimento):
    hoje = date.today()
    if data_vencimento < hoje:
        return True, "VENCIDO!"
    
    diferenca = relativedelta(data_vencimento, hoje)
    meses_restantes = (diferenca.years * 12) + diferenca.months
    
    if meses_restantes <= 5:
        if meses_restantes == 0:
            dias_restantes = (data_vencimento - hoje).days
            return True, f"Alerta: Vence em {dias_restantes} dias"
        return True, f"Alerta: Vence em {meses_restantes} mês(es)"
    
    return False, f"Válido por {meses_restantes} meses"

@app.context_processor
def utility_processor():
    return dict(calcular_alerta_avcb=calcular_alerta_avcb)

# -----------------------------------------------------------------------------
# 4. ROTAS DO PAINEL PRINCIPAL & CLIENTES
# -----------------------------------------------------------------------------

@app.route('/')
def index():
    busca = request.args.get('busca', '')
    filtro_alerta = request.args.get('alerta', '')

    query = Cliente.query
    if busca:
        query = query.filter(
            (Cliente.nome.ilike(f'%{busca}%')) | 
            (Cliente.cnpj_cpf.ilike(f'%{busca}%')) |
            (Cliente.cidade.ilike(f'%{busca}%'))
        )

    todos_clientes = query.order_by(Cliente.nome).all()

    if filtro_alerta == 'sim':
        clientes_filtrados = [c for c in todos_clientes if calcular_alerta_avcb(c.data_vencimento_avcb)[0]]
    else:
        clientes_filtrados = todos_clientes

    return render_template('index.html', clientes=clientes_filtrados, busca=busca, filtro_alerta=filtro_alerta)


@app.route('/cliente/novo', methods=['GET', 'POST'])
def novo_cliente():
    if request.method == 'POST':
        area_str = request.form.get('area_construida')
        pav_str = request.form.get('numero_pavimentos')

        cliente = Cliente(
            # 1. Identificação
            nome=request.form.get('nome'),
            nome_fantasia=request.form.get('nome_fantasia'),
            cnpj_cpf=request.form.get('cnpj_cpf'),
            inscricao_estadual=request.form.get('inscricao_estadual'),

            # 2. Contato
            responsavel=request.form.get('responsavel'),
            telefone=request.form.get('telefone'),
            telefone_secundario=request.form.get('telefone_secundario'),
            email=request.form.get('email'),
            email_financeiro=request.form.get('email_financeiro'),

            # 3. Endereço
            cep=request.form.get('cep'),
            logradouro=request.form.get('logradouro'),
            numero=request.form.get('numero'),
            complemento=request.form.get('complemento'),
            bairro=request.form.get('bairro'),
            cidade=request.form.get('cidade'),
            estado=request.form.get('estado'),

            # 4. Dados Técnicos
            area_construida=float(area_str) if area_str else None,
            tipo_ocupacao=request.form.get('tipo_ocupacao'),
            numero_pavimentos=int(pav_str) if pav_str else None,
            numero_projeto_cb=request.form.get('numero_projeto_cb'),
            data_inicio_avcb=datetime.strptime(request.form.get('data_inicio_avcb'), '%Y-%m-%d').date(),
            data_vencimento_avcb=datetime.strptime(request.form.get('data_vencimento_avcb'), '%Y-%m-%d').date(),

            # 5. Observações
            observacoes=request.form.get('observacoes')
        )
        db.session.add(cliente)
        db.session.commit()
        flash('Cliente e dados técnicos cadastrados com sucesso!', 'success')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    return render_template('cadastro.html', cliente=None)


@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
def editar_cliente(id):
    cliente = Cliente.query.get_or_404(id)

    if request.method == 'POST':
        area_str = request.form.get('area_construida')
        pav_str = request.form.get('numero_pavimentos')

        # 1. Identificação
        cliente.nome = request.form.get('nome')
        cliente.nome_fantasia = request.form.get('nome_fantasia')
        cliente.cnpj_cpf = request.form.get('cnpj_cpf')
        cliente.inscricao_estadual = request.form.get('inscricao_estadual')

        # 2. Contato
        cliente.responsavel = request.form.get('responsavel')
        cliente.telefone = request.form.get('telefone')
        cliente.telefone_secundario = request.form.get('telefone_secundario')
        cliente.email = request.form.get('email')
        cliente.email_financeiro = request.form.get('email_financeiro')

        # 3. Endereço
        cliente.cep = request.form.get('cep')
        cliente.logradouro = request.form.get('logradouro')
        cliente.numero = request.form.get('numero')
        cliente.complemento = request.form.get('complemento')
        cliente.bairro = request.form.get('bairro')
        cliente.cidade = request.form.get('cidade')
        cliente.estado = request.form.get('estado')

        # 4. Dados Técnicos
        cliente.area_construida = float(area_str) if area_str else None
        cliente.tipo_ocupacao = request.form.get('tipo_ocupacao')
        cliente.numero_pavimentos = int(pav_str) if pav_str else None
        cliente.numero_projeto_cb = request.form.get('numero_projeto_cb')
        cliente.data_inicio_avcb = datetime.strptime(request.form.get('data_inicio_avcb'), '%Y-%m-%d').date()
        cliente.data_vencimento_avcb = datetime.strptime(request.form.get('data_vencimento_avcb'), '%Y-%m-%d').date()

        # 5. Observações
        cliente.observacoes = request.form.get('observacoes')

        db.session.commit()
        flash('Cadastro completo atualizado com sucesso!', 'success')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    return render_template('cadastro.html', cliente=cliente)


@app.route('/cliente/deletar/<int:id>')
def deletar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente e todo o histórico vinculado foram removidos.', 'warning')
    return redirect(url_for('index'))


@app.route('/cliente/<int:id>')
def detalhe_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    documentos = Documento.query.filter_by(cliente_id=id).order_by(Documento.data_upload.desc()).all()
    alerta_ativo, mensagem_alerta = calcular_alerta_avcb(cliente.data_vencimento_avcb)
    
    return render_template(
        'detalhe_cliente.html', 
        cliente=cliente, 
        documentos=documentos, 
        alerta_ativo=alerta_ativo, 
        mensagem_alerta=mensagem_alerta
    )


@app.route('/cliente/<int:id>/upload', methods=['POST'])
def upload_documento(id):
    cliente = Cliente.query.get_or_404(id)
    
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
def deletar_documento(doc_id):
    doc = Documento.query.get_or_404(doc_id)
    cliente_id = doc.cliente_id

    caminho = os.path.join(app.config['UPLOAD_FOLDER'], doc.nome_arquivo)
    if os.path.exists(caminho):
        os.remove(caminho)

    db.session.delete(doc)
    db.session.commit()
    flash('Documento removido com sucesso.', 'info')
    return redirect(url_for('detalhe_cliente', id=cliente_id))


@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# -----------------------------------------------------------------------------
# 5. ROTAS DE PROPOSTAS COMERCIAIS
# -----------------------------------------------------------------------------

@app.route('/propostas')
def listar_propostas():
    filtro = request.args.get('filtro', 'ativas')
    
    query = Proposta.query
    if filtro == 'ativas':
        query = query.filter_by(status='Aguardando Aprovação')
    elif filtro == 'aprovadas':
        query = query.filter_by(status='Aprovado')
    elif filtro == 'canceladas':
        query = query.filter_by(status='Cancelado')

    propostas = query.order_by(Proposta.id.desc()).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()
    tipos_servico = TipoServico.query.order_by(TipoServico.nome).all()

    total_aguardando = sum(p.valor_total for p in Proposta.query.filter_by(status='Aguardando Aprovação').all())
    total_aprovadas = sum(p.valor_total for p in Proposta.query.filter_by(status='Aprovado').all())
    qtd_aguardando = Proposta.query.filter_by(status='Aguardando Aprovação').count()

    return render_template(
        'propostas.html',
        propostas=propostas,
        clientes=clientes,
        tipos_servico=tipos_servico,
        filtro_atual=filtro,
        total_aguardando=total_aguardando,
        total_aprovadas=total_aprovadas,
        qtd_aguardando=qtd_aguardando
    )


@app.route('/propostas/nova', methods=['POST'])
def criar_proposta():
    cliente_id = int(request.form.get('cliente_id'))
    validade_dias = int(request.form.get('validade_dias') or 15)
    condicoes = request.form.get('condicoes_pagamento') or 'Boleto Bancário / Transferência'
    observacoes = request.form.get('observacoes')
    
    total_existentes = Proposta.query.count() + 1
    numero_proposta = f"PROP-{date.today().year}-{total_existentes:03d}"

    nova_prop = Proposta(
        numero_proposta=numero_proposta,
        cliente_id=cliente_id,
        validade_dias=validade_dias,
        condicoes_pagamento=condicoes,
        observacoes=observacoes,
        status='Aguardando Aprovação'
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
    flash(f'Proposta Comercial {nova_prop.numero_proposta} gerada com sucesso!', 'success')
    return redirect(url_for('listar_propostas'))


@app.route('/propostas/<int:id>/status', methods=['POST'])
def atualizar_status_proposta(id):
    proposta = Proposta.query.get_or_404(id)
    novo_status = request.form.get('novo_status')
    
    if novo_status in ['Aguardando Aprovação', 'Aprovado', 'Cancelado']:
        status_anterior = proposta.status
        proposta.status = novo_status

        if novo_status == 'Aprovado' and status_anterior != 'Aprovado':
            for item in proposta.itens:
                nova_ordem = ServicoCliente(
                    cliente_id=proposta.cliente_id,
                    tipo_servico_id=item.tipo_servico_id,
                    valor_cobrado=item.valor_unitario,
                    status='Em Andamento',
                    data_solicitacao=date.today(),
                    data_previsao=date.today() + relativedelta(days=proposta.validade_dias or 30),
                    observacoes=f"[Ref. {proposta.numero_proposta}] {item.descricao_personalizada or ''}".strip(),
                    status_pagamento='A Faturar'
                )
                db.session.add(nova_ordem)
            
            db.session.commit()
            flash(f'Proposta {proposta.numero_proposta} aprovada! Atividades liberadas para acompanhamento em Serviços.', 'success')
            return redirect(url_for('listar_propostas'))

        db.session.commit()
        flash(f'Status da Proposta {proposta.numero_proposta} alterado para "{novo_status}"!', 'info')
    
    return redirect(url_for('listar_propostas'))

@app.route('/propostas/<int:id>/editar', methods=['POST'])
def editar_proposta(id):
    proposta = Proposta.query.get_or_404(id)
    
    # 1. Atualiza dados principais
    proposta.cliente_id = int(request.form.get('cliente_id'))
    proposta.validade_dias = int(request.form.get('validade_dias') or 15)
    proposta.condicoes_pagamento = request.form.get('condicoes_pagamento') or 'Boleto Bancário / Transferência'
    proposta.observacoes = request.form.get('observacoes')
    
    # 2. Remove os itens antigos da proposta para reinserir os atualizados
    ItemProposta.query.filter_by(proposta_id=proposta.id).delete()
    
    # 3. Captura os novos itens enviados no formulário de edição
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

@app.route('/propostas/<int:id>/pdf')
def gerar_pdf_proposta(id):
    proposta = Proposta.query.get_or_404(id)
    cliente = proposta.cliente
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    elementos = []
    styles = getSampleStyleSheet()

    estilo_titulo = ParagraphStyle('TituloDoc', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=colors.HexColor("#1e293b"))
    estilo_sub = ParagraphStyle('SubTituloDoc', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, leading=14, textColor=colors.HexColor("#0284c7"))
    estilo_corpo = ParagraphStyle('CorpoDoc', parent=styles['Normal'], fontName='Helvetica', fontSize=9, leading=13, textColor=colors.HexColor("#334155"))
    estilo_corpo_bold = ParagraphStyle('CorpoBold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, leading=13, textColor=colors.HexColor("#1e293b"))

    elementos.append(Paragraph("DRD2 ENGENHARIA & PREVENÇÃO CONTRA INCÊNDIO", estilo_titulo))
    elementos.append(Paragraph("Assessoria Técnica, Projetos, Laudos e Licenciamento AVCB / CLCB", estilo_sub))
    elementos.append(Spacer(1, 10))
    elementos.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284c7"), spaceAfter=15))

    endereco_formatado = f"{cliente.logradouro or ''}, {cliente.numero or 'S/N'} {cliente.complemento or ''} - {cliente.bairro or ''}, {cliente.cidade or ''}/{cliente.estado or ''}"

    dados_cabecalho = [
        [
            Paragraph(f"<b>PROPOSTA COMERCIAL:</b> {proposta.numero_proposta}", estilo_corpo),
            Paragraph(f"<b>DATA DE EMISSÃO:</b> {proposta.data_criacao.strftime('%d/%m/%Y')}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>CLIENTE:</b> {cliente.nome}", estilo_corpo),
            Paragraph(f"<b>CNPJ / CPF:</b> {cliente.cnpj_cpf or '-'}", estilo_corpo)
        ],
        [
            Paragraph(f"<b>LOCAL / ENDEREÇO:</b> {endereco_formatado}", estilo_corpo),
            Paragraph(f"<b>VALIDADE:</b> {proposta.validade_dias} dias", estilo_corpo)
        ],
        [
            Paragraph(f"<b>RESPONSÁVEL / TEL:</b> {cliente.responsavel or '-'} | {cliente.telefone}", estilo_corpo),
            Paragraph(f"<b>E-MAIL:</b> {cliente.email}", estilo_corpo)
        ]
    ]
    tabela_cab = Table(dados_cabecalho, colWidths=[3.5*inch, 3.5*inch])
    tabela_cab.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#f1f5f9")),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elementos.append(tabela_cab)
    elementos.append(Spacer(1, 15))

    elementos.append(Paragraph("ESCOPO DOS SERVIÇOS TÉCNICOS PROPOSTOS", estilo_sub))
    elementos.append(Spacer(1, 8))

    dados_itens = [
        [
            Paragraph("<b>Item / Serviço</b>", estilo_corpo_bold),
            Paragraph("<b>Detalhamento Técnico / Escopo</b>", estilo_corpo_bold),
            Paragraph("<b>Valor (R$)</b>", estilo_corpo_bold)
        ]
    ]

    for idx, item in enumerate(proposta.itens, 1):
        descricao = item.descricao_personalizada or item.tipo_servico.descricao_padrao or "Conforme normas técnicas vigentes e ITs do Corpo de Bombeiros."
        dados_itens.append([
            Paragraph(f"<b>{idx}. {item.tipo_servico.nome}</b>", estilo_corpo),
            Paragraph(descricao, estilo_corpo),
            Paragraph(f"R$ {item.valor_unitario:,.2f}", estilo_corpo_bold)
        ])

    dados_itens.append([
        Paragraph("<b>TOTAL GLOBAL DO INVESTIMENTO</b>", estilo_corpo_bold),
        Paragraph("", estilo_corpo),
        Paragraph(f"<b>R$ {proposta.valor_total:,.2f}</b>", ParagraphStyle('TotalText', parent=estilo_corpo_bold, fontSize=11, textColor=colors.HexColor("#16a34a")))
    ])

    tabela_itens = Table(dados_itens, colWidths=[2.2*inch, 3.6*inch, 1.2*inch])
    tabela_itens.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#0f172a")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('GRID', (0,0), (-1,-2), 0.5, colors.HexColor("#cbd5e1")),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor("#f1f5f9")),
        ('LINEABOVE', (0,-1), (-1,-1), 1.5, colors.HexColor("#0f172a")),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    elementos.append(tabela_itens)
    elementos.append(Spacer(1, 15))

    elementos.append(Paragraph("CONDIÇÕES COMERCIAIS & PAGAMENTO", estilo_sub))
    elementos.append(Spacer(1, 6))
    elementos.append(Paragraph(f"• <b>Condição de Pagamento:</b> {proposta.condicoes_pagamento}", estilo_corpo))
    if proposta.observacoes:
        elementos.append(Paragraph(f"• <b>Observações:</b> {proposta.observacoes}", estilo_corpo))
    elementos.append(Paragraph("• <b>Incluso:</b> Emissão de ART (Anotação de Responsabilidade Técnica), taxas e assessoria completa.", estilo_corpo))

    elementos.append(Spacer(1, 35))

    dados_assinaturas = [
        [
            Paragraph("____________________________________________<br/><b>DRD2 ENGENHARIA</b><br/>Responsável Técnico", estilo_corpo),
            Paragraph("____________________________________________<br/><b>DE ACORDO DO CLIENTE</b><br/>Assinatura / Carimbo", estilo_corpo)
        ]
    ]
    tab_ass = Table(dados_assinaturas, colWidths=[3.5*inch, 3.5*inch])
    tab_ass.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elementos.append(tab_ass)

    doc.build(elementos)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Carta_Proposta_{proposta.numero_proposta}.pdf",
        mimetype='application/pdf'
    )

# -----------------------------------------------------------------------------
# 6. ROTAS DE OPERAÇÃO & SERVIÇOS
# -----------------------------------------------------------------------------

@app.route('/servicos')
def consultar_servicos():
    filtro_status = request.args.get('status', 'Em Andamento')
    
    query = ServicoCliente.query
    if filtro_status != 'Todos':
        query = query.filter_by(status=filtro_status)
        
    servicos_operacionais = query.order_by(ServicoCliente.data_previsao.asc(), ServicoCliente.id.desc()).all()
    catalogo = TipoServico.query.order_by(TipoServico.nome).all()
    clientes = Cliente.query.order_by(Cliente.nome).all()

    qtd_em_andamento = ServicoCliente.query.filter_by(status='Em Andamento').count()
    qtd_pendentes = ServicoCliente.query.filter_by(status='Pendente').count()
    qtd_concluidos = ServicoCliente.query.filter_by(status='Concluido').count()

    return render_template(
        'servicos.html', 
        catalogo=catalogo, 
        servicos_operacionais=servicos_operacionais, 
        clientes=clientes,
        filtro_atual=filtro_status,
        qtd_em_andamento=qtd_em_andamento,
        qtd_pendentes=qtd_pendentes,
        qtd_concluidos=qtd_concluidos,
        hoje=date.today()
    )


@app.route('/servicos/catalogo/novo', methods=['POST'])
def novo_tipo_servico():
    nome = request.form.get('nome')
    descricao = request.form.get('descricao')
    valor_sugerido = float(request.form.get('valor_sugerido') or 0.0)

    if nome:
        novo_tipo = TipoServico(nome=nome, descricao_padrao=descricao, valor_sugerido=valor_sugerido)
        db.session.add(novo_tipo)
        db.session.commit()
        flash(f'Serviço "{nome}" cadastrado no catálogo!', 'success')
        
    return redirect(url_for('consultar_servicos'))


@app.route('/servicos/vincular', methods=['POST'])
def vincular_servico_cliente():
    cliente_id = int(request.form.get('cliente_id'))
    tipo_servico_id = int(request.form.get('tipo_servico_id'))
    valor_cobrado = float(request.form.get('valor_cobrado') or 0.0)
    data_previsao_str = request.form.get('data_previsao')
    observacoes = request.form.get('observacoes')

    data_previsao = datetime.strptime(data_previsao_str, '%Y-%m-%d').date() if data_previsao_str else None

    novo_vinculo = ServicoCliente(
        cliente_id=cliente_id,
        tipo_servico_id=tipo_servico_id,
        valor_cobrado=valor_cobrado,
        data_previsao=data_previsao,
        observacoes=observacoes,
        status='Em Andamento',
        status_pagamento='A Faturar'
    )
    db.session.add(novo_vinculo)
    db.session.commit()
    flash('Atividade manual criada e em execução!', 'success')
    return redirect(url_for('consultar_servicos'))


@app.route('/servicos/atualizar-operacao/<int:id>', methods=['POST'])
def atualizar_operacao_servico(id):
    servico = ServicoCliente.query.get_or_404(id)
    
    servico.status = request.form.get('status', servico.status)
    data_prev_str = request.form.get('data_previsao')
    servico.data_previsao = datetime.strptime(data_prev_str, '%Y-%m-%d').date() if data_prev_str else None
    servico.observacoes = request.form.get('observacoes')

    db.session.commit()

    if servico.status == 'Concluido':
        flash(f'Atividade "{servico.tipo_servico.nome}" ({servico.cliente.nome}) concluída e liberada para o Financeiro!', 'success')
    else:
        flash('Acompanhamento técnico atualizado.', 'info')

    return redirect(url_for('consultar_servicos', status=request.form.get('filtro_retorno', 'Em Andamento')))

# -----------------------------------------------------------------------------
# 7. ROTAS DO MÓDULO FINANCEIRO
# -----------------------------------------------------------------------------

@app.route('/financeiro')
def financeiro():
    filtro_status = request.args.get('status', 'todos')
    hoje = date.today()

    servicos_concluidos = ServicoCliente.query.filter_by(status='Concluido').order_by(
        ServicoCliente.data_vencimento_boleto.asc(),
        ServicoCliente.id.desc()
    ).all()

    lista_processada = []
    for s in servicos_concluidos:
        status_exibicao = s.status_pagamento
        if s.status_pagamento in ['Boleto Emitido', 'A Faturar'] and s.data_vencimento_boleto and s.data_vencimento_boleto < hoje:
            status_exibicao = 'Em Atraso'
        
        item_dict = {
            'servico': s,
            'status_calculado': status_exibicao,
            'esta_vencido': s.data_vencimento_boleto and s.data_vencimento_boleto < hoje and s.status_pagamento != 'Pago'
        }

        if filtro_status == 'aguardando' and status_exibicao == 'Boleto Emitido':
            lista_processada.append(item_dict)
        elif filtro_status == 'atrasados' and status_exibicao == 'Em Atraso':
            lista_processada.append(item_dict)
        elif filtro_status == 'afaturar' and status_exibicao == 'A Faturar':
            lista_processada.append(item_dict)
        elif filtro_status == 'pagos' and status_exibicao == 'Pago':
            lista_processada.append(item_dict)
        elif filtro_status == 'todos':
            lista_processada.append(item_dict)

    total_recebido = sum(s.valor_cobrado for s in servicos_concluidos if s.status_pagamento == 'Pago')
    total_aguardando = sum(s.valor_cobrado for s in servicos_concluidos if s.status_pagamento == 'Boleto Emitido' and (not s.data_vencimento_boleto or s.data_vencimento_boleto >= hoje))
    total_atrasado = sum(s.valor_cobrado for s in servicos_concluidos if (s.status_pagamento == 'Em Atraso') or (s.data_vencimento_boleto and s.data_vencimento_boleto < hoje and s.status_pagamento != 'Pago'))
    total_a_faturar = sum(s.valor_cobrado for s in servicos_concluidos if s.status_pagamento == 'A Faturar' and not s.data_vencimento_boleto)

    qtd_atrasados = len([s for s in servicos_concluidos if s.data_vencimento_boleto and s.data_vencimento_boleto < hoje and s.status_pagamento != 'Pago'])

    return render_template(
        'financeiro.html',
        itens=lista_processada,
        filtro_atual=filtro_status,
        total_recebido=total_recebido,
        total_aguardando=total_aguardando,
        total_atrasado=total_atrasado,
        total_a_faturar=total_a_faturar,
        qtd_atrasados=qtd_atrasados,
        hoje=hoje
    )


@app.route('/financeiro/servico/<int:id>/atualizar', methods=['POST'])
def atualizar_cobranca_servico(id):
    servico = ServicoCliente.query.get_or_404(id)
    
    data_venc_str = request.form.get('data_vencimento_boleto')
    servico.data_vencimento_boleto = datetime.strptime(data_venc_str, '%Y-%m-%d').date() if data_venc_str else None
    servico.status_pagamento = request.form.get('status_pagamento', servico.status_pagamento)

    nova_nota = request.form.get('nova_ocorrencia')
    if nova_nota and nova_nota.strip():
        data_registro = datetime.now().strftime('%d/%m/%Y %H:%M')
        registro = f"[{data_registro}] {nova_nota.strip()}"
        servico.historico_cobranca = f"{registro}\n{servico.historico_cobranca}" if servico.historico_cobranca else registro

    if 'arquivo_boleto' in request.files:
        file_boleto = request.files['arquivo_boleto']
        if file_boleto and file_boleto.filename != '':
            nome_limpo = secure_filename(file_boleto.filename)
            nome_salvo = f"boleto_{servico.id}_{int(datetime.utcnow().timestamp())}_{nome_limpo}"
            file_boleto.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_salvo))
            servico.arquivo_boleto = nome_salvo

    if 'arquivo_nf' in request.files:
        file_nf = request.files['arquivo_nf']
        if file_nf and file_nf.filename != '':
            nome_limpo = secure_filename(file_nf.filename)
            nome_salvo = f"nf_{servico.id}_{int(datetime.utcnow().timestamp())}_{nome_limpo}"
            file_nf.save(os.path.join(app.config['UPLOAD_FOLDER'], nome_salvo))
            servico.arquivo_nf = nome_salvo

    db.session.commit()
    flash(f'Dados de cobrança de {servico.cliente.nome} atualizados com sucesso!', 'success')
    return redirect(url_for('financeiro', status=request.form.get('filtro_retorno', 'todos')))

# -----------------------------------------------------------------------------
# 8. INICIALIZAÇÃO E CRIAÇÃO AUTOMÁTICA DAS TABELAS
# -----------------------------------------------------------------------------
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)