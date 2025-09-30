Este repositorio contém os arquivos necessários para realização dos testes realizados duranta a Avaliação Experimental do TCC: **Extração e estruturação de informações de páginas HTML usando LLMs**.

### Arquivos:

### updated_app.py:
Arquivo principal responsável por:  
-Geração da Interface Web para extração de informação de páginas HTML.  
-Navegação web (usando Selenium) até a URL definida na Interface.  
-Limpeza do código-fonte da página Web removendo informações não-relevantes (cabeçalhos, rodapés, etc) (usando BeautifulSoup).  
-Chamada do Modelo da OpenAI (**gpt-4o-mini**) para extração das informações (definidas na Interface web) do código-fonte limpo.  
-Apresentação dos resultados em forma de Tabela.  
-Exportação dos Resultados no formato CSV e JSON.  

### style.css, main.js e index.html:
Arquivos auxiliares para formatação da Interface Web.  
A Interface deve ser aberta em um Navegador no seguinte endereço: http://127.0.0.1:5000/

#### index.html 
Responsável pela estrutura da Interface web. Define o conteúdo e a organização hierárquica que será apresentada na página.
#### style.css
Responável pela aparência, design e apresentação da página. Usa a estrutura definida no HTML para tornar a página visualmente atraente.
#### index.html
Adiciona interatividade e lógica funcional à página. Permite que a Interface/página Web responda às ações do usuário e manipule os dados.  

#### Sintaxe de uso:
> python .\updated_app.py

#### TCC_Metricas_Avaliacao_Resumo.ipynb
Responsável pelos cálculos das Metricas ROUGE-1 e BERTScore-F1 para os Resumos gerados pelo modelo  (**gpt-4o-mini**)


#### URLs_Datasets_TCC.txt
Contem todas as URLs utilizadas, de todos os 4 Datasets, para extração de informação e informações adicionais como data da busca (i.e extração) e como foram realizadas as buscas nos sites.
