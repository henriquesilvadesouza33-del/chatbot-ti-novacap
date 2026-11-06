# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
from openai import OpenAI
import sqlite3
import os
import io
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
CORS(app)

DB_NAME = "suporte_novacap.db"
API_KEY = os.getenv("SENAI_API_KEY")
BASE_URL = os.getenv("BASE_URL")

if API_KEY: API_KEY = API_KEY.strip("'").strip(""")
if BASE_URL: BASE_URL = BASE_URL.strip("'").strip(""")
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

def inicializar_banco():
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS chamados (id INTEGER PRIMARY KEY AUTOINCREMENT, ip_usuario TEXT, historico TEXT, status TEXT DEFAULT 'Em atendimento pela IA', data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit(); conn.close()

PROMPT_SISTEMA = "Você é o assistente oficial de pré-suporte de TI da Novacap. Responda de forma gentil, curta e técnica. Diretrizes: 1. Ajude em problemas simples. 2. Se grave, responda estritamente apenas a palavra: TRANSFERIR_AGORA"
PASTA_APP = os.path.dirname(os.path.abspath(__file__))
ARQUIVOS_PUBLICOS = {"index.html", "icone-ti.ico", "painel.html"}

@app.route('/')
def pagina_chat(): return send_from_directory(PASTA_APP, "index.html")
@app.route('/painel')
def pagina_painel(): return send_from_directory(PASTA_APP, "painel.html")
@app.route('/<nome_arquivo>')
def arquivo_publico(nome_arquivo):
    if nome_arquivo not in ARQUIVOS_PUBLICOS: abort(404)
    return send_from_directory(PASTA_APP, nome_arquivo)

@app.route('/api/chat', methods=['POST'])
def chat_endpoint():
    dados = request.json or {}; msg = dados.get("mensagem", ""); ip = dados.get("ip", "127.0.0.1")
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("SELECT id, historico, status FROM chamados WHERE ip_usuario = ? AND status != 'Encerrado' ORDER BY id DESC LIMIT 1", (ip,))
    res = cursor.fetchone()
    if res:
        ch_id, historico_atual, status_atual = res[0], res[1], res[2]
        historico_atual = f"{historico_atual}\nUsuário: {msg}"
    else:
        historico_atual = f"Usuário: {msg}"; status_atual = "Em atendimento pela IA"
        cursor.execute("INSERT INTO chamados (ip_usuario, historico, status) VALUES (?, ?, ?)", (ip, historico_atual, status_atual))
        conn.commit(); ch_id = cursor.lastrowid
    if status_atual in ("Transferido para Técnico", "Em espera", "Em Atendimento Humano"):
        cursor.execute("UPDATE chamados SET historico = ? WHERE id = ?", (historico_atual, ch_id))
        conn.commit(); conn.close()
        return jsonify({"resposta": "Aguardando suporte técnico humano...", "transferir": True})
    try:
        resposta_ia = client.chat.completions.create(model='openai/gpt-oss-20b', messages=[{"role": "system", "content": PROMPT_SISTEMA}, {"role": "user", "content": historico_atual}])
        texto_ia = resposta_ia.choices[0].message.content.strip(); gatilho = False
        if "TRANSFERIR_AGORA" in texto_ia:
            texto_ia = "Encaminhando para a triagem técnica corporativa."; status_atual = "Transferido para Técnico"; gatilho = True
        historico_atual += f"\nIA: {texto_ia}"
        cursor.execute("UPDATE chamados SET historico = ?, status = ? WHERE id = ?", (historico_atual, status_atual, ch_id))
        conn.commit()
        return jsonify({"resposta": texto_ia, "transferir": gatilho})
    except Exception as e: return jsonify({"resposta": f"Erro: {str(e)}"}), 500
    finally: conn.close()

@app.route('/api/tecnico/chamados', methods=['GET'])
def obter_chamados():
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("SELECT id, ip_usuario, historico, status, data_hora FROM chamados ORDER BY id DESC")
    linhas = cursor.fetchall(); conn.close()
    return jsonify([{"id": l[0], "ip": l[1], "historico": l[2], "status": l[3], "data": l[4]} for l in linhas])

@app.route('/api/tecnico/chamados/<int:chamado_id>/responder', methods=['POST'])
def tecnico_responder(chamado_id):
    dados = request.json or {}; msg = dados.get("mensagem", "").strip()
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("SELECT historico FROM chamados WHERE id = ?", (chamado_id,))
    linha = cursor.fetchone()
    if not linha: conn.close(); return jsonify({"erro": "Não encontrado"}), 404
    novo_h = f"{linha[0]}\n🛠️ Técnico: {msg}"
    cursor.execute("UPDATE chamados SET historico = ?, status = 'Em Atendimento Humano' WHERE id = ?", (novo_h, chamado_id))
    conn.commit(); conn.close()
    return jsonify({"status": "sucesso"})

@app.route('/api/tecnico/chamados/<int:chamado_id>/status', methods=['POST'])
def mudar_status(chamado_id):
    dados = request.json or {}; novo_status = dados.get("status")
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("UPDATE chamados SET status = ? WHERE id = ?", (novo_status, chamado_id))
    conn.commit(); conn.close()
    return jsonify({"status": "sucesso"})

@app.route('/api/tecnico/relatorio/<tipo>', methods=['GET'])
def gerar_relatorio(tipo):
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    if tipo == 'diario': query = "SELECT id, ip_usuario, status, data_hora FROM chamados WHERE date(data_hora) = date('now', 'localtime') ORDER BY id DESC"
    elif tipo == 'mensal': query = "SELECT id, ip_usuario, status, data_hora FROM chamados WHERE strftime('%Y-%m', data_hora) = strftime('%Y-%m', 'now', 'localtime') ORDER BY id DESC"
    elif tipo == 'anual': query = "SELECT id, ip_usuario, status, data_hora FROM chamados WHERE strftime('%Y', data_hora) = strftime('%Y', 'now', 'localtime') ORDER BY id DESC"
    else: conn.close(); return jsonify({"erro": "Inválido"}), 400
    cursor.execute(query); linhas = cursor.fetchall(); conn.close()
    output = io.StringIO(); output.write('\ufeffID;IP;Status;Data_Hora\n')
    for l in linhas: output.write(f"{l[0]};{l[1]};{l[2]};{l[3]}\n")
    return app.response_class(output.getvalue(), mimetype='text/csv', headers={"Content-disposition": f"attachment; filename=relatorio_{tipo}.csv"})

@app.route('/api/chat/atualizar', methods=['POST'])
def cliente_buscar_atualizacoes():
    dados = request.json or {}; ip = dados.get("ip", "127.0.0.1")
    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()
    cursor.execute("SELECT historico, status FROM chamados WHERE ip_usuario = ? AND status != 'Encerrado' ORDER BY id DESC LIMIT 1", (ip,))
    r = cursor.fetchone(); conn.close()
    if r: return jsonify({"historico": r[0], "status": r[1]})
    return jsonify({"status": "Nenhum chamado ativo"})

if __name__ == '__main__':
    inicializar_banco()
    print('🚀 Servidor Novacap Atualizado Completo!')
    app.run(host='0.0.0.0', port=5000, debug=True)