const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function push(payload) {
  const listeners = {};
  const shown = [];
  const context = {
    URL,
    self: {
      addEventListener: (name, callback) => { listeners[name] = callback; },
      registration: {
        scope: 'https://app.example.test/',
        showNotification: async (title, options) => { shown.push({ title, options }); },
      },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'web', 'pauseable-push-sw.js'), 'utf8'), context);
  const pending = [];
  listeners.push({ data: { json: () => payload }, waitUntil: promise => pending.push(promise) });
  await Promise.all(pending);
  return shown[0];
}

test('regular safety pushes retain generic privacy-safe text', async () => {
  const shown = await push({ type: 'app_alert', alert_id: 'alert-one', body: 'private patient details' });
  assert.equal(shown.title, 'PAUSEABLE 안전 알림');
  assert.equal(shown.options.body, '새 안전 알림이 도착했습니다. 앱에서 확인해 주세요.');
  assert.equal(shown.options.tag, 'pauseable-alert-one');
  assert.equal(shown.options.data.url, 'https://app.example.test/?tab=alerts');
  assert.ok(!JSON.stringify(shown).includes('private patient details'));
});

test('test pushes are clearly labelled as not a real danger', async () => {
  const shown = await push({ type: 'push_test', alert_id: 'push-test-one' });
  assert.equal(shown.title, 'PAUSEABLE 알림 연결 시험');
  assert.equal(shown.options.body, '알림 연결 시험입니다. 실제 위험 상황이 아닙니다.');
  assert.equal(shown.options.tag, 'pauseable-push-test-one');
});

test('explicit sound-off requests silent delivery for real and test pushes', async () => {
  for (const type of ['app_alert', 'push_test']) {
    const shown = await push({ type, sound_enabled: false });
    assert.equal(shown.options.silent, true);
  }
});

test('sound-on and legacy payloads keep browser default notification sound', async () => {
  for (const payload of [{sound_enabled: true}, {}]) {
    const shown = await push(payload);
    assert.equal(shown.options.silent, false);
  }
});

test('push-only updates activate immediately without replacing asset caches', async () => {
  const listeners = {};
  let skipped = false;
  let claimed = false;
  const context = { self: {
    addEventListener: (name, callback) => { listeners[name] = callback; },
    skipWaiting: async () => { skipped = true; },
    clients: { claim: async () => { claimed = true; } },
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'web', 'pauseable-push-sw.js'), 'utf8'), context);
  const pending = [];
  listeners.install({waitUntil: promise => pending.push(promise)});
  listeners.activate({waitUntil: promise => pending.push(promise)});
  await Promise.all(pending);
  assert.equal(skipped, true);
  assert.equal(claimed, true);
  assert.equal(listeners.fetch, undefined);
});

test('checking a subscription refreshes the worker without permission prompts or losing it on failure', async () => {
  for (const fails of [false, true]) {
    let updates = 0;
    const registration = {
      update: async () => { updates++; if (fails) throw new Error('offline'); },
      pushManager: {getSubscription: async () => ({toJSON: () => ({endpoint: 'same-subscription'})})},
    };
    const context = {
      URL,
      document: {baseURI: 'https://app.example.test/'},
      window: {isSecureContext: true, PushManager: {}, Notification: {}},
      Notification: {permission: 'granted', requestPermission: () => assert.fail('no permission prompt')},
      navigator: {serviceWorker: {getRegistration: async () => registration}},
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'web', 'pauseable-push.js'), 'utf8'), context);
    const result = JSON.parse(await context.window.pauseablePush.currentSubscription());
    assert.equal(updates, 1);
    assert.equal(result.endpoint, 'same-subscription');
  }
});
