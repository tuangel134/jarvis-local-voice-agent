# Jarvis Web UI — Fase Web-2

Esta fase vuelve la UI parte real del runtime:

- corre en segundo plano como `jarvis-web.service`
- arranca junto con `jarvis.service`
- `jarvis-web` ya no secuestra la terminal
- la web muestra logs vivos de `journalctl --user -u jarvis`
- el orbe reacciona al micrófono local
- el backend infiere estados `idle/listening/thinking/speaking` desde los logs
- la UI queda lista para un puente más fino de amplitud real de TTS

## URL
- http://127.0.0.1:7070

## Servicio
```bash
systemctl --user status jarvis-web --no-pager -n 50
```

## Abrir la UI
```bash
jarvis-web
```

## Logs rápidos
```bash
curl http://127.0.0.1:7070/api/logs
```
