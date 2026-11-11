"""Inicia sempre em loopback para evitar exposição da sessão Telegram."""
import uvicorn

if __name__ == '__main__':
    uvicorn.run('telecourse.server:app', host='127.0.0.1', port=8000, reload=False)
