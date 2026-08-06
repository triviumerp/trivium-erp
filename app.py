import os
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from flask_sqlalchemy import SQLAlchemy

# 1. Criação do Objeto App (DEVE vir DEPOIS das importações acima)
app = Flask(__name__)

# 2. Configuração do Diretório de Uploads
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'chave_secreta_para_mensagens_flash_drd2'

# 3. Configuração da Conexão com o Banco de Dados (Local x Nuvem)
uri_banco = os.getenv('DATABASE_URL', 'sqlite:///database.db')

if uri_banco.startswith("postgres://"):
    uri_banco = uri_banco.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = uri_banco
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 4. Inicialização do Banco de Dados
db = SQLAlchemy(app)

# -----------------------------------------------------------------------------
# MODELOS DO BANCO DE DADOS (TABELAS)
# -----------------------------------------------------------------------------
class Cliente(db.Model):
    __tablename__ = 'clientes'
    
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    data_inicio_avcb = db.Column(db.Date, nullable=False)
    data_vencimento_avcb = db.Column(db.Date, nullable=False)
    valor_proposta = db.Column(db.Float, nullable=False, default=0.0)
    status_boleto = db.Column(db.String(20), nullable=False, default='Pendente') # 'Pendente', 'Pago', 'Atrasado'

    # Relacionamento com a tabela de documentos (exclui docs se o cliente for deletado)
    documentos = db.relationship('Documento', backref='cliente', cascade='all, delete-orphan', lazy=True)


class Documento(db.Model):
    __tablename__ = 'documentos'
    
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    nome_arquivo = db.Column(db.String(255), nullable=False)
    tipo_documento = db.Column(db.String(50), nullable=False) # 'AVCB', 'Projeto', 'ART', 'Outros'
    data_upload = db.Column(db.DateTime, default=datetime.utcnow)

# Criar o banco e as tabelas automaticamente se não existirem
with app.app_context():
    db.create_all()

# -----------------------------------------------------------------------------
# REGRA DE NEGÓCIO: ALERTA DE VENCIMENTO DO AVCB
# -----------------------------------------------------------------------------
def calcular_alerta_avcb(data_vencimento):
    """
    Calcula a diferença em meses entre a data atual e o vencimento do AVCB.
    Retorna: (alerta_ativo: bool, mensagem: str)
    Regra: Se faltarem 5 meses ou menos, ativa o alerta vermelho.
    """
    hoje = date.today()
    if data_vencimento < hoje:
        return True, "VENCIDO!"
    
    # Diferença exata de tempo
    diferenca = relativedelta(data_vencimento, hoje)
    meses_restantes = (diferenca.years * 12) + diferenca.months
    
    if meses_restantes <= 5:
        if meses_restantes == 0:
            dias_restantes = (data_vencimento - hoje).days
            return True, f"Alerta: Vence em {dias_restantes} dias"
        return True, f"Alerta: Vence em {meses_restantes} mês(es)"
    
    return False, f"Válido por {meses_restantes} meses"

# Injeta a função de alerta no motor Jinja2 para usar direto nos arquivos HTML
@app.context_processor
def utility_processor():
    return dict(calcular_alerta_avcb=calcular_alerta_avcb)

# -----------------------------------------------------------------------------
# ROTAS DO SISTEMA
# -----------------------------------------------------------------------------

# 1. DASHBOARD PRINCIPAL (Listagem + Busca + Filtro de Alerta)
@app.route('/')
def index():
    busca = request.args.get('busca', '')
    filtro_alerta = request.args.get('alerta', '')

    query = Cliente.query

    # Filtra por nome se houver busca
    if busca:
        query = query.filter(Cliente.nome.ilike(f'%{busca}%'))

    todos_clientes = query.all()

    # Filtro para exibir apenas AVCBs próximos de vencer (<= 5 meses)
    clientes_filtrados = []
    if filtro_alerta == 'sim':
        for c in todos_clientes:
            alerta_ativo, _ = calcular_alerta_avcb(c.data_vencimento_avcb)
            if alerta_ativo:
                clientes_filtrados.append(c)
    else:
        clientes_filtrados = todos_clientes

    return render_template('index.html', clientes=clientes_filtrados, busca=busca, filtro_alerta=filtro_alerta)


# 2. CADASTRAR CLIENTE
@app.route('/cliente/novo', methods=['GET', 'POST'])
def novo_cliente():
    if request.method == 'POST':
        nome = request.form.get('nome')
        telefone = request.form.get('telefone')
        email = request.form.get('email')
        data_inicio = datetime.strptime(request.form.get('data_inicio_avcb'), '%Y-%m-%d').date()
        data_venc = datetime.strptime(request.form.get('data_vencimento_avcb'), '%Y-%m-%d').date()
        valor = float(request.form.get('valor_proposta', 0.0))
        status = request.form.get('status_boleto')

        cliente = Cliente(
            nome=nome,
            telefone=telefone,
            email=email,
            data_inicio_avcb=data_inicio,
            data_vencimento_avcb=data_venc,
            valor_proposta=valor,
            status_boleto=status
        )
        db.session.add(cliente)
        db.session.commit()
        
        flash('Cliente cadastrado com sucesso!', 'success')
        return redirect(url_for('index'))

    return render_template('cadastro.html', cliente=None)


# 3. EDITAR CLIENTE
@app.route('/cliente/editar/<int:id>', methods=['GET', 'POST'])
def editar_cliente(id):
    cliente = Cliente.query.get_or_404(id)

    if request.method == 'POST':
        cliente.nome = request.form.get('nome')
        cliente.telefone = request.form.get('telefone')
        cliente.email = request.form.get('email')
        cliente.data_inicio_avcb = datetime.strptime(request.form.get('data_inicio_avcb'), '%Y-%m-%d').date()
        cliente.data_vencimento_avcb = datetime.strptime(request.form.get('data_vencimento_avcb'), '%Y-%m-%d').date()
        cliente.valor_proposta = float(request.form.get('valor_proposta', 0.0))
        cliente.status_boleto = request.form.get('status_boleto')

        db.session.commit()
        flash('Dados do cliente atualizados!', 'success')
        return redirect(url_for('detalhe_cliente', id=cliente.id))

    return render_template('cadastro.html', cliente=cliente)


# 4. EXCLUIR CLIENTE
@app.route('/cliente/deletar/<int:id>')
def deletar_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    db.session.delete(cliente)
    db.session.commit()
    flash('Cliente e seus registros foram removidos.', 'warning')
    return redirect(url_for('index'))


# 5. PERFIL DO CLIENTE (Documentos + Financeiro)
@app.route('/cliente/<int:id>')
def detalhe_cliente(id):
    cliente = Cliente.query.get_or_404(id)
    documentos = Documento.query.filter_by(cliente_id=id).order_by(Documento.data_upload.desc()).all()
    alerta_ativo, mensagem_alerta = calcular_alerta_avcb(cliente.data_vencimento_avcb)
    
    return render_template('detalhe_cliente.html', 
                           cliente=cliente, 
                           documentos=documentos, 
                           alerta_ativo=alerta_ativo, 
                           mensagem_alerta=mensagem_alerta)


# 6. ATUALIZAR STATUS FINANCEIRO
@app.route('/cliente/<int:id>/financeiro', methods=['POST'])
def atualizar_financeiro(id):
    cliente = Cliente.query.get_or_404(id)
    cliente.valor_proposta = float(request.form.get('valor_proposta', 0.0))
    cliente.status_boleto = request.form.get('status_boleto')
    
    db.session.commit()
    flash('Status financeiro atualizado!', 'success')
    return redirect(url_for('detalhe_cliente', id=cliente.id))


# 7. UPLOAD DE DOCUMENTOS (PDF / IMAGEM)
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
        nome_original = file.filename
        nome_salvo = f"cli_{cliente.id}_{int(datetime.utcnow().timestamp())}_{nome_original}"
        caminho_completo = os.path.join(app.config['UPLOAD_FOLDER'], nome_salvo)
        file.save(caminho_completo)

        doc = Documento(
            cliente_id=cliente.id,
            nome_arquivo=nome_salvo,
            tipo_documento=tipo
        )
        db.session.add(doc)
        db.session.commit()
        
        flash('Documento anexado com sucesso!', 'success')

    return redirect(url_for('detalhe_cliente', id=id))


# 8. DOWNLOAD / ABRIR ARQUIVO
@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# 9. EXCLUIR DOCUMENTO
@app.route('/documento/deletar/<int:doc_id>')
def deletar_documento(doc_id):
    doc = Documento.query.get_or_404(doc_id)
    cliente_id = doc.cliente_id

    # Deleta o arquivo físico da pasta static/uploads
    caminho_arquivo = os.path.join(app.config['UPLOAD_FOLDER'], doc.nome_arquivo)
    if os.path.exists(caminho_arquivo):
        os.remove(caminho_arquivo)

    db.session.delete(doc)
    db.session.commit()
    
    flash('Documento removido.', 'info')
    return redirect(url_for('detalhe_cliente', id=cliente_id))


if __name__ == '__main__':
    app.run(debug=True)