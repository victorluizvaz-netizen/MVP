# Content OS (MVP) — Whisper + Groq

Um app em **Streamlit** para organizar clientes, transcrever vídeos com **Whisper** e gerar conteúdos com **Groq**.

## Funcionalidades
- Cadastro de clientes + presets (system prompt e templates por tipo)
- Upload de vídeo, biblioteca por cliente, transcrição e histórico
- Gerador manual e gerador a partir de transcrição
- Rotinas (ex.: toda segunda) com execução via botão (MVP)
- Histórico pesquisável

## Rodar local
```bash
pip install -r requirements.txt
export GROQ_API_KEY="SUA_CHAVE"
streamlit run app.py
```

## Streamlit Cloud
- Configure `GROQ_API_KEY` em **Secrets**
- `packages.txt` instala o `ffmpeg`
