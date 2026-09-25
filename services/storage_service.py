import io
import os
import uuid
import boto3
from PIL import Image, ImageOps
from botocore.config import Config
from werkzeug.utils import secure_filename

EXTENSOES_PERMITIDAS = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}
MAX_TAMANHO_BYTES = 2 * 1024 * 1024  # 2 MB por arquivo

def obter_cliente_s3():
    """Conecta ao Supabase Storage via protocolo S3."""
    return boto3.client(
        's3',
        endpoint_url=os.getenv('SUPABASE_S3_ENDPOINT'),
        aws_access_key_id=os.getenv('SUPABASE_S3_ACCESS_KEY'),
        aws_secret_access_key=os.getenv('SUPABASE_S3_SECRET_KEY'),
        region_name=os.getenv('SUPABASE_S3_REGION', 'sa-east-1'),
        config=Config(signature_version='s3v4')
    )

def otimizar_imagem_se_necessario(file_storage, max_dimensao=1600, qualidade=80):
    """
    Se for imagem (PNG/JPG/WEBP), redimensiona proporcionalmente,
    corrige a orientação EXIF do celular e comprime em JPEG na memória.
    Retorna (BytesIO_otimizado, nova_extensao, content_type).
    """
    ext = file_storage.filename.rsplit('.', 1)[-1].lower()
    
    # Se for PDF, mantém original
    if ext == 'pdf':
        return file_storage, ext, 'application/pdf'

    try:
        img = Image.open(file_storage)
        # Corrige rotação automática de foto tirada no celular (dados EXIF)
        img = ImageOps.exif_transpose(img)
        
        # Converte modos com transparência para RGB com fundo branco
        if img.mode in ('RGBA', 'P'):
            fundo_branco = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                fundo_branco.paste(img, mask=img.split()[3])
            else:
                fundo_branco.paste(img)
            img = fundo_branco
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Redimensiona mantendo a proporção caso exceda max_dimensao
        img.thumbnail((max_dimensao, max_dimensao), Image.Resampling.LANCZOS)

        buffer_saida = io.BytesIO()
        img.save(buffer_saida, format='JPEG', optimize=True, quality=qualidade)
        buffer_saida.seek(0)
        
        return buffer_saida, 'jpg', 'image/jpeg'
    except Exception as e:
        print(f"[AVISO COMPRESSAO IMAGEM]: {e}. Mantendo arquivo original.")
        file_storage.seek(0)
        return file_storage, ext, file_storage.content_type

def salvar_arquivo_supabase(file_storage, pasta_destino, empresa_id):
    """
    Valida extensão, comprime fotos automaticamente via Pillow,
    valida o tamanho final (máx 2MB), renomeia com UUID e faz upload.
    Retorna a chave única: emp_<id>/<pasta>/<uuid>.<ext>
    """
    if not file_storage or not getattr(file_storage, 'filename', None):
        return None

    nome_seguro = secure_filename(file_storage.filename)
    if '.' not in nome_seguro:
        raise ValueError("Arquivo sem extensão válida.")

    extensao = nome_seguro.rsplit('.', 1)[-1].lower()
    if extensao not in EXTENSOES_PERMITIDAS:
        raise ValueError(f"Extensão '.{extensao}' não é permitida por motivos de segurança.")

    # 1. Compressão e Otimização Automática
    arquivo_processado, nova_ext, content_type = otimizar_imagem_se_necessario(file_storage)

    # 2. Validação rigorosa do tamanho pós-compressão (Máx 2 MB)
    arquivo_processado.seek(0, os.SEEK_END)
    tamanho = arquivo_processado.tell()
    arquivo_processado.seek(0)

    if tamanho > MAX_TAMANHO_BYTES:
        raise ValueError("O arquivo excede o limite máximo permitido de 2 MB mesmo após otimização.")

    chave_bucket = f"emp_{empresa_id}/{pasta_destino}/{uuid.uuid4().hex}.{nova_ext}"
    bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
    
    s3 = obter_cliente_s3()
    s3.upload_fileobj(
        arquivo_processado,
        bucket,
        chave_bucket,
        ExtraArgs={
            'ContentType': content_type
        }
    )
    return chave_bucket

def excluir_arquivo_supabase(chave_bucket):
    """Remove o arquivo do bucket S3."""
    if not chave_bucket:
        return False
    try:
        bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
        s3 = obter_cliente_s3()
        s3.delete_object(Bucket=bucket, Key=chave_bucket)
        return True
    except Exception as e:
        print(f"[ERRO AO EXCLUIR ARQUIVO S3]: {e}")
        return False

def gerar_url_temporaria(chave_bucket, tempo_segundos=900):
    """Gera link pré-assinado com validade de 15 minutos (900s)."""
    if not chave_bucket:
        return None

    bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
    s3 = obter_cliente_s3()

    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': chave_bucket},
        ExpiresIn=tempo_segundos
    )

def obter_arquivo_bytes(chave_bucket):
    """
    Baixa os bytes do arquivo em memória (BytesIO).
    Ideal para alimentar o ReportLab (geração de PDF de logo) sem gravar no disco.
    """
    if not chave_bucket:
        return None
    try:
        bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
        s3 = obter_cliente_s3()
        resposta = s3.get_object(Bucket=bucket, Key=chave_bucket)
        return io.BytesIO(resposta['Body'].read())
    except Exception as e:
        print(f"[ERRO AO BAIXAR BYTES S3]: {e}")
        return None

def excluir_pasta_empresa_supabase(empresa_id):
    """
    Remove todos os arquivos e anexos pertencentes à empresa no bucket Supabase.
    Identifica todos os objetos com o prefixo emp_<empresa_id>/
    """
    try:
        bucket = os.getenv('SUPABASE_BUCKET_NAME', 'trivium-documentos')
        s3 = obter_cliente_s3()
        prefixo = f"emp_{empresa_id}/"

        paginator = s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=prefixo):
            if 'Contents' in page:
                objetos = [{'Key': obj['Key']} for obj in page['Contents']]
                s3.delete_objects(Bucket=bucket, Delete={'Objects': objetos})
        return True
    except Exception as e:
        print(f"[ERRO AO LIMPAR ARQUIVOS DA EMPRESA NO S3]: {e}")
        return False