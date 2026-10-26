
(() => {
  const workerUrl = new URL('pauseable-push-sw.js', document.baseURI);
  const scopeUrl = new URL('.', document.baseURI);

  function supported() {
    return window.isSecureContext &&
      'serviceWorker' in navigator &&
      'PushManager' in window &&
      'Notification' in window;
  }

  function decodePublicKey(value) {
    const padded = value.replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(padded.padEnd(Math.ceil(padded.length / 4) * 4, '='));
    return Uint8Array.from(raw, (character) => character.charCodeAt(0));
  }

  async function registration() {
    if (!supported()) throw new Error('이 브라우저에서는 웹 푸시를 사용할 수 없습니다.');
    return navigator.serviceWorker.register(workerUrl.href, {
      scope: scopeUrl.pathname,
      updateViaCache: 'none',
    });
  }

  window.pauseablePush = {
    isSupported: supported,
    permission: () => supported() ? Notification.permission : 'unsupported',
    currentSubscription: async () => {
      if (!supported()) return '';
      const existing = await navigator.serviceWorker.getRegistration(scopeUrl.href);
      if (!existing) return '';


      try { void existing.update().catch(() => {}); } catch (_) {}
      const subscription = await existing.pushManager.getSubscription();
      return subscription ? JSON.stringify(subscription.toJSON()) : '';
    },
    subscribe: async (publicKey) => {
      if (!supported()) throw new Error('이 브라우저에서는 웹 푸시를 사용할 수 없습니다.');

      const permission = await Notification.requestPermission();
      if (permission !== 'granted') throw new Error('브라우저 알림 권한이 허용되지 않았습니다.');
      const worker = await registration();
      const key = decodePublicKey(publicKey);
      let subscription = await worker.pushManager.getSubscription();
      if (subscription) {
        const oldKey = subscription.options.applicationServerKey;
        const oldBytes = oldKey ? new Uint8Array(oldKey) : null;
        if (!oldBytes || oldBytes.length !== key.length ||
            oldBytes.some((byte, index) => byte !== key[index])) {
          await subscription.unsubscribe();
          subscription = null;
        }
      }
      subscription ??= await worker.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: key,
      });
      return JSON.stringify(subscription.toJSON());
    },
    unsubscribe: async () => {
      const existing = await navigator.serviceWorker.getRegistration(scopeUrl.href);
      const subscription = await existing?.pushManager.getSubscription();
      return subscription ? subscription.unsubscribe() : true;
    },
  };
})();
