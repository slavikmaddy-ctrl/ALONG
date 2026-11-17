(function () {
  var mapHost = document.getElementById("along-map");
  if (!mapHost) {
    return;
  }
  var HERE = "Моё местоположение";
  var fromInput = document.getElementById("from-input");
  var toInput = document.getElementById("to-input");
  var dateInput = document.getElementById("date-input");
  var kindInput = document.getElementById("kind-input");
  var serviceRow = document.getElementById("service-row");
  var fallback = document.getElementById("map-fallback");
  var geoNote = document.getElementById("geo-note");
  var fromError = document.getElementById("from-error");
  var toError = document.getElementById("to-error");
  var dateError = document.getElementById("date-error");
  var map = null;
  var marker = null;
  var mapReady = false;
  var mapLive = false;
  var cursorParked = false;
  var cursorBtn = document.getElementById("map-cursor");
  var mapOpenBtn = document.getElementById("map-open");
  var geoGranted = false;
  var activeIndex = -1;
  var routeSeq = 0;

  function showMapError(text) {
    if (!fallback) {
      return;
    }
    fallback.hidden = false;
    fallback.textContent = text;
  }

  function pin() {
    var el = document.createElement("div");
    el.className = "along-pin";
    return el;
  }

  function placeMarker(lat, lon, zoom) {
    if (!map || !window.maplibregl) {
      return;
    }
    try {
      if (marker) {
        marker.setLngLat([lon, lat]);
      } else {
        marker = new maplibregl.Marker({ element: pin() }).setLngLat([lon, lat]).addTo(map);
      }
      map.flyTo({ center: [lon, lat], zoom: zoom });
      drawLine();
    } catch (error) {
      showMapError("Метку на карте поставить не удалось.");
    }
  }

  function clearRoute() {
    if (!map || typeof map.getLayer !== "function") {
      return;
    }
    ["along-route", "along-route-casing"].forEach(function (id) {
      try {
        if (map.getLayer(id)) {
          map.removeLayer(id);
        }
      } catch (error) {
        /* Слой уже снят при смене стиля. */
      }
    });
    try {
      if (map.getSource("along-route")) {
        map.removeSource("along-route");
      }
    } catch (error) {
      /* Источник уже снят вместе со стилем. */
    }
  }

  function setRoute(coordinates) {
    clearRoute();
    var data = {
      type: "Feature",
      geometry: { type: "LineString", coordinates: coordinates }
    };
    map.addSource("along-route", { type: "geojson", data: data });
    map.addLayer({
      id: "along-route-casing",
      type: "line",
      source: "along-route",
      paint: { "line-color": "#000000", "line-width": 8, "line-opacity": 0.2 }
    });
    map.addLayer({
      id: "along-route",
      type: "line",
      source: "along-route",
      paint: { "line-color": "#ff9f12", "line-width": 5 }
    });
  }

  function drawLine() {
    if (!map || !mapReady || typeof map.getSource !== "function") {
      return;
    }
    var fromLat = parseFloat(document.getElementById("from-lat").value);
    var fromLon = parseFloat(document.getElementById("from-lon").value);
    var toLat = parseFloat(document.getElementById("to-lat").value);
    var toLon = parseFloat(document.getElementById("to-lon").value);
    if (![fromLat, fromLon, toLat, toLon].every(function (n) { return !isNaN(n); })) {
      clearRoute();
      return;
    }
    var straight = [[fromLon, fromLat], [toLon, toLat]];
    try {
      setRoute(straight);
    } catch (error) {
      return;
    }
    var seq = ++routeSeq;
    var url = "https://router.project-osrm.org/route/v1/driving/"
      + fromLon + "," + fromLat + ";" + toLon + "," + toLat
      + "?overview=full&geometries=geojson";
    fetch(url).then(function (response) {
      if (!response.ok) {
        throw new Error("osrm");
      }
      return response.json();
    }).then(function (payload) {
      if (seq !== routeSeq || !map || !mapReady) {
        return;
      }
      var geometry = payload && payload.code === "Ok" && payload.routes && payload.routes[0]
        ? payload.routes[0].geometry
        : null;
      if (!geometry || geometry.type !== "LineString" || !geometry.coordinates || geometry.coordinates.length < 2) {
        return;
      }
      setRoute(geometry.coordinates);
    }).catch(function () {
      /* Прямая уже на карте: сбой OSRM страницу не ломает. */
    });
  }

  function paintProp(id, prop, value) {
    try {
      if (map.getLayer(id)) {
        map.setPaintProperty(id, prop, value);
      }
    } catch (error) {
      /* Слой чужого стиля мог исчезнуть — карту это не роняет. */
    }
  }

  function paintWarmMap() {
    if (!map || typeof map.getLayer !== "function") {
      return;
    }
    paintProp("background", "background-color", "#1a140f");
    paintProp("water", "fill-color", "#1a3a4a");
    paintProp("waterway", "line-color", "#2f6d86");
    paintProp("landuse_park", "fill-color", "#314228");
    paintProp("landcover_wood", "fill-color", "#28381f");
    paintProp("landcover_wood", "fill-opacity", 0.9);
    paintProp("landcover_wood", "fill-pattern", undefined);
    paintProp("landuse_residential", "fill-color", "#3a2b22");
    paintProp("landuse_residential", "fill-opacity", 0.72);
    paintProp("building", "fill-color", "#4e3b2e");
    paintProp("building", "fill-outline-color", "#6d5644");
    paintProp("highway_path", "line-color", "#6b5340");
    paintProp("highway_minor", "line-color", "#a67c52");
    paintProp("highway_minor", "line-opacity", 1);
    paintProp("highway_major_casing", "line-color", "#3a2410");
    paintProp("highway_major_inner", "line-color", "#ff9f12");
    paintProp("highway_major_subtle", "line-color", "#ff9f12");
    paintProp("highway_motorway_casing", "line-color", "#3a2410");
    paintProp("highway_motorway_inner", "line-color", "#ff9f12");
    paintProp("highway_motorway_subtle", "line-color", "#ff9f12");
    [
      "water_name", "place_city", "place_city_large", "place_town",
      "place_country_major", "place_country_minor"
    ].forEach(function (id) {
      paintProp(id, "text-color", "#f6efe4");
      paintProp(id, "text-halo-color", "#1a140f");
      paintProp(id, "text-halo-width", 1.1);
    });
    paintLightLabels();
  }

  function paintLightLabels() {
    if (!map || typeof map.getStyle !== "function") {
      return;
    }
    var style = null;
    try {
      style = map.getStyle();
    } catch (error) {
      return;
    }
    var layers = style && style.layers ? style.layers : [];
    layers.forEach(function (layer) {
      if (!layer || layer.type !== "symbol") {
        return;
      }
      var layout = layer.layout || {};
      if (!layout["text-field"]) {
        return;
      }
      paintProp(layer.id, "text-color", "#ffffff");
      paintProp(layer.id, "text-halo-color", "#000000");
      paintProp(layer.id, "text-halo-width", 1.2);
    });
  }

  function releasePageScroll() {
    document.documentElement.style.overflow = "";
    document.body.style.overflow = "";
    if (!map) {
      return;
    }
    ["scrollZoom", "dragPan", "boxZoom", "doubleClickZoom", "touchZoomRotate"].forEach(function (name) {
      var handler = map[name];
      if (!handler || typeof handler.disable !== "function") {
        return;
      }
      try {
        handler.disable();
      } catch (error) {
        /* Обработчик уже выключен. */
      }
    });
  }

  function restoreMarker() {
    var latEl = document.getElementById("from-lat");
    var lonEl = document.getElementById("from-lon");
    if (!latEl || !lonEl) {
      return;
    }
    var lat = parseFloat(latEl.value);
    var lon = parseFloat(lonEl.value);
    if (isNaN(lat) || isNaN(lon)) {
      return;
    }
    placeMarker(lat, lon, 12);
  }

  function hideMap() {
    var stageMap = mapHost.closest ? mapHost.closest(".stage-map") : null;
    setMapLive(false);
    releasePageScroll();
    if (stageMap) {
      stageMap.hidden = true;
    }
    if (cursorBtn) {
      cursorBtn.hidden = true;
    }
    if (mapOpenBtn) {
      mapOpenBtn.hidden = false;
    }
  }

  function showMap() {
    var stageMap = mapHost.closest ? mapHost.closest(".stage-map") : null;
    if (stageMap) {
      stageMap.hidden = false;
    }
    if (mapOpenBtn) {
      mapOpenBtn.hidden = true;
    }
    releasePageScroll();
    if (!map) {
      bootMap();
      return;
    }
    window.requestAnimationFrame(function () {
      try {
        map.resize();
      } catch (error) {
        /* Контейнер карты ещё без размера. */
      }
      drawLine();
      restoreMarker();
    });
  }

  var HANDLERS = ["scrollZoom", "dragPan", "boxZoom", "doubleClickZoom", "touchZoomRotate", "keyboard"];

  function setMapLive(on) {
    mapLive = !!on;
    mapHost.classList.toggle("is-locked", !mapLive);
    if (map) {
      HANDLERS.forEach(function (name) {
        var handler = map[name];
        if (!handler) {
          return;
        }
        try {
          if (mapLive) {
            handler.enable();
          } else {
            handler.disable();
          }
        } catch (error) {
          /* Обработчик стиля мог быть недоступен. */
        }
      });
    }
    if (cursorBtn) {
      cursorBtn.classList.toggle("is-live", mapLive);
      cursorBtn.textContent = mapLive ? "Закрыть карту" : "Двигать карту";
    }
    try {
      if (map && map.getCanvas) {
        map.getCanvas().style.pointerEvents = mapLive ? "auto" : "none";
      }
    } catch (error) {
      /* Холст ещё не создан. */
    }
  }

  function pointOnMap(x, y) {
    var rect = mapHost.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  function pointOnCursor(x, y) {
    if (!cursorBtn || cursorBtn.hidden) {
      return false;
    }
    var rect = cursorBtn.getBoundingClientRect();
    return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
  }

  function overPageUi(x, y) {
    var stack = document.elementsFromPoint(x, y);
    for (var i = 0; i < stack.length; i += 1) {
      var el = stack[i];
      if (!el || el === cursorBtn || (cursorBtn && cursorBtn.contains(el))) {
        continue;
      }
      if (el.closest && el.closest(".search-form, .service-row, .site-header, .suggest-list, .skip")) {
        return true;
      }
    }
    return false;
  }

  var aimX = 0;
  var aimY = 0;
  var viewX = 0;
  var viewY = 0;
  var cursorFrame = 0;

  function placeCursor(left, top, centered) {
    cursorBtn.style.left = left + "px";
    cursorBtn.style.top = top + "px";
    cursorBtn.style.transform = centered ? "translate(-50%, -50%)" : "none";
  }

  function tickCursor() {
    cursorFrame = 0;
    if (!cursorBtn || cursorBtn.hidden || cursorParked) {
      return;
    }
    var targetX = mapLive ? aimX + 26 : aimX;
    var targetY = mapLive ? aimY + 28 : aimY;
    var gain = mapLive ? 0.2 : 1;
    viewX += (targetX - viewX) * gain;
    viewY += (targetY - viewY) * gain;
    placeCursor(viewX, viewY, !mapLive);
    cursorFrame = window.requestAnimationFrame(tickCursor);
  }

  function kickCursor() {
    if (!cursorFrame) {
      cursorFrame = window.requestAnimationFrame(tickCursor);
    }
  }

  function bindMapGate() {
    if (!cursorBtn) {
      return;
    }
    document.addEventListener("mousemove", function (event) {
      aimX = event.clientX;
      aimY = event.clientY;
      var onMap = pointOnMap(aimX, aimY);
      var onBtn = pointOnCursor(aimX, aimY);
      if ((!onMap && !onBtn) || overPageUi(aimX, aimY)) {
        cursorBtn.hidden = true;
        cursorParked = false;
        if (mapLive) {
          setMapLive(false);
        }
        return;
      }
      if (onBtn && mapLive) {
        cursorParked = true;
      }
      cursorBtn.hidden = false;
      if (!mapLive) {
        viewX = aimX;
        viewY = aimY;
        placeCursor(viewX, viewY, true);
      } else if (!cursorParked) {
        kickCursor();
      }
    });
    cursorBtn.addEventListener("mouseleave", function () {
      cursorParked = false;
      if (mapLive) {
        kickCursor();
      }
    });
    cursorBtn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      var next = !mapLive;
      setMapLive(next);
      cursorParked = false;
      if (next) {
        viewX = aimX + 26;
        viewY = aimY + 28;
        placeCursor(viewX, viewY, false);
      } else {
        viewX = aimX;
        viewY = aimY;
        placeCursor(viewX, viewY, true);
      }
    });
    setMapLive(false);
  }

  function bootRaster() {
    try {
      if (map) map.remove();
    } catch (error) {
      map = null;
    }
    map = null;
    marker = null;
    mapReady = false;
    map = new maplibregl.Map({
      container: "along-map",
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap"
          }
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }]
      },
      center: [70, 60],
      zoom: 2.6,
      interactive: false
    });
    mapHost.classList.add("is-raster");
    map.on("load", function () {
      mapReady = true;
      map.resize();
      drawLine();
      restoreMarker();
    });
  }

  function bootMap() {
    if (!window.maplibregl) {
      showMapError("Карта не открылась. Проверьте сеть и обновите страницу.");
      return;
    }
    try {
      map = new maplibregl.Map({
        container: "along-map",
        style: "https://tiles.openfreemap.org/styles/dark",
        center: [70, 60],
        zoom: 2.6,
        attributionControl: true,
        interactive: false
      });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      map.on("load", function () {
        mapReady = true;
        if (fallback) fallback.hidden = true;
        paintWarmMap();
        setMapLive(false);
        map.once("idle", paintLightLabels);
        map.resize();
        drawLine();
        restoreMarker();
      });
      map.on("error", function () {
        if (!mapReady) bootRaster();
      });
    } catch (error) {
      showMapError("Карта не открылась. Проверьте сеть и обновите страницу.");
    }
  }

  var suggestTimer = 0;
  var suggestSeq = 0;

  function setCoords(prefix, place) {
    var latEl = document.getElementById(prefix + "-lat");
    var lonEl = document.getElementById(prefix + "-lon");
    if (!latEl || !lonEl) {
      return;
    }
    latEl.value = place ? place.lat : "";
    lonEl.value = place ? place.lon : "";
  }

  function normalizePlaces(payload) {
    if (!Array.isArray(payload)) {
      return [];
    }
    var places = [];
    payload.forEach(function (item) {
      if (!item || !item.display_name) {
        return;
      }
      var lat = parseFloat(item.lat);
      var lon = parseFloat(item.lon);
      if (isNaN(lat) || isNaN(lon)) {
        return;
      }
      places.push({ name: String(item.display_name), lat: lat, lon: lon });
    });
    return places.slice(0, 5);
  }

  function closeList(list, input) {
    list.hidden = true;
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    activeIndex = -1;
  }

  function focusPlace(lat, lon) {
    function go() {
      placeMarker(lat, lon, 16);
    }
    if (mapReady) {
      go();
      return;
    }
    var wait = 0;
    var timer = window.setInterval(function () {
      wait += 1;
      if (mapReady || wait > 20) {
        window.clearInterval(timer);
        if (mapReady) go();
      }
    }, 250);
  }

  function choose(input, list, place) {
    if (!place || isNaN(place.lat) || isNaN(place.lon) || !place.name) {
      return;
    }
    if (input === fromInput && input.value === HERE) {
      return;
    }
    input.value = place.name;
    input.dataset.picked = "1";
    input.dispatchEvent(new Event("change", { bubbles: true }));
    closeList(list, input);
    var prefix = input === fromInput ? "from" : "to";
    setCoords(prefix, place);
    if (input === fromInput) {
      geoGranted = false;
    }
    focusPlace(place.lat, place.lon);
    refreshServices();
  }

  function paintList(input, list, items) {
    var empty = document.getElementById(input.id + "-empty");
    list.innerHTML = "";
    activeIndex = -1;
    if (!input.value.trim() || input.value === HERE) {
      list.hidden = true;
      if (empty) empty.hidden = true;
      return;
    }
    if (!items.length) {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Ничего не найдено. Уточните запрос";
      }
      return;
    }
    if (empty) empty.hidden = true;
    items.forEach(function (place, index) {
      var item = document.createElement("li");
      item.setAttribute("role", "presentation");
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.textContent = place.name;
      button.dataset.name = place.name;
      button.dataset.lat = String(place.lat);
      button.dataset.lon = String(place.lon);
      button.addEventListener("mousedown", function (event) {
        event.preventDefault();
        choose(input, list, place);
      });
      item.appendChild(button);
      list.appendChild(item);
      if (index === 0) {
        button.classList.add("is-active");
        activeIndex = 0;
      }
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  }

  function bindSuggest(input, list) {
    function requestSuggest(query) {
      var ticket = ++suggestSeq;
      fetch("/api/geocode?q=" + encodeURIComponent(query)).then(function (response) {
        if (!response.ok) {
          throw new Error("geocode");
        }
        return response.json();
      }).then(function (payload) {
        if (ticket !== suggestSeq || input.value.trim() !== query || input.value === HERE) {
          return;
        }
        if (document.activeElement !== input) {
          return;
        }
        paintList(input, list, normalizePlaces(payload));
      }).catch(function () {
        if (ticket !== suggestSeq || input.value.trim() !== query || input.value === HERE) {
          return;
        }
        if (document.activeElement !== input) {
          return;
        }
        paintList(input, list, []);
      });
    }

    function scheduleSuggest(delay) {
      window.clearTimeout(suggestTimer);
      var query = input.value.trim();
      if (input.value === HERE || query.length < 2) {
        suggestSeq += 1;
        closeList(list, input);
        return;
      }
      suggestTimer = window.setTimeout(function () {
        requestSuggest(query);
      }, delay);
    }

    input.addEventListener("input", function () {
      input.dataset.picked = "";
      if (input === fromInput && input.value !== HERE) {
        geoGranted = false;
      }
      if (input.value !== HERE) {
        setCoords(input === fromInput ? "from" : "to", null);
      }
      drawLine();
      refreshServices();
      scheduleSuggest(400);
    });
    input.addEventListener("keydown", function (event) {
      if (list.hidden && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        scheduleSuggest(0);
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveActive(list, 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveActive(list, -1);
      } else if (event.key === "Enter" && !list.hidden) {
        var current = list.querySelectorAll("button")[activeIndex];
        if (current) {
          event.preventDefault();
          choose(input, list, {
            name: current.dataset.name || current.textContent,
            lat: parseFloat(current.dataset.lat),
            lon: parseFloat(current.dataset.lon)
          });
        }
      } else if (event.key === "Escape") {
        closeList(list, input);
      }
    });
    input.addEventListener("blur", function () {
      window.setTimeout(function () { closeList(list, input); }, 140);
    });
  }

  function moveActive(list, step) {
    var buttons = list.querySelectorAll("button");
    if (!buttons.length) return;
    activeIndex = (activeIndex + step + buttons.length) % buttons.length;
    buttons.forEach(function (button, index) {
      button.classList.toggle("is-active", index === activeIndex);
    });
  }

  function picked(input) {
    return input.dataset.picked === "1" && input.value.trim();
  }

  function dateOk() {
    if (!dateInput || !dateInput.value) return false;
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var chosen = new Date(dateInput.value + "T00:00:00");
    return chosen >= today;
  }

  function refreshServices() {
    var fromReady = geoGranted || (picked(fromInput) && fromInput.value !== HERE) || (geoGranted && fromInput.value === HERE);
    if (fromInput.value === HERE && fromInput.dataset.picked === "1") fromReady = true;
    var toReady = picked(toInput);
    var whenReady = dateOk();
    if (fromInput.value && toInput.value && fromInput.value === toInput.value) {
      toError.hidden = false;
      toError.textContent = "Укажите разные точки";
      toReady = false;
    } else if (toError) {
      toError.hidden = true;
    }
    if (dateInput && dateInput.value && !whenReady && dateError) {
      dateError.hidden = false;
      dateError.textContent = "Выберите сегодня или будущую дату";
    } else if (dateError) {
      dateError.hidden = true;
    }
    var ready = fromReady && toReady;
    if (!fromReady && fromInput.value && fromInput.dataset.picked !== "1" && fromInput.value !== HERE) {
      fromError.hidden = false;
      fromError.textContent = "Выберите адрес из списка";
    } else if (fromError && (fromReady || !fromInput.value)) {
      fromError.hidden = true;
    }
    if (!toReady && toInput.value && toInput.dataset.picked !== "1" && toInput.value !== fromInput.value) {
      toError.hidden = false;
      toError.textContent = "Выберите адрес из списка";
    }
    serviceRow.hidden = !ready;
    if (!ready) return;
    var params = new URLSearchParams({
      from: fromInput.value,
      to: toInput.value
    });
    if (dateInput && dateInput.value) {
      params.set("date", dateInput.value);
    }
    if (kindInput && kindInput.value) {
      params.set("kind", kindInput.value);
    }
    var fromLat = document.getElementById("from-lat").value.trim();
    var fromLon = document.getElementById("from-lon").value.trim();
    var toLat = document.getElementById("to-lat").value.trim();
    var toLon = document.getElementById("to-lon").value.trim();
    if (fromLat && fromLon) {
      params.set("from_lat", fromLat);
      params.set("from_lon", fromLon);
    }
    if (toLat && toLon) {
      params.set("to_lat", toLat);
      params.set("to_lon", toLon);
    }
    document.getElementById("svc-trips").href = "/trips?" + params.toString();
    document.getElementById("svc-route").href = "/route?" + params.toString();
    document.getElementById("svc-schedule").href = "/schedule?" + params.toString() + "&mode=bus";
    document.getElementById("svc-plan").href = "/trips/new?" + params.toString();
  }

  function askGeo() {
    if (!navigator.geolocation) {
      if (geoNote) {
        geoNote.hidden = false;
        geoNote.textContent = "Браузер не передал геолокацию. Введите адрес вручную.";
      }
      return;
    }
    navigator.geolocation.getCurrentPosition(function (position) {
      geoGranted = true;
      fromInput.value = HERE;
      fromInput.dataset.picked = "1";
      document.getElementById("from-lat").value = position.coords.latitude;
      document.getElementById("from-lon").value = position.coords.longitude;
      if (geoNote) geoNote.hidden = true;
      var wait = 0;
      var timer = window.setInterval(function () {
        wait += 1;
        if (mapReady || wait > 20) {
          window.clearInterval(timer);
          if (mapReady) placeMarker(position.coords.latitude, position.coords.longitude, 12);
        }
      }, 250);
      refreshServices();
    }, function (error) {
      geoGranted = false;
      if (fromInput.value === HERE) {
        fromInput.value = "";
        fromInput.dataset.picked = "";
        document.getElementById("from-lat").value = "";
        document.getElementById("from-lon").value = "";
      }
      if (geoNote) {
        geoNote.hidden = false;
        geoNote.textContent = error && error.code === 1
          ? "Геолокация недоступна. Введите адрес вручную."
          : "Координаты не пришли. Введите адрес вручную.";
      }
      refreshServices();
    }, { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 });
  }

  var bgVideo = document.querySelector(".hero-video");
  if (bgVideo) {
    bgVideo.muted = true;
    var playVideo = bgVideo.play();
    if (playVideo && typeof playVideo.catch === "function") {
      playVideo.catch(function () {});
    }
  }

  bindMapGate();
  if (mapOpenBtn) {
    mapOpenBtn.addEventListener("click", function (event) {
      event.preventDefault();
      showMap();
    });
  }
  hideMap();
  var mapClose = document.getElementById("map-close");
  if (mapClose) {
    mapClose.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      hideMap();
    });
  }
  bindSuggest(fromInput, document.getElementById("from-list"));
  bindSuggest(toInput, document.getElementById("to-list"));
  if (dateInput) {
    dateInput.addEventListener("input", refreshServices);
    dateInput.addEventListener("change", refreshServices);
  }
  if (kindInput) {
    kindInput.addEventListener("change", refreshServices);
  }
  var retry = document.getElementById("geo-retry");
  if (retry) retry.addEventListener("click", askGeo);
  var searchForm = document.getElementById("ride-search");
  if (searchForm) {
    searchForm.addEventListener("submit", function (event) {
      var latEl = document.getElementById("from-lat");
      var lonEl = document.getElementById("from-lon");
      var lat = latEl ? latEl.value.trim() : "";
      var lon = lonEl ? lonEl.value.trim() : "";
      if (fromInput.value === HERE && (!lat || !lon)) {
        event.preventDefault();
        fromInput.focus();
        fromInput.select();
        if (geoNote) {
          geoNote.hidden = false;
          geoNote.textContent = "Не удалось определить местоположение. Введите город вручную.";
        }
        return;
      }
      ["from-lat", "from-lon", "to-lat", "to-lon"].forEach(function (id) {
        var field = document.getElementById(id);
        if (field && !field.value.trim()) {
          field.disabled = true;
        }
      });
    });
  }
  askGeo();

  var bands = document.querySelectorAll(".reveal");
  if (bands.length) {
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !("IntersectionObserver" in window)) {
      bands.forEach(function (node) { node.classList.add("is-in"); });
    } else {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.16 });
      bands.forEach(function (node) { observer.observe(node); });
    }
  }
})();
