// The only reason this file exists: iOS will not show a notification unless
// it is sent from a service worker. A home-screen web app can ask for
// permission and be granted it, and `new Notification(...)` will still throw
// — which is exactly what was happening, silently, inside a try/catch.
//
// It deliberately has no fetch handler. A caching service worker would pin
// players to whichever version of the app their phone happened to install
// first, and a round where one phone is running last week's rules is worse
// than no offline support at all. Updates keep working exactly as before.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

// Tapping the notification should put you in the round, not open a second
// copy of the app beside the one already running.
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of open) if ('focus' in c) return c.focus();
    if (self.clients.openWindow) return self.clients.openWindow('./');
  })());
});
