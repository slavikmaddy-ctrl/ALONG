(function () {
  document.documentElement.classList.add("js");

  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.querySelector("[data-nav]");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "Закрыть" : "Меню";
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.textContent = "Меню";
        toggle.focus();
      }
    });
  }

  var bands = document.querySelectorAll(".reveal");
  if (bands.length && "IntersectionObserver" in window) {
    var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      bands.forEach(function (node) { node.classList.add("is-in"); });
    } else {
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            observer.unobserve(entry.target);
          }
        });
      }, { threshold: 0.16, rootMargin: "0px 0px -8% 0px" });
      bands.forEach(function (node) { observer.observe(node); });
    }
  } else {
    bands.forEach(function (node) { node.classList.add("is-in"); });
  }

  var mapHost = document.getElementById("along-map");
  if (!mapHost) {
    return;
  }

  var CITIES = [
    { name: "Москва", lat: 55.7558, lon: 37.6173 },
    { name: "Санкт-Петербург", lat: 59.9343, lon: 30.3351 },
    { name: "Казань", lat: 55.7887, lon: 49.1221 },
    { name: "Новосибирск", lat: 55.0084, lon: 82.9357 },
    { name: "Екатеринбург", lat: 56.8389, lon: 60.6057 },
    { name: "Нижний Новгород", lat: 56.2965, lon: 43.9361 },
    { name: "Самара", lat: 53.1959, lon: 50.1002 },
    { name: "Уфа", lat: 54.7388, lon: 55.9721 },
    { name: "Ростов-на-Дону", lat: 47.2357, lon: 39.7015 },
    { name: "Краснодар", lat: 45.0355, lon: 38.9753 },
    { name: "Воронеж", lat: 51.6608, lon: 39.2003 },
    { name: "Пермь", lat: 58.0105, lon: 56.2502 },
    { name: "Волгоград", lat: 48.708, lon: 44.5133 },
    { name: "Красноярск", lat: 56.0153, lon: 92.8932 },
    { name: "Сочи", lat: 43.6028, lon: 39.7342 },
    { name: "Иннополис", lat: 55.752, lon: 48.7446 },
    { name: "Минск", lat: 53.9006, lon: 27.559 },
    { name: "Гомель", lat: 52.4345, lon: 30.9754 },
    { name: "Брест", lat: 52.0976, lon: 23.7341 },
    { name: "Алматы", lat: 43.222, lon: 76.8512 },
    { name: "Астана", lat: 51.1694, lon: 71.4491 },
    { name: "Шымкент", lat: 42.3417, lon: 69.5901 },
    { name: "Ереван", lat: 40.1792, lon: 44.4991 },
    { name: "Гюмри", lat: 40.7894, lon: 43.8475 },
    { name: "Бишкек", lat: 42.8746, lon: 74.5698 },
    { name: "Ош", lat: 40.5283, lon: 72.7985 },
    { name: "Ташкент", lat: 41.2995, lon: 69.2401 },
    { name: "Самарканд", lat: 39.6542, lon: 66.9597 },
    { name: "Душанбе", lat: 38.5598, lon: 68.787 },
    { name: "Худжанд", lat: 40.2826, lon: 69.6222 },
    { name: "Баку", lat: 40.4093, lon: 49.8671 },
    { name: "Гянджа", lat: 40.6828, lon: 46.3606 }
  ];

  var HERE = "Моё местоположение";
  var fromInput = document.getElementById("from-input");
  var toInput = document.getElementById("to-input");
  var dateInput = document.getElementById("date-input");
  var serviceRow = document.getElementById("service-row");
  var fallback = document.getElementById("map-fallback");
  var map = null;
  var marker = null;
  var mapReady = false;
  var geoGranted = false;
  var activeIndex = -1;

  function showMapError(text) {
    if (!fallback || fallback.textContent) {
      return;
    }
    fallback.hidden = false;
    fallback.textContent = text;
  }

  function placeMarker(lat, lon, zoom) {
    if (!map || !window.DG) {
      return;
    }
    try {
      if (marker) {
        marker.setLatLng([lat, lon]);
      } else {
        marker = DG.marker([lat, lon]).addTo(map);
      }
      map.setView([lat, lon], zoom);
    } catch (error) {
      showMapError("Карта 2ГИС открылась не до конца: метку поставить не удалось.");
    }
  }

  function bootMap() {
    if (!window.DG || typeof DG.then !== "function") {
      showMapError("Интерактивная карта 2ГИС без ключа API не открылась. Ключ в макет не подставлен.");
      return;
    }
    try {
      DG.then(function () {
        try {
          if (typeof DG.map !== "function") {
            showMapError("Интерактивная карта 2ГИС без ключа API не открылась. Ключ в макет не подставлен.");
            return;
          }
          map = DG.map("along-map", {
            center: [56.5, 60],
            zoom: 3,
            scrollWheelZoom: false,
            fullscreenControl: false
          });
          mapReady = true;
          window.setTimeout(function () {
            try {
              if (map && map.invalidateSize) {
                map.invalidateSize();
              }
            } catch (ignore) {
              /* размер контейнера уже задан */
            }
          }, 250);
        } catch (error) {
          showMapError("Интерактивная карта 2ГИС без ключа API не открылась. Ключ в макет не подставлен.");
        }
      });
    } catch (error) {
      showMapError("Интерактивная карта 2ГИС без ключа API не открылась. Ключ в макет не подставлен.");
    }
    window.setTimeout(function () {
      var tile = mapHost.querySelector("img");
      var blocked = tile && tile.src.indexOf("nomap") !== -1;
      if (!mapReady || blocked) {
        showMapError("Карта 2ГИС подключена, но без ключа API тайлы не открываются. Ключ в макет не подставлен.");
      }
    }, 2000);
  }

  function matches(query) {
    var needle = query.trim().toLowerCase();
    if (needle.length < 1) {
      return [];
    }
    return CITIES.filter(function (city) {
      return city.name.toLowerCase().indexOf(needle) !== -1;
    }).slice(0, 7);
  }

  function closeList(list, input) {
    if (!list || !input) {
      return;
    }
    list.hidden = true;
    list.innerHTML = "";
    input.setAttribute("aria-expanded", "false");
    activeIndex = -1;
  }

  function choose(input, list, name) {
    input.value = name;
    closeList(list, input);
    input.focus();
    refreshServices();
    if (input === fromInput && name !== HERE) {
      var city = CITIES.filter(function (item) { return item.name === name; })[0];
      if (city) {
        placeMarker(city.lat, city.lon, 8);
      }
    }
  }

  function paintList(input, list) {
    var items = matches(input.value);
    list.innerHTML = "";
    activeIndex = -1;
    if (!items.length) {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      return;
    }
    items.forEach(function (city, index) {
      var item = document.createElement("li");
      item.setAttribute("role", "presentation");
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.textContent = city.name;
      button.addEventListener("mousedown", function (event) {
        event.preventDefault();
        choose(input, list, city.name);
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

  function moveActive(list, step) {
    var buttons = list.querySelectorAll("button");
    if (!buttons.length) {
      return;
    }
    activeIndex = (activeIndex + step + buttons.length) % buttons.length;
    buttons.forEach(function (button, index) {
      button.classList.toggle("is-active", index === activeIndex);
    });
  }

  function bindSuggest(input, list) {
    input.addEventListener("input", function () {
      if (input === fromInput && input.value !== HERE) {
        geoGranted = false;
      }
      paintList(input, list);
      refreshServices();
    });
    input.addEventListener("keydown", function (event) {
      if (list.hidden && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        paintList(input, list);
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
          choose(input, list, current.textContent);
        }
      } else if (event.key === "Escape") {
        closeList(list, input);
      }
    });
    input.addEventListener("blur", function () {
      window.setTimeout(function () { closeList(list, input); }, 120);
    });
  }

  function filled(input) {
    return !!(input && input.value && input.value.trim());
  }

  function refreshServices() {
    if (!serviceRow || !fromInput || !toInput || !dateInput) {
      return;
    }
    var ready = geoGranted
      ? filled(toInput) && filled(dateInput)
      : filled(fromInput) && filled(toInput) && filled(dateInput);
    serviceRow.hidden = !ready;
  }

  function onGeoSuccess(position) {
    if (!position || !position.coords) {
      return;
    }
    geoGranted = true;
    fromInput.value = HERE;
    refreshServices();
    var lat = position.coords.latitude;
    var lon = position.coords.longitude;
    if (mapReady) {
      placeMarker(lat, lon, 12);
    } else {
      var waits = 0;
      var timer = window.setInterval(function () {
        waits += 1;
        if (mapReady || waits > 20) {
          window.clearInterval(timer);
          if (mapReady) {
            placeMarker(lat, lon, 12);
          }
        }
      }, 250);
    }
  }

  bootMap();
  bindSuggest(fromInput, document.getElementById("from-list"));
  bindSuggest(toInput, document.getElementById("to-list"));
  if (dateInput) {
    dateInput.addEventListener("input", refreshServices);
    dateInput.addEventListener("change", refreshServices);
  }

  if (navigator.geolocation && navigator.geolocation.getCurrentPosition) {
    navigator.geolocation.getCurrentPosition(onGeoSuccess, function () {
      geoGranted = false;
      refreshServices();
    }, { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 });
  }
})();
