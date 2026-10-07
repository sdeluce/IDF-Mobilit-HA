/* IDFM Prochain Départ - Lovelace card (vanilla custom element, no build). */
(() => {
  const MODE_COLORS = {
    metro: "#003CA6", rer: "#E3051C", train: "#00814F",
    tram: "#00643C", bus: "#00A88F", other: "#666666",
  };
  const MODE_LABELS = {
    fr: { metro: "Métro", rer: "RER", train: "Train", tram: "Tram", bus: "Bus", other: "Départ" },
    en: { metro: "Metro", rer: "RER", train: "Train", tram: "Tram", bus: "Bus", other: "Departure" },
  };
  const TEXTS = {
    fr: { leaveIn: "Partir dans", now: "Partir maintenant !", none: "Aucun départ", at: "à", then: "Puis :", min: "min" },
    en: { leaveIn: "Leave in", now: "Leave now!", none: "No departure", at: "at", then: "Then:", min: "min" },
  };
  const WEATHER_ICONS = {
    sunny: "mdi:weather-sunny",
    "clear-night": "mdi:weather-night",
    partlycloudy: "mdi:weather-partly-cloudy",
    cloudy: "mdi:weather-cloudy",
    rainy: "mdi:weather-rainy",
    pouring: "mdi:weather-pouring",
    snowy: "mdi:weather-snowy",
    "snowy-rainy": "mdi:weather-snowy-rainy",
    fog: "mdi:weather-fog",
    hail: "mdi:weather-hail",
    lightning: "mdi:weather-lightning",
    "lightning-rainy": "mdi:weather-lightning-rainy",
    windy: "mdi:weather-windy",
    "windy-variant": "mdi:weather-windy-variant",
    exceptional: "mdi:alert-circle-outline",
  };
  const INVALID = new Set(["unknown", "unavailable", "", null, undefined]);

  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };

  const STYLE = `
    :host { display: block; }
    ha-card, .card { display: block; container-type: inline-size; height: 100%; box-sizing: border-box;
      background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
      border-radius: var(--ha-card-border-radius, 16px); overflow: hidden; }
    .wrap { display: flex; flex-direction: column; height: 100%; box-sizing: border-box;
      padding: clamp(10px, 4cqi, 22px); gap: 2px; }
    .top { display: flex; align-items: center; gap: 10px; }
    .badge { min-width: 1.9em; padding: 0 .35em; height: 1.9em; box-sizing: border-box; border-radius: 8px;
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700;
      font-size: clamp(14px, 6cqi, 26px); flex: none; }
    .badge[hidden] { display: none; }
    .stop { flex: 1; min-width: 0; font-weight: 700; font-size: clamp(15px, 6cqi, 26px);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .clock { font-size: clamp(14px, 5.5cqi, 24px); color: var(--primary-text-color, #212121);
      font-variant-numeric: tabular-nums; }
    .label { font-size: clamp(11px, 3.8cqi, 16px); color: var(--secondary-text-color, #727272); margin-top: 4px; }
    .big { font-weight: 800; line-height: 1.05; font-size: clamp(36px, 22cqi, 110px);
      font-variant-numeric: tabular-nums; flex: 1; display: flex; align-items: center; white-space: nowrap; }
    .big.small { font-size: clamp(22px, 9cqi, 48px); white-space: normal; }
    .big.alert { color: var(--error-color, #db4437); }
    .next { font-size: clamp(11px, 3.8cqi, 15px); color: var(--secondary-text-color, #727272); min-height: 1.2em; }
    .bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px;
      font-size: clamp(12px, 4.6cqi, 20px); }
    .dep { display: flex; align-items: center; gap: 6px; min-width: 0; }
    .rt { width: .55em; height: .55em; border-radius: 50%; background: var(--success-color, #43a047);
      animation: pulse 1.6s ease-in-out infinite; flex: none; }
    .rt[hidden] { display: none; }
    .weather { display: flex; align-items: center; gap: 4px; color: var(--secondary-text-color, #727272); }
    .weather[hidden] { display: none; }
    .weather ha-icon { --mdc-icon-size: 1.4em; }
    @keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: .3; transform: scale(.7); } }
    @media (prefers-reduced-motion: reduce) { .rt { animation: none; } }
  `;

  class IdfmDepartureCard extends HTMLElement {
    constructor() {
      super();
      this._config = null;
      this._hass = null;
      this._timer = null;
      this._built = false;
      this.attachShadow({ mode: "open" });
    }

    static getConfigForm() {
      return {
        schema: [
          { name: "entity", required: true,
            selector: { entity: { domain: "sensor", integration: "idfm_departure" } } },
          { name: "weather_entity", selector: { entity: { domain: "weather" } } },
          { name: "title", selector: { text: {} } },
          { name: "show_next", selector: { boolean: {} } },
          { name: "show_clock", selector: { boolean: {} } },
        ],
        computeLabel: (s) => ({
          entity: "Entité (capteur leave_at)", weather_entity: "Météo (optionnel)",
          title: "Titre (remplace l'arrêt)", show_next: "Afficher les départs suivants",
          show_clock: "Afficher l'heure",
        }[s.name] || s.name),
      };
    }

    static getStubConfig(hass) {
      const states = (hass && hass.states) || {};
      const ids = Object.keys(states).filter((id) => id.startsWith("sensor."));
      const pick = ids.find((id) => id.endsWith("_leave_at"))
        || ids.find((id) => states[id].attributes && states[id].attributes.stop_name !== undefined);
      return { type: "custom:idfm-departure-card", entity: pick || "", show_next: false, show_clock: true };
    }

    setConfig(config) {
      if (!config || !config.entity) throw new Error("L'option 'entity' est requise");
      this._config = { show_next: false, show_clock: true, ...config };
      this._render();
    }

    set hass(hass) {
      const old = this._hass;
      this._hass = hass;
      const c = this._config;
      if (!c) return;
      if (old && old.states[c.entity] === hass.states[c.entity]
          && (!c.weather_entity || old.states[c.weather_entity] === hass.states[c.weather_entity])
          && old.locale === hass.locale) return;
      this._render();
    }

    getCardSize() { return 3; }
    getGridOptions() { return { columns: 6, rows: 3, min_rows: 2 }; }

    connectedCallback() {
      this._render();
      if (!this._timer) this._timer = setInterval(() => this._render(), 10000);
    }
    disconnectedCallback() {
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
    }

    _lang() {
      const l = ((this._hass && this._hass.locale && this._hass.locale.language) || "fr").slice(0, 2);
      return l === "fr" ? "fr" : "en";
    }

    _fmt(iso) {
      const t = Date.parse(iso);
      if (!iso || Number.isNaN(t)) return "";
      const opts = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
      const tz = this._hass && this._hass.config && this._hass.config.time_zone;
      if (tz) opts.timeZone = tz;
      try {
        return new Intl.DateTimeFormat("fr-FR", opts).format(t);
      } catch (e) {
        delete opts.timeZone;
        return new Intl.DateTimeFormat("fr-FR", opts).format(t);
      }
    }

    _build() {
      const root = this.shadowRoot;
      const style = document.createElement("style");
      style.textContent = STYLE;
      const card = document.createElement("ha-card");
      card.className = "card";
      const wrap = el("div", "wrap");
      const top = el("div", "top");
      this._badge = el("span", "badge");
      this._stop = el("span", "stop");
      this._clock = el("span", "clock");
      top.append(this._badge, this._stop, this._clock);
      this._label = el("div", "label");
      this._big = el("div", "big");
      this._big.setAttribute("aria-live", "polite");
      this._next = el("div", "next");
      const bottom = el("div", "bottom");
      const dep = el("div", "dep");
      this._depText = el("span");
      this._rt = el("span", "rt");
      dep.append(this._depText, this._rt);
      this._weather = el("div", "weather");
      this._wIcon = document.createElement("ha-icon");
      this._wTemp = el("span");
      this._weather.append(this._wIcon, this._wTemp);
      bottom.append(dep, this._weather);
      wrap.append(top, this._label, this._big, this._next, bottom);
      card.append(wrap);
      root.replaceChildren(style, card);
      this._built = true;
    }

    _current(st) {
      // Returns {valid, leaveAt, info} applying roll-over to a later departure.
      const a = st.attributes || {};
      let info = { line: a.line, line_color: a.line_color, line_text_color: a.line_text_color,
        mode: a.mode, stop_departure: a.stop_departure, realtime: a.realtime };
      let leaveAt = INVALID.has(st.state) ? NaN : Date.parse(st.state);
      const now = Date.now();
      const list = Array.isArray(a.departures) ? a.departures : [];
      if (Number.isNaN(leaveAt) || Math.floor((leaveAt - now) / 60000) < -1) {
        const next = list.find((d) => {
          const t = Date.parse(d && d.leave_at);
          return !Number.isNaN(t) && t > now && (Number.isNaN(leaveAt) || t > leaveAt);
        });
        if (next) {
          leaveAt = Date.parse(next.leave_at);
          info = { line: next.line, line_color: next.line_color, line_text_color: next.line_text_color,
            mode: next.mode, stop_departure: next.stop_departure, realtime: next.realtime };
        }
      }
      return { leaveAt, info, list };
    }

    _render() {
      if (!this._config) return;
      if (!this._built) this._build();
      const c = this._config;
      const hass = this._hass;
      const lang = this._lang();
      const T = TEXTS[lang];
      const st = hass && hass.states && hass.states[c.entity];

      this._clock.hidden = c.show_clock === false;
      if (!this._clock.hidden) this._clock.textContent = this._fmt(new Date().toISOString());

      if (!st) {
        this._badge.hidden = true;
        this._stop.textContent = c.title || c.entity;
        this._label.textContent = "";
        this._big.className = "big small";
        this._big.textContent = T.none;
        this._next.textContent = "";
        this._depText.textContent = "";
        this._rt.hidden = true;
        this._renderWeather();
        return;
      }

      const a = st.attributes || {};
      const { leaveAt, info, list } = this._current(st);
      const valid = !Number.isNaN(leaveAt);
      const mode = MODE_COLORS[info.mode] ? info.mode : "other";

      this._stop.textContent = c.title || a.stop_name || "";
      if (info.line) {
        this._badge.hidden = false;
        this._badge.textContent = String(info.line);
        this._badge.style.background = info.line_color || MODE_COLORS[mode];
        this._badge.style.color = info.line_text_color || "#ffffff";
      } else {
        this._badge.hidden = true;
      }

      if (valid) {
        const mins = Math.floor((leaveAt - Date.now()) / 60000);
        this._label.textContent = mins > 0 ? T.leaveIn : "";
        if (mins > 0) {
          this._big.className = "big";
          this._big.textContent = `${mins} ${T.min}`;
        } else {
          this._big.className = "big small alert";
          this._big.textContent = T.now;
        }
      } else {
        this._label.textContent = "";
        this._big.className = "big small";
        this._big.textContent = T.none;
      }

      const depTime = valid ? this._fmt(info.stop_departure) : "";
      const modeLabel = MODE_LABELS[lang][mode];
      this._depText.textContent = depTime ? `${modeLabel} ${T.at} ${depTime}` : "";
      this._rt.hidden = !(valid && info.realtime === true && depTime);

      if (c.show_next === true && valid) {
        const nexts = list
          .map((d) => Date.parse(d && d.leave_at) ? d : null)
          .filter((d) => d && Date.parse(d.leave_at) > leaveAt + 1000)
          .slice(0, 2)
          .map((d) => this._fmt(d.stop_departure || d.leave_at))
          .filter(Boolean);
        this._next.textContent = nexts.length ? `${T.then} ${nexts.join(", ")}` : "";
      } else {
        this._next.textContent = "";
      }
      this._renderWeather();
    }

    _renderWeather() {
      const c = this._config;
      const w = c.weather_entity && this._hass && this._hass.states[c.weather_entity];
      if (!w) { this._weather.hidden = true; return; }
      this._weather.hidden = false;
      this._wIcon.setAttribute("icon", WEATHER_ICONS[w.state] || "mdi:weather-cloudy");
      const t = Number(w.attributes && w.attributes.temperature);
      this._wTemp.textContent = Number.isFinite(t) ? `${Math.round(t)}°` : "";
    }
  }

  if (!customElements.get("idfm-departure-card")) {
    customElements.define("idfm-departure-card", IdfmDepartureCard);
  }
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "idfm-departure-card",
    name: "IDFM Prochain Départ",
    description: "Prochain départ à quitter la maison, avec minutes restantes, ligne et météo.",
    preview: true,
  });
})();
