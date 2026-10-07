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
    fr: { platform: "voie", leaveIn: "Partir dans", now: "Partir maintenant !", none: "Aucun départ", at: "à", then: "Puis :", min: "min",
      arrivalAt: (n, t) => `Arrivée à ${n} : ${t}`, noFilter: "filtre destination indisponible" },
    en: { platform: "platform", leaveIn: "Leave in", now: "Leave now!", none: "No departure", at: "at", then: "Then:", min: "min",
      arrivalAt: (n, t) => `Arrives ${n} at ${t}`, noFilter: "destination filter unavailable" },
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

  const SCALE_FIELD = { name: "scale", selector: { number: { min: 0.5, max: 3, step: 0.1, mode: "box" } } };
  const SIZE_LABELS = {
    scale: "Échelle globale (0.5 à 3, défaut 1)", card_height: "Hauteur de la carte (ex. 100% ou 300px)",
    minutes_size: "Taille des minutes (px ou 20cqi, 2em...)", header_size: "Taille de l'en-tête",
    badge_size: "Taille de la pastille", footer_size: "Taille de la ligne du bas", row_size: "Taille du texte des lignes",
    time_size: "Taille des heures", platform_size: "Taille de la voie",
  };
  const SIZE_RE = /^\d+(\.\d+)?(px|em|rem|%|cqi|vw|vh)$/;
  // Config option -> CSS custom property set inline on ha-card (inline wins over theme / card-mod).
  const SIZE_VARS = {
    minutes_size: "--idfm-minutes-size", header_size: "--idfm-header-size", badge_size: "--idfm-badge-size",
    footer_size: "--idfm-footer-size", row_size: "--idfm-row-size", time_size: "--idfm-time-size",
    platform_size: "--idfm-platform-size", card_height: "--idfm-card-height",
  };

  const STYLE = `
    :host { display: block; height: 100%; }
    ha-card, .card { display: block; container-type: inline-size; height: var(--idfm-card-height, 100%); box-sizing: border-box;
      background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
      border-radius: var(--ha-card-border-radius, 16px); overflow: hidden;
      --d-pad: clamp(10px, 4cqi, 22px); --d-badge: clamp(14px, 6cqi, 26px); --d-header: clamp(15px, 6cqi, 26px);
      --d-clock: clamp(14px, 5.5cqi, 24px); --d-label: clamp(11px, 3.8cqi, 16px); --d-minutes: clamp(36px, 22cqi, 110px);
      --d-small: clamp(22px, 9cqi, 48px); --d-next: clamp(11px, 3.8cqi, 15px); --d-footer: clamp(12px, 4.6cqi, 20px); }
    /* Probe: card taken out of flow to tell whether the host has a definite (grid-imposed) height. */
    .card[data-probe] { position: absolute !important; height: 0 !important; width: 100% !important; visibility: hidden; }
    /* Fixed-height context (sections grid, panel, card_height): 2D container, sizes also capped by height. */
    .card[data-fixed] { container-type: size; }
    .card[data-fixed][data-layout="tall"] {
      --d-pad: min(clamp(10px, 4cqi, 22px), 6cqh); --d-badge: min(clamp(14px, 6cqi, 26px), 6.5cqh);
      --d-header: min(clamp(15px, 6cqi, 26px), 8.5cqh); --d-clock: min(clamp(14px, 5.5cqi, 24px), 8cqh);
      --d-label: min(clamp(11px, 3.8cqi, 16px), 6.5cqh); --d-minutes: min(clamp(36px, 22cqi, 110px), 30cqh);
      --d-small: min(clamp(22px, 9cqi, 48px), 14cqh); --d-next: min(clamp(11px, 3.8cqi, 15px), 6.5cqh);
      --d-footer: min(clamp(12px, 4.6cqi, 20px), 8cqh); }
    .card[data-fixed][data-layout="wide"] {
      --d-pad: min(clamp(10px, 3cqi, 22px), 8cqh); --d-badge: min(12cqh, 28px); --d-header: min(13cqh, 28px);
      --d-clock: min(11cqh, 24px); --d-label: min(9cqh, 18px); --d-minutes: min(52cqh, 16cqi);
      --d-small: min(24cqh, 6cqi); --d-next: min(9cqh, 16px); --d-footer: min(11cqh, 22px); }
    .wrap { display: flex; flex-direction: column; height: 100%; box-sizing: border-box;
      padding: calc(var(--idfm-padding, var(--d-pad)) * var(--idfm-scale, 1)); gap: 2px; }
    .left { display: contents; }
    .card[data-layout="wide"] .wrap { display: grid; grid-template-columns: minmax(0, auto) minmax(0, 1fr);
      grid-template-rows: auto 1fr auto auto; column-gap: calc(var(--d-pad) * 1.5); }
    .card[data-layout="wide"] .left { display: flex; flex-direction: column; justify-content: center;
      grid-column: 1; grid-row: 1 / -1; min-width: 0; }
    .card[data-layout="wide"] .left .label { margin-top: 0; }
    .card[data-layout="wide"] .left .big { flex: none; line-height: 1; }
    .card[data-layout="wide"] .top { grid-column: 2; grid-row: 1; }
    .card[data-layout="wide"] .next { grid-column: 2; grid-row: 2; align-self: end; min-height: 0; }
    .card[data-layout="wide"] .bottom { grid-column: 2; grid-row: 3; }
    .card[data-layout="wide"] .arr-line { grid-column: 2; grid-row: 4; }
    .top { display: flex; align-items: center; gap: 10px; }
    .badge { min-width: 1.9em; padding: 0 .35em; height: 1.9em; box-sizing: border-box; border-radius: 8px;
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700;
      font-size: calc(var(--idfm-badge-size, var(--d-badge)) * var(--idfm-scale, 1)); flex: none; }
    .badge[hidden] { display: none; }
    .stop { flex: 1; min-width: 0; font-weight: 700; font-size: calc(var(--idfm-header-size, var(--d-header)) * var(--idfm-scale, 1));
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .clock { font-size: calc(var(--idfm-clock-size, var(--d-clock)) * var(--idfm-scale, 1)); color: var(--primary-text-color, #212121);
      font-variant-numeric: tabular-nums; }
    .label { font-size: calc(var(--idfm-label-size, var(--d-label)) * var(--idfm-scale, 1)); color: var(--secondary-text-color, #727272); margin-top: 4px; }
    .big { font-weight: 800; line-height: 1.05; font-size: calc(var(--idfm-minutes-size, var(--d-minutes)) * var(--idfm-scale, 1));
      font-variant-numeric: tabular-nums; flex: 1; display: flex; align-items: center; white-space: nowrap; }
    .big.small { font-size: calc(var(--idfm-minutes-small-size, var(--d-small)) * var(--idfm-scale, 1)); white-space: normal; }
    .big.alert { color: var(--error-color, #db4437); }
    .next { font-size: calc(var(--idfm-next-size, var(--d-next)) * var(--idfm-scale, 1)); color: var(--secondary-text-color, #727272); min-height: 1.2em; }
    .bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px;
      font-size: calc(var(--idfm-footer-size, var(--d-footer)) * var(--idfm-scale, 1)); }
    .bottom-wrap { display: flex; flex-direction: column; gap: 2px; }
    .plat { flex: none; white-space: nowrap; margin-left: .35em; }
    .plat[hidden] { display: none; }
    .plat b { font-weight: 800; line-height: 1;
      font-size: calc(var(--idfm-platform-size, calc(var(--idfm-footer-size, var(--d-footer)) * 1.25)) * var(--idfm-scale, 1)); }
    .dep-text { flex: none; white-space: nowrap; }
    .arr-inline { display: flex; align-items: baseline; flex: 1 1 0; min-width: 11ch; margin-left: .6em; white-space: nowrap; }
    .arr-name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin: 0 .3em; }
    .arr-arrow, .arr-time { flex: none; white-space: nowrap; }
    .arr-line { font-size: calc(var(--idfm-next-size, var(--d-next)) * var(--idfm-scale, 1)); color: var(--secondary-text-color, #727272);
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: none; }
    .arr-inline[hidden], .arr-line[hidden], .warn[hidden] { display: none; }
    .warn { cursor: help; flex: none; font-size: .85em; opacity: .8; }
    @container (max-width: 380px) {
      .arr-inline { display: none; }
      .arr-line:not([hidden]) { display: block; }
    }
    .dep { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 0; flex: 1 1 auto; min-width: 0; }
    .rt { margin-left: .4em; width: .55em; height: .55em; border-radius: 50%; background: var(--success-color, #43a047);
      animation: pulse 1.6s ease-in-out infinite; flex: none; }
    .rt[hidden] { display: none; }
    .weather { flex: none; display: flex; align-items: center; gap: 4px; color: var(--secondary-text-color, #727272); }
    .weather[hidden] { display: none; }
    .weather ha-icon { --mdc-icon-size: calc(var(--idfm-weather-icon-size, 1.4em) * var(--idfm-scale, 1)); }
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
          { name: "show_arrival", selector: { boolean: {} } },
          { name: "show_platform", selector: { boolean: {} } },
          { name: "layout", selector: { select: { mode: "dropdown", options: [
            { value: "auto", label: "Auto" }, { value: "tall", label: "Vertical" }, { value: "wide", label: "Horizontal (large et bas)" }] } } },
          SCALE_FIELD, { name: "minutes_size", selector: { text: {} } },
          { name: "header_size", selector: { text: {} } }, { name: "badge_size", selector: { text: {} } },
          { name: "footer_size", selector: { text: {} } }, { name: "platform_size", selector: { text: {} } },
          { name: "card_height", selector: { text: {} } },
        ],
        computeLabel: (s) => ({
          ...SIZE_LABELS,
          show_platform: "Afficher la voie",
          entity: "Entité (capteur leave_at)", weather_entity: "Météo (optionnel)",
          title: "Titre (remplace l'arrêt)", show_next: "Afficher les départs suivants",
          show_clock: "Afficher l'heure", layout: "Disposition (auto, vertical, horizontal)", show_arrival: "Afficher l'arrivée à destination",
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
      if (!config || typeof config.entity !== "string") throw new Error("L'option 'entity' est requise");
      this._config = { show_next: false, show_clock: true, show_arrival: true, show_platform: true, ...config };
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

    _applySizes() {
      const card = this._card;
      const c = this._config;
      if (!card || !c) return;
      const set = (prop, v, key) => {
        if (v === undefined || v === null || v === "") { card.style.removeProperty(prop); return; }
        let out = null;
        if (typeof v === "number" && Number.isFinite(v) && v > 0) out = `${v}px`;
        else if (typeof v === "string" && SIZE_RE.test(v.trim())) out = v.trim();
        if (out === null) {
          console.warn(`idfm-departure-card: valeur ignorée pour '${key}': ${JSON.stringify(v)}`);
          card.style.removeProperty(prop);
        } else card.style.setProperty(prop, out);
      };
      const sc = Number(c.scale);
      if (c.scale === undefined || c.scale === null || c.scale === "") card.style.removeProperty("--idfm-scale");
      else if (Number.isFinite(sc) && sc >= 0.5 && sc <= 3) card.style.setProperty("--idfm-scale", String(sc));
      else {
        console.warn(`idfm-departure-card: 'scale' doit être entre 0.5 et 3: ${JSON.stringify(c.scale)}`);
        card.style.removeProperty("--idfm-scale");
      }
      for (const [key, prop] of Object.entries(SIZE_VARS)) set(prop, c[key], key);
    }

    getCardSize() { return 3; }
    getGridOptions() { return { columns: 6, rows: 3, min_rows: 2 }; }

    _applyLayout() {
      const card = this._card;
      const c = this._config;
      if (!card || !c || !this.isConnected) return;
      const ch = typeof c.card_height === "string" ? c.card_height.trim() : c.card_height;
      const cfgFixed = (typeof ch === "number" && ch > 0) || (typeof ch === "string" && SIZE_RE.test(ch) && !ch.endsWith("%"));
      // Probe: with the card out of flow, the host keeps a non-zero height only if its parent imposes one.
      card.setAttribute("data-probe", "");
      const hostH = this.clientHeight;
      card.removeAttribute("data-probe");
      const fixed = cfgFixed || hostH >= 40;
      const w = this.clientWidth;
      const h = cfgFixed ? card.clientHeight : hostH;
      let layout = "tall";
      if (c.layout === "wide") layout = "wide";
      else if (c.layout !== "tall" && fixed && h > 0 && w / h >= 3.5) layout = "wide";
      const setAttr = (n, v) => { if (v === null) card.removeAttribute(n); else if (card.getAttribute(n) !== v) card.setAttribute(n, v); };
      setAttr("data-fixed", fixed ? "" : null);
      setAttr("data-layout", layout);
    }

    connectedCallback() {
      this._render();
      if (typeof ResizeObserver !== "undefined" && !this._ro) {
        this._ro = new ResizeObserver(() => this._applyLayout());
        this._ro.observe(this);
      }
      this._applyLayout();
      if (!this._timer) this._timer = setInterval(() => this._render(), 10000);
    }
    disconnectedCallback() {
      if (this._ro) { this._ro.disconnect(); this._ro = null; }
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
      this._card = card;
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
      this._depText = el("span", "dep-text");
      this._arrInline = el("span", "arr-inline");
      this._arrName = el("span", "arr-name");
      this._arrTime = el("span", "arr-time");
      this._arrInline.append(el("span", "arr-arrow", "\u2192"), this._arrName, this._arrTime);
      this._plat = el("span", "plat");
      this._plat.hidden = true;
      this._platLbl = el("span");
      this._platNum = el("b");
      this._plat.append(this._platLbl, this._platNum);
      this._rt = el("span", "rt");
      this._warn = el("span", "warn", "\u26A0");
      this._warn.hidden = true;
      dep.append(this._depText, this._rt, this._plat, this._arrInline, this._warn);
      this._weather = el("div", "weather");
      this._wIcon = document.createElement("ha-icon");
      this._wTemp = el("span");
      this._weather.append(this._wIcon, this._wTemp);
      bottom.append(dep, this._weather);
      this._arrLine = el("div", "arr-line");
      this._arrLine.hidden = true;
      this._arrInline.hidden = true;
      const left = el("div", "left");
      left.append(this._label, this._big);
      wrap.append(top, left, this._next, bottom, this._arrLine);
      card.append(wrap);
      root.replaceChildren(style, card);
      this._built = true;
    }

    _current(st) {
      // Returns {valid, leaveAt, info} applying roll-over to a later departure.
      const a = st.attributes || {};
      let info = { line: a.line, line_color: a.line_color, line_text_color: a.line_text_color,
        mode: a.mode, stop_departure: a.stop_departure, realtime: a.realtime,
        arrival_at: a.arrival_at, platform: a.platform };
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
            mode: next.mode, stop_departure: next.stop_departure, realtime: next.realtime,
            arrival_at: next.arrival_at, platform: next.platform };
        }
      }
      return { leaveAt, info, list };
    }

    _render() {
      if (!this._config) return;
      if (!this._built) this._build();
      this._applySizes();
      this._applyLayout();
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
        this._plat.hidden = true;
        this._rt.hidden = true;
        this._arrInline.hidden = true;
        this._arrLine.hidden = true;
        this._warn.hidden = true;
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
      const plat = info.platform === undefined || info.platform === null ? "" : String(info.platform).trim();
      if (depTime && plat && c.show_platform !== false) {
        this._platLbl.textContent = `\u00B7 ${T.platform} `;
        this._platNum.textContent = plat;
        this._plat.hidden = false;
      } else {
        this._platLbl.textContent = "";
        this._platNum.textContent = "";
        this._plat.hidden = true;
      }
      this._rt.hidden = !(valid && info.realtime === true && depTime);

      const destName = typeof a.destination_name === "string" ? a.destination_name : "";
      const arrTime = valid && destName && c.show_arrival !== false ? this._fmt(info.arrival_at) : "";
      if (arrTime) {
        this._arrName.textContent = destName;
        this._arrName.title = destName;
        this._arrTime.textContent = arrTime;
        this._arrInline.hidden = false;
        this._arrLine.textContent = T.arrivalAt(destName, arrTime);
        this._arrLine.hidden = false;
      } else {
        this._arrName.textContent = "";
        this._arrTime.textContent = "";
        this._arrInline.hidden = true;
        this._arrLine.textContent = "";
        this._arrLine.hidden = true;
      }
      const noFilter = a.destination_filter_active === false;
      this._warn.hidden = !noFilter;
      this._warn.title = noFilter ? T.noFilter : "";

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

  const LIST_TEXTS = {
    fr: { leave: "Partir", station: "Gare", platform: "Voie", arrival: "Arrivée", inMin: (n) => `dans ${n} min`,
      now: "maintenant", walk: (n) => `Marche ${n} min · marge incluse`, none: "Aucun départ" },
    en: { leave: "Leave", station: "Station", platform: "Platform", arrival: "Arrival", inMin: (n) => `in ${n} min`,
      now: "now", walk: (n) => `Walk ${n} min · buffer included`, none: "No departure" },
  };
  const LIST_STYLE = `
    :host { display: block; }
    ha-card, .card { display: block; container-type: inline-size; height: var(--idfm-card-height, 100%); box-sizing: border-box;
      background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
      border-radius: var(--ha-card-border-radius, 16px); overflow: hidden; }
    .wrap { display: flex; flex-direction: column; box-sizing: border-box; padding: calc(var(--idfm-padding, clamp(10px, 3cqi, 20px)) * var(--idfm-scale, 1)); gap: 6px; }
    .head { display: flex; align-items: baseline; gap: 10px; }
    .title { flex: 1; min-width: 0; font-weight: 700; font-size: calc(var(--idfm-header-size, clamp(15px, 4.5cqi, 24px)) * var(--idfm-scale, 1));
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .clock { font-size: calc(var(--idfm-clock-size, clamp(14px, 4cqi, 22px)) * var(--idfm-scale, 1)); font-variant-numeric: tabular-nums; }
    .walk { font-size: calc(var(--idfm-sub-size, 12px) * var(--idfm-scale, 1)); color: var(--secondary-text-color, #727272); min-height: 1em; }
    .walk:empty { display: none; }
    .table { --cols: 48px minmax(0, 1fr) 104px 72px 56px 68px; display: flex; flex-direction: column; }
    .table.noarr { --cols: 48px minmax(0, 1fr) 104px 72px 56px; }
    .tr { display: grid; grid-template-columns: var(--cols); align-items: center; column-gap: 10px;
      padding: 6px 0; border-top: 1px solid var(--divider-color, #e0e0e0); }
    .tr.hd { border-top: 0; padding: 0 0 2px;
      color: var(--secondary-text-color, #727272); }
    .table.nodir { --cols: 48px 104px 72px 56px 68px; }
    .table.nodir.noarr { --cols: 48px 104px 72px 56px; }
    .tr.hd > span { font-size: calc(var(--idfm-col-header-size, 11px) * var(--idfm-scale, 1)); text-transform: uppercase; }
    .badge { min-width: 2.2em; padding: 0 .35em; height: 2em; box-sizing: border-box; border-radius: 8px;
      display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: calc(var(--idfm-badge-size, 15px) * var(--idfm-scale, 1)); justify-self: start; }
    .dir { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: calc(var(--idfm-row-size, 15px) * var(--idfm-scale, 1)); }
    .c { min-width: 0; font-variant-numeric: tabular-nums; display: flex; flex-direction: column; }
    .v { font-weight: 700; font-size: calc(var(--idfm-time-size, 16px) * var(--idfm-scale, 1)); }
    .rel { font-size: calc(var(--idfm-sub-size, 12px) * var(--idfm-scale, 1)); color: var(--secondary-text-color, #727272); }
    .rel.alert { color: var(--error-color, #db4437); font-weight: 700; }
    .voie .v { font-size: calc(var(--idfm-platform-size, 22px) * var(--idfm-scale, 1)); font-weight: 800; }
    .lbl { display: none; font-size: calc(var(--idfm-col-header-size, 10px) * var(--idfm-scale, 1)); text-transform: uppercase; color: var(--secondary-text-color, #727272); }
    .rt { width: .55em; height: .55em; border-radius: 50%; background: var(--success-color, #43a047);
      animation: pulse 1.6s ease-in-out infinite; flex: none; }
    .empty { padding: 16px 0; text-align: center; color: var(--secondary-text-color, #727272); }
    @keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: .3; transform: scale(.7); } }
    @media (prefers-reduced-motion: reduce) { .rt { animation: none; } }
    @container (max-width: 519px) {
      .table:not(.nodir) { --cols: 48px 104px 72px 56px 68px; }
      .table:not(.nodir).noarr { --cols: 48px 104px 72px 56px; }
      .tr > .dir, .tr.hd > .dir { display: none; }
      .tr.hd > .dir { display: none; }
    }
    @container (max-width: 359px) {
      .table, .table.noarr, .table.nodir, .table.nodir.noarr,
      .table:not(.nodir), .table:not(.nodir).noarr { --cols: 1.3fr 1fr 1fr 1fr; }
      .table.noarr, .table.noarr:not(.nodir) { --cols: 1.3fr 1fr 1fr; }
      .tr.hd { display: none; }
      .tr { row-gap: 4px; column-gap: 8px; }
      .tr > .dir { display: block; grid-column: 2 / -1; }
      .table.nodir .tr > .badge { grid-column: 1 / -1; }
      .lbl { display: block; }
    }
  `;

  class IdfmDepartureListCard extends IdfmDepartureCard {
    _applyLayout() {} // list card is auto-height; no 2D layout
    static getConfigForm() {
      return {
        schema: [
          { name: "entity", required: true,
            selector: { entity: { domain: "sensor", integration: "idfm_departure" } } },
          { name: "title", selector: { text: {} } },
          { name: "count", selector: { number: { min: 1, max: 10, mode: "box" } } },
          { name: "show_arrival", selector: { boolean: {} } },
          { name: "show_direction", selector: { boolean: {} } },
          SCALE_FIELD, { name: "header_size", selector: { text: {} } }, { name: "badge_size", selector: { text: {} } },
          { name: "row_size", selector: { text: {} } }, { name: "time_size", selector: { text: {} } },
          { name: "platform_size", selector: { text: {} } }, { name: "card_height", selector: { text: {} } },
        ],
        computeLabel: (s) => ({
          ...SIZE_LABELS,
          entity: "Entité (capteur leave_at)", title: "Titre (remplace l'arrêt)",
          count: "Nombre de départs (1-10)", show_arrival: "Afficher l'arrivée",
          show_direction: "Afficher la direction",
        }[s.name] || s.name),
      };
    }

    static getStubConfig(hass) {
      const c = IdfmDepartureCard.getStubConfig(hass);
      return { type: "custom:idfm-departure-list-card", entity: c.entity, count: 5 };
    }

    setConfig(config) {
      if (!config || typeof config.entity !== "string") throw new Error("L'option 'entity' est requise");
      let n = Math.round(Number(config.count));
      if (!Number.isFinite(n)) n = 5;
      this._config = { show_arrival: true, show_direction: true, ...config, count: Math.min(10, Math.max(1, n)) };
      this._rows = 0;
      this._render();
    }

    getCardSize() { return 1 + (this._rows || (this._config ? this._config.count : 5)); }
    getGridOptions() { return { columns: 12, min_columns: 6, rows: "auto" }; }

    _build() {
      const style = document.createElement("style");
      style.textContent = LIST_STYLE;
      const card = document.createElement("ha-card");
      card.className = "card";
      this._card = card;
      const wrap = el("div", "wrap");
      const head = el("div", "head");
      this._title = el("span", "title");
      this._clock = el("span", "clock");
      head.append(this._title, this._clock);
      this._walk = el("div", "walk");
      this._table = el("div", "table");
      wrap.append(head, this._walk, this._table);
      card.append(wrap);
      this.shadowRoot.replaceChildren(style, card);
      this._built = true;
    }

    _cell(cls, label, children) {
      const c = el("div", `c ${cls}`);
      if (label) c.append(el("span", "lbl", label));
      return c;
    }

    _render() {
      if (!this._config) return;
      if (!this._built) this._build();
      this._applySizes();
      const c = this._config;
      const lang = this._lang();
      const T = LIST_TEXTS[lang];
      const st = this._hass && this._hass.states && this._hass.states[c.entity];
      const a = (st && st.attributes) || {};
      const now = Date.now();
      this._clock.textContent = this._fmt(new Date(now).toISOString());

      const stop = c.title || a.stop_name || (st ? "" : c.entity);
      const dest = typeof a.destination_name === "string" ? a.destination_name : "";
      this._title.textContent = dest ? `${stop} → ${dest}` : stop;

      const all = Array.isArray(a.departures) ? a.departures : [];
      const rows = [];
      all.forEach((d, i) => {
        const t = Date.parse(d && d.leave_at);
        if (Number.isNaN(t) || t < now) return;
        rows.push({ d, t, platform: d.platform !== undefined ? d.platform : (i === 0 ? a.platform : null) });
      });
      const shown = rows.slice(0, c.count);
      this._rows = shown.length;

      const walk = Number(a.walk_min !== undefined && a.walk_min !== null ? a.walk_min
        : shown.length ? shown[0].d.walk_min : NaN);
      this._walk.textContent = Number.isFinite(walk) && walk > 0 ? T.walk(Math.round(walk)) : "";

      const showDir = c.show_direction !== false;
      const showArr = c.show_arrival !== false && shown.some((r) => !Number.isNaN(Date.parse(r.d.arrival_at)));
      this._table.className = `table${showArr ? "" : " noarr"}${showDir ? "" : " nodir"}`;

      if (!shown.length) {
        this._table.replaceChildren(el("div", "empty", T.none));
        return;
      }
      const hd = el("div", "tr hd");
      hd.append(el("span", "", ""));
      if (showDir) hd.append(el("span", "dir", ""));
      hd.append(el("span", "", T.leave), el("span", "", T.station), el("span", "", T.platform));
      if (showArr) hd.append(el("span", "", T.arrival));
      hd.setAttribute("role", "presentation");
      const out = [hd];
      for (const r of shown) {
        const d = r.d;
        const mode = MODE_COLORS[d.mode] ? d.mode : "other";
        const tr = el("div", "tr");
        const badge = el("span", "badge", String(d.line || MODE_LABELS[lang][mode]));
        badge.style.background = d.line_color || MODE_COLORS[mode];
        badge.style.color = d.line_text_color || "#ffffff";
        tr.append(badge);
        if (showDir) tr.append(el("span", "dir", d.direction ? String(d.direction) : ""));

        const mins = Math.floor((r.t - now) / 60000);
        const leave = this._cell("leave", T.leave);
        leave.append(el("span", "v", this._fmt(d.leave_at)),
          el("span", mins <= 0 ? "rel alert" : "rel", mins <= 0 ? T.now : T.inMin(mins)));
        const gare = this._cell("gare", T.station);
        const gv = el("span", "v", this._fmt(d.stop_departure));
        const gbox = el("div", "c");
        gbox.style.flexDirection = "row";
        gbox.style.alignItems = "center";
        gbox.style.gap = "6px";
        gbox.append(gv);
        if (d.realtime === true) gbox.append(el("span", "rt"));
        gare.append(gbox);
        const voie = this._cell("voie", T.platform);
        const pf = r.platform;
        voie.append(el("span", "v", pf !== null && pf !== undefined && String(pf) !== "" ? String(pf) : "–"));
        tr.append(leave, gare, voie);
        if (showArr) {
          const arr = this._cell("arr", T.arrival);
          arr.append(el("span", "v", this._fmt(d.arrival_at) || "–"));
          tr.append(arr);
        }
        out.push(tr);
      }
      this._table.replaceChildren(...out);
    }
  }

  const register = (tag, cls, name, description) => {
    if (!customElements.get(tag)) customElements.define(tag, cls);
    window.customCards = window.customCards || [];
    if (!window.customCards.some((c) => c && c.type === tag)) {
      window.customCards.push({ type: tag, name, description, preview: true });
    }
  };
  register("idfm-departure-list-card", IdfmDepartureListCard, "IDFM Départs détaillés",
    "Tableau des prochains départs : ligne, direction, heure pour partir, voie et arrivée.");
  register("idfm-departure-card", IdfmDepartureCard, "IDFM Prochain Départ",
    "Prochain départ à quitter la maison, avec minutes restantes, ligne et météo.");
})();
