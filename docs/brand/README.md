# Still Working identity

The continuous-check mark combines an open circle with a check travelling through its opening. It represents a quiet, ongoing watch and the reassurance of a completed check-in.

- `mark.svg`: forest-green symbol on a transparent background.
- `wordmark.svg`: horizontal logo on a transparent background, for light surfaces.
- `app-icon.svg`: ivory symbol on a rounded forest-green tile.

The page embeds the same symbol and a self-contained SVG favicon. These master assets are not required for the page to render.

## Palette

| Colour | Hex | Purpose |
| --- | --- | --- |
| Forest | `#255A43` | Brand, quiet status, primary symbol |
| Ivory | `#F7F8F2` | Main canvas |
| Ink | `#243D33` | Body and wordmark |
| Sage | `#BDCF91` | Small accents |
| Pale green | `#E8EFDF` | Supporting surfaces |
| Terracotta | `#A05232` | An issue that needs attention |

Georgia gives the main status a warm editorial character. The system sans-serif keeps practical information familiar and fast to read. No font downloads or external services are needed. Keep at least one quarter of the symbol's width clear around it; use the symbol without the wordmark below 120 pixels wide.

## Page implementation

`tools/page.css` is embedded into `docs/index.html` by `tools/render_page.py` on every scheduled render. The design includes automatic dark mode, a reduced-motion alternative, mobile layouts, keyboard focus states, and a native evidence disclosure that works without JavaScript.

The page shows the existing recorded state. Decorative motion is not a live connectivity indicator. Supplier dates continue to mean last published change, not last successful health check. The alert state uses terracotta, an exclamation symbol, the existing note, and a supplier-specific attention label.
