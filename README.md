# Prompt — Aplicativo de Anotação de Dados (Neo-Label)

## Objetivo
Construir uma aplicação web para anotação de dados (rotulagem) voltada a datasets de Machine Learning. O sistema deve permitir que usuários façam upload de dados, criem projetos de anotação, definam esquemas de rótulos e exportem os dados anotados.

## Stack Técnica

### Backend
- **Linguagem:** Python 3.11+
- **Framework:** FastAPI
- **ORM:** SQLAlchemy 2.0 (async)
- **Banco de Dados:** PostgreSQL
- **Migrações:** Alembic
- **Autenticação:** JWT (OAuth2 password flow)
- **Validação:** Pydantic v2
- **Gerenciador de dependências:** `uv` ou `poetry`
- **Testes:** pytest + httpx

### Frontend
- **Linguagem:** TypeScript
- **Framework:** React 18+ (com Vite)
- **Roteamento:** React Router
- **Estado/Dados:** TanStack Query (React Query) + Zustand
- **UI:** TailwindCSS + shadcn/ui
- **Formulários:** React Hook Form + Zod
- **HTTP Client:** Axios ou fetch nativo
- **Testes:** Vitest + React Testing Library

## Funcionalidades Essenciais

1. **Autenticação e Usuários**
   - Registro, login, logout
   - Perfis: admin, anotador, revisor

2. **Projetos de Anotação**
   - Criar/editar/excluir projetos
   - Tipos suportados: classificação de texto, classificação de imagem, NER, bounding boxes
   - Definição de esquema de rótulos (labels) por projeto

3. **Upload e Gerenciamento de Dados**
   - Upload em lote (CSV, JSON, ZIP de imagens)
   - Visualização paginada dos itens
   - Atribuição de itens a anotadores

4. **Interface de Anotação**
   - Tela dedicada por tipo de tarefa
   - Atalhos de teclado
   - Navegação item-a-item (anterior/próximo)
   - Salvamento automático

5. **Revisão e Qualidade**
   - Fluxo de revisão por um segundo anotador
   - Métricas: progresso do projeto, concordância inter-anotadores (Cohen's kappa)

6. **Exportação**
   - Formatos: JSON, CSV, COCO (para imagens), JSONL

## Estrutura de Diretórios Sugerida

```
proj-neo-label/
├── backend/
│   ├── app/
│   │   ├── api/            # routers FastAPI
│   │   ├── core/           # config, security
│   │   ├── models/         # SQLAlchemy
│   │   ├── schemas/        # Pydantic
│   │   ├── services/       # lógica de negócio
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── hooks/
│   │   ├── api/
│   │   ├── stores/
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml
└── README.md
```

## Requisitos Não-Funcionais
- Documentação OpenAPI automática (via FastAPI)
- CORS configurado para o frontend
- Docker Compose para dev (backend + db + frontend)
- Logs estruturados
- Variáveis de ambiente via `.env`

## Entregáveis
1. Código-fonte do backend e frontend
2. `docker-compose.yml` funcional
3. README com instruções de setup
4. Migrações iniciais do banco
5. Ao menos um fluxo ponta-a-ponta funcionando (criar projeto → upload → anotar → exportar)
