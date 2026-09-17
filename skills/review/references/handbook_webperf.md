# Review Handbook: Web Performance & Core Web Vitals

This handbook provides an adversarial checklist for auditing frontend loading speed, rendering bottlenecks, JavaScript bundle bloat, and runtime responsiveness. Findings map to category `Performance` in the 12-field finding schema.

---

## 1. Core Web Vitals (CWV) Defenses

### Largest Contentful Paint (LCP) — Target < 2.5s
- **Rule**: Prioritize loading and rendering of the largest visible element (hero image, heading text, poster video).
- **Smells**:
  - Hero image loaded via lazy loading (`loading="lazy"` on LCP element hurts LCP).
  - Missing resource hints (`<link rel="preload" as="image" href="...">` for critical hero assets).
  - Client-side render waterfall: CSS ➔ JS bundle ➔ API fetch ➔ Image URL discovery ➔ Image download.
- **Defect Trigger**: Critical hero visual delayed behind multiple serial network hops.

### Cumulative Layout Shift (CLS) — Target < 0.1
- **Rule**: All dynamically injected images, ads, embeds, and dynamic widgets MUST have explicit layout dimensions or aspect-ratio reservations.
- **Smells**:
  - `<img>` or `<video>` tags missing `width` and `height` attributes or CSS `aspect-ratio`.
  - Content injected above existing rendered content without reserving space (e.g. banners, notification toasts).
  - Web fonts causing Flash of Invisible Text (FOIT) without `font-display: swap` or matching fallback font metrics.
- **Defect Trigger**: Page shifts unexpectedly under user cursor during load.

### Interaction to Next Paint (INP) — Target < 200ms
- **Rule**: Event handlers and UI state updates MUST not block the main thread for > 50ms.
- **Smells**:
  - Synchronous heavy JSON parsing, filtering of large arrays, or crypto operations in `onClick` or `onChange`.
  - Layout thrashing: alternating DOM writes and reads (`element.style.height = ...; const h = element.offsetHeight; element.style.height = ...;`).
  - Missing debouncing/throttling on rapid events (`scroll`, `resize`, `input`).
- **Defect Trigger**: Input delay / UI freeze noticeable to the user when clicking or typing.

---

## 2. JavaScript Bundle Size & Asset Budgets

### Dead Weight & Tree-Shaking Failures
- **Rule**: Avoid monolithic imports when lightweight modular alternatives exist.
- **Smells**:
  - `import _ from 'lodash'` instead of `import debounce from 'lodash/debounce'` or native ES.
  - `import moment from 'moment'` instead of `Intl.DateTimeFormat` or `date-fns`.
  - Importing entire icon libraries (`import { Icon } from 'lucide-react'` in non-tree-shaken bundlers).

### Code Splitting & Dynamic Imports
- **Rule**: Heavy routes, modals, and non-critical admin/analytics scripts MUST be loaded lazily via `React.lazy()` or dynamic `import()`.

---

## 3. Network & Caching Policies

### Critical Rendering Path
- **Rule**: Scripts in `<head>` MUST be marked `defer` or `async` unless explicitly intended to block rendering.
- **Cache-Control**: Static hashed assets (`main.[hash].js`) MUST have immutable long-lived caching (`Cache-Control: public, max-age=31536000, immutable`).

---

## 4. Finding Schema Mapping

When filing web performance findings:
- **Category**: `Performance`.
- **Severity**:
  - `HIGH`: Main thread blocking > 500ms on interactive controls; critical rendering path blocked by megabyte bundle; missing image dimensions on hero causing severe layout shift (CLS > 0.25).
  - `MEDIUM`: Uncompressed assets, missing lazy loading on below-the-fold images, monolithic utility library imports.
  - `LOW`: Minor font loading optimization, missing preconnect hints.
