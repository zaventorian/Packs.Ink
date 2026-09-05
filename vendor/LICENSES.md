# Third-party notices

Packs.Ink ships these libraries from `/vendor/` (same-origin, so a CDN outage
can never blank the site). Each is used unmodified except for the version
header comment. All are MIT licensed; the license text is reproduced once at
the bottom, and each copyright line below applies to it.

| File | Package | Version | Copyright |
|---|---|---|---|
| `react.production.min.js` | react | 18.3.1 | Copyright (c) Facebook, Inc. and its affiliates (Meta Platforms, Inc.) |
| `react-dom.production.min.js` | react-dom | 18.3.1 | Copyright (c) Facebook, Inc. and its affiliates (Meta Platforms, Inc.); contains Modernizr 3.0.0pre (custom build), MIT |
| `htm.js` | htm | 3.x | Copyright (c) 2018 Jason Miller |
| `supabase.js` | @supabase/supabase-js | 2.108.1 | Copyright (c) 2020 Supabase |
| `html2canvas.min.js` | html2canvas | 1.4.1 | Copyright (c) 2022 Niklas von Hertzen |
| `qrcode.js` | qrcode-generator | 2.0.4 | Copyright (c) 2009 Kazuhiko Arase. "QR Code" is a registered trademark of DENSO WAVE INCORPORATED. |
| `ort/ort.wasm.min.js`, `ort/ort-wasm-simd-threaded.{mjs,wasm}` | onnxruntime-web | 1.20.1 | Copyright (c) Microsoft Corporation |

The card scanner additionally loads `@techstark/opencv-js` 4.10.0 from jsDelivr
inside a worker (Apache-2.0, OpenCV contributors), and the PP-OCRv3 models under
`/scanner/` are from PaddleOCR (Apache-2.0, PaddlePaddle authors).

## MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
