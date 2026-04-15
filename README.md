# Neo-Label

Aplicação web para anotação de dados (rotulagem) voltada a datasets de Machine Learning. Permite criar projetos, fazer upload de dados, anotar com atalhos de teclado e exportar o resultado.

## Funcionalidades

- **Autenticação** por usuário/senha (JWT). Usuário padrão criado na primeira execução: `neuromate` / `123456`.
- **Projetos de anotação** com tipos:
  - **Pose detection** — 17 keypoints no padrão COCO, avatar de bebê interativo como guia, suporte a upload de vídeos e extração de frames via FFmpeg.
  - **Image segmentation** (em desenvolvimento).
- **Upload de vídeo** com escolha de FPS (de 1 frame/min até 30 frames/s) para extração automática de frames.
- **Interface de anotação** com:
  - Clique no mouse ou modo 100% teclado (setas + Enter/Space).
  - Atalhos: `Tab`/`N` próximo keypoint, `1`-`9` pular, `O` oculto, `U` desfazer, `[` / `]` item anterior/próximo.
  - Desfazer (histórico de 50 passos) e limpar ponto/tudo.
  - Salvamento automático a cada ação.
- **Exportação** em JSON, JSONL e CSV.

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, armazenamento em JSON no filesystem (sem banco de dados), JWT + bcrypt, FFmpeg para vídeos.
- **Frontend:** React 18 + TypeScript, Vite, TailwindCSS, TanStack Query, Zustand, React Router, React Hook Form.

## Pré-requisitos

- Python 3.12
- Node.js 18+
- FFmpeg (para extração de frames de vídeo)

## Instalação e execução

```bash
cp .env.example .env
```

### Opção 1 — script interativo

```bash
python run.py
```

Menu com opções para iniciar/parar/reiniciar backend e frontend, ver status, logs, e abrir a UI.

### Opção 2 — manual

```bash
# Backend
cd backend
uvicorn app.main:app --reload

# Frontend (em outro terminal)
cd frontend
npm install
npm run dev
```

### Opção 3 — Docker

```bash
docker compose up
```

- API: <http://localhost:8000/docs>
- UI: <http://localhost:5173>

## Dados

Todos os dados ficam em `./data/` (configurável via `DATA_DIR` no `.env`). Cada projeto vira uma subpasta contendo configuração, items, anotações, vídeos enviados e frames extraídos. Não há banco de dados — é seguro fazer backup apenas copiando essa pasta.

## Variáveis de ambiente

Veja `.env.example`. Principais:

- `DATA_DIR` — onde salvar os dados (default `./data`).
- `SECRET_KEY` — chave JWT (troque em produção).
- `FRONTEND_URL` — origem permitida pelo CORS.
- `BACKEND_PORT`, `VITE_API_URL` — portas/URLs de dev.
