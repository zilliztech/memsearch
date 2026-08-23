import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'

function createHarness() {
  let cursor = 0
  let stateValues = []
  let stateSetters = []
  const refs = []
  let moduleDefinition
  let dockRenderer

  const React = {
    createElement(type, props, ...children) {
      return {
        type,
        props: {
          ...(props || {}),
          children: children.length <= 1 ? children[0] : children,
        },
      }
    },
    useState(initial) {
      const index = cursor++
      const value = index < stateValues.length ? stateValues[index] : initial
      return [value, stateSetters[index] || (() => {})]
    },
    useCallback(fn) {
      cursor++
      return fn
    },
    useEffect() {
      cursor++
    },
    useRef(initial) {
      const index = cursor++
      if (!refs[index]) refs[index] = { current: initial }
      return refs[index]
    },
  }

  const context = vm.createContext({
    window: {
      __ModuleLoader__: {
        load(definition) {
          moduleDefinition = definition
        },
      },
    },
  })
  const source = fs.readFileSync(new URL('../client.js', import.meta.url), 'utf8')
  vm.runInContext(source, context)
  const client = moduleDefinition.factory((name) => {
    assert.equal(name, 'react')
    return React
  })
  const slots = {
    inject(_name, register) {
      register()
    },
    register(_meta, renderer) {
      dockRenderer = renderer
    },
  }
  client.apply({ get: () => slots })

  function renderWith(values, setters = []) {
    cursor = 0
    stateValues = values
    stateSetters = setters
  }

  renderWith([[], false, true, {}, null, null])
  const panelElement = dockRenderer({ sessionId: 'session-1' })
  const panelTree = panelElement.type(panelElement.props)
  const browserElement = findElement(panelTree, (element) => (
    typeof element.type === 'function' && element.type.name === 'MemsearchBrowser'
  ))
  assert.ok(browserElement, 'MemsearchBrowser component is reachable from the expanded panel')

  return {
    Browser: browserElement.type,
    context,
    renderWith,
  }
}

function visit(value, callback) {
  if (Array.isArray(value)) {
    for (const child of value) visit(child, callback)
    return
  }
  if (!value || typeof value !== 'object') return
  callback(value)
  visit(value.props?.children, callback)
}

function findElement(tree, predicate) {
  let match = null
  visit(tree, (element) => {
    if (match === null && predicate(element)) match = element
  })
  return match
}

function fileRow(tree, name) {
  return findElement(tree, (element) => {
    if (element.type !== 'div' || typeof element.props?.onClick !== 'function') return false
    let found = false
    visit(element.props.children, (child) => {
      const children = child.props?.children
      if (children === name || (Array.isArray(children) && children.includes(name))) found = true
    })
    return found
  })
}

async function flushPromises() {
  await new Promise((resolve) => setImmediate(resolve))
}

test('markdown preview renders inline styles and leaves unsafe links inert', () => {
  const { Browser, renderWith } = createHarness()
  renderWith([
    true,
    { '/': { dirs: [], files: [] } },
    { '/': true },
    null,
    { text: '**bold** *italic* `code` [guide](guide.md) [bad](javascript:alert)', ext: 'md' },
    false,
  ])
  const tree = Browser({ sessionId: 'session-1' })
  const types = []
  visit(tree, (element) => types.push(element.type))
  assert.ok(types.includes('strong'))
  assert.ok(types.includes('em'))
  assert.ok(types.includes('code'))
  const anchors = []
  visit(tree, (element) => {
    if (element.type === 'a') anchors.push(element)
  })
  assert.equal(anchors.length, 1, 'only the safe relative link is clickable')
  assert.equal(anchors[0].props.href, 'guide.md')
})

test('an older file response cannot replace a newer preview after rerender', async () => {
  const { Browser, context, renderWith } = createHarness()
  const pending = []
  const previewUpdates = []
  context.fetch = (url) => new Promise((resolve) => pending.push({ url, resolve }))

  const values = [
    true,
    { '/': { dirs: [], files: ['first.md', 'second.md'] } },
    { '/': true },
    null,
    null,
    false,
  ]
  const setters = []
  setters[4] = (value) => previewUpdates.push(value)

  renderWith(values, setters)
  const firstTree = Browser({ sessionId: 'session-1' })
  fileRow(firstTree, 'first.md').props.onClick()

  renderWith(values, setters)
  const secondTree = Browser({ sessionId: 'session-1' })
  fileRow(secondTree, 'second.md').props.onClick()
  assert.equal(pending.length, 2)

  pending[1].resolve({ ok: true, json: async () => ({ content: 'SECOND', ext: 'md' }) })
  await flushPromises()
  pending[0].resolve({ ok: true, json: async () => ({ content: 'FIRST', ext: 'md' }) })
  await flushPromises()

  assert.equal(previewUpdates.at(-1).text, 'SECOND')
  assert.ok(!previewUpdates.some((update) => update.text === 'FIRST'))
})
