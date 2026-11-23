// Pixel-art upscaler for the zoomed game screen.
//
// Zooming only magnifies the game's own pixels, so icons turn into blocks.
// This redraws the magnified screen with the xBR method (after Hyllian's
// "xBR level 2"): it looks at each game pixel's neighbours, finds edges, and
// draws them as smooth lines at the screen's real resolution, while flat areas
// and colours stay crisp.  It can't add detail the pictures don't have; it
// makes the existing detail look like it was drawn larger.
//
// It runs on the graphics chip (WebGL 2) in a canvas laid over the game.  The
// game's own canvas stays where it was (invisible), so touches and the zoom
// code are unchanged.
//
//   const up = Upscaler.create(gameCanvas)   // null if WebGL 2 is missing
//   up.show(scale, tx, ty)   // where the game canvas is (CSS px), and draw
//   up.hide()
//   up.update(imageData, x, y)   // part of the game screen changed
'use strict';

(() => {
const VS = `#version 300 es
in vec2 pos;
void main() { gl_Position = vec4(pos, 0.0, 1.0); }`;

const FS = `#version 300 es
precision highp float;
precision highp int;
uniform sampler2D src;
uniform ivec2 srcSize;     // game screen, in game pixels
uniform vec3 place;        // game canvas corner (CSS px) and CSS px per game pixel
uniform vec2 view;         // drawing buffer height (device px), device px per CSS px
out vec4 outColor;

vec3 px(ivec2 p) { return texelFetch(src, clamp(p, ivec2(0), srcSize - 1), 0).rgb; }
// Colour difference, weighted by how bright each channel looks (0..48).
float df(vec3 a, vec3 b) { return 48.0 * dot(abs(a - b), vec3(0.299, 0.587, 0.114)); }
bool eq(vec3 a, vec3 b) { return df(a, b) < 15.0; }
bool ne(vec3 a, vec3 b) { return df(a, b) > 0.01; }
// How much of this spot lies past the line v = c (w = one screen pixel, for anti-aliasing).
float cov(float v, float c, float w) { return clamp((v - c) / w + 0.5, 0.0, 1.0); }

// One corner of game pixel c.  sg mirrors the neighbourhood so that every
// corner can use the bottom-right rules; f is the spot inside the pixel,
// mirrored the same way.  Returns the colour to blend in and how much.
//      B
//    D E F F4      E is the pixel itself; the corner is towards I.
//    G H I I4
//      H5 I5     (C is above F)
vec4 corner(ivec2 c, ivec2 sg, vec2 f, float w) {
  #define P(x, y) px(c + ivec2(x, y) * sg)
  vec3 E = P(0, 0), B = P(0, -1), C = P(1, -1), D = P(-1, 0), F = P(1, 0);
  vec3 G = P(-1, 1), H = P(0, 1), I = P(1, 1);
  vec3 F4 = P(2, 0), I4 = P(2, 1), H5 = P(0, 2), I5 = P(1, 2);
  if (!ne(E, F) || !ne(E, H)) return vec4(0.0);
  // Is there an edge running from H to F (cutting off this corner)?
  float wd1 = df(E, C) + df(E, G) + df(I, H5) + df(I, F4) + 4.0 * df(H, F);
  float wd2 = df(H, D) + df(H, I5) + df(F, I4) + df(F, B) + 4.0 * df(E, I);
  bool ok = (!eq(F, B) && !eq(F, C)) || (!eq(H, D) && !eq(H, G))
         || (eq(E, I) && ((!eq(F, F4) && !eq(F, I4)) || (!eq(H, H5) && !eq(H, I5))))
         || eq(E, G) || eq(E, C);
  if (!(wd1 < wd2 && ok)) return vec4(0.0);
  float a = cov(f.x + f.y, 1.5, w * 1.414);                              // 45 degrees
  if (2.0 * df(F, G) <= df(H, C) && ne(E, G) && ne(D, G))
    a = max(a, cov(f.y + 0.5 * f.x, 1.0, w * 1.118));                    // shallow
  if (2.0 * df(H, C) <= df(F, G) && ne(E, C) && ne(B, C))
    a = max(a, cov(f.x + 0.5 * f.y, 1.0, w * 1.118));                    // steep
  return vec4(df(E, F) <= df(E, H) ? F : H, a);
}

void main() {
  vec2 css = vec2(gl_FragCoord.x, view.x - gl_FragCoord.y) / view.y;
  vec2 g = (css - place.xy) / place.z;                 // in game pixels
  if (g.x < 0.0 || g.y < 0.0 || g.x >= float(srcSize.x) || g.y >= float(srcSize.y)) {
    outColor = vec4(0.0, 0.0, 0.0, 1.0);
    return;
  }
  ivec2 c = ivec2(floor(g));
  vec2 f = fract(g);
  float w = 1.0 / (place.z * view.y);                  // one screen pixel, in game pixels
  vec3 col = px(c);
  for (int k = 0; k < 4; k++) {
    ivec2 sg = ivec2((k & 1) == 0 ? 1 : -1, (k & 2) == 0 ? 1 : -1);
    vec2 fm = vec2(sg.x > 0 ? f.x : 1.0 - f.x, sg.y > 0 ? f.y : 1.0 - f.y);
    vec4 r = corner(c, sg, fm, w);
    col = mix(col, r.rgb, r.a);
  }
  outColor = vec4(col, 1.0);
}`;

function create(game) {
  const cv = document.createElement('canvas');
  cv.id = 'hq';
  const gl = cv.getContext('webgl2', { alpha: false, antialias: false, preserveDrawingBuffer: false });
  if (!gl) return null;

  function shader(type, text) {
    const s = gl.createShader(type);
    gl.shaderSource(s, text);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  const prog = gl.createProgram();
  try {
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  } catch (err) {
    console.warn('upscaler unavailable:', err);
    return null;
  }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'pos');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = (n) => gl.getUniformLocation(prog, n);
  const uSize = U('srcSize'), uPlace = U('place'), uView = U('view');
  gl.uniform1i(U('src'), 0);

  const tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
  let texW = 0, texH = 0;

  let shown = false, lost = false, queued = false, stale = true;
  const at = { s: 1, tx: 0, ty: 0 };
  cv.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost = true; api.hide(); });

  function full() {             // copy the whole game screen
    texW = game.width; texH = game.height;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, game);
    stale = false;
  }
  function draw() {
    queued = false;
    if (!shown || lost) return;
    if (stale || texW !== game.width || texH !== game.height) full();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(window.innerWidth * dpr), h = Math.round(window.innerHeight * dpr);
    if (cv.width !== w || cv.height !== h) {
      cv.width = w; cv.height = h;
      cv.style.width = window.innerWidth + 'px'; cv.style.height = window.innerHeight + 'px';
    }
    gl.viewport(0, 0, w, h);
    gl.uniform2i(uSize, texW, texH);
    gl.uniform3f(uPlace, at.tx, at.ty, at.s);
    gl.uniform2f(uView, h, h / window.innerHeight);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
  function later() { if (!queued) { queued = true; requestAnimationFrame(draw); } }

  const api = {
    canvas: cv,
    get shown() { return shown; },
    get usable() { return !lost; },
    show(s, tx, ty) {
      if (lost) return false;
      Object.assign(at, { s, tx, ty });
      if (!shown) { shown = true; stale = true; cv.style.display = 'block'; }
      later();
      return true;
    },
    hide() {
      if (!shown) return;
      shown = false;
      cv.style.display = 'none';
    },
    update(img, x, y) {
      if (!shown) { stale = true; return; }
      if (stale || texW !== game.width || texH !== game.height) { stale = true; return later(); }
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texSubImage2D(gl.TEXTURE_2D, 0, x, y, img.width, img.height, gl.RGBA, gl.UNSIGNED_BYTE, img);
      later();
    },
  };
  cv.style.display = 'none';
  return api;
}

window.Upscaler = { create };
})();
