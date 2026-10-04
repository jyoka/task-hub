// The ship view's script, loaded by the page src/picture.ts shipHtml() writes (the CSP lets in nothing else).
// It paints the picture the extension posts (src/picture.ts ShipState), shows `#id title` for the figure under the
// pointer, and tells the extension how wide the view is and when the hide button is pressed.
// Plain browser JavaScript: the build does not touch media/.
(() => {
  const vscode = acquireVsCodeApi()
  const PX = 5 // CSS pixels to one pixel of the picture
  const $ = id => document.getElementById(id)
  const main = $('main'), stage = $('stage'), canvas = $('ship'), tip = $('tip')
  const aboard = $('aboard'), badges = $('badges'), toggle = $('toggle')
  let spots = []
  let listed = ''

  const hex = v => `#${v.toString(16).padStart(6, '0')}`
  const span = (text, cls, title) => {
    const el = document.createElement('span')
    el.textContent = text
    if (cls) el.className = cls
    if (title) el.title = title
    return el
  }

  const paint = p => {
    const scale = window.devicePixelRatio || 1
    canvas.width = p.columns * PX * scale
    canvas.height = p.rows * PX * scale
    canvas.style.width = `${p.columns * PX}px`
    canvas.style.height = `${p.rows * PX}px`
    const g = canvas.getContext('2d')
    g.setTransform(scale, 0, 0, scale, 0, 0)
    g.clearRect(0, 0, p.columns * PX, p.rows * PX)
    for (let y = 0; y < p.rows; y++) for (let x = 0; x < p.columns; x++) {
      const v = p.px[y * p.columns + x]
      if (v < 0) continue
      g.fillStyle = hex(v)
      g.fillRect(x * PX, y * PX, PX, PX)
    }
    // a glyph fills one terminal cell: a column wide, two pixels tall
    g.font = `bold ${PX * 2}px monospace`
    g.textAlign = 'center'
    g.textBaseline = 'middle'
    for (const t of p.glyphs) {
      const top = Math.floor(t.y / 2) * 2 * PX
      if (t.bg >= 0) {
        g.fillStyle = hex(t.bg)
        g.fillRect(t.x * PX, top, PX, PX * 2)
      }
      g.fillStyle = hex(t.fg)
      g.fillText(t.ch, (t.x + 0.5) * PX, top + PX)
    }
    spots = p.spots
  }

  // Who is aboard and the badges change only with the board: rebuilt then, not every frame (a hovered title stays).
  const list = s => {
    const key = JSON.stringify([s.aboard, s.empty, s.badges, s.total])
    if (key === listed) return
    listed = key
    aboard.replaceChildren(...(s.empty ? [span('船は空です', 'dim')] : []), ...s.aboard.map(a => {
      const group = span('', '')
      group.append(span(a.label, 'dim'), ...a.figures.map(f => span(` #${f.id}`, a.kind, f.tip)))
      if (a.after) group.append(span(` ${a.after}`, 'dim'))
      return group
    }))
    badges.replaceChildren(...(s.badges.length > 0 ? [span(`実績 ${s.badges.length}/${s.total}`, 'dim')] : []),
      ...s.badges.map(b => span(`★${b.name}`, 'badge', b.desc)))
  }

  window.addEventListener('message', e => {
    const s = e.data
    toggle.textContent = s.hidden ? '船を出す' : '船を隠す'
    stage.hidden = !s.picture
    if (s.picture) paint(s.picture)
    else {
      spots = []
      tip.hidden = true
    }
    list(s)
  })

  canvas.addEventListener('mousemove', e => {
    const x = e.offsetX / PX
    const y = e.offsetY / PX
    const spot = spots.find(p => x >= p.x && x < p.x + p.w && y >= p.y && y < p.y + p.h)
    if (!spot) {
      tip.hidden = true
      return
    }
    tip.textContent = spot.tip
    tip.hidden = false
    tip.style.left = `${Math.max(0, Math.min(e.offsetX + 8, stage.clientWidth - tip.offsetWidth))}px`
    tip.style.top = `${e.offsetY + 12}px`
  })
  canvas.addEventListener('mouseleave', () => { tip.hidden = true })
  toggle.addEventListener('click', () => vscode.postMessage({ type: 'toggle' }))

  // The width in the picture's pixels: told when the page loads (also after the view was hidden) and on a resize.
  let told = 0
  const size = () => {
    const columns = Math.floor(main.clientWidth / PX)
    if (columns > 0 && columns !== told) {
      told = columns
      vscode.postMessage({ type: 'size', columns })
    }
  }
  new ResizeObserver(size).observe(main)
  size()
})()
