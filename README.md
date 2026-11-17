# Score de equilibrio · plataformas de fuerza (ForceDecks)

App web (HTML + API en Python) para Vercel. Sube el ZIP/CSV exportados de ForceDecks y, opcionalmente, el Word de Tinetti;
devuelve un **score de equilibrio 0–100** por paciente, su desglose y la comparación con Tinetti.

## Despliegue en Vercel
```bash
npm i -g vercel
cd balance-app

vercel --prod   # producción
```
o sube la carpeta a GitHub e impórtala en vercel.com (detecta Flask por `app.py`).

Desarrollo local: `pip install -r requirements.txt && python app.py` → http://localhost:3000  ·  Tests: `pip install pytest && pytest tests`

## Estructura
```
public/index.html     Interfaz (lee ZIP en el navegador, comprime cada CSV con gzip y lo envía a la API)
app.py                Flask (entrypoint de Vercel): sirve la interfaz y /api/*
balance/io.py         Lectura de CSV ForceDecks (coma decimal, 1000 Hz) y clasificación por nombre de archivo
balance/metrics.py    Métricas por prueba (COP, un pie, sentarse-pararse, giro)
balance/scoring.py    Conversión a subscores 0–100, pesos, niveles y alertas
balance/reference.json  Anclas y pesos del score  ← lo que se edita para recalibrar
balance/tinetti.py    Lee el Word: la opción RESALTADA de cada ítem es la puntuación
```
Límite de Vercel: 4,5 MB por petición. Por eso el navegador envía **un archivo por petición, comprimido** (el CSV más grande, 4,2 MB, queda en ~1 MB) y el ZIP de 45 MB se abre en el navegador, nunca se sube entero.

## Qué se mide
**Score principal (0–100)**, solo con pruebas que también evalúa el Tinetti:
| Dominio (peso) | Prueba | Métricas |
|---|---|---|
| Bipodal ojos abiertos (35) | Quiet Stand | velocidad COP, área elipse 95 % |
| Bipodal ojos cerrados (30) | Quiet Stand Close Eyes | ídem (+ cociente de Romberg como alerta) |
| Sentarse–pararse (35) | Sit to Stand to Sit | tiempo por repetición, variabilidad |

**Apartado aparte (no entra al score):**
* **Giro de 360°** (`_giro.csv`): duración y nº de pasos → score propio 0–100, comparado con los ítems «vuelta» del Tinetti.
* **Empuje**: se hizo sin plataformas; se registra a mano (0/1/2) en la app, precargado desde el Word.

**No se usa:** apoyo en un pie (no se evaluó en Tinetti) ni salto (CMJ). Esos CSV se ignoran.

Cada métrica → 0–100 por interpolación lineal entre un valor «bueno» y uno «malo» (`reference.json`). El score es el promedio ponderado de los dominios
disponibles (se renormaliza si falta alguna prueba; se informa la cobertura). Niveles: ≥ 80 Bueno · 60–79 Intermedio · < 60 Reducido.
La comparación con Tinetti usa el **Tinetti comparable** (máx. 12): sentado, levantarse, intentos, bipedestación inmediata y mantenida, ojos cerrados y sentarse.

Detalles técnicos: señal remuestreada a 100 Hz, COP filtrado a 10 Hz; COP bipodal = promedio ponderado por fuerza de ambas plataformas
(separación entre centros configurable, 400 mm por defecto); el peso corporal sale del Quiet Stand (o del peso registrado en `athletes.csv`);


## Limitaciones (importante)
* **Las anclas son provisionales**, no normas validadas: salen de rangos típicos en adultos mayores y del rango de la cohorte piloto (n = 11). El score sirve para comparar y seguir la evolución de pacientes, no como diagnóstico ni predicción de caídas.
* En la cohorte piloto **hubo muy poca concordancia con Tinetti** (Spearman ≈ 0,16 con el Tinetti comparable). Con n = 11 y Tinetti con efecto techo (6 de 11 pacientes con 12/12) no valida ni invalida el score. Para validarlo hacen falta más pacientes, incluyendo casos con bajo desempeño, y un desenlace clínico (caídas, otra escala).
* El Word de Tinetti es una plantilla donde la opción puntuada se marca con resaltado. Si un ítem no está resaltado se trata como «no registrado» (✱ parcial), no como 0.
* La duración del giro es la del archivo grabado; si incluye tiempo antes/después del giro se sobreestima.
* La app no guarda datos: cada archivo se procesa en memoria y se descarta.
