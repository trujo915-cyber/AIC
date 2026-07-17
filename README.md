# Calificador de laboratorios — Ing. Química EPN

App para calificar coloquios (fotos) e informes (PDF) con ayuda de IA
(Gemini), revisando siempre antes de escribir la nota en el Excel.

## Estructura del proyecto

```
carla_app/
├── app.py                          # la aplicación (interfaz)
├── requirements.txt                # dependencias
├── .streamlit/
│   └── secrets.toml.example        # plantilla de claves (copiar y renombrar)
└── core/                           # la lógica, en módulos independientes
    ├── excel_parser.py             # lee el Excel por patrón, no por celda fija
    ├── excel_writer.py             # escribe notas sin arriesgar datos existentes
    ├── prompt_builder.py           # arma la instrucción para la IA
    ├── ai_client.py                # llama a Gemini
    ├── name_matcher.py             # verifica nombres contra el roster
    ├── grading_engine.py           # orquesta todo el lote
    └── profile_manager.py          # guarda/carga rúbricas + ejemplos
```

## Antes de desplegar: consigue tu API key de Gemini (gratis)

1. Entra a **https://aistudio.google.com/apikey**
2. Inicia sesión con tu cuenta de Google.
3. Clic en "Create API key" (o "Crear clave de API").
4. Copia la clave — la necesitarás en el paso 4 de abajo. Guárdala en un
   lugar seguro (no la compartas ni la pegues en ningún chat).

## Desplegar en Streamlit Community Cloud (gratis)

No necesitas saber programar para estos pasos, solo ir siguiéndolos.

### 1. Crear cuenta en GitHub (si no tienes)

Entra a **github.com** → "Sign up" → crea tu cuenta gratuita.

### 2. Crear un repositorio nuevo

1. Arriba a la derecha, clic en el **+** → "New repository".
2. Nómbralo, por ejemplo `calificador-labo`.
3. Márcalo como **Private** (privado).
4. Clic en "Create repository".

### 3. Subir los archivos del proyecto (sin usar comandos)

1. En tu repo recién creado, clic en **"uploading an existing file"**
   (o el botón "Add file" → "Upload files").
2. Arrastra TODOS los archivos y carpetas de este proyecto que te compartí
   (mantén la carpeta `core/` como carpeta — arrástrala completa).
3. **NO subas** ningún archivo `secrets.toml` real (solo existe el
   `.example`, que sí puedes subir).
4. Clic en "Commit changes".

### 4. Crear cuenta en Streamlit Community Cloud

1. Entra a **share.streamlit.io**
2. Clic en "Sign up" o "Continue with GitHub" y conecta tu cuenta de GitHub.
3. Si tu repositorio es privado, Streamlit te pedirá un permiso adicional
   para poder leerlo — acéptalo (son datos de tu cuenta de GitHub, no del
   contenido de tus calificaciones).

### 5. Desplegar la app

1. Clic en "New app" (o "Create app").
2. Elige tu repositorio (`calificador-labo`), branch `main`, y como
   archivo principal: `app.py`.
3. Antes de darle a "Deploy", abre **"Advanced settings"** → sección
   **Secrets** → pega esto (reemplazando con tus valores reales):

   ```toml
   GEMINI_API_KEY = "tu_api_key_real_copiada_en_el_paso_anterior"
   APP_PASSWORD = "una_contraseña_que_tú_elijas"
   ```

4. Clic en "Deploy". Espera 2-5 minutos mientras se instala todo.

### 6. Listo

Te va a dar una dirección web fija, algo como
`https://calificador-labo-xxxxx.streamlit.app`. Guárdala — es la misma
dirección que abrirás desde el celular (en el navegador, como cualquier
página web) y desde la laptop. No necesitas instalar nada en ninguno de
los dos: ambos entran al mismo lugar en el servidor.

Si algún día cambias el código y lo vuelves a subir a GitHub, la app se
actualiza sola en un par de minutos.

## Uso básico dentro de la app

1. Sube el Excel del paralelo → confirma qué prácticas y estudiantes detectó.
2. Elige qué práctica vas a calificar, y si es coloquio o informe.
3. Pega la rúbrica y sube 1+ ejemplo(s) ya calificados por ti (o carga un
   perfil guardado de una vez anterior).
4. Sube las fotos/PDFs nuevos a calificar.
5. Revisa la tabla: todo lo marcado en rojo/con alerta necesita que lo mires
   tú; lo demás puedes aprobarlo tal cual.
6. Descarga el Excel actualizado y súbelo a tu carpeta de OneDrive.

## Notas importantes

- **Nunca subas** archivos reales de estudiantes (Excel, fotos, PDFs) ni tu
  archivo real `secrets.toml` al repositorio de GitHub — el `.gitignore`
  ya está configurado para evitarlo por accidente, pero revisa igual antes
  de cada "Commit".
- Los "perfiles" (rúbrica + ejemplos) que descargues desde la barra lateral
  contienen fotos/PDFs de trabajos de estudiantes — trátalos como
  información privada (mismo cuidado que ya tienes con tus Excel).
- Si Gemini cambia sus condiciones de free tier más adelante, el único
  archivo que tocaría ajustar es `core/ai_client.py` (la línea `MODEL`).
