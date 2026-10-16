import io
import os
import uuid
import shutil
from werkzeug.utils import secure_filename
from PIL import Image, ImageOps

try:
    import pypdf
except ImportError:
    pypdf = None

# Extensões seguras permitidas
EXTENSOES_PERMITIDAS = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}
MAX_TAMANHO_BYTES = 2 * 1024 * 1024  # Limite estrito de 2 MB por arquivo

# Diretório base do Disco Persistente do Render (ou fallback para ambiente local)
PASTA_STORAGE_LOCAL = os.getenv(
    'UPLOAD_STORAGE_PATH',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'uploads')
)

os.makedirs(PASTA_STORAGE_LOCAL, exist_ok=True)


def _caminho_absoluto(chave_relativa):
    """Resolve a chave relativa para o caminho real no disco persistente."""
    if not chave_relativa:
        return None
    # Prevenção contra path traversal
    chave_limpa = chave_relativa.replace('\\', '/').lstrip('/')
    return os.path.join(PASTA_STORAGE_LOCAL, chave_limpa)


def otimizar_pdf(file_storage):
    """
    Comprime streams internas de PDFs (texto, fontes e vetores) se o pypdf estiver disponível.
    Retorna (BytesIO, 'pdf', 'application/pdf').
    """
    file_storage.seek(0)
    conteudo = file_storage.read()

    if not pypdf:
        return io.BytesIO(conteudo), 'pdf', 'application/pdf'

    try:
        leitor = pypdf.PdfReader(io.BytesIO(conteudo))
        escritor = pypdf.PdfWriter()

        for pagina in leitor.pages:
            pagina.compress_content_streams()
            escritor.add_page(pagina)

        if leitor.metadata:
            escritor.add_metadata(leitor.metadata)

        buffer_saida = io.BytesIO()
        escritor.write(buffer_saida)
        buffer_saida.seek(0)

        # Se a compressão reduziu o tamanho, usa a versão otimizada
        if buffer_saida.getbuffer().nbytes < len(conteudo):
            return buffer_saida, 'pdf', 'application/pdf'
    except Exception as e:
        print(f"[AVISO COMPRESSAO PDF]: {e}. Mantendo arquivo original.")

    return io.BytesIO(conteudo), 'pdf', 'application/pdf'


def otimizar_imagem_se_necessario(file_storage, pasta_destino='documentos', max_dimensao=1920, qualidade=82):
    """
    Redimensiona proporcionalmente, corrige orientação EXIF e reduz o tamanho:
    - Se for logotipo ou imagem com transparência (PNG): preserva o canal alpha.
    - Se for foto geral (câmera, comprovantes, ordens de serviço): converte para JPEG otimizado.
    """
    ext = file_storage.filename.rsplit('.', 1)[-1].lower()

    if ext == 'pdf':
        return otimizar_pdf(file_storage)

    file_storage.seek(0)
    try:
        img = Image.open(file_storage)
        img = ImageOps.exif_transpose(img)

        # 1. Tratamento para logotipos ou imagens com canal de transparência
        if pasta_destino == 'logos' or ext == 'png':
            max_dim = min(max_dimensao, 1000)
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            buffer_saida = io.BytesIO()

            if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                img.save(buffer_saida, format='PNG', optimize=True)
                buffer_saida.seek(0)
                return buffer_saida, 'png', 'image/png'
            else:
                img = img.convert('RGB')
                img.save(buffer_saida, format='JPEG', optimize=True, quality=qualidade)
                buffer_saida.seek(0)
                return buffer_saida, 'jpg', 'image/jpeg'

        # 2. Tratamento para fotos gerais de operação, comprovantes e notas
        if img.mode in ('RGBA', 'P', 'LA'):
            fundo_branco = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                fundo_branco.paste(img, mask=img.split()[3])
            else:
                fundo_branco.paste(img)
            img = fundo_branco
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        img.thumbnail((max_dimensao, max_dimensao), Image.Resampling.LANCZOS)
        buffer_saida = io.BytesIO()
        img.save(buffer_saida, format='JPEG', optimize=True, quality=qualidade)
        buffer_saida.seek(0)

        return buffer_saida, 'jpg', 'image/jpeg'
    except Exception as e:
        print(f"[AVISO COMPRESSAO IMAGEM]: {e}. Usando original.")
        file_storage.seek(0)
        return io.BytesIO(file_storage.read()), ext, getattr(file_storage, 'content_type', 'application/octet-stream')


def salvar_arquivo_supabase(file_storage, pasta_destino, empresa_id):
    """
    Substitui a dependência do Supabase: grava de forma nativa e segura
    no Disco Persistente do Render com isolamento multi-tenant (emp_<id>/<pasta>/<uuid>.<ext>).
    """
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None

    nome_seguro = secure_filename(file_storage.filename)
    if '.' not in nome_seguro:
        raise ValueError("Arquivo sem extensão válida.")

    extensao = nome_seguro.rsplit('.', 1)[-1].lower()
    if extensao not in EXTENSOES_PERMITIDAS:
        raise ValueError(f"Extensão '.{extensao}' não é permitida por motivos de segurança.")

    # 1. Compressão inteligente
    arquivo_processado, nova_ext, _ = otimizar_imagem_se_necessario(
        file_storage, pasta_destino=pasta_destino
    )

    # 2. Validação rigorosa do tamanho final (Teto de 2 MB)
    arquivo_processado.seek(0, os.SEEK_END)
    tamanho = arquivo_processado.tell()
    arquivo_processado.seek(0)

    if tamanho > MAX_TAMANHO_BYTES:
        tamanho_mb = round(tamanho / (1024 * 1024), 2)
        raise ValueError(f"O arquivo ({tamanho_mb} MB) excede o limite máximo permitido de 2 MB mesmo após otimização.")

    # 3. Criação do caminho isolado da empresa no disco persistente
    nome_uuid = f"{uuid.uuid4().hex}.{nova_ext}"
    chave_relativa = f"emp_{empresa_id}/{pasta_destino}/{nome_uuid}"

    diretorio_destino = os.path.join(PASTA_STORAGE_LOCAL, f"emp_{empresa_id}", pasta_destino)
    os.makedirs(diretorio_destino, exist_ok=True)

    caminho_final = os.path.join(diretorio_destino, nome_uuid)
    with open(caminho_final, 'wb') as f_out:
        f_out.write(arquivo_processado.read())

    return chave_relativa


def excluir_arquivo_supabase(chave_bucket):
    """Remove o arquivo do disco persistente."""
    if not chave_bucket:
        return False
    caminho = _caminho_absoluto(chave_bucket)
    if caminho and os.path.exists(caminho):
        try:
            os.remove(caminho)
            return True
        except Exception as e:
            print(f"[ERRO AO EXCLUIR ARQUIVO DO DISCO]: {e}")
    return False


def gerar_url_temporaria(chave_bucket, tempo_segundos=900):
    """
    Substitui a URL pré-assinada do S3.
    Retorna a rota interna segura do próprio ERP para entrega do arquivo.
    """
    if not chave_bucket:
        return None
    return f"/uploads/{chave_bucket}"


def obter_arquivo_bytes(chave_bucket):
    """
    Lê os bytes do arquivo direto do disco montado do Render.
    Alimenta o ReportLab (geração de PDFs) ou pacotes ZIP instantaneamente sem requisição de rede.
    """
    if not chave_bucket:
        return None
    caminho = _caminho_absoluto(chave_bucket)
    if caminho and os.path.exists(caminho):
        try:
            with open(caminho, 'rb') as f_in:
                return io.BytesIO(f_in.read())
        except Exception as e:
            print(f"[ERRO AO LER BYTES DO ARQUIVO]: {e}")
    return None


def excluir_pasta_empresa_supabase(empresa_id):
    """Remove todos os dados e pastas da empresa no disco persistente."""
    caminho_empresa = os.path.join(PASTA_STORAGE_LOCAL, f"emp_{empresa_id}")
    if os.path.exists(caminho_empresa):
        try:
            shutil.rmtree(caminho_empresa)
            return True
        except Exception as e:
            print(f"[ERRO AO EXCLUIR DIRETORIO DA EMPRESA]: {e}")
    return False