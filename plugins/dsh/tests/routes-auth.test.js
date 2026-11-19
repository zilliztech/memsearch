import test from 'node:test'
import assert from 'node:assert/strict'
import { registerSkillReviewRoutes } from '../index.js'

function fixture(get) {
  const routes = []
  const ctx = {
    get,
    agents: { get: () => { throw new Error('rejected requests must not access sessions') } },
  }
  registerSkillReviewRoutes(ctx, { register: route => routes.push(route) }, 'memsearch')
  assert.equal(routes.length, 5)
  return routes
}

function response() {
  return {
    writeHead(status) { this.status = status },
    end(body) { this.body = JSON.parse(body) },
  }
}

for (const status of [401, 403]) {
  test(`all HTTP routes honor DSH rejection ${status} before reading or executing`, async () => {
    const headers = { host: '127.0.0.1:3080', origin: 'http://127.0.0.1:3081' }
    let checked = 0
    const routes = fixture(name => {
      assert.equal(name, 'connection')
      return { requestRejection(request) {
        assert.deepEqual(Object.keys(request), ['headers'])
        assert.equal(request.headers, headers)
        checked++
        return status
      } }
    })
    for (const route of routes) {
      const res = response()
      await route.handler({
        method: 'POST', headers,
        get url() { throw new Error('must not parse rejected request') },
        on() { throw new Error('must not read rejected request body') },
      }, res)
      assert.equal(res.status, status, route.path)
    }
    assert.equal(checked, 5)
  })
}

for (const [name, get] of [
  ['missing service', () => undefined],
  ['missing API', () => ({})],
  ['lookup failure', () => { throw new Error('unavailable') }],
  ['authentication failure', () => ({ requestRejection() { throw new Error('unavailable') } })],
]) {
  test(`all HTTP routes fail closed on ${name}`, async () => {
    for (const route of fixture(get)) {
      const res = response()
      await route.handler({ headers: {} }, res)
      assert.equal(res.status, 503, route.path)
      assert.equal(res.body.error, 'authentication unavailable')
    }
  })
}

test('routes resolve authentication on every request, including after late mount or disposal', async () => {
  let connection
  const routes = fixture(() => connection)
  for (const status of [503, 405, 401, 503]) {
    connection = status === 503 ? undefined : {
      requestRejection: () => status === 405 ? undefined : 401,
    }
    for (const route of routes) {
      const res = response()
      await route.handler({ method: 'DELETE', headers: {} }, res)
      assert.equal(res.status, status, route.path)
    }
  }
})
