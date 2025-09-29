from flask import Flask, request, jsonify, render_template, send_file
import os
import re
import json
import time
import uuid
import threading
import logging
import base64
from werkzeug.utils import secure_filename
import pandas as pd
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Inicializar Flask
app = Flask(__name__)

# Configurações
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
RESULTS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Criar diretórios se não existirem
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# Configurar limite de upload
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Dicionário para armazenar tarefas
tasks = {}

def allowed_file(filename):
    """Verifica se o arquivo tem uma extensão permitida"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def scrape_webpage_with_selenium(url, headless=True, wait_time=5):
    """
    Faz o scraping de uma página web usando Selenium para simular um navegador real.
    
    Args:
        url (str): URL da página web a ser extraída
        headless (bool): Se True, executa o navegador em modo headless (sem interface gráfica)
        wait_time (int): Tempo de espera em segundos para carregamento da página
        
    Returns:
        str: Conteúdo HTML da página
    """
    try:
        # Configurar opções do Chrome
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")


        # Forçar idioma preferencial: pt-BR > pt > en-US > en  (Solução para o YouTube)
        ###chrome_options.add_argument("--lang=pt-BR")
        ###prefs = {"intl.accept_languages": "pt-BR,pt,en-US,en"}
        ###chrome_options.add_experimental_option("prefs", prefs)

        
        # Adicionar user-agent para parecer um navegador real
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.7049.84 Safari/537.36")
        
        # Inicializar o driver
        logger.info("Inicializando o Chrome WebDriver...")
        driver = webdriver.Chrome(options=chrome_options)


        # Forçar Accept-Language via DevTools Protocol (CDP) (Solução para o Youtube)
        ###driver.execute_cdp_cmd(
        ###    "Network.setExtraHTTPHeaders",
        ###    {"headers": {"Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7"}}
        ###)

        
        # Acessar a URL
        logger.info(f"Acessando a URL: {url}")
        driver.get(url)
        
        # Aguardar o carregamento da página
        logger.info(f"Aguardando {wait_time} segundos para carregamento completo...")
        time.sleep(wait_time)
        
        # Obter o conteúdo HTML
        html_content = driver.page_source
        
        # Fechar o driver
        driver.quit()
        
        return html_content
    
    except Exception as e:
        logger.error(f"Erro ao acessar a URL com Selenium: {e}")
        return None

def clean_text(html_content):
    """
    Limpa o conteúdo HTML removendo elementos não relevantes como cabeçalho, rodapé, propagandas, etc.
    
    Args:
        html_content (str): Conteúdo HTML da página
        
    Returns:
        str: Texto limpo e processado
    """
    if not html_content:
        return ""
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remover elementos não relevantes
    for element in soup.select('script, style, iframe, .ads, .banner, .advertisement, .cookie-notice'):
        if element:
            element.decompose()
    
 
###-----------------------------Parte que nao existia em Summary--------------------------
    # 1. Substituir o conteúdo de <noscript> pelo texto, só se o noscript ainda estiver dentro da árvore
    for noscript in soup.select('noscript'):
        noscript_text = noscript.get_text(separator='\n', strip=True)
        if noscript.parent is not None:
            try:
                noscript.insert_before(noscript_text)
                noscript.decompose()
            except Exception:
                # Se falhar inserir, tenta só remover a tag
                noscript.extract()
        else:
            # Se não tem parent, ignora (não tenta substituir nem nada)
            pass
###-----------------------------------------------------------------------------------------

    # Para outras páginas, extrair texto visível
    # Remover elementos não desejados
    #for element in soup.select('script, style, meta, link, noscript'):
    for element in soup.select('script, style, meta, link'):			     #Removendo "noscript" funciona p/ Magalu
        element.decompose()
    
    # Extrair texto visível
    cleaned_text = soup.get_text(separator='\n', strip=True)
    
    # Remover linhas em branco extras
    cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)
    
    return cleaned_text.strip()

def is_ollama_vision_model(model_provider):
    """
    Verifica se o modelo é um modelo Ollama com capacidade de visão.
    
    Args:
        model_provider (str): Nome do modelo
        
    Returns:
        bool: True se for um modelo Ollama com capacidade de visão, False caso contrário
    """
    ollama_vision_models = [
        'llama3.2-vision:11b',
        ##'gemma3:latest',
	'qwen2.5vl:7b'
    ]
    return model_provider in ollama_vision_models

def process_image_with_ollama_vision(image_path, prompt, model_provider, api_base=None):
    """
    Processa uma imagem usando um modelo Ollama com capacidade de visão.
    
    Args:
        image_path (str): Caminho para o arquivo de imagem
        prompt (str): Prompt para o modelo
        model_provider (str): Nome do modelo Ollama
        api_base (str): URL base da API do Ollama
        
    Returns:
        str: Resposta do modelo
    """
    try:
        # Definir a URL base padrão se não fornecida
        if api_base is None:
            api_base = "http://localhost:11434"
        
        # Remover o prefixo "http://" ou "https://" para o endpoint
        api_endpoint = api_base.replace("http://", "").replace("https://", "")
        
        # Ler a imagem e codificar em base64
        with open(image_path, "rb") as image_file:
            image_data = base64.b64encode(image_file.read()).decode('utf-8')
        
        # Preparar o payload para a API do Ollama
        payload = {
            "model": model_provider,
            "prompt": prompt,
            "stream": False,
            "images": [image_data]
        }
        
        # Fazer a requisição para a API do Ollama
        response = requests.post(
            f"{api_base}/api/generate",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        # Verificar se a requisição foi bem-sucedida
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "")
        else:
            logger.error(f"Erro na API do Ollama: {response.status_code} - {response.text}")
            return f"Erro na API do Ollama: {response.status_code}"
    
    except Exception as e:
        logger.error(f"Erro ao processar imagem com Ollama Vision: {e}")
        return f"Erro ao processar imagem: {str(e)}"

def extract_fields_with_llm(text, fields, model_provider="openai", api_base=None, image_path=None):
    """
    Extrai campos específicos do texto ou imagem usando um modelo LLM.
    Adiciona um campo 'Resumo' automaticamente se 'Descrição' ou similar for solicitado.
    
    Args:
        text (str): Texto processado da página web ou None se usando imagem
        fields (list): Lista de campos a serem extraídos
        model_provider (str): Provedor do modelo LLM ("openai", "openai-vision" ou "ollama")
        api_base (str): URL base da API do modelo LLM (opcional)
        image_path (str): Caminho para a imagem a ser processada (opcional)
        
    Returns:
        list: Lista de dicionários com os campos extraídos para cada resultado encontrado
    """
    import json
    import re
    
    # Verificar se um campo de descrição foi solicitado
    description_field = None
    fields_lower = [f.lower() for f in fields]
    description_keywords = ['descrição', 'descricao', 'description', 'detalhes', 'details']
    for keyword in description_keywords:
        if keyword in fields_lower:
            # Encontrar o nome original do campo
            original_index = fields_lower.index(keyword)
            description_field = fields[original_index]
            break
    
    # Adicionar campo Resumo se Descrição foi solicitada
    fields_to_extract = list(fields) # Criar cópia para não modificar a original
    add_summary_instruction = False
    if description_field and 'Resumo' not in fields_to_extract:
        fields_to_extract.append('Resumo')
        add_summary_instruction = True
        logger.info("Campo de descrição encontrado. Adicionando campo 'Resumo' à extração.")
    
    # Verificar se estamos usando um modelo de visão com uma imagem
    is_vision_model = model_provider == "openai-vision" or is_ollama_vision_model(model_provider)
    
    # Construir o prompt para o LLM
    prompt_base = f"""
    ###Analise {'esta imagem' if is_vision_model and image_path else 'o texto abaixo'} e extraia TODAS as ocorrências das seguintes informações: 
    Analise {'esta imagem' if is_vision_model and image_path else 'o texto abaixo'} e extraia as 5 PRIMEIRAS ocorrências das seguintes informações:
    {', '.join(fields_to_extract)}
    
    Se houver múltiplos itens ou produtos, extraia as informações para CADA UM DELES.
    
    Responda APENAS com um array JSON válido onde cada elemento é um objeto com as chaves correspondentes aos campos solicitados.
    Exemplo de formato esperado:
    [
      {{
        "{fields_to_extract[0]}": "valor1 para item1",
        "{fields_to_extract[1]}": "valor2 para item1",			##Usado na versao vision_select
        ...
      }},
      {{
        "{fields_to_extract[0]}": "valor1 para item2",
        "{fields_to_extract[1]}": "valor2 para item2",			##Usado na versao vision_select
        ...
      }},
      ...
    ]
    
    Se alguma informação não estiver disponível para um item específico, use "Não disponível" como valor.
    Se não encontrar nenhum item, retorne um array com um único objeto contendo os campos solicitados.
    """
    
    # Adicionar instrução para gerar resumo se necessário
    if add_summary_instruction:
        prompt_base += f"\n\nIMPORTANTE: Retorne TODAS as informações contidas no campo '{description_field}', não trunque ou modifique de forma alguma estas informações."

    if add_summary_instruction:
        prompt_base += f"\n\nIMPORTANTE: Para o campo 'Resumo', gere um resumo conciso do campo '{description_field}' com no máximo 30 palavras."
    
    # Adicionar texto se não for modelo de visão
    if not (is_vision_model and image_path):
        prompt = prompt_base + f"\n\nTexto:\n{text}"
    else:
        prompt = prompt_base
    
    try:
        # Usar OpenAI (GPT-4o Mini ou GPT-4o Vision)
        if model_provider.lower() in ["openai", "openai-vision"]:
            ###import os
            ###from openai import OpenAI
            from openai import Client
            
            # Usar a chave de API da variável de ambiente
            ###client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")
            client = Client(api_key=os.environ.get("OPENAI_API_KEY")
            )
            
            # Preparar as mensagens
            if is_vision_model and image_path:
                # Ler a imagem e codificar em base64
                with open(image_path, "rb") as image_file:
                    image_data = base64.b64encode(image_file.read()).decode('utf-8')
                
                # Criar mensagem com conteúdo de imagem
                messages = [
                    {
                        "role": "system", 
                        "content": "Você é um assistente especializado em extrair informações estruturadas de imagens de páginas web."
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ]
                
                # Chamar a API da OpenAI com o modelo GPT-4o Vision
                response = client.chat.completions.create(
                    model="gpt-4o",  # Modelo com capacidade de visão
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000
                )
            else:
                # Mensagens para modelo de texto
                messages = [
                    {
                        "role": "system", 
                        "content": "Você é um assistente especializado em extrair informações estruturadas de textos."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ]
                
                # Chamar a API da OpenAI com o modelo GPT-4o Mini
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000
                )
            
            # Extrair o conteúdo da resposta
            result = response.choices[0].message.content
        
        # Usar Ollama
        elif model_provider.lower() not in ["openai", "openai-vision"]:
            # Verificar se o modelo Ollama tem capacidade de visão e se temos uma imagem
            if is_vision_model and image_path:
                # Usar a função específica para processar imagens com Ollama Vision
                result = process_image_with_ollama_vision(
                    image_path=image_path,
                    prompt=prompt,
                    model_provider=model_provider,
                    api_base=api_base
                )
            else:
                # Usar Ollama para processamento de texto
                try:
                    # Tentar primeiro com a biblioteca litellm
                    try:
                        from litellm import completion
                        
                        # Definir a URL base padrão se não fornecida
                        if api_base is None:
                            api_base = "http://localhost:11434"
                        
                        # Preparar as mensagens
                        messages = [
                            {
                                "role": "system", 
                                "content": "Você é um assistente especializado em extrair informações estruturadas de textos."
                            },
                            {
                                "role": "user", 
                                "content": prompt
                            }
                        ]
                        
                        # Chamar a API usando litellm
                        response = completion(
                            model="ollama/" + model_provider,
                            messages=messages,
                            api_base=api_base,
                            temperature=0.0,
                            stream=False,
                            max_tokens=2000
                        )
                        
                        # Extrair o conteúdo da resposta
                        result = response.choices[0].message.content
                    
                    except (ImportError, Exception) as e:
                        logger.error(f"Erro ao usar litellm: {e}")
                        # Tentar com a biblioteca ollama diretamente
                        import ollama
                        
                        # Definir o host do Ollama se fornecido
                        if api_base is not None and api_base != "http://localhost:11434":
                            ollama.host = api_base
                        
                        # Preparar as mensagens
                        messages = [
                            {
                                "role": "system", 
                                "content": "Você é um assistente especializado em extrair informações estruturadas de textos."
                            },
                            {
                                "role": "user", 
                                "content": prompt
                            }
                        ]
                        
                        # Chamar a API do Ollama diretamente
                        response = ollama.chat(
                            model=model_provider,
                            messages=messages,

    			    # Mova 'temperature' para dentro do dicionário 'options'
                            options={
                            "temperature": 0.0,
                            "num_predict":2000
                            }
                            ##temperature=0.0,
                            ##num_predict=2000
                        )
                        
                        # Extrair o conteúdo da resposta
                        result = response['message']['content']
                
                except Exception as e:
                    logger.error(f"Erro ao usar Ollama: {e}")
                    return [{field: f"Erro na API Ollama: {str(e)}" for field in fields_to_extract}]
        
        else:
            return [{field: f"Provedor de modelo não suportado: {model_provider}" for field in fields_to_extract}]
        
        # Tentar extrair o JSON da resposta
        try:
            # Procurar por padrões de array JSON na resposta
            json_match = re.search(r'(\[.*\])', result, re.DOTALL)
            if json_match:
                result = json_match.group(1)
            
            # Tentar carregar como JSON
            extracted_data_list = json.loads(result)
            
            # Verificar se o resultado é uma lista
            if not isinstance(extracted_data_list, list):
                logger.warning("O resultado não é uma lista, convertendo para lista com um único item")
                extracted_data_list = [extracted_data_list]
            
            # Verificar se todos os campos solicitados estão presentes em cada item
            for item in extracted_data_list:
                for field in fields_to_extract:
                    if field not in item:
                        item[field] = "Não disponível"
            
            return extracted_data_list
        
        except json.JSONDecodeError:
            logger.error(f"Erro ao decodificar JSON da resposta do LLM: {result}")
            # Criar uma lista com um único dicionário com valores padrão
            return [{field: "Erro na extração" for field in fields_to_extract}]
    
    except Exception as e:
        logger.error(f"Erro ao chamar a API do LLM: {e}")
        return [{field: "Erro na API" for field in fields_to_extract}]

def generate_csv(data, output_file):
    """
    Gera um arquivo CSV com os dados extraídos.
    
    Args:
        data (list): Lista de dicionários com os dados extraídos
        output_file (str): Caminho para o arquivo CSV de saída
        
    Returns:
        bool: True se o CSV foi gerado com sucesso, False caso contrário
    """
    try:
        # Converter para DataFrame
        df = pd.DataFrame(data)
        
        # Salvar como CSV utf-8 para Português
        df.to_csv(output_file, index=False, encoding="utf-8-sig")
        
        return True
    
    except Exception as e:
        logger.error(f"Erro ao gerar CSV: {e}")
        return False

def generate_json(data, output_file):
    """
    Gera um arquivo JSON com os dados extraídos.
    
    Args:
        data (list): Lista de dicionários com os dados extraídos
        output_file (str): Caminho para o arquivo JSON de saída
        
    Returns:
        bool: True se o JSON foi gerado com sucesso, False caso contrário
    """
    try:
        # Salvar como JSON com formatação e codificação UTF-8 para Português
        with open(output_file, 'w', encoding='utf-8-sig') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return True
    
    except Exception as e:
        logger.error(f"Erro ao gerar JSON: {e}")
        return False

def create_mock_html():
    """
    Cria um HTML de exemplo para testes.
    
    Returns:
        str: Conteúdo HTML de exemplo
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Página de Exemplo - Livro</title>
    </head>
    <body>
        <header>
            <nav>Menu de Navegação</nav>
            <div class="ads">Anúncio de Cabeçalho</div>
        </header>
        
        <main>
            <h1>Dom Casmurro</h1>
            
            <div class="product-info">
                <div class="author">
                    <h2>Autor</h2>
                    <p>ASSIS, MACHADO DE</p>
                </div>
                
                <div class="details">
                    <h2>Detalhes do Produto</h2>
                    <ul>
                        <li><strong>Número de Páginas:</strong> 400</li>
                        <li><strong>Editora:</strong> PENGUIN COMPANHIA</li>
                        <li><strong>ISBN:</strong> 9788582850350</li>
                        <li><strong>Ano de Publicação:</strong> 2019</li>
                    </ul>
                </div>
                
                <div class="price">
                    <h2>Preço</h2>
                    <p class="current-price">R$ 69,69</p>
                    <p class="old-price">R$ 79,90</p>
                </div>
            </div>
            
            <div class="description">
                <h2>Descrição</h2>
                <p>
                    Publicado em 1899, Dom Casmurro é um dos romances mais conhecidos de Machado de Assis.
                    A obra narra a história de Bentinho, que, após se tornar advogado, casa-se com Capitu,
                    sua namorada de infância. O ciúme excessivo do protagonista o leva a suspeitar de uma
                    traição entre sua esposa e seu melhor amigo, Escobar.
                </p>
            </div>
        </main>
        
        <aside>
            <div class="ads">Anúncio Lateral</div>
            <div class="related-products">
                <h3>Produtos Relacionados</h3>
                <ul>
                    <li>Memórias Póstumas de Brás Cubas</li>
                    <li>Quincas Borba</li>
                    <li>O Alienista</li>
                </ul>
            </div>
        </aside>
        
        <footer>
            <div class="copyright">© 2025 Livraria Exemplo</div>
            <div class="ads">Anúncio de Rodapé</div>
        </footer>
    </body>
    </html>
    """

def process_url(url, fields, model_provider, api_base=None, use_mock=False, image_path=None):
    """
    Processa uma URL ou imagem e extrai campos específicos.
    
    Args:
        url (str): URL da página web (opcional)
        fields (list): Lista de campos a serem extraídos
        model_provider (str): Provedor do modelo LLM
        api_base (str): URL base da API do modelo LLM (opcional)
        use_mock (bool): Se True, usa dados de exemplo em vez de acessar a URL
        image_path (str): Caminho para a imagem a ser processada (opcional)
        
    Returns:
        tuple: (dados_extraídos, texto_processado, contagem_resultados)
    """
    # Verificar se temos URL ou imagem
    if not url and not image_path and not use_mock:
        logger.error("Nem URL nem imagem fornecida para processamento")
        return [{"Erro": "URL ou imagem não fornecida"}], "URL ou imagem não fornecida", 0
    
    # Processar URL ou usar dados de exemplo
    if url or use_mock:
        # Obter conteúdo HTML
        if use_mock:
            logger.info("Usando dados de exemplo para teste")
            html_content = create_mock_html()
        else:
            logger.info(f"Acessando URL: {url}")
            html_content = scrape_webpage_with_selenium(url)
            
            if not html_content:
                logger.error("Falha ao obter conteúdo HTML da página")
                return [{"Erro": "Falha ao obter conteúdo HTML da página"}], "Falha ao obter conteúdo HTML da página", 0
        
        # Limpar e processar o texto
        logger.info("Limpando e processando o texto")
        text = clean_text(html_content)
    else:
        # Se estamos usando apenas imagem, não temos texto para processar
        text = None
    
    # Extrair campos com LLM
    logger.info(f"Extraindo campos com modelo LLM: {model_provider}")
    extracted_data = extract_fields_with_llm(text, fields, model_provider, api_base, image_path)
    
    # Verificar se a extração foi bem-sucedida
    if not extracted_data:
        logger.error("Falha ao extrair dados com o modelo LLM")
        return [{"Erro": "Falha ao extrair dados com o modelo LLM"}], text, 0
    
    # Contar resultados
    result_count = len(extracted_data) if isinstance(extracted_data, list) else 1
    
    return extracted_data, text, result_count

def process_task(task_id, url=None, fields=None, model_provider="openai", api_base=None, use_mock=False, image_path=None):
    """
    Processa uma tarefa de extração de informações.
    
    Args:
        task_id (str): ID da tarefa
        url (str): URL da página web a ser processada (opcional)
        fields (list): Lista de campos a serem extraídos
        model_provider (str): Provedor do modelo LLM
        api_base (str): URL base da API do modelo LLM (opcional)
        use_mock (bool): Se True, usa dados de exemplo em vez de acessar a URL
        image_path (str): Caminho para a imagem a ser processada (opcional)
    """
    try:
        # Atualizar status da tarefa
        tasks[task_id]['status'] = 'processing'
        
        # Processar URL ou imagem
        extracted_data, text, result_count = process_url(url, fields, model_provider, api_base, use_mock, image_path)
        
        # Salvar texto processado
        text_file = os.path.join(RESULTS_FOLDER, f"{task_id}_text.txt")
        with open(text_file, 'w', encoding='utf-8-sig') as f:
            f.write(text if text else "Processamento baseado em imagem, sem texto disponível.")
        
        # Gerar CSV
        csv_file = os.path.join(RESULTS_FOLDER, f"{task_id}_data.csv")
        generate_csv(extracted_data, csv_file)
        
        # Gerar JSON
        json_file = os.path.join(RESULTS_FOLDER, f"{task_id}_data.json")
        generate_json(extracted_data, json_file)
        
        # Atualizar status da tarefa
        tasks[task_id]['status'] = 'completed'
        tasks[task_id]['extracted_data'] = extracted_data
        tasks[task_id]['text_file'] = text_file
        tasks[task_id]['csv_file'] = csv_file
        tasks[task_id]['json_file'] = json_file
        tasks[task_id]['result_count'] = result_count
        
        logger.info(f"Tarefa {task_id} concluída com sucesso. {result_count} resultados encontrados.")
    
    except Exception as e:
        logger.error(f"Erro ao processar tarefa {task_id}: {e}")
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['message'] = str(e)

@app.route('/')
def index():
    # Usar o HTML atualizado que informa sobre o resumo
    return render_template('index.html') # Assume que index.html será substituído pelo atualizado

@app.route('/api/test-llm', methods=['GET'])
def test_llm():
    try:
        model_provider = request.args.get('model_provider', "openai")
        api_base = request.args.get('api_base', "http://localhost:11434")
        
        # Verificar se o modelo é um modelo de visão do Ollama
        if is_ollama_vision_model(model_provider):
            # Testar a conexão com o Ollama para modelos de visão
            # Criar uma pequena imagem de teste
            import numpy as np
            from PIL import Image
            
            # Criar uma imagem em branco
            image = Image.new('RGB', (100, 100), color=(255, 255, 255))
            image_path = os.path.join(UPLOAD_FOLDER, "test_image.jpg")
            image.save(image_path)
            
            # Testar o processamento de imagem
            result = process_image_with_ollama_vision(
                image_path=image_path,
                prompt="Descreva esta imagem brevemente.",
                model_provider=model_provider,
                api_base=api_base
            )
            
            if "Erro" in result:
                return jsonify({'status': 'error', 'message': result}), 500
            
            return jsonify({'status': 'success', 'message': 'Conexão com modelo de visão Ollama estabelecida com sucesso'})
            
        # Verificar se o modelo é um modelo Ollama normal
        elif model_provider not in ["openai", "openai-vision"]:
            try:
                # Tentar primeiro com a biblioteca litellm
                try:
                    from litellm import completion
                    
                    # Testar a conexão com o Ollama
                    response = completion(
                        model="ollama/" + model_provider,
                        messages=[{"role": "user", "content": "Olá, você está funcionando?"}],
                        api_base=api_base,
                        ###temperature=0.0,
                        stream=False,
                        max_tokens=10
                    )
                    
                    return jsonify({'status': 'success', 'message': 'Conexão com Ollama estabelecida com sucesso'})
                
                except (ImportError, Exception) as e:
                    logger.error(f"Erro ao usar litellm: {e}")
                    # Tentar com a biblioteca ollama diretamente
                    import ollama
                    
                    # Definir o host do Ollama se fornecido
                    if api_base is not None and api_base != "http://localhost:11434":
                        ollama.host = api_base
                    
                    # Testar a conexão com o Ollama
                    response = ollama.chat(
                        model=model_provider,
                        messages=[{"role": "user", "content": "Olá, você está funcionando?"}],
                        ###temperature=0.0
                    )
                    
                    return jsonify({'status': 'success', 'message': 'Conexão com Ollama estabelecida com sucesso'})
            
            except Exception as e:
                logger.error(f"Erro ao testar conexão com Ollama: {e}")
                return jsonify({'status': 'error', 'message': f'Erro ao conectar com Ollama: {str(e)}'}), 500
        
        # Verificar se o modelo é um modelo OpenAI
        elif model_provider in ["openai", "openai-vision"]:
            try:
                # Verificar se a chave de API está definida
                ###import os
                api_key = os.environ.get("OPENAI_API_KEY")
                if not api_key:
                    return jsonify({'status': 'error', 'message': 'Chave de API da OpenAI não encontrada. Defina a variável de ambiente OPENAI_API_KEY.'}), 500
                
                # Testar a conexão com a OpenAI
                from openai import Client
                client = Client(api_key=api_key)
                
                # Usar o modelo apropriado
                model = "gpt-4o" if model_provider == "openai-vision" else "gpt-4o-mini"
                
                # Testar a conexão
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Olá, você está funcionando?"}],
                    ###temperature=0.0,
                    max_tokens=10
                )
                
                return jsonify({'status': 'success', 'message': 'Conexão com OpenAI estabelecida com sucesso'})
            
            except Exception as e:
                logger.error(f"Erro ao testar conexão com OpenAI: {e}")
                return jsonify({'status': 'error', 'message': f'Erro ao conectar com OpenAI: {str(e)}'}), 500
        
        else:
            return jsonify({'status': 'error', 'message': f'Provedor de modelo não suportado: {model_provider}'}), 400
    
    except Exception as e:
        logger.error(f"Erro ao testar conexão com LLM: {e}")
        return jsonify({'status': 'error', 'message': f'Erro ao conectar com LLM: {str(e)}'}), 500

@app.route('/api/scrape', methods=['POST'])
def scrape():
    try:
        # Obter parâmetros do formulário
        url = request.form.get('url', '')
        fields_str = request.form.get('fields', '')
        model_provider = request.form.get('model_provider', 'openai')
        api_base = request.form.get('api_base', None)
        use_mock = request.form.get('use_mock', 'false').lower() == 'true'
        
        # Processar campos
        fields = [field.strip() for field in fields_str.split(',') if field.strip()]
        
        if not fields:
            return jsonify({'error': 'Nenhum campo especificado para extração'}), 400
        
        # Verificar se há uma imagem
        image_path = None
        if 'page_image' in request.files:
            file = request.files['page_image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(image_path)
                logger.info(f"Imagem salva em: {image_path}")
        
        # Verificar se temos URL ou imagem
        if not url and not image_path and not use_mock:
            return jsonify({'error': 'Nem URL nem imagem fornecidas para processamento'}), 400
        
        # Criar ID da tarefa
        task_id = str(uuid.uuid4())
        
        # Inicializar tarefa
        tasks[task_id] = {
            'id': task_id,
            'status': 'pending',
            'url': url,
            'image_path': image_path,
            'fields': fields,
            'model_provider': model_provider,
            'api_base': api_base,
            'use_mock': use_mock,
            'created_at': time.time()
        }
        
        # Iniciar processamento em thread separada
        thread = threading.Thread(
            target=process_task,
            args=(task_id, url, fields, model_provider, api_base, use_mock, image_path)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({'task_id': task_id})
    
    except Exception as e:
        logger.error(f"Erro ao iniciar scraping: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<task_id>', methods=['GET'])
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Tarefa não encontrada'}), 404
    
    task = tasks[task_id]
    
    response = {
        'status': task['status'],
        'created_at': task['created_at']
    }
    
    if task['status'] == 'completed':
        response['extracted_data'] = task['extracted_data']
        response['result_count'] = task['result_count']
    
    if task['status'] == 'error' and 'message' in task:
        response['message'] = task['message']
    
    return jsonify(response)

@app.route('/api/download/<task_id>/<file_type>', methods=['GET'])
def download_file(task_id, file_type):
    if task_id not in tasks:
        return jsonify({'error': 'Tarefa não encontrada'}), 404
    
    task = tasks[task_id]
    
    if task['status'] != 'completed':
        return jsonify({'error': 'Tarefa ainda não foi concluída'}), 400
    
    if file_type == 'csv':
        return send_file(task['csv_file'], as_attachment=True, download_name='extracted_data.csv')
    elif file_type == 'json':
        return send_file(task['json_file'], as_attachment=True, download_name='extracted_data.json')
    elif file_type == 'text':
        return send_file(task['text_file'], as_attachment=True, download_name='processed_text.txt')
    else:
        return jsonify({'error': 'Tipo de arquivo inválido'}), 400

if __name__ == '__main__':
    # Criar diretório templates se não existir
    if not os.path.exists('templates'):
        os.makedirs('templates')
    # Criar diretório static se não existir
    if not os.path.exists('static/css'):
        os.makedirs('static/css')
    if not os.path.exists('static/js'):
        os.makedirs('static/js')
        
    # Copiar/Renomear arquivos HTML, CSS, JS para os locais corretos se necessário
    # (Assumindo que os arquivos corretos já estão nos locais esperados ou serão colocados lá)
    # Exemplo: os.rename('/home/ubuntu/updated_index_with_summary_note.html', 'templates/index.html')
    # Exemplo: os.rename('/home/ubuntu/fixed_main.js', 'static/js/main.js')
    # Exemplo: os.rename('/home/ubuntu/updated_style.css', 'static/css/style.css')
    
    # Verificar se o arquivo index.html existe no diretório templates
    if not os.path.exists('templates/index.html'):
        logger.warning("Arquivo templates/index.html não encontrado. A aplicação pode não funcionar corretamente.")
        # Opcional: Copiar o arquivo HTML atualizado para o local correto
        try:
            import shutil
            shutil.copyfile('/home/ubuntu/updated_index_with_summary_note.html', 'templates/index.html')
            logger.info("Arquivo index.html copiado para templates/")
        except Exception as e:
            logger.error(f"Falha ao copiar index.html: {e}")
            
    # Verificar se os arquivos CSS e JS existem
    if not os.path.exists('static/js/main.js'):
         logger.warning("Arquivo static/js/main.js não encontrado.")
         try:
            import shutil
            shutil.copyfile('/home/ubuntu/fixed_main.js', 'static/js/main.js')
            logger.info("Arquivo main.js copiado para static/js/")
         except Exception as e:
            logger.error(f"Falha ao copiar main.js: {e}")
            
    if not os.path.exists('static/css/style.css'):
         logger.warning("Arquivo static/css/style.css não encontrado.")
         try:
            import shutil
            # Assumindo que o style.css correto está em /home/ubuntu/updated_style.css
            shutil.copyfile('/home/ubuntu/updated_style.css', 'static/css/style.css') 
            logger.info("Arquivo style.css copiado para static/css/")
         except Exception as e:
            logger.error(f"Falha ao copiar style.css: {e}")

    app.run(host='0.0.0.0', port=5000, debug=True)
