"""
bot.py — совместимость. Основная логика теперь в app.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

# Импортируем app.py — он запускает бота в фоне и создаёт Flask
from app import app, WEB_HOST, WEB_PORT

if __name__ == "__main__":
    print(f"🌐 Starting on {WEB_HOST}:{WEB_PORT}")
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, use_reloader=False, threaded=True)
