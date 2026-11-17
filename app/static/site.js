(function () {
  var MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  document.documentElement.classList.add("js");
  initNav();
  initToasts();
  initCalendars();
  initQuickDates();
  initDialogs();

  function initDialogs() {
    document.querySelectorAll("[data-open-dialog]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = document.getElementById(button.getAttribute("data-open-dialog"));
        if (dialog && typeof dialog.showModal === "function") {
          dialog.showModal();
        }
      });
    });
    document.querySelectorAll("[data-close-dialog]").forEach(function (button) {
      button.addEventListener("click", function () {
        var dialog = button.closest("dialog");
        if (dialog && typeof dialog.close === "function") {
          dialog.close();
        }
      });
    });
    var sent = document.getElementById("resign-sent");
    if (sent && typeof sent.showModal === "function" && !sent.open) {
      sent.showModal();
    }
  }

  function initNav() {
    var toggle = document.querySelector("[data-nav-toggle]");
    var nav = document.querySelector("[data-nav]");
    if (!toggle || !nav) {
      return;
    }
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "Закрыть" : "Меню";
    });
    nav.addEventListener("click", function (event) {
      if (event.target.closest("a")) {
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.textContent = "Меню";
      }
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

  function initToasts() {
    var source = document.getElementById("flash-messages");
    var box = document.getElementById("toasts");
    if (!source || !box || !source.content) {
      return;
    }
    source.content.querySelectorAll("p").forEach(function (node) {
      var toast = document.createElement("div");
      toast.className = "toast";
      toast.textContent = node.textContent;
      box.appendChild(toast);
      window.requestAnimationFrame(function () {
        toast.classList.add("is-on");
      });
      window.setTimeout(function () {
        toast.classList.remove("is-on");
        toast.classList.add("is-out");
        window.setTimeout(function () {
          toast.remove();
        }, 400);
      }, 3000);
    });
  }

  function isoDate(date) {
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return date.getFullYear() + "-" + month + "-" + day;
  }

  function presetDate(name) {
    var now = new Date();
    var day = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    if (name === "tomorrow") {
      day.setDate(day.getDate() + 1);
    }
    if (name === "weekend") {
      var shift = (6 - day.getDay()) % 7;
      day.setDate(day.getDate() + shift);
    }
    return isoDate(day);
  }

  function markDatePills(value) {
    document.querySelectorAll("[data-date-preset]").forEach(function (button) {
      var active = presetDate(button.getAttribute("data-date-preset")) === value;
      button.classList.toggle("is-active", active);
      if (active) {
        button.setAttribute("aria-pressed", "true");
      } else {
        button.removeAttribute("aria-pressed");
      }
    });
  }

  function dayMap(list) {
    var map = {};
    if (!list) {
      return map;
    }
    list.forEach(function (item) {
      if (item && item.date) {
        map[item.date] = item.count || 0;
      }
    });
    return map;
  }

  function readDays(id) {
    var node = id ? document.getElementById(id) : null;
    if (!node) {
      return {};
    }
    try {
      return dayMap(JSON.parse(node.textContent || "[]"));
    } catch (error) {
      return {};
    }
  }

  function syncDatePills(days) {
    document.querySelectorAll("[data-date-preset]").forEach(function (button) {
      var value = presetDate(button.getAttribute("data-date-preset"));
      var live = !!days[value];
      button.disabled = !live;
      button.classList.toggle("is-disabled", !live);
      if (!live) {
        button.classList.remove("is-active");
        button.removeAttribute("aria-pressed");
      }
    });
  }

  function loadTripFilter(form) {
    var params = new URLSearchParams(new FormData(form));
    var action = form.getAttribute("action") || window.location.pathname;
    var next = action + "?" + params.toString();
    var feed = document.querySelector("[data-trip-feed]");
    if (feed) {
      feed.setAttribute("aria-busy", "true");
    }
    fetch(next, {
      headers: { "X-Requested-With": "fetch" },
      credentials: "same-origin"
    }).then(function (response) {
      if (!response.ok) {
        throw new Error("status");
      }
      return response.text();
    }).then(function (html) {
      var doc = new DOMParser().parseFromString(html, "text/html");
      var fresh = doc.querySelector("[data-trip-feed]");
      var current = document.querySelector("[data-trip-feed]");
      if (!fresh || !current) {
        throw new Error("feed");
      }
      current.replaceWith(fresh);
      history.replaceState(null, "", next);
    }).catch(function () {
      var current = document.querySelector("[data-trip-feed]");
      if (current) {
        current.removeAttribute("aria-busy");
      }
    });
  }

  function initQuickDates() {
    var pills = document.querySelector("[data-date-pills]");
    var form = document.querySelector("form.filters");
    if (!pills || !form) {
      return;
    }
    var input = form.querySelector("[data-trip-date]");
    if (input) {
      markDatePills(input.value);
    }
    pills.addEventListener("click", function (event) {
      var button = event.target.closest("[data-date-preset]");
      if (!button || button.disabled) {
        return;
      }
      event.preventDefault();
      var value = presetDate(button.getAttribute("data-date-preset"));
      if (input) {
        input.value = value;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
      markDatePills(value);
      loadTripFilter(form);
    });
  }

  function initCalendars() {
    document.querySelectorAll("[data-calendar]").forEach(function (root) {
      setupCalendar(root);
    });
  }

  function formatTripDay(stamp) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(stamp)) {
      return stamp || "";
    }
    var parts = stamp.split("-");
    var dayNum = parseInt(parts[2], 10);
    var month = parseInt(parts[1], 10) - 1;
    if (!dayNum || month < 0 || month > 11 || !MONTHS_GEN[month]) {
      return stamp;
    }
    return dayNum + " " + MONTHS_GEN[month] + " " + parts[0];
  }

  function setupCalendar(root) {
    var input = document.getElementById(root.getAttribute("data-input"));
    if (!input) {
      return;
    }
    var days = readDays(root.getAttribute("data-days-id"));
    var blank = root.getAttribute("data-blank") || "Когда есть поездки";
    root.classList.add("day-pick");
    var trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "day-pick__btn";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    var value = document.createElement("span");
    value.className = "day-pick__value";
    var chev = document.createElement("span");
    chev.className = "day-pick__chev";
    chev.setAttribute("aria-hidden", "true");
    trigger.appendChild(value);
    trigger.appendChild(chev);
    var list = document.createElement("ul");
    list.className = "day-pick__list";
    list.hidden = true;
    list.setAttribute("role", "listbox");
    root.appendChild(trigger);
    root.appendChild(list);

    function liveStamps() {
      return Object.keys(days).filter(function (stamp) {
        return days[stamp] && /^\d{4}-\d{2}-\d{2}$/.test(stamp);
      }).sort();
    }

    function closeMenu() {
      list.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }

    function paint() {
      var stamps = liveStamps();
      if (input.value && !days[input.value]) {
        input.value = "";
      }
      var label = input.value ? formatTripDay(input.value) : blank;
      value.textContent = label;
      trigger.title = label;
      trigger.classList.toggle("is-empty", !input.value);
      list.textContent = "";
      if (!stamps.length) {
        var empty = document.createElement("li");
        empty.className = "day-pick__empty";
        empty.textContent = blank.indexOf("рейс") >= 0 ? "Пока нет дней с рейсами" : "Пока нет дней с поездками";
        list.appendChild(empty);
      }
      stamps.forEach(function (stamp) {
        var item = document.createElement("li");
        var button = document.createElement("button");
        button.type = "button";
        button.className = "day-pick__opt";
        button.setAttribute("role", "option");
        var text = formatTripDay(stamp);
        button.textContent = text;
        button.title = text;
        if (input.value === stamp) {
          button.classList.add("is-picked");
          button.setAttribute("aria-selected", "true");
        }
        button.addEventListener("click", function () {
          input.value = stamp;
          input.dispatchEvent(new Event("change", { bubbles: true }));
          closeMenu();
          paint();
          markDatePills(stamp);
          var mode = root.getAttribute("data-submit");
          var form = root.closest("form");
          if (mode === "feed" && form) {
            loadTripFilter(form);
          } else if (mode === "1" && form) {
            form.submit();
          }
        });
        item.appendChild(button);
        list.appendChild(item);
      });
      syncDatePills(days);
      if (input.value) {
        markDatePills(input.value);
      }
    }

    trigger.addEventListener("click", function () {
      var willOpen = list.hidden;
      list.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });
    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) {
        closeMenu();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !list.hidden) {
        closeMenu();
      }
    });
    input.addEventListener("change", function () {
      paint();
    });

    var timer = 0;
    function reload() {
      var endpoint = root.getAttribute("data-endpoint");
      if (!endpoint) {
        paint();
        return;
      }
      var params = new URLSearchParams();
      var fromEl = document.getElementById(root.getAttribute("data-from") || "");
      var toEl = document.getElementById(root.getAttribute("data-to") || "");
      var kindEl = document.getElementById(root.getAttribute("data-kind") || "");
      var mode = root.getAttribute("data-mode") || "";
      if (fromEl && fromEl.value.trim()) {
        params.set("from", fromEl.value.trim());
      }
      if (toEl && toEl.value.trim()) {
        params.set("to", toEl.value.trim());
      }
      if (kindEl && kindEl.value) {
        params.set("kind", kindEl.value);
      }
      if (mode) {
        params.set("mode", mode);
      }
      fetch(endpoint + "?" + params.toString(), { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("days");
          }
          return response.json();
        })
        .then(function (payload) {
          days = dayMap(payload);
          if (input.value && !days[input.value]) {
            input.value = "";
          }
          paint();
        })
        .catch(function () {
          paint();
        });
    }

    ["data-from", "data-to", "data-kind"].forEach(function (attr) {
      var el = document.getElementById(root.getAttribute(attr) || "");
      if (!el) {
        return;
      }
      el.addEventListener("change", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(reload, 250);
      });
      el.addEventListener("input", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(reload, 350);
      });
    });
    try {
      paint();
    } catch (error) {
      list.textContent = "";
    }
    reload();
  }
})();

(function () {
  var content = document.getElementById("content");
  if (!content) {
    return;
  }

  var reduceMotion = false;
  try {
    reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (error) {
    reduceMotion = false;
  }

  var leaving = false;

  function showContent() {
    content.classList.remove("page-exit");
  }

  window.addEventListener("pageshow", function () {
    leaving = false;
    showContent();
  });

  function isInternalNavigation(link, url) {
    var target = (link.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") {
      return false;
    }
    if (link.hasAttribute("download")) {
      return false;
    }
    if (url.origin !== window.location.origin) {
      return false;
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return false;
    }

    var path = url.pathname || "/";
    if (path === "/logout" || path.indexOf("/logout/") === 0) {
      return false;
    }
    if (path === "/admin/trips/export" || path.indexOf("/admin/trips/export/") === 0) {
      return false;
    }

    var fileName = path.split("/").pop() || "";
    if (/\.(csv|tsv|pdf|zip|gz|rar|7z|xlsx?|docx?|pptx?|png|jpe?g|gif|webp|svg|ico|txt|json|xml|mp3|mp4|webm)$/i.test(fileName)) {
      return false;
    }
    return true;
  }

  document.addEventListener("click", function (event) {
    if (event.defaultPrevented) {
      return;
    }
    if (event.button !== 0) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }

    var node = event.target;
    if (!node || typeof node.closest !== "function") {
      return;
    }
    var link = node.closest("a");
    if (!link) {
      return;
    }

    var href = link.getAttribute("href");
    if (!href) {
      return;
    }
    var trimmed = href.trim();
    if (!trimmed || trimmed.charAt(0) === "#" || /^javascript:/i.test(trimmed)) {
      return;
    }

    var url;
    try {
      url = new URL(trimmed, window.location.href);
    } catch (error) {
      return;
    }

    if (!isInternalNavigation(link, url)) {
      return;
    }

    if (url.pathname === window.location.pathname && url.search === window.location.search) {
      return;
    }

    event.preventDefault();
    if (leaving) {
      return;
    }
    leaving = true;
    var nextUrl = url.href;

    if (reduceMotion) {
      window.location.href = nextUrl;
      return;
    }

    content.classList.remove("page-enter");
    void content.offsetWidth;
    content.classList.add("page-exit");
    window.setTimeout(function () {
      window.location.href = nextUrl;
    }, 300);
  });
})();
