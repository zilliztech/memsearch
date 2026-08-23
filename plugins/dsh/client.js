/**
 * memsearch-dsh — browser half (skill review panel).
 *
 * A non-blocking dock strip above the composer that lists MemSearch skill
 * candidates distilled from memory journals and lets the human review or
 * install them:
 *
 *   - data:   GET  /memsearch-dsh/skill-candidates
 *   - review: POST /memsearch-dsh/skill-review  { sessionId, name, action: 'review' }
 *             queues a user message into the live agent's inbox; the agent
 *             reviews the candidate on the next turn (non-blocking).
 *   - install:POST /memsearch-dsh/skill-review  { sessionId, name, action: 'install' }
 *             runs `memsearch skills install` in the background to the
 *             resolved target (paths config, else ~/.agents/skills).
 *
 * The bundle is a prebuilt client-module artifact: it registers its factory
 * with `window.__ModuleLoader__.load({ id, factory })` (lazy CJS table —
 * nothing runs until the shell materializes the module), and exports the
 * Cordis client plugin shape (`inject` + `apply`). The only external module it
 * requires is `react`, which the web shell provides.
 *
 * @module @zilliz/memsearch-dsh/client
 */
window.__ModuleLoader__.load({
  id: '@zilliz/memsearch-dsh',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' })

    var React = require('react')
    var useState = React.useState
    var useEffect = React.useEffect
    var useCallback = React.useCallback
    var useRef = React.useRef

    var NS = 'memsearch-skill-review'
    var CSS_TAG = 'memsearch-skill-review-css'

    var CSS =
      '.msr-root{' +
        '--msr-bg:var(--dsw-alias-bg-layer-1,#1c1f26);' +
        '--msr-bg-2:var(--dsw-alias-bg-layer-2,#242830);' +
        '--msr-border:var(--dsw-alias-border-l1,rgba(148,163,184,.18));' +
        '--msr-text:var(--dsw-alias-label-primary,#e2e8f0);' +
        '--msr-text-2:var(--dsw-alias-label-secondary,#94a3b8);' +
        '--msr-brand:var(--dsw-alias-brand-primary,#3b82f6);' +
        '--msr-success:var(--dsw-alias-state-success-primary,#22c55e);' +
        '--msr-warn:var(--dsw-alias-state-warn-primary,#f59e0b);' +
        '--msr-error:var(--dsw-alias-state-error-primary,#ef4444);' +
        'font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;' +
      '}' +
      '.msr-bar{display:flex;align-items:center;gap:8px;width:100%;padding:6px 10px;box-sizing:border-box;' +
        'border:1px solid var(--msr-border);border-radius:8px;background:var(--msr-bg);color:var(--msr-text);' +
        'font-size:13px;line-height:1.4;}' +
      '.msr-badge{display:inline-flex;align-items:center;gap:5px;background:color-mix(in srgb,var(--msr-brand) 16%,transparent);' +
        'color:var(--msr-brand);border-radius:999px;padding:2px 9px;font-size:12px;font-weight:600;white-space:nowrap;}' +
      '.msr-count{font-weight:700;color:var(--msr-warn);}' +
      '.msr-spacer{flex:1;}' +
      '.msr-btn{border:1px solid var(--msr-border);background:var(--msr-bg-2);color:var(--msr-text);border-radius:6px;' +
        'padding:3px 10px;font-size:12px;cursor:pointer;font-family:inherit;white-space:nowrap;}' +
      '.msr-btn:hover{border-color:var(--msr-brand);color:var(--msr-brand);}' +
      '.msr-btn.primary{background:var(--msr-brand);border-color:var(--msr-brand);color:#fff;font-weight:600;}' +
      '.msr-btn.primary:hover{filter:brightness(1.1);color:#fff;}' +
      '.msr-btn.danger{color:var(--msr-error);}' +
      '.msr-btn.danger:hover{border-color:var(--msr-error);color:var(--msr-error);}' +
      '.msr-btn.ghost{background:transparent;}' +
      '.msr-btn:disabled{opacity:.55;cursor:default;}' +
      '.msr-panel{margin-top:6px;border:1px solid var(--msr-border);border-radius:10px;background:var(--msr-bg);' +
        'color:var(--msr-text);overflow:hidden;}' +
      '.msr-panel-head{display:flex;align-items:center;gap:8px;padding:8px 12px;font-size:12px;color:var(--msr-text-2);' +
        'border-bottom:1px solid var(--msr-border);}' +
      '.msr-panel-title{font-weight:700;color:var(--msr-text);font-size:13px;}' +
      '.msr-list{padding:4px;}' +
      '.msr-item{display:flex;align-items:flex-start;gap:10px;padding:9px 10px;border-radius:8px;}' +
      '.msr-item:hover{background:var(--msr-bg-2);}' +
      '.msr-item+.msr-item{border-top:1px solid var(--msr-border);}' +
      '.msr-item-main{flex:1;min-width:0;}' +
      '.msr-item-name{font-weight:650;font-size:13px;display:flex;align-items:center;gap:8px;}' +
      '.msr-tag{font-size:10px;font-weight:700;letter-spacing:.04em;padding:1px 7px;border-radius:999px;text-transform:uppercase;}' +
      '.msr-tag.candidate{background:color-mix(in srgb,var(--msr-warn) 18%,transparent);color:var(--msr-warn);}' +
      '.msr-tag.installed{background:color-mix(in srgb,var(--msr-success) 18%,transparent);color:var(--msr-success);}' +
      '.msr-item-desc{font-size:12px;color:var(--msr-text-2);margin-top:3px;}' +
      '.msr-item-meta{font-size:11px;color:var(--msr-text-2);margin-top:3px;opacity:.85;}' +
      '.msr-item-meta code{background:var(--msr-bg-2);border:1px solid var(--msr-border);border-radius:4px;' +
        'padding:0 4px;font-size:10px;}' +
      '.msr-item-actions{display:flex;gap:6px;flex-shrink:0;align-items:center;}' +
      '.msr-note{padding:8px 12px;border-top:1px solid var(--msr-border);font-size:11px;color:var(--msr-text-2);' +
        'display:flex;align-items:center;gap:6px;}' +
      '.msr-toast{margin-top:6px;padding:7px 12px;border-radius:8px;font-size:12px;border:1px solid var(--msr-border);' +
        'background:var(--msr-bg-2);color:var(--msr-text);}' +
      '.msr-toast.ok{border-color:color-mix(in srgb,var(--msr-success) 45%,transparent);color:var(--msr-success);}' +
      '.msr-toast.warn{border-color:color-mix(in srgb,var(--msr-warn) 45%,transparent);color:var(--msr-warn);}' +
      '.msr-toast.err{border-color:color-mix(in srgb,var(--msr-error) 45%,transparent);color:var(--msr-error);}' +
      '.msr-capsule{display:inline-flex;align-items:center;gap:7px;padding:3px 11px;box-sizing:border-box;' +
        'border:1px solid var(--msr-border);border-radius:999px;background:var(--msr-bg);color:var(--msr-text);' +
        'font-size:12px;font-weight:600;cursor:pointer;line-height:1.6;white-space:nowrap;transition:border-color .12s ease;}' +
      '.msr-capsule:hover{border-color:var(--msr-brand);}' +
      '.msr-capsule-dot{display:inline-flex;align-items:center;justify-content:center;min-width:17px;height:17px;' +
        'border-radius:999px;padding:0 4px;font-size:10px;font-weight:700;color:#fff;' +
        'background:var(--msr-warn);}' +
      '.msr-capsule-dot.zero{background:var(--msr-bg-2);color:var(--msr-text-2);border:1px solid var(--msr-border);}' +
      '.msr-capsule-chev{font-size:9px;color:var(--msr-text-2);}' +
      '.msr-link-btn{border:none;background:none;color:var(--msr-brand);font-size:11px;font-weight:600;' +
        'cursor:pointer;padding:2px 6px;border-radius:5px;font-family:inherit;white-space:nowrap;}' +
      '.msr-link-btn:hover{background:color-mix(in srgb,var(--msr-brand) 14%,transparent);}' +
      '.msr-link-btn:disabled{opacity:.5;cursor:default;}' +
      '.msr-fs{margin-top:6px;border:1px solid var(--msr-border);border-radius:10px;background:var(--msr-bg);' +
        'color:var(--msr-text);overflow:hidden;}' +
      '.msr-fs-head{display:flex;align-items:center;gap:8px;padding:7px 12px;font-size:12px;color:var(--msr-text-2);' +
        'border-bottom:1px solid var(--msr-border);cursor:pointer;user-select:none;}' +
      '.msr-fs-head:hover{background:var(--msr-bg-2);}' +
      '.msr-fs-body{display:flex;max-height:320px;overflow:auto;}' +
      '.msr-fs-tree{flex:1;min-width:220px;padding:6px;font-size:12px;border-right:1px solid var(--msr-border);}' +
      '.msr-fs-row{display:flex;align-items:center;gap:6px;padding:3px 8px;border-radius:6px;cursor:pointer;' +
        'white-space:nowrap;color:var(--msr-text);}' +
      '.msr-fs-row:hover{background:var(--msr-bg-2);}' +
      '.msr-fs-row.sel{background:color-mix(in srgb,var(--msr-brand) 18%,transparent);color:var(--msr-brand);}' +
      '.msr-fs-row.muted{color:var(--msr-text-2);opacity:.55;cursor:not-allowed;}' +
      '.msr-fs-row.muted:hover{background:none;color:var(--msr-text-2);}' +
      '.msr-fs-icon{flex:none;font-size:11px;}' +
      '.msr-fs-name{overflow:hidden;text-overflow:ellipsis;}' +
      '.msr-fs-depth{flex:none;width:12px;}' +
      '.msr-preview{flex:1.4;min-width:260px;padding:10px 14px;overflow:auto;font-size:13px;line-height:1.6;}' +
      '.msr-preview.empty{color:var(--msr-text-2);font-size:12px;}' +
      '.msr-md h1{font-size:17px;font-weight:700;margin:10px 0 6px;}' +
      '.msr-md h2{font-size:15px;font-weight:700;margin:10px 0 5px;}' +
      '.msr-md h3{font-size:14px;font-weight:600;margin:8px 0 4px;}' +
      '.msr-md p{margin:6px 0;}' +
      '.msr-md ul,.msr-md ol{margin:6px 0;padding-left:20px;}' +
      '.msr-md li{margin:2px 0;}' +
      '.msr-md code{background:var(--msr-bg-2);border:1px solid var(--msr-border);border-radius:4px;' +
        'padding:0 4px;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}' +
      '.msr-md pre{background:var(--msr-bg-2);border:1px solid var(--msr-border);border-radius:8px;' +
        'padding:10px 12px;overflow:auto;font-size:12px;line-height:1.5;' +
        'font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}' +
      '.msr-md pre code{background:none;border:none;padding:0;}' +
      '.msr-md hr{border:none;border-top:1px solid var(--msr-border);margin:10px 0;}' +
      '.msr-md a{color:var(--msr-brand);text-decoration:none;}' +
      '.msr-md a:hover{text-decoration:underline;}' +
      '.msr-md blockquote{border-left:3px solid var(--msr-border);margin:6px 0;padding:2px 12px;color:var(--msr-text-2);}' +
      '.msr-md table{border-collapse:collapse;margin:8px 0;font-size:12px;}' +
      '.msr-md th,.msr-md td{border:1px solid var(--msr-border);padding:4px 10px;}' +
      '.msr-md th{background:var(--msr-bg-2);font-weight:600;}'

    /** Insert the panel stylesheet once per page. */
    function ensureCss() {
      if (typeof document === 'undefined') return
      if (document.querySelector('style[data-plugin-css="' + CSS_TAG + '"]')) return
      var tag = document.createElement('style')
      tag.dataset.pluginCss = CSS_TAG
      tag.textContent = CSS
      document.head.appendChild(tag)
    }

    /**
     * Minimal read-only Markdown renderer (React elements, no HTML strings —
     * XSS-safe by construction). Supports the subset actually used in
     * .memsearch files: ATX headings, paragraphs, bold/italic/inline code,
     * fenced code blocks, bullet/numbered lists, links, hr, blockquote, tables.
     */
    function renderMarkdown(source) {
      var h = React.createElement
      if (!source) return null
      var lines = source.replace(/\r\n/g, '\n').split('\n')
      var out = []
      var i = 0
      var key = 0

      function inline(text) {
        var nodes = []
        // React escapes text nodes, so keep the source text unchanged here.
        var esc = String(text)
        // inline code
        var parts = esc.split(/`([^`]+)`/g)
        for (var p = 0; p < parts.length; p++) {
          var part = parts[p]
          if (p % 2 === 1) {
            nodes.push(h('code', { key: 'c' + key++ }, part))
            continue
          }
          // bold / italic via regex on the remaining source text
          var boldRe = /\*\*([^*]+)\*\*/g
          var rest = part
          var last = 0
          var m
          var pending = []
          while ((m = boldRe.exec(rest)) !== null) {
            if (m.index > last) pending.push(rest.slice(last, m.index))
            pending.push(h('strong', { key: 'b' + key++ }, m[1]))
            last = m.index + m[0].length
          }
          if (last < rest.length) pending.push(rest.slice(last))
          // then italic within each pending plain text
          for (var q = 0; q < pending.length; q++) {
            var node = pending[q]
            if (typeof node !== 'string') { nodes.push(node); continue }
            var itParts = node.split(/(?<!\*)\*([^*]+)\*(?!\*)/g)
            for (var r = 0; r < itParts.length; r++) {
              if (r % 2 === 1) nodes.push(h('em', { key: 'i' + key++ }, itParts[r]))
              else if (itParts[r]) nodes.push(itParts[r])
            }
          }
        }
        return nodes
      }

      function linkify(text) {
        // Parse links around the other inline styles. Unsafe URL schemes stay
        // as plain text rather than becoming clickable anchors.
        var source = String(text)
        var nodes = []
        var linkRe = /\[([^\]]+)\]\(([^)\s]+)\)/g
        var last = 0
        var m
        while ((m = linkRe.exec(source)) !== null) {
          nodes = nodes.concat(inline(source.slice(last, m.index)))
          var href = m[2]
          var hasScheme = /^[a-z][a-z0-9+.-]*:/i.test(href)
          var safe = /^(https?:|mailto:)/i.test(href) || (!hasScheme && !/^\/\//.test(href))
          if (safe) {
            nodes.push(h('a', { key: 'a' + key++, href: href, target: '_blank', rel: 'noreferrer' }, inline(m[1])))
          } else {
            nodes = nodes.concat(inline(m[0]))
          }
          last = m.index + m[0].length
        }
        nodes = nodes.concat(inline(source.slice(last)))
        return nodes.length === 0 ? null : nodes
      }

      while (i < lines.length) {
        var line = lines[i]
        var trimmed = line.trim()
        var m
        // fenced code block
        if (/^```/.test(trimmed)) {
          var buf = []
          i++
          while (i < lines.length && !/^```/.test(lines[i].trim())) { buf.push(lines[i]); i++ }
          i++ // skip closing fence
          out.push(h('pre', { key: 'pre' + key++ }, h('code', null, buf.join('\n'))))
          continue
        }
        // ATX heading
        if ((m = /^(#{1,6})\s+(.*)$/.exec(trimmed))) {
          var level = m[1].length
          var text = m[2]
          var Tag = 'h' + level
          out.push(h(Tag, { key: 'h' + key++ }, linkify(text)))
          i++
          continue
        }
        // hr
        if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
          out.push(h('hr', { key: 'hr' + key++ }))
          i++
          continue
        }
        // blockquote
        if (/^>\s?/.test(trimmed)) {
          var qbuf = []
          while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
            qbuf.push(lines[i].trim().replace(/^>\s?/, ''))
            i++
          }
          out.push(h('blockquote', { key: 'q' + key++ }, qbuf.join('\n')))
          continue
        }
        // bullet list
        if ((m = /^[-*+]\s+(.*)$/.exec(trimmed))) {
          var litems = []
          while (i < lines.length && (m = /^[-*+]\s+(.*)$/.exec(lines[i].trim()))) {
            litems.push(h('li', { key: 'li' + key++ }, linkify(m[1])))
            i++
          }
          out.push(h('ul', { key: 'ul' + key++ }, litems))
          continue
        }
        // numbered list
        if ((m = /^\d+\.\s+(.*)$/.exec(trimmed))) {
          var oitems = []
          while (i < lines.length && (m = /^\d+\.\s+(.*)$/.exec(lines[i].trim()))) {
            oitems.push(h('li', { key: 'oli' + key++ }, linkify(m[1])))
            i++
          }
          out.push(h('ol', { key: 'ol' + key++ }, oitems))
          continue
        }
        // table (header | --- | rows)
        if (lines[i + 1] && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1]) && trimmed.includes('|')) {
          var headerCells = trimmed.replace(/^\||\|$/g, '').split('|').map(function (s) { return s.trim() })
          i += 2
          var rows = []
          while (i < lines.length && lines[i].includes('|')) {
            var cells = lines[i].replace(/^\||\|$/g, '').split('|').map(function (s) { return s.trim() })
            rows.push(h('tr', { key: 'tr' + key++ }, cells.map(function (c, ci) { return h('td', { key: ci }, linkify(c)) })))
            i++
          }
          out.push(h('table', { key: 'tbl' + key++ },
            h('thead', null, h('tr', null, headerCells.map(function (c, ci) { return h('th', { key: ci }, linkify(c)) }))),
            rows.length ? h('tbody', null, rows) : null))
          continue
        }
        // blank
        if (trimmed === '') { i++; continue }
        // paragraph (accumulate until blank)
        var pbuf = [trimmed]
        i++
        while (i < lines.length && lines[i].trim() !== '' && !/^```/.test(lines[i]) && !/^#{1,6}\s/.test(lines[i]) && !/^[-*+]\s/.test(lines[i]) && !/^\d+\.\s/.test(lines[i])) {
          pbuf.push(lines[i].trim())
          i++
        }
        out.push(h('p', { key: 'p' + key++ }, linkify(pbuf.join(' '))))
      }
      return out
    }

    /**
     * Read-only .memsearch file browser + preview. Two panes: a lazily-loaded
     * directory tree on the left, a rendered markdown/text preview on the
     * right. No write capability anywhere.
     */
    function MemsearchBrowser(props) {
      var sessionId = props.sessionId
      var open = useState(false)
      var setOpen = open[1]
      // listings: rel -> { path, rel, dirs, files } — one cached listing per
      // directory, so expanding one level never destroys a sibling level.
      var listings = useState({})
      var setListings = listings[1]
      var expanded = useState({})
      var setExpanded = expanded[1]
      var sel = useState(null) // { rel, name, ext }
      var setSel = sel[1]
      var preview = useState(null) // { text, err }
      var setPreview = preview[1]
      var loading = useState(false)
      var setLoading = loading[1]

      // File types the read-only preview can render; everything else is shown
      // greyed out and cannot be opened.
      var PREVIEW_EXTS = ['md', 'markdown', 'json', 'txt', 'toml', 'yml', 'yaml', 'sh', 'py', 'js', 'ts']

      var loadDir = useCallback(function (rel) {
        setLoading(true)
        fetch('/memsearch-dsh/list-memsearch?sessionId=' + encodeURIComponent(sessionId) + '&path=' + encodeURIComponent(rel || ''))
          .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, d: d } }) })
          .then(function (r) {
            if (!r.ok) throw new Error(r.d.error || 'list failed')
            setListings(function (prev) {
              var next = {}
              for (var k in prev) next[k] = prev[k]
              next[rel || '/'] = r.d
              return next
            })
          })
          .catch(function (err) {
            setListings(function (prev) {
              var next = {}
              for (var k in prev) next[k] = prev[k]
              next[rel || '/'] = { path: '', rel: rel, dirs: [], files: [], err: String(err.message || err) }
              return next
            })
          })
          .finally(function () { setLoading(false) })
      }, [sessionId])

      // Prime the root listing once.
      useEffect(function () { loadDir('') }, [loadDir])

      var toggleDir = function (rel) {
        var key = rel || '/'
        setExpanded(function (prev) {
          var next = {}
          for (var k in prev) next[k] = prev[k]
          next[key] = !next[key]
          return next
        })
        if (!listings[0][key]) loadDir(rel)
      }

      // Monotonic request id: a slow response for an older click must never
      // overwrite the preview of a newer click (race guard).
      var reqSeq = useRef(0)
      var openFile = function (rel, name, ext) {
        var seq = ++reqSeq.current
        setSel({ rel: rel, name: name, ext: ext })
        if (PREVIEW_EXTS.indexOf(ext) < 0) {
          if (seq === reqSeq.current) setPreview({ err: 'File type .' + ext + ' is not supported for preview (read-only .md/.json/.txt/.toml and similar text).' })
          return
        }
        setPreview({ text: null })
        fetch('/memsearch-dsh/read-file?sessionId=' + encodeURIComponent(sessionId) + '&path=' + encodeURIComponent(rel))
          .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, d: d } }) })
          .then(function (r) {
            if (seq !== reqSeq.current) return // stale response — a newer click won
            if (!r.ok) throw new Error(r.d.error || 'read failed')
            setPreview({ text: r.d.content, ext: r.d.ext })
          })
          .catch(function (err) {
            if (seq !== reqSeq.current) return
            setPreview({ text: null, err: String(err.message || err) })
          })
      }

      var h = React.createElement

      // Recursive tree renderer — a plain function, NOT a component. Defining a
      // component inside render would give it a new identity on every render,
      // making React unmount/remount the whole tree (lost expansion, lost
      // clicks). A plain recursive call returns elements directly.
      var renderDir = function (rel, name, depth) {
        var key = rel || '/'
        var isOpen = !!expanded[0][key]
        var listing = listings[0][key]
        var children = null
        if (isOpen && listing) {
          var dirChildren = (listing.dirs || []).map(function (d) {
            var childRel = rel ? rel + '/' + d : d
            return renderDir(childRel, d, depth + 1)
          })
          var fileChildren = (listing.files || []).map(function (f) {
            var fRel = rel ? rel + '/' + f : f
            var dot = f.lastIndexOf('.')
            var ext = dot >= 0 ? f.slice(dot + 1).toLowerCase() : ''
            var previewable = PREVIEW_EXTS.indexOf(ext) >= 0
            var isSel = sel[0] && sel[0].rel === fRel
            return h('div', {
              key: fRel,
              className: 'msr-fs-row' + (isSel ? ' sel' : '') + (previewable ? '' : ' muted'),
              style: { paddingLeft: 8 + (depth + 1) * 14 },
              onClick: function () { openFile(fRel, f, ext) },
            },
              h('span', { className: 'msr-fs-icon' }, previewable ? '📄' : '🚫'),
              h('span', { className: 'msr-fs-name' }, f))
          })
          children = h('div', { key: 'kids' }, dirChildren.concat(fileChildren))
        }
        return h('div', { key: key },
          h('div', { className: 'msr-fs-row', style: { paddingLeft: 8 + depth * 14 }, onClick: function () { toggleDir(rel) } },
            h('span', { className: 'msr-fs-icon' }, isOpen && listing ? '▾' : '▸'),
            h('span', { className: 'msr-fs-icon' }, '📁'),
            h('span', { className: 'msr-fs-name' }, name)),
          children)
      }

      var previewPane
      if (preview[0] && preview[0].err) {
        previewPane = h('div', { className: 'msr-preview empty' }, '⚠ ' + preview[0].err)
      } else if (preview[0] && preview[0].text !== null) {
        var ext = preview[0].ext
        var isMd = ext === 'md' || ext === 'markdown'
        previewPane = h('div', { className: 'msr-md msr-preview' },
          isMd ? renderMarkdown(preview[0].text) : h('pre', { className: 'msr-md' }, preview[0].text))
      } else {
        previewPane = h('div', { className: 'msr-preview empty' }, 'Select a file to preview its contents (read-only).')
      }

      var rootListing = listings[0]['/']
      return h('div', { className: 'msr-fs' },
        h('div', { className: 'msr-fs-head', onClick: function () { setOpen(!open[0]) } },
          h('span', null, open[0] ? '▾' : '▸'),
          h('span', null, '📁'),
          h('span', { className: 'msr-panel-title' }, '.memsearch/'),
          h('span', { className: 'msr-spacer' }),
          h('span', null, loading[0] ? 'Loading…' : (rootListing ? rootListing.path : ''))),
        open[0]
          ? h('div', { className: 'msr-fs-body' },
              h('div', { className: 'msr-fs-tree' },
                h('div', { key: 'root' }, renderDir('', '.memsearch/', 0))),
              previewPane)
          : null)
    }

    /** The dock strip: candidate count + expandable review list. */
    function SkillReviewPanel(props) {
      var sessionId = props.sessionId
      var candidates = useState(null) // null = loading
      var setCandidates = candidates[1]
      var collapsed = useState(true)
      var setCollapsed = collapsed[1]
      var open = useState(false)
      var setOpen = open[1]
      var dismissed = useState({})
      var setDismissed = dismissed[1]
      var toast = useState(null)
      var setToast = toast[1]
      var busy = useState(null)
      var setBusy = busy[1]

      var load = useCallback(function () {
        fetch('/memsearch-dsh/skill-candidates?sessionId=' + encodeURIComponent(sessionId))
          .then(function (res) { return res.json() })
          .then(function (data) {
            setCandidates(Array.isArray(data.candidates) ? data.candidates : [])
          })
          .catch(function () { setCandidates([]) })
      }, [sessionId])

      useEffect(function () { load() }, [load])

      useEffect(function () {
        if (toast[0] === null) return
        var t = setTimeout(function () { setToast(null) }, 4000)
        return function () { clearTimeout(t) }
      }, [toast[0]])

      var act = function (name, action) {
        setBusy(name)
        fetch('/memsearch-dsh/skill-review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId: sessionId, name: name, action: action }),
        })
          .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data } }) })
          .then(function (r) {
            if (!r.ok || !r.data.ok) throw new Error(r.data.error || 'request failed')
            if (action === 'review') {
              setToast({ kind: 'ok', text: 'Review queued for ' + name + ' — the agent will pick it up on the next turn.' })
            } else {
              setToast({ kind: 'ok', text: 'Installing ' + name + ' to ' + r.data.target + ' in the background.' })
              setTimeout(load, 2500)
            }
          })
          .catch(function (err) {
            setToast({ kind: 'err', text: String(err && err.message ? err.message : err) })
          })
          .finally(function () { setBusy(null) })
      }

      var openDir = function (scope) {
        setBusy('__dir__')
        fetch('/memsearch-dsh/open-memsearch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId: sessionId, scope: scope }),
        })
          .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data } }) })
          .then(function (r) {
            if (!r.ok) throw new Error(r.data.error || 'could not open directory')
            setToast({ kind: 'ok', text: 'Opening ' + r.data.path + ' in your file manager…' })
          })
          .catch(function (err) {
            setToast({ kind: 'err', text: String(err && err.message ? err.message : err) + ' — open the folder manually to browse it.' })
          })
          .finally(function () { setBusy(null) })
      }

      var h = React.createElement
      var visible = (candidates[0] || []).filter(function (c) { return !dismissed[0][c.name] })
      var pending = visible.filter(function (c) { return c.status === 'candidate' })
      var installed = visible.length - pending.length
      var loading = candidates[0] === null

      var expand = function () {
        setCollapsed(false)
        setOpen(true)
      }

      var capsule = h(
        'button', { className: 'msr-capsule', onClick: expand, title: 'MemSearch skill candidates — click to review' },
        h('span', { className: 'msr-badge', style: { background: 'transparent', padding: 0 } }, '🧠 MemSearch'),
        h('span', { className: 'msr-capsule-dot ' + (pending.length > 0 ? '' : 'zero') }, String(pending.length)),
        h('span', { className: 'msr-capsule-chev' }, '▾')
      )

      var bar = h(
        'div', { className: 'msr-bar' },
        h('span', { className: 'msr-badge' }, 'MemSearch'),
        loading
          ? h('span', null, 'Loading skill candidates…')
          : h('span', null,
              h('span', { className: 'msr-count' }, String(pending.length)),
              ' skill candidate' + (pending.length === 1 ? '' : 's') + ' awaiting review',
              h('span', { style: { color: 'var(--msr-text-2)', fontSize: 12 } },
                ' (installed ' + installed + ' · total ' + visible.length + ')')),
        h('span', { className: 'msr-spacer' }),
        h('button', { className: 'msr-btn', onClick: function () { setOpen(!open[0]) } },
          open[0] ? 'Collapse' : 'Review'),
        h('button', { className: 'msr-btn ghost', onClick: function () { setDismissed({}); load() } }, 'Refresh'),
        h('button', { className: 'msr-btn ghost', onClick: function () { setCollapsed(true) } }, 'Hide')
      )

      var items = visible.map(function (c) {
        return h(
          'div', { className: 'msr-item', key: c.name },
          h('div', { className: 'msr-item-main' },
            h('div', { className: 'msr-item-name' },
              c.name,
              h('span', { className: 'msr-tag ' + c.status }, c.status)),
            h('div', { className: 'msr-item-desc' }, c.description),
            h('div', { className: 'msr-item-meta' },
              c.sources.length > 0
                ? h('span', null,
                    'from ',
                    c.sources.slice(0, 3).map(function (s, i) { return h('code', { key: i }, s) }),
                    c.sources.length > 3 ? h('span', null, ' +' + (c.sources.length - 3)) : null)
                : null,
              ' · seen ' + c.occurrences + (c.occurrences === 1 ? ' time' : ' times'),
              c.installedPaths.length > 0 ? ' · installed to ' + c.installedPaths[0] : null),
            c.reason ? h('div', { className: 'msr-item-meta', style: { opacity: 0.9 } }, c.reason) : null
          ),
          h('div', { className: 'msr-item-actions' },
            c.status === 'candidate'
              ? h('button', {
                  className: 'msr-btn primary',
                  disabled: busy[0] === c.name,
                  onClick: function () { act(c.name, 'review') },
                }, 'Review')
              : null,
            c.status === 'candidate'
              ? h('button', {
                  className: 'msr-btn',
                  disabled: busy[0] === c.name,
                  onClick: function () { act(c.name, 'install') },
                }, 'Install')
              : null,
            h('button', {
              className: 'msr-btn ghost danger',
              onClick: function () {
                setDismissed(function (d) {
                  var next = {}
                  for (var k in d) next[k] = d[k]
                  next[c.name] = true
                  return next
                })
              },
            }, 'Dismiss')
          )
        )
      })

      var panel = open[0]
        ? h(
            'div', { className: 'msr-panel' },
            h('div', { className: 'msr-panel-head' },
              h('span', { className: 'msr-panel-title' }, 'Skill candidates'),
              h('span', { className: 'msr-spacer' }),
              h('span', { style: { color: 'var(--msr-text-2)' } }, 'Review opens in the conversation · Install runs in the background')),
            visible.length === 0
              ? h('div', { className: 'msr-item', style: { color: 'var(--msr-text-2)' } },
                  loading ? 'Loading…' : 'No skill candidates.')
              : h('div', { className: 'msr-list' }, items),
            h(MemsearchBrowser, { sessionId: sessionId }),
            h('div', { className: 'msr-note' },
              'Installation is a manual step (memsearch skills install) and is never automatic. Target directory follows plugins.dsh.memory_to_skill.paths, defaulting to ~/.agents/skills.')
          )
        : null

      return h(
        'div', { className: 'msr-root' },
        collapsed[0] ? capsule : bar,
        !collapsed[0] ? panel : null,
        toast[0] ? h('div', { className: 'msr-toast ' + toast[0].kind }, toast[0].text) : null
      )
    }

    exports.inject = ['slots']

    exports.apply = function apply(ctx) {
      var slots = ctx.get('slots')
      if (slots === undefined) return
      ensureCss()
      slots.inject('conversation.input.dock', function () {
        return slots.register(
          { name: 'conversation.input.dock', id: 'skill-review' },
          function (props) {
            return React.createElement(SkillReviewPanel, { sessionId: props.sessionId })
          },
        )
      })
    }

    return module.exports
  },
})
