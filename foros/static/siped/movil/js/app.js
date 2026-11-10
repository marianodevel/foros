/* PWA SIPED: service worker, instalación, push, búsqueda y feedback. */
(function () {
  "use strict";

  function cookie(nombre) {
    var partes = document.cookie ? document.cookie.split("; ") : [];
    for (var i = 0; i < partes.length; i += 1) {
      var par = partes[i].split("=");
      if (par[0] === nombre) {
        return decodeURIComponent(par.slice(1).join("="));
      }
    }
    return "";
  }

  var toastActual = null;

  function mostrarToast(texto, esError) {
    if (toastActual) {
      toastActual.remove();
    }
    var toast = document.createElement("div");
    toast.className = "toast" + (esError ? " error" : "");
    toast.setAttribute("role", esError ? "alert" : "status");
    toast.textContent = texto;
    document.body.appendChild(toast);
    toastActual = toast;
    window.setTimeout(
      function () {
        toast.remove();
        if (toastActual === toast) {
          toastActual = null;
        }
      },
      esError ? 7000 : 5000
    );
  }

  async function api(url, datos) {
    var respuesta = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": cookie("csrftoken"),
      },
      body: datos ? JSON.stringify(datos) : "{}",
    });
    var cuerpo = null;
    try {
      cuerpo = await respuesta.json();
    } catch (error) {
      cuerpo = null;
    }
    if (!respuesta.ok) {
      var mensaje = cuerpo && cuerpo.error ? cuerpo.error : "Error del servidor.";
      throw new Error(mensaje);
    }
    return cuerpo || {};
  }

  function base64AArray(valor) {
    var relleno = "=".repeat((4 - (valor.length % 4)) % 4);
    var base64 = (valor + relleno).replace(/-/g, "+").replace(/_/g, "/");
    var bruto = window.atob(base64);
    var salida = new Uint8Array(bruto.length);
    for (var i = 0; i < bruto.length; i += 1) {
      salida[i] = bruto.charCodeAt(i);
    }
    return salida;
  }

  /* Mensajes del servidor: cierre y descarte de éxitos. */
  function prepararMensajes() {
    var mensajes = document.querySelectorAll("[data-mensaje]");
    for (var i = 0; i < mensajes.length; i += 1) {
      var mensaje = mensajes[i];
      if (mensaje.dataset.preparado === "1") {
        continue;
      }
      mensaje.dataset.preparado = "1";

      var cerrar = mensaje.querySelector("[data-cerrar-mensaje]");
      if (cerrar) {
        cerrar.addEventListener("click", function (evento) {
          evento.currentTarget.closest("[data-mensaje]").remove();
        });
      }

      if (
        mensaje.classList.contains("success") &&
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ) {
        window.setTimeout(function (nodo) {
          nodo.remove();
        }, 5000, mensaje);
      }
    }
  }

  prepararMensajes();
  document.addEventListener("htmx:afterSwap", prepararMensajes);

  /* Instalación (Android / Chrome). */
  var promptInstalacion = null;
  var btnInstalar = document.getElementById("btn-instalar");

  window.addEventListener("beforeinstallprompt", function (evento) {
    evento.preventDefault();
    promptInstalacion = evento;
    if (btnInstalar) {
      btnInstalar.hidden = false;
    }
  });

  window.addEventListener("appinstalled", function () {
    promptInstalacion = null;
    if (btnInstalar) {
      btnInstalar.hidden = true;
    }
    mostrarToast("SIPED se instaló correctamente.");
  });

  if (btnInstalar) {
    btnInstalar.addEventListener("click", async function () {
      if (!promptInstalacion) {
        mostrarToast("Usá el menú del navegador y elegí «Instalar app».", true);
        return;
      }
      promptInstalacion.prompt();
      await promptInstalacion.userChoice;
      promptInstalacion = null;
      btnInstalar.hidden = true;
    });
  }

  /* Service worker. */
  var registroSw = null;

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker
      .register("/siped/sw.js", { scope: "/siped/" })
      .then(function (registro) {
        registroSw = registro;
      })
      .catch(function (error) {
        console.warn("No se pudo registrar el service worker:", error);
      });
  }

  /* Notificaciones push (sólo en la pestaña Perfil). */
  var config = document.getElementById("push-config");

  function iniciarPush() {
    if (!config) {
      return;
    }

    var vapid = config.dataset.vapidPublicKey || "";
    var toggle = document.getElementById("push-toggle");
    var estado = document.getElementById("push-estado");
    var probar = document.getElementById("push-probar");
    var suscripcionesServidor = Number(config.dataset.suscripciones || 0);

    if (!estado || !toggle) {
      return;
    }

    if (!("PushManager" in window) || !("Notification" in window)) {
      estado.textContent = "Este navegador no soporta notificaciones push.";
      toggle.disabled = true;
      if (probar) {
        probar.disabled = true;
      }
      return;
    }

    if (!vapid) {
      estado.textContent = "Falta la clave pública VAPID en el servidor.";
      toggle.disabled = true;
      if (probar) {
        probar.disabled = true;
      }
      return;
    }

    async function obtenerSuscripcion() {
      if (!registroSw) {
        registroSw = await navigator.serviceWorker.ready;
      }
      return registroSw.pushManager.getSubscription();
    }

    function pintarEstado(suscripcion) {
      var activo = Boolean(suscripcion);

      if (Notification.permission === "denied") {
        estado.textContent =
          "El navegador bloqueó las notificaciones. Habilitalas desde la configuración del sitio.";
        toggle.checked = false;
        toggle.disabled = true;
        if (probar) {
          probar.disabled = true;
        }
        return;
      }

      toggle.disabled = false;
      toggle.checked = activo;
      estado.textContent = activo
        ? "Notificaciones activas en este dispositivo."
        : "Notificaciones desactivadas en este dispositivo.";
      if (probar) {
        probar.disabled = !(activo || suscripcionesServidor > 0);
      }
    }

    async function activar() {
      var permiso = await Notification.requestPermission();
      if (permiso !== "granted") {
        throw new Error("No se otorgó permiso para notificaciones.");
      }
      var suscripcion = await obtenerSuscripcion();
      if (!suscripcion) {
        if (!registroSw) {
          registroSw = await navigator.serviceWorker.ready;
        }
        suscripcion = await registroSw.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: base64AArray(vapid),
        });
      }
      await api("/siped/m/push/suscribir/", suscripcion.toJSON());
      suscripcionesServidor = Math.max(1, suscripcionesServidor);
      pintarEstado(suscripcion);
      mostrarToast("Notificaciones activadas.");
    }

    async function desactivar() {
      var suscripcion = await obtenerSuscripcion();
      if (suscripcion) {
        await api("/siped/m/push/desuscribir/", {
          endpoint: suscripcion.endpoint,
        });
        await suscripcion.unsubscribe();
      }
      suscripcionesServidor = Math.max(0, suscripcionesServidor - 1);
      pintarEstado(null);
      mostrarToast("Notificaciones desactivadas.");
    }

    toggle.addEventListener("change", async function () {
      var deseado = toggle.checked;
      toggle.disabled = true;
      try {
        if (deseado) {
          await activar();
        } else {
          await desactivar();
        }
      } catch (error) {
        toggle.checked = !deseado;
        mostrarToast(error.message || "No se pudo cambiar el estado del push.", true);
      } finally {
        if (Notification.permission !== "denied") {
          toggle.disabled = false;
        }
      }
    });

    if (probar) {
      probar.addEventListener("click", async function () {
        probar.disabled = true;
        try {
          var resultado = await api("/siped/m/push/test/");
          if (!resultado.enviados) {
            mostrarToast(
              "No hay dispositivos suscriptos. Activá el push primero.",
              true
            );
            return;
          }
          mostrarToast("Notificación de prueba enviada.");
        } catch (error) {
          mostrarToast(error.message || "No se pudo enviar la prueba.", true);
        } finally {
          probar.disabled = suscripcionesServidor <= 0;
        }
      });
    }

    obtenerSuscripcion()
      .then(pintarEstado)
      .catch(function () {
        estado.textContent = "No se pudo consultar el estado del dispositivo.";
      });
  }

  iniciarPush();

  /* Mostrar u ocultar contraseña. */
  var botonRevelar = document.getElementById("revelar-password");
  if (botonRevelar) {
    botonRevelar.addEventListener("click", function () {
      var campo = document.querySelector(".campo-password input");
      if (!campo) {
        return;
      }
      var visible = campo.type === "text";
      campo.type = visible ? "password" : "text";
      botonRevelar.setAttribute(
        "aria-label",
        visible ? "Mostrar contraseña" : "Ocultar contraseña"
      );
      botonRevelar.setAttribute("aria-pressed", visible ? "false" : "true");
      var uso = botonRevelar.querySelector("use");
      if (uso) {
        uso.setAttribute(
          "href",
          visible ? "#icono-ojo" : "#icono-ojo-tachado"
        );
      }
    });
  }

  /* Enfocar el resumen de errores tras un login fallido. */
  var resumenErrores = document.getElementById("resumen-errores");
  if (resumenErrores) {
    resumenErrores.focus();
  }

  /* Evitar envíos duplicados del login. */
  var formularioLogin = document.querySelector(".formulario");
  var btnIngresar = document.getElementById("btn-ingresar");
  if (formularioLogin && btnIngresar) {
    formularioLogin.addEventListener("submit", function () {
      btnIngresar.disabled = true;
      btnIngresar.textContent = "Ingresando…";
    });
  }

  /* Confirmación para acciones destructivas. */
  var formulariosConfirmar = document.querySelectorAll("[data-confirmar]");
  for (var i = 0; i < formulariosConfirmar.length; i += 1) {
    formulariosConfirmar[i].addEventListener("submit", function (evento) {
      if (!window.confirm(evento.currentTarget.dataset.confirmar)) {
        evento.preventDefault();
      }
    });
  }

  /* Filtro local de expedientes. */
  var buscador = document.getElementById("buscar-expediente");
  if (buscador) {
    var lista = document.getElementById("lista-expedientes");
    var sinResultados = document.getElementById("sin-resultados");
    var conteo = document.getElementById("conteo-expedientes");
    var limpiar = document.getElementById("limpiar-busqueda");
    var limpiarVacio = document.getElementById("limpiar-desde-vacio");
    var terminoBuscado = document.getElementById("termino-buscado");
    var tarjetas = lista ? lista.querySelectorAll(".expediente") : [];

    function normalizar(texto) {
      return (texto || "")
        .toString()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase();
    }

    function aplicarFiltro() {
      var termino = normalizar(buscador.value.trim());
      var visibles = 0;

      for (var j = 0; j < tarjetas.length; j += 1) {
        var coincide =
          !termino || normalizar(tarjetas[j].dataset.busqueda).indexOf(termino) !== -1;
        tarjetas[j].hidden = !coincide;
        if (coincide) {
          visibles += 1;
        }
      }

      if (conteo) {
        conteo.textContent =
          visibles + (visibles === 1 ? " expediente" : " expedientes");
      }
      if (sinResultados) {
        sinResultados.hidden = visibles > 0;
      }
      if (terminoBuscado) {
        terminoBuscado.textContent = buscador.value.trim();
      }
      if (limpiar) {
        limpiar.hidden = !buscador.value.trim();
      }
    }

    function limpiarBusqueda() {
      buscador.value = "";
      aplicarFiltro();
      buscador.focus();
    }

    buscador.addEventListener("input", aplicarFiltro);

    if (limpiar) {
      limpiar.addEventListener("click", limpiarBusqueda);
    }
    if (limpiarVacio) {
      limpiarVacio.addEventListener("click", limpiarBusqueda);
    }

    if (buscador.value.trim()) {
      aplicarFiltro();
    }
  }
})();
