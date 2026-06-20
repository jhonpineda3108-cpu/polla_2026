# La Quiniela Mundial Hub

App de quiniela para el Mundial 2026: tabla de posiciones, grupos, pronósticos,
podio/premios y fase eliminatoria interactiva.

## Estructura

```
quiniela-mundial-hub/
├── backend/              <- API en Python (FastAPI). Va en Render.
│   ├── main.py
│   ├── requirements.txt
│   └── apuestas_extraidas.xlsx   <- tu Excel real (agrégalo tú)
└── frontend/              <- página web normal (HTML/CSS/JS). Va en GitHub Pages.
    └── index.html
```

## 1. Backend (Render)

1. Sube este repo completo a GitHub.
2. En [render.com](https://render.com) → **New** → **Web Service** → conecta el repo.
3. **Root Directory**: `backend`
4. **Build Command**: `pip install -r requirements.txt`
5. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Variables de entorno (Settings → Environment):
   - `ADMIN_PASSWORD` → tu contraseña de admin
   - `HF_TOKEN` (opcional, para respaldo automático) → token de Hugging Face con permiso de escritura
   - `HF_REPO_ID` (opcional) → ej. `tu-usuario/quiniela-datos` (debe ser un Dataset en HF)
   - `HF_REPO_TYPE` (opcional) → `dataset`
7. Sube tu `apuestas_extraidas.xlsx` real a la carpeta `backend/` antes de hacer commit, o
   súbelo después directo desde la pestaña **Shell** de Render.
8. Al terminar el deploy, copia la URL que te da Render (algo como `https://quiniela-api.onrender.com`).

## 2. Frontend (GitHub Pages)

1. Abre `frontend/index.html` y cambia esta línea con la URL real de tu backend:
   ```js
   const API_BASE = window.API_BASE || "https://quiniela-api.onrender.com";
   ```
2. En GitHub: **Settings** del repo → **Pages** → Source: rama `main`, carpeta `/frontend`.
3. GitHub te da una URL pública, algo como `https://tu-usuario.github.io/quiniela-mundial-hub/`.

## Notas

- El plan gratis de Render "duerme" el backend tras ~15 min sin uso; la primera
  petición después de dormir tarda unos segundos en despertar. Es normal.
- El bracket de la fase eliminatoria se inicializa desde el panel de Admin
  (pestaña Bracket) o llamando directo a `POST /api/admin/bracket/inicializar`.
- La contraseña de admin por defecto es `polla2026` si no configuras
  `ADMIN_PASSWORD` — cámbiala antes de hacerlo público.
