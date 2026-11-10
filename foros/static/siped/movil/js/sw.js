/* Service Worker de la PWA SIPED.
 *
 * Sólo cachea la cáscara estática de la app. Las páginas y los datos de
 * expedientes se piden siempre a la red: nunca quedan almacenados en el
 * dispositivo.
 */

const CACHE = "siped-pwa-v3";
const ESTATICOS = [
  "/static/siped/movil/css/movil.css",
  "/static/siped/movil/js/app.js",
  "/static/siped/movil/icons/icon-192.png",
  "/siped/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ESTATICOS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((claves) =>
      Promise.all(
        claves
          .filter((clave) => clave !== CACHE)
          .map((clave) => caches.delete(clave))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  const url = new URL(event.request.url);

  // Estáticos propios: respuesta inmediata desde caché y actualización en
  // segundo plano (stale-while-revalidate).
  if (url.pathname.startsWith("/static/siped/movil/")) {
    event.respondWith(
      caches.match(event.request).then((cacheado) => {
        const red = fetch(event.request)
          .then((respuesta) => {
            if (respuesta && respuesta.ok) {
              const copia = respuesta.clone();
              caches
                .open(CACHE)
                .then((cache) => cache.put(event.request, copia));
            }
            return respuesta;
          })
          .catch(() => cacheado);
        return cacheado || red;
      })
    );
    return;
  }

  // Navegación: siempre red. Sin conexión se muestra un aviso sin datos.
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(
        () =>
          new Response(
            "<!doctype html><meta charset='utf-8'>" +
              "<meta name='viewport' content='width=device-width'>" +
              "<title>SIPED sin conexión</title>" +
              "<body style='font-family:system-ui;padding:2rem;text-align:center'>" +
              "<h1>SIPED</h1><p>Sin conexión. Volvé a intentar cuando tengas red.</p>",
            { headers: { "Content-Type": "text/html; charset=utf-8" } }
          )
      )
    );
  }
});

self.addEventListener("push", (event) => {
  let datos = {};
  if (event.data) {
    try {
      datos = event.data.json();
    } catch (error) {
      console.error("Push con payload inválido:", error);
    }
  }

  const titulo = datos.title || "SIPED";
  const opciones = {
    body: datos.body || "Tenés novedades en tus expedientes.",
    icon: datos.icon || "/static/siped/movil/icons/icon-192.png",
    badge: datos.badge || "/static/siped/movil/icons/badge-72.png",
    tag: datos.tag || "siped-novedades",
    renotify: Boolean(datos.renotify),
    data: datos.data || { url: "/siped/m/novedades/" },
  };

  event.waitUntil(self.registration.showNotification(titulo, opciones));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destino =
    (event.notification.data && event.notification.data.url) ||
    "/siped/m/novedades/";

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((ventanas) => {
        const abierta = ventanas.find(
          (ventana) => ventana.url.includes("/siped/") && !ventana.closed
        );
        if (abierta) {
          return abierta.focus();
        }
        return self.clients.openWindow(destino);
      })
  );
});
