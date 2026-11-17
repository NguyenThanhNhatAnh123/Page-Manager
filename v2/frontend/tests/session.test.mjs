import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, unlink, rmdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import test, { after } from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/api.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022,
}}).outputText;
const directory = await mkdtemp(join(tmpdir(), 'pagemanager-session-tests-'));
const moduleFile = join(directory, 'api.mjs');
await writeFile(moduleFile, compiled);
after(async () => { await unlink(moduleFile); await rmdir(directory); });
let sequence = 0;

async function environment(t) {
  const original = { window: globalThis.window, fetch: globalThis.fetch, XMLHttpRequest: globalThis.XMLHttpRequest };
  const window = new EventTarget();
  const saved = new Map();
  window.localStorage = { setItem: (key, value) => saved.set(key, value) };
  globalThis.window = window;
  t.after(() => Object.assign(globalThis, original));
  const api = await import(pathToFileURL(moduleFile).href + `?instance=${sequence++}`);
  return { api, window, saved };
}

function delayedFetch() {
  let finish;
  globalThis.fetch = () => new Promise(resolve => { finish = resolve; });
  return (status, value) => finish(new Response(JSON.stringify(value), { status }));
}

test('an old successful response cannot enter the next account cache', async t => {
  const { api } = await environment(t);
  api.setCsrf('account-a');
  const finish = delayedFetch();
  const pending = api.api('/api/pages');
  api.setCsrf('account-b');
  finish(200, { items: [{ name: 'Private Page A' }] });
  await assert.rejects(pending, error => error instanceof api.ApiError && error.status === 409);
});

test('a late unauthorized response cannot log out the next account', async t => {
  const { api, window } = await environment(t);
  let expired = 0;
  window.addEventListener('pm-session-expired', () => expired++);
  api.setCsrf('account-a');
  const finish = delayedFetch();
  const pending = api.api('/api/pages');
  api.setCsrf('account-b');
  finish(401, { detail: 'Expired old session' });
  await assert.rejects(pending, error => error.status === 409);
  assert.equal(expired, 0);
});

test('current account responses and actual expiry still work', async t => {
  const { api, window } = await environment(t);
  let expired = 0;
  window.addEventListener('pm-session-expired', () => expired++);
  api.setCsrf('account-a');
  globalThis.fetch = async () => new Response(JSON.stringify({ total: 2 }), { status: 200 });
  assert.deepEqual(await api.api('/api/pages'), { total: 2 });
  globalThis.fetch = async () => new Response('{}', { status: 401 });
  await assert.rejects(api.api('/api/pages'), error => error.status === 401);
  assert.equal(expired, 1);
});

test('other tabs receive an auth boundary without any stored credentials', async t => {
  const { api, window, saved } = await environment(t);
  let resets = 0;
  const stop = api.watchSessionChanges(() => resets++);
  api.notifySessionChange();
  api.notifySessionChange();
  assert.equal(saved.size, 1);
  const [key, value] = [...saved][0];
  assert.match(value, /^[0-9a-f-]{36}$/i);
  const unrelated = Object.assign(new Event('storage'), { key: 'pm-theme' });
  window.dispatchEvent(unrelated);
  assert.equal(resets, 0);
  window.dispatchEvent(Object.assign(new Event('storage'), { key }));
  assert.equal(resets, 1);
  stop();
  window.dispatchEvent(Object.assign(new Event('storage'), { key }));
  assert.equal(resets, 1);
});

test('an upload completing after account change is discarded', async t => {
  const { api } = await environment(t);
  let request;
  globalThis.XMLHttpRequest = class {
    upload = {};
    constructor() { request = this; }
    open() {}
    setRequestHeader() {}
    send() {}
  };
  api.setCsrf('account-a');
  const pending = api.upload({ name: 'private-a.mp4' }, () => {});
  api.setCsrf('account-b');
  request.status = 200;
  request.responseText = JSON.stringify({ asset: { id: 'private-a' } });
  request.onload();
  await assert.rejects(pending, error => error.status === 409);
});

test('current upload expiry clears the account view', async t => {
  const { api, window } = await environment(t);
  let request, expired = 0;
  window.addEventListener('pm-session-expired', () => expired++);
  globalThis.XMLHttpRequest = class {
    upload = {};
    constructor() { request = this; }
    open() {}
    setRequestHeader() {}
    send() {}
  };
  api.setCsrf('account-a');
  const pending = api.upload({ name: 'private-a.mp4' }, () => {});
  request.status = 401;
  request.responseText = JSON.stringify({ detail: 'Session expired' });
  request.onload();
  await assert.rejects(pending, error => error.status === 401);
  assert.equal(expired, 1);
});
