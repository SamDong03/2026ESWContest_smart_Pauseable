
self.addEventListener('install', (event) => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data?.json() ?? {};
  } catch (_) {
    payload = {};
  }
  const isTest = payload.type === 'push_test';
  const url = new URL('./?tab=alerts', self.registration.scope).href;
  event.waitUntil(self.registration.showNotification(isTest ? 'PAUSEABLE 알림 연결 시험' : 'PAUSEABLE 안전 알림', {
    body: isTest ? '알림 연결 시험입니다. 실제 위험 상황이 아닙니다.' : '새 안전 알림이 도착했습니다. 앱에서 확인해 주세요.',
    icon: new URL('icons/Icon-192.png', self.registration.scope).href,
    badge: new URL('icons/Icon-192.png', self.registration.scope).href,
    tag: typeof payload.alert_id === 'string'
      ? `pauseable-${payload.alert_id}`
      : 'pauseable-alert',
    data: { url },

    silent: payload.sound_enabled === false,
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL('./?tab=alerts', self.registration.scope).href;
  event.waitUntil((async () => {
    const windows = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const windowClient of windows) {
      if (windowClient.url.startsWith(self.registration.scope)) {
        await windowClient.navigate(url);
        return windowClient.focus();
      }
    }
    return clients.openWindow(url);
  })());
});
