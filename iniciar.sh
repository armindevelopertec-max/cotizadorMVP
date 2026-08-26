#!/bin/bash
cd "$(dirname "$0")"

TOKEN="${API_TOKEN:-cambiar_este_token_seguro_aqui}"
PORT=8000

echo "========================================="
echo "  BLUETEL - Cotizador Server"
echo "========================================="
echo ""
echo "Token de acceso: ${TOKEN:0:4}****"
echo "Puerto local: $PORT"
echo ""

# Iniciar servidor Python
echo "[1/2] Iniciando servidor local..."
python3 server.py &
SERVER_PID=$!
sleep 1

if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "ERROR: No se pudo iniciar server.py"
    exit 1
fi
echo "  -> Servidor corriendo (PID: $SERVER_PID)"

# Iniciar tunnel Cloudflare
echo "[2/2] Iniciando tunnel Cloudflare..."
./bin/cloudflared tunnel --url http://localhost:$PORT --no-autoupdate 2>&1 &
TUNNEL_PID=$!
sleep 3

echo ""
echo "========================================="
echo "  ACCESO LOCAL:"
echo "  http://localhost:$PORT/cotizador.html"
echo "========================================="
echo ""
echo "  Presiona Ctrl+C para detener todo"
echo "========================================="

# Trap para cerrar todo al salir
cleanup() {
    echo ""
    echo "Deteniendo servicios..."
    kill $SERVER_PID 2>/dev/null
    kill $TUNNEL_PID 2>/dev/null
    echo "Listo."
    exit 0
}
trap cleanup SIGINT SIGTERM

wait
